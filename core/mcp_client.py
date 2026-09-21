"""Aerie · 云栖 — 通用 MCP 客户端（stdio transport）。

作用：按配置拉起外部 MCP server 子进程，通过 JSON-RPC over stdio 做
initialize 握手 + tools/list 同步 + tools/call 调用，并把远端工具注册进
``core/tool_registry.py`` 的 ``ToolRegistry``，让现有的 Function Calling
ReAct 循环可以直接调用它们。

本模块实现范围（刻意保持最小）：
  - 仅 stdio transport（本地子进程 + 行分隔 JSON-RPC）
  - 仅 MCP 的最小方法子集：``initialize`` / ``notifications/initialized`` /
    ``tools/list`` / ``tools/call``
  - 默认关闭：配置总开关 ``enabled: false``（默认）时 ``start()`` 不建立任何连接
  - 连接生命周期显式：``connect()`` 建连、``close()`` 关停、``atexit`` 兜底回收子进程

明确不做（留给后续需要时再加，避免预防性抽象）：
  - HTTP / SSE transport、resources / prompts / sampling、server→client 反向调用
  - 单连接并发多路复用：每个 server 一个连接，请求-响应串行（``asyncio.Lock``）
  - 重连/退避、健康检查、输出大小上限、权限校验（属于 ToolRegistry 层的事）

工具命名与去重规则：
  注册名 = ``mcp__<server>__<remote_tool>``（非法字符替换为 ``_``，超 64 字符
  截断并追加名字哈希）。三条规则：
    1. 前缀 ``mcp__`` 保证不会与内置工具 / skill 撞名（它们都不带该前缀）；
    2. 同一连接重复 ``tools/list`` 到的同名工具 → 跳过（幂等）；
    3. 目标名已被注册表里其它工具占用 → **跳过并告警**，绝不覆盖既有工具。
  远端工具若返回 ``isError: true``，归一化结果里会带 ``error`` 字段，这样
  ``llm_caller`` 的 ``success = "error" not in result`` 会把它判定为失败。
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import logging
import os
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "mcp_servers.yaml"

TOOL_NAME_PREFIX = "mcp__"
_MAX_TOOL_NAME_LEN = 64
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")

CLIENT_NAME = "aerie"
CLIENT_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"

_STDIO_BUFFER_LIMIT = 8 * 1024 * 1024  # MCP 单帧可能很大，默认 64KiB 会溢出
_STDERR_TAIL_LINES = 20
_CLOSE_GRACE_SECONDS = 2.0


# ── 错误 ──────────────────────────────────────────────

class MCPError(Exception):
    """可诊断的 MCP 客户端错误。

    ``kind`` 标明失败阶段，便于上层分类处理 / 展示：
      - ``config``          配置非法（缺 command、transports 不支持等）
      - ``connect``         子进程起不来（命令不存在、无权限）
      - ``handshake``       initialize 握手失败
      - ``protocol``        响应不是合法 JSON-RPC
      - ``method_not_found``远端无此方法（JSON-RPC -32601）
      - ``timeout``         等待响应超时
      - ``remote``          远端返回 JSON-RPC error（非 -32601）
      - ``process_exit``    子进程在请求期间退出
      - ``closed``          连接已关闭
    """

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        server: str = "",
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.server = server
        self.detail = detail or {}

    def as_dict(self) -> dict:
        """归一化为项目工具统一的 error 结构。"""
        out = {
            "status": "error",
            "error": f"mcp_{self.kind}: {self.message}",
            "kind": self.kind,
        }
        if self.server:
            out["server"] = self.server
        if self.detail:
            out["detail"] = self.detail
        return out


# ── 配置 ──────────────────────────────────────────────

def _as_bool(value: Any) -> bool:
    """宽松解析布尔值（手写 YAML 里 ``"false"`` 也要按 False 处理）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass
class MCPServerConfig:
    """单个 MCP server 的连接配置（stdio）。"""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout_seconds: float = 30.0
    call_timeout_seconds: float = 120.0
    enabled: bool = False

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "MCPServerConfig":
        if not isinstance(data, dict):
            raise MCPError("config", f"server '{name}' 配置必须是映射", server=name)
        transport = str(data.get("transport", "stdio") or "stdio").lower()
        if transport != "stdio":
            raise MCPError(
                "config",
                f"server '{name}' 使用不支持的 transport: {transport}（当前仅支持 stdio）",
                server=name,
            )
        command = str(data.get("command") or "").strip()
        if not command:
            raise MCPError("config", f"server '{name}' 缺少 command", server=name)
        args = data.get("args") or []
        if not isinstance(args, (list, tuple)):
            raise MCPError("config", f"server '{name}' 的 args 必须是列表", server=name)
        env = data.get("env") or {}
        if not isinstance(env, dict):
            raise MCPError("config", f"server '{name}' 的 env 必须是映射", server=name)
        cwd = data.get("cwd")
        return cls(
            name=name,
            command=command,
            args=[str(a) for a in args],
            env={str(k): str(v) for k, v in env.items()},
            cwd=str(cwd) if cwd else None,
            timeout_seconds=float(data.get("timeout_seconds", 30.0) or 30.0),
            call_timeout_seconds=float(data.get("call_timeout_seconds", 120.0) or 120.0),
            enabled=_as_bool(data.get("enabled", False)),
        )


def load_servers_config(
    config_path: str | Path | None = None,
    servers: dict | None = None,
) -> tuple[bool, dict[str, dict]]:
    """读取 MCP server 定义。

    返回 ``(总开关, {name: 原始定义})``。

    - 显式传入 ``servers`` 时：视为调用方明确授权，忽略总开关与配置文件；
    - 否则读 ``config_path``（默认 ``config/mcp_servers.yaml``）：
      文件不存在 / ``enabled`` 未显式置 true → 总开关为 False（默认关闭）。
    """
    if servers is not None:
        return True, {str(k): v for k, v in servers.items()}

    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        logger.debug("MCP 配置不存在: %s（MCP 保持关闭）", path)
        return False, {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("MCP 配置读取失败 %s: %s", path, e)
        return False, {}
    if not isinstance(data, dict):
        logger.warning("MCP 配置格式非法（顶层应为映射）: %s", path)
        return False, {}
    enabled = _as_bool(data.get("enabled", False))
    raw = data.get("servers") or {}
    if not isinstance(raw, dict):
        logger.warning("MCP 配置 servers 段应为映射: %s", path)
        raw = {}
    return enabled, {str(k): v for k, v in raw.items()}


# ── 命名 ──────────────────────────────────────────────

def local_tool_name(server: str, remote_tool: str) -> str:
    """把远端工具名映射为注册名 ``mcp__<server>__<remote>``（含长度保护）。"""
    raw = f"{TOOL_NAME_PREFIX}{_SAFE_NAME_RE.sub('_', server)}__{_SAFE_NAME_RE.sub('_', remote_tool)}"
    if len(raw) <= _MAX_TOOL_NAME_LEN:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{raw[: _MAX_TOOL_NAME_LEN - 9]}_{digest}"


# ── 单个连接 ──────────────────────────────────────────

class MCPServerClient:
    """一个 MCP server 的 stdio 连接。

    生命周期：``connect()`` → ``list_tools()`` / ``call_tool()`` → ``close()``。
    连接对象不做自动重连；断了就报 ``process_exit``，由上层决定是否重建。
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.server_name = config.name
        self.tools: list[dict] = []
        self.registered_tools: dict[str, str] = {}  # 注册名 -> 远端工具名
        self.server_info: dict = {}
        self.protocol_version: str = ""

        self._proc: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self._pending: dict[int, tuple[asyncio.Future, str]] = {}
        self._next_id = 0
        self._lock = asyncio.Lock()
        self._closed = False

    # ── 观测 ─────────────────────────────────────────

    @property
    def connected(self) -> bool:
        proc = self._proc
        return bool(proc is not None and proc.returncode is None)

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail)

    # ── 生命周期 ─────────────────────────────────────

    async def connect(self) -> dict:
        """拉起子进程并完成 initialize 握手。返回 serverInfo。"""
        if self.connected:
            return self.server_info
        self._closed = False
        env = dict(os.environ)
        env.update(self.config.env)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.config.command,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.cwd,
                env=env,
                limit=_STDIO_BUFFER_LIMIT,
            )
        except FileNotFoundError as e:
            raise MCPError(
                "connect",
                f"命令不存在: {self.config.command}",
                server=self.server_name,
                detail={"argv": [self.config.command, *self.config.args], "errno": str(e)},
            ) from e
        except (PermissionError, OSError) as e:
            raise MCPError(
                "connect",
                f"启动失败: {type(e).__name__}: {e}",
                server=self.server_name,
                detail={"argv": [self.config.command, *self.config.args]},
            ) from e

        _ACTIVE_CLIENTS.add(self)
        _ensure_atexit()
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        try:
            result = await self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
                },
                timeout=self.config.timeout_seconds,
            )
        except MCPError as e:
            await self.close()
            stderr = self.stderr_tail()
            raise MCPError(
                "handshake",
                f"initialize 失败（{e.kind}）: {e.message}"
                + (f" | stderr: {stderr}" if stderr else ""),
                server=self.server_name,
                detail={"cause": e.kind},
            ) from e

        if not isinstance(result, dict):
            await self.close()
            raise MCPError(
                "protocol", "initialize 返回非对象", server=self.server_name
            )
        self.protocol_version = str(result.get("protocolVersion") or "")
        self.server_info = result.get("serverInfo") or {}
        if self.protocol_version and self.protocol_version != PROTOCOL_VERSION:
            logger.warning(
                "MCP %s: 协商到协议版本 %s（本客户端为 %s）",
                self.server_name, self.protocol_version, PROTOCOL_VERSION,
            )
        await self._notify("notifications/initialized", {})
        logger.info(
            "MCP %s 已连接: %s",
            self.server_name, self.server_info.get("name") or self.config.command,
        )
        return self.server_info

    async def close(self) -> None:
        """关停连接：先关 stdin 让 server 自然退出，超时则 terminate/kill。"""
        self._closed = True
        proc, self._proc = self._proc, None
        self._fail_pending(MCPError("closed", "连接已关闭", server=self.server_name))

        if proc is not None:
            if proc.stdin is not None and not proc.stdin.is_closing():
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_CLOSE_GRACE_SECONDS)
                except asyncio.TimeoutError:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=_CLOSE_GRACE_SECONDS)
                    except asyncio.TimeoutError:
                        proc.kill()
                        try:
                            await proc.wait()
                        except Exception:
                            pass
                except Exception:
                    pass

        for task in (self._stdout_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.debug("MCP %s: 读取任务收尾异常", self.server_name, exc_info=True)
        self._stdout_task = self._stderr_task = None
        _ACTIVE_CLIENTS.discard(self)
        logger.info("MCP %s 连接已关闭", self.server_name)

    def terminate_nowait(self) -> None:
        """同步强杀子进程（atexit 兜底，防止子进程泄漏）。"""
        self._closed = True
        proc = self._proc
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        for task in (self._stdout_task, self._stderr_task):
            if task is not None and not task.done():
                try:
                    task.cancel()
                except Exception:
                    pass
        _ACTIVE_CLIENTS.discard(self)

    # ── 协议 ─────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        """拉取 ``tools/list``。失败抛 MCPError。"""
        result = await self._request(
            "tools/list", {}, timeout=self.config.timeout_seconds
        )
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise MCPError(
                "protocol",
                "tools/list 返回结构非法（缺 tools 列表）",
                server=self.server_name,
            )
        self.tools = [t for t in result["tools"] if isinstance(t, dict)]
        return self.tools

    async def call_tool(
        self, remote_tool: str, arguments: dict | None = None, *, timeout: float | None = None
    ) -> dict:
        """调用远端工具。成功返回归一化结果，失败抛 MCPError。"""
        result = await self._request(
            "tools/call",
            {"name": remote_tool, "arguments": arguments or {}},
            timeout=timeout or self.config.call_timeout_seconds,
        )
        if not isinstance(result, dict):
            raise MCPError(
                "protocol", "tools/call 返回非对象", server=self.server_name
            )
        return self._normalize_call_result(remote_tool, result)

    async def invoke(self, remote_tool: str, arguments: dict | None = None) -> dict:
        """调用远端工具且**永不抛错**，返回项目统一的工具结果结构。

        注册进 ToolRegistry 的就是这个方法：任何失败都转成 ``{"error": ...}``
        （上层 ``llm_caller`` 用 ``"error" not in result`` 判定失败）。
        """
        try:
            return await self.call_tool(remote_tool, arguments)
        except MCPError as e:
            out = e.as_dict()
            out["tool"] = remote_tool
            logger.warning("MCP %s 调用 %s 失败: %s", self.server_name, remote_tool, e)
            return out
        except Exception as e:  # 兜底：注册进来的函数不能把工具循环带崩
            logger.exception("MCP %s 调用 %s 异常", self.server_name, remote_tool)
            return {
                "status": "error",
                "error": f"mcp_unexpected: {type(e).__name__}: {e}",
                "kind": "unexpected",
                "server": self.server_name,
                "tool": remote_tool,
            }

    # ── 注册进 ToolRegistry ──────────────────────────

    def register_tools(self, registry: Any, tools: list[dict] | None = None) -> dict:
        """把远端工具注册进 ToolRegistry。

        返回 ``{"registered": {注册名: 远端名}, "skipped": {注册名: 原因}}``。
        冲突规则见模块文档：不覆盖既有工具，冲突一律跳过并告警。
        """
        registered: dict[str, str] = {}
        skipped: dict[str, str] = {}
        for spec in tools if tools is not None else self.tools:
            remote_name = str(spec.get("name") or "").strip()
            if not remote_name:
                continue
            name = local_tool_name(self.server_name, remote_name)
            if name in self.registered_tools:
                skipped[name] = "already_registered"
                continue
            try:
                existing = registry.get(name)
            except AttributeError:
                existing = None
            if existing is not None:
                logger.warning(
                    "MCP %s: 工具名 %s 已被占用，跳过注册（不覆盖既有工具）",
                    self.server_name, name,
                )
                skipped[name] = "name_conflict"
                continue
            registry.register(
                name=name,
                func=self._make_callable(remote_name),
                schema=self._to_openai_schema(name, remote_name, spec),
                provider_hint="text",
                category="mcp",
            )
            self.registered_tools[name] = remote_name
            registered[name] = remote_name
        return {"registered": registered, "skipped": skipped}

    def _make_callable(self, remote_name: str):
        """生成注册用的可调用对象（async，参数按关键字展开）。"""

        async def _invoke(**kwargs: Any) -> dict:
            return await self.invoke(remote_name, kwargs)

        _invoke.__name__ = f"mcp_{_SAFE_NAME_RE.sub('_', remote_name)}"
        return _invoke

    def _to_openai_schema(self, name: str, remote_name: str, spec: dict) -> dict:
        schema = spec.get("inputSchema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        desc = str(spec.get("description") or "").strip()
        origin = f"[MCP:{self.server_name}/{remote_name}]"
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{origin} {desc}".strip(),
                "parameters": schema,
            },
        }

    # ── 内部：传输 ───────────────────────────────────

    async def _request(self, method: str, params: dict, *, timeout: float) -> Any:
        async with self._lock:
            proc = self._proc
            if proc is None:
                raise MCPError(
                    "closed",
                    f"连接不可用（method={method}）",
                    server=self.server_name,
                )
            if proc.returncode is not None:
                raise MCPError(
                    "process_exit",
                    f"子进程已退出（method={method}, returncode={proc.returncode}）",
                    server=self.server_name,
                    detail={"returncode": proc.returncode, "stderr": self.stderr_tail()},
                )
            loop = asyncio.get_running_loop()
            req_id = self._next_id
            self._next_id += 1
            future: asyncio.Future = loop.create_future()
            self._pending[req_id] = (future, method)
            try:
                await self._write(
                    {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
                )
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError as e:
                raise MCPError(
                    "timeout",
                    f"{method} 超时（{timeout}s）",
                    server=self.server_name,
                    detail={"timeout_seconds": timeout},
                ) from e
            finally:
                self._pending.pop(req_id, None)

    async def _notify(self, method: str, params: dict) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, payload: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise MCPError(
                "process_exit", "写入失败：子进程已退出", server=self.server_name
            )
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            proc.stdin.write(data)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise MCPError(
                "process_exit",
                f"写入失败：子进程已关闭管道（{type(e).__name__}）",
                server=self.server_name,
                detail={"stderr": self.stderr_tail()},
            ) from e

    async def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                try:
                    line = await proc.stdout.readline()
                except (asyncio.LimitOverrunError, ValueError) as e:
                    self._fail_pending(
                        MCPError("protocol", f"响应帧超过读取上限: {e}", server=self.server_name)
                    )
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._fail_pending(
                        MCPError("protocol", f"读取响应失败: {e}", server=self.server_name)
                    )
                    return
                if not line:
                    self._fail_pending(
                        MCPError(
                            "process_exit",
                            f"MCP server 进程结束（returncode={proc.returncode}）",
                            server=self.server_name,
                            detail={"stderr": self.stderr_tail()},
                        )
                    )
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning(
                        "MCP %s: 收到非 JSON 行（已忽略）: %r",
                        self.server_name, text[:200],
                    )
                    continue
                await self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP %s: stdout 读取循环异常退出", self.server_name)

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _dispatch(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        msg_id = msg.get("id")
        if msg_id is not None and ("result" in msg or "error" in msg):
            entry = self._pending.get(msg_id)
            if entry is None:
                logger.debug("MCP %s: 收到未知 id=%s 的响应", self.server_name, msg_id)
                return
            future, method = entry
            if future.done():
                return
            if "error" in msg:
                future.set_exception(self._remote_error(method, msg["error"]))
            else:
                future.set_result(msg.get("result"))
            return
        method = msg.get("method")
        if not isinstance(method, str):
            return
        if msg_id is not None:
            # server → client 请求：本客户端尚未实现，明确回 -32601 而不是装死。
            logger.warning("MCP %s: 未实现的 server→client 方法 %s", self.server_name, method)
            await self._write({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"client does not implement method: {method}"},
            })
        else:
            logger.debug("MCP %s: 通知 %s", self.server_name, method)

    def _remote_error(self, method: str, error: Any) -> MCPError:
        if isinstance(error, dict):
            code = error.get("code")
            message = str(error.get("message") or "remote error")
        else:
            code = None
            message = str(error)
        kind = "method_not_found" if code == -32601 else "remote"
        return MCPError(
            kind,
            f"{method} 远端返回错误: {message}",
            server=self.server_name,
            detail={"code": code, "data": (error or {}).get("data") if isinstance(error, dict) else None},
        )

    def _fail_pending(self, error: MCPError) -> None:
        for req_id, (future, _method) in list(self._pending.items()):
            if not future.done():
                future.set_exception(error)
            self._pending.pop(req_id, None)

    def _normalize_call_result(self, remote_tool: str, result: dict) -> dict:
        content = result.get("content")
        if not isinstance(content, list):
            content = []
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
        ]
        is_error = bool(result.get("isError", False))
        out: dict = {
            "status": "error" if is_error else "ok",
            "server": self.server_name,
            "tool": remote_tool,
            "is_error": is_error,
            "text": "\n".join(texts),
            "content": content,
        }
        if isinstance(result.get("structuredContent"), dict):
            out["structured"] = result["structuredContent"]
        if is_error:
            out["error"] = f"mcp_remote: {out['text'][:200] or 'remote tool reported isError'}"
        return out


# ── 进程退出兜底 ──────────────────────────────────────

_ACTIVE_CLIENTS: set[MCPServerClient] = set()
_ATEXIT_REGISTERED = False


def _ensure_atexit() -> None:
    global _ATEXIT_REGISTERED
    if not _ATEXIT_REGISTERED:
        atexit.register(_reap_all_nowait)
        _ATEXIT_REGISTERED = True


def _reap_all_nowait() -> None:
    """进程退出时同步回收所有仍存活的 MCP 子进程（不泄漏）。"""
    for client in list(_ACTIVE_CLIENTS):
        try:
            client.terminate_nowait()
        except Exception:
            pass


# ── 多 server 管理 ────────────────────────────────────

class MCPClientManager:
    """按配置管理多个 MCP 连接，并把它们的工具注册进 ToolRegistry。

    默认关闭：总开关（配置 ``enabled``）为 false 时 ``start()`` 不做任何连接、
    不触碰 ToolRegistry，现有启动行为完全不变。
    """

    def __init__(
        self,
        registry: Any,
        *,
        config_path: str | Path | None = None,
        servers: dict | None = None,
    ) -> None:
        self.registry = registry
        self.config_path = config_path
        self._explicit_servers = servers
        self._clients: dict[str, MCPServerClient] = {}
        self._started = False
        self._summary: dict = self._empty_summary()

    # ── 配置 ─────────────────────────────────────────

    def server_configs(self) -> list[MCPServerConfig]:
        """返回**已启用**的 server 配置；配置非法时抛出 MCPError(kind=config)。"""
        enabled, raw = load_servers_config(self.config_path, self._explicit_servers)
        if not enabled:
            return []
        out: list[MCPServerConfig] = []
        for name, data in raw.items():
            cfg = MCPServerConfig.from_dict(name, data)
            if cfg.enabled:
                out.append(cfg)
            else:
                logger.debug("MCP server %s 未启用，跳过", name)
        return out

    @staticmethod
    def _empty_summary() -> dict:
        return {"enabled": False, "started": [], "failed": {}, "tools_registered": 0}

    # ── 生命周期 ─────────────────────────────────────

    async def start(self) -> dict:
        """建立所有已启用连接并注册工具。任何单个 server 失败都不影响其它。

        返回 ``{"enabled", "started": [...], "failed": {name: 原因}, "tools_registered": n}``。
        """
        if self._started:
            return self._summary
        self._started = True
        summary = self._empty_summary()

        enabled, raw = load_servers_config(self.config_path, self._explicit_servers)
        if not enabled or not raw:
            logger.info(
                "MCP 客户端未启用（总开关=%s，server 数=%d），不建立任何连接",
                enabled, len(raw),
            )
            self._summary = summary
            return summary

        summary["enabled"] = True
        for name, data in raw.items():
            try:
                cfg = MCPServerConfig.from_dict(name, data)
            except MCPError as e:
                logger.error("MCP server %s 配置非法: %s", name, e)
                summary["failed"][name] = f"{e.kind}: {e.message}"
                continue
            if not cfg.enabled:
                logger.debug("MCP server %s 未启用，跳过", name)
                continue
            await self._connect_one(cfg, summary)

        self._summary = summary
        return summary

    async def _connect_one(self, cfg: MCPServerConfig, summary: dict) -> None:
        """连接单个 server 并注册其工具；失败只记录，不抛出。"""
        client = MCPServerClient(cfg)
        try:
            await client.connect()
            tools = await client.list_tools()
            result = client.register_tools(self.registry, tools)
        except MCPError as e:
            logger.error("MCP %s 连接失败: %s", cfg.name, e)
            summary["failed"][cfg.name] = f"{e.kind}: {e.message}"
            await client.close()
            return
        except Exception as e:  # 兜底：单个 server 不能带崩启动流程
            logger.exception("MCP %s 初始化异常", cfg.name)
            summary["failed"][cfg.name] = f"unexpected: {type(e).__name__}: {e}"
            await client.close()
            return

        self._clients[cfg.name] = client
        summary["started"].append(cfg.name)
        summary["tools_registered"] += len(result["registered"])
        if result["skipped"]:
            logger.warning("MCP %s: 跳过工具 %s", cfg.name, result["skipped"])
        logger.info("MCP %s 就绪：%d 个工具已注册", cfg.name, len(result["registered"]))

    async def aclose(self) -> None:
        """关闭所有连接（可重复调用）。"""
        for name, client in list(self._clients.items()):
            try:
                await client.close()
            except Exception:
                logger.exception("MCP %s 关闭异常", name)
        self._clients.clear()
        _reap_all_nowait()
        self._started = False

    def close_sync(self) -> None:
        """同步回收所有子进程（atexit / 进程退出路径）。"""
        for client in list(self._clients.values()):
            try:
                client.terminate_nowait()
            except Exception:
                pass
        self._clients.clear()
        _reap_all_nowait()

    async def __aenter__(self) -> "MCPClientManager":
        await self.start()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    # ── 查询 ─────────────────────────────────────────

    @property
    def started(self) -> bool:
        return self._started

    def client_names(self) -> list[str]:
        return list(self._clients.keys())

    def get_client(self, server_name: str) -> MCPServerClient | None:
        return self._clients.get(server_name)

    def summary(self) -> dict:
        """当前状态快照（可观测用）。"""
        return {
            **self._summary,
            "connected": sorted(n for n, c in self._clients.items() if c.connected),
            "tools": {
                n: sorted(c.registered_tools.keys()) for n, c in self._clients.items()
            },
        }

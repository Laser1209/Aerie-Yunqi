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


def _expand_env(value: str) -> str:
    """展开 ``${VAR}`` / ``$VAR`` 形态的环境变量引用。

    配置文件里用 ``Authorization: "Bearer ${NOTION_TOKEN}"`` 这种写法，可以让
    设置页写入的凭据（.env + os.environ）直接生效，不必把密钥抄进 YAML ——
    YAML 是会被提交进版本库的。
    """
    if not isinstance(value, str) or "$" not in value:
        return value
    return os.path.expandvars(value)


# transport 别名 → 内部标识。stdio 是子进程；其余都归到同一个 HTTP 实现
# （MCP 现行规范只有 stdio 与 Streamable HTTP 两种，SSE 是它的响应形态之一）。
_HTTP_TRANSPORTS = frozenset({"http", "https", "streamable-http", "streamable_http", "sse"})


def _env_suffix(name: str) -> str:
    """把 server 名转成可做环境变量后缀的形式（非字母数字一律换成下划线）。"""
    return _SAFE_NAME_RE.sub("_", str(name)).upper()


def _env_flag(*names: str) -> bool | None:
    """按顺序找第一个**被显式设置**的环境变量，返回其布尔值；都没设返回 None。

    为什么要这条路：设置页的开关如果直接改 ``config/mcp_servers.yaml``，就得整篇
    重写 YAML —— 那个文件里全是解释"为什么"的注释，一次 safe_dump 就全没了。
    改为「YAML 声明默认值（带注释、可提交）+ .env 存运行期开关（用户数据、不进
    版本库）」，与项目里 feature_flags 的 ``AERIE_FEATURE_*`` 是同一套范式。
    """
    for n in names:
        raw = os.environ.get(n)
        if raw is None or not str(raw).strip():
            continue
        return _as_bool(raw)
    return None


@dataclass
class MCPServerConfig:
    """单个 MCP server 的连接配置（stdio 子进程 或 远程 Streamable HTTP）。"""

    name: str
    transport: str = "stdio"
    # stdio
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    # http
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    timeout_seconds: float = 30.0
    call_timeout_seconds: float = 120.0
    enabled: bool = False

    @property
    def is_http(self) -> bool:
        return self.transport in _HTTP_TRANSPORTS

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "MCPServerConfig":
        if not isinstance(data, dict):
            raise MCPError("config", f"server '{name}' 配置必须是映射", server=name)
        transport = str(data.get("transport", "stdio") or "stdio").lower()
        if transport != "stdio" and transport not in _HTTP_TRANSPORTS:
            raise MCPError(
                "config",
                f"server '{name}' 使用不支持的 transport: {transport}"
                f"（支持 stdio / http）",
                server=name,
            )
        common = {
            "name": name,
            "transport": transport,
            "timeout_seconds": float(data.get("timeout_seconds", 30.0) or 30.0),
            "call_timeout_seconds": float(data.get("call_timeout_seconds", 120.0) or 120.0),
            "enabled": _as_bool(data.get("enabled", False)),
        }
        # .env 里的开关优先于 YAML 默认值（见 _env_flag 的说明）
        override = _env_flag(f"AERIE_MCP_SERVER_{_env_suffix(name)}")
        if override is not None:
            common["enabled"] = override

        if transport in _HTTP_TRANSPORTS:
            url = str(data.get("url") or "").strip()
            if not url:
                raise MCPError("config", f"server '{name}' 缺少 url", server=name)
            if not url.lower().startswith(("http://", "https://")):
                raise MCPError(
                    "config", f"server '{name}' 的 url 必须是 http(s) 地址", server=name
                )
            raw_headers = data.get("headers") or {}
            if not isinstance(raw_headers, dict):
                raise MCPError("config", f"server '{name}' 的 headers 必须是映射", server=name)
            return cls(
                url=url,
                headers={str(k): _expand_env(str(v)) for k, v in raw_headers.items()},
                **common,
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
            command=command,
            args=[str(a) for a in args],
            env={str(k): _expand_env(str(v)) for k, v in env.items()},
            cwd=str(cwd) if cwd else None,
            **common,
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
    override = _env_flag("AERIE_MCP_ENABLED")
    if override is not None:
        enabled = override
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


# ── HTTP 响应解析 ─────────────────────────────────────

_HTTP_BODY_SNIPPET = 400


def _short_body(text: str, limit: int = _HTTP_BODY_SNIPPET) -> str:
    """截断响应体，避免把整段 HTML/JSON 灌进日志与错误详情。"""
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _iter_sse_events(text: str) -> list[str]:
    """把 SSE 文本拆成各事件的 ``data`` 负载。

    只关心 ``data`` 字段：MCP 的流式响应把每条 JSON-RPC 消息放在一个 event 的
    data 里，前面可能还有 progress / message 之类的通知。``:`` 开头的是心跳
    注释，直接忽略。
    """
    events: list[str] = []
    data_lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip("\r")
        if not line:
            if data_lines:
                events.append("\n".join(data_lines))
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if data_lines:
        events.append("\n".join(data_lines))
    return events


def _response_from_sse(text: str, req_id: int) -> Any | None:
    """从 SSE 流里挑出 id 匹配的那条 JSON-RPC 响应。

    流里可能有若干通知（无 id 或 id 不匹配），真正属于本次请求的那条才是结果。
    """
    for payload in _iter_sse_events(text):
        try:
            msg = json.loads(payload)
        except Exception:
            continue
        if isinstance(msg, dict) and msg.get("id") == req_id:
            return msg
    return None


# ── 单个连接 ──────────────────────────────────────────

class MCPServerClient:
    """一个 MCP server 的连接（stdio 子进程 或 远程 Streamable HTTP）。

    生命周期：``connect()`` → ``list_tools()`` / ``call_tool()`` → ``close()``。
    连接对象不做自动重连；断了就报 ``process_exit`` / ``http_error``，
    由上层决定是否重建。
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
        # HTTP transport 的会话标识：服务端在 initialize 响应头上给出时，
        # 之后每个请求都要带回去（2025-06-18 规范；2026-07-28 起取消了会话）。
        self._http_session_id: str = ""

    # ── 观测 ─────────────────────────────────────────

    @property
    def connected(self) -> bool:
        if self.config.is_http:
            return not self._closed and bool(self.server_info)
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return False
        # M4: 读循环一旦退出（协议错误 / 进程结束）连接即不可用，
        # 不能只看 returncode——否则子进程还活着但读循环已死时会误报 True。
        task = self._stdout_task
        return task is not None and not task.done()

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail)

    # ── 生命周期 ─────────────────────────────────────

    async def connect(self) -> dict:
        """建立连接并完成 initialize 握手。返回 serverInfo。

        stdio：拉起子进程；http：直接对远端端点做握手（无子进程）。
        """
        if self.connected:
            return self.server_info
        self._closed = False
        if self.config.is_http:
            return await self._connect_http()
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
        except BaseException:
            # M2: 取消（CancelledError）/ 中断等同样要回收子进程。此处只用同步
            # 强杀：取消路径不能再 await；也不能只靠 atexit（os._exit 会绕过）。
            self.terminate_nowait()
            raise

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
            self.server_name, self.server_info.get("name") or self._endpoint_label(),
        )
        return self.server_info

    def _endpoint_label(self) -> str:
        """日志里怎么称呼这个 server：stdio 用命令，http 用地址。"""
        return self.config.url if self.config.is_http else self.config.command

    async def _connect_http(self) -> dict:
        """HTTP transport 的建连：没有子进程，只有一个 initialize 握手。"""
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
            self._closed = True
            raise MCPError(
                "handshake",
                f"initialize 失败（{e.kind}）: {e.message}",
                server=self.server_name,
                detail={**e.detail, "url": self.config.url, "cause": e.kind},
            ) from e

        if not isinstance(result, dict):
            self._closed = True
            raise MCPError("protocol", "initialize 返回非对象", server=self.server_name)

        self.protocol_version = str(result.get("protocolVersion") or "")
        self.server_info = result.get("serverInfo") or {}
        if self.protocol_version and self.protocol_version != PROTOCOL_VERSION:
            logger.warning(
                "MCP %s: 协商到协议版本 %s（本客户端为 %s）",
                self.server_name, self.protocol_version, PROTOCOL_VERSION,
            )
        await self._notify("notifications/initialized", {})
        logger.info(
            "MCP %s 已连接（http）: %s",
            self.server_name, self.server_info.get("name") or self.config.url,
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
            try:
                registry.register(
                    name=name,
                    func=self._make_callable(remote_name),
                    schema=self._to_openai_schema(name, remote_name, spec),
                    provider_hint="text",
                    category="mcp",
                )
            except Exception as e:
                # M3: 逐个工具隔离。某个工具注册失败只跳过它，不留半注册状态、
                # 不让整个 server 变成 failed（否则 registry 里残留可被模型看到、
                # 却因 _clients 无此连接而永远调不通的工具）。
                logger.warning(
                    "MCP %s: 工具 %s 注册失败，跳过（%s: %s）",
                    self.server_name, name, type(e).__name__, e,
                )
                skipped[name] = f"register_failed: {type(e).__name__}"
                continue
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
        if self.config.is_http:
            return await self._request_http(method, params, timeout=timeout)
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
            if self._stdout_task is None or self._stdout_task.done():
                # M4: 读循环已退出 → 连接不可用。立刻失败，别让调用白等满超时。
                raise MCPError(
                    "process_exit",
                    f"读取循环已停止，连接不可用（method={method}）",
                    server=self.server_name,
                    detail={"stderr": self.stderr_tail()},
                )
            loop = asyncio.get_running_loop()
            req_id = self._next_id
            self._next_id += 1
            future: asyncio.Future = loop.create_future()
            self._pending[req_id] = (future, method)
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            try:
                # M1: 写阶段也必须受超时保护。对端不读 stdin 时 stdout/stdin 管道
                # 写满，drain() 会永久阻塞并把整条连接（_lock）一起锁死。
                await asyncio.wait_for(self._write(payload), timeout=timeout)
            except asyncio.TimeoutError as e:
                self._pending.pop(req_id, None)
                # 管道已写满且对端不读 → 连接不可用，直接关停回收，避免后续调用继续卡
                await self.close()
                raise MCPError(
                    "timeout",
                    f"{method} 写入超时（{timeout}s）：对端未读取 stdin",
                    server=self.server_name,
                    detail={"timeout_seconds": timeout},
                ) from e
            try:
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
        if self.config.is_http:
            await self._notify_http(method, params)
            return
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # ── 内部：HTTP transport ──────────────────────────

    def _post_jsonrpc(self, payload: dict, *, timeout: float) -> tuple[int, dict, str]:
        """同步发一条 JSON-RPC 消息，返回 ``(status, headers, body_text)``。

        用 requests 而不是引入 aiohttp：项目已依赖 requests，且这里每次都是
        "发一条、等一条"的短交互，丢到线程里 await 就够，不值得为此加一个
        HTTP 客户端依赖。
        """
        import requests

        headers = {
            "Content-Type": "application/json",
            # 规范强制要求同时声明两种可接受的响应类型：服务端可能回一个单 JSON，
            # 也可能回 SSE 流（流里先带通知，最后才是本次响应）。
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol_version or PROTOCOL_VERSION,
        }
        headers.update(self.config.headers)
        if self._http_session_id:
            headers["Mcp-Session-Id"] = self._http_session_id

        resp = requests.post(
            self.config.url, json=payload, headers=headers, timeout=timeout
        )
        # 服务端可能在 initialize 的响应头上分配会话 id，之后每个请求都要带回去。
        session_id = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if session_id:
            self._http_session_id = session_id
        return resp.status_code, dict(resp.headers), resp.text

    def _parse_http_body(self, body: str, content_type: str, req_id: int) -> Any | None:
        """从响应体里取出**属于本次请求**的那条 JSON-RPC 消息（单 JSON 与 SSE 都支持）。

        id 必须对得上：`id` 不符说明拿到的是别的请求的结果（或一条通知），
        把它当成本次结果返回就是静默的数据串台。
        """
        if "text/event-stream" in str(content_type or "").lower():
            return _response_from_sse(body, req_id)
        try:
            data = json.loads(body)
        except Exception:
            return None
        # 批量响应（数组）在本客户端用不到，但收到时按 id 挑出我们那条更稳妥。
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id") == req_id:
                    return item
            return None
        if not isinstance(data, dict):
            return None
        if data.get("id") == req_id:
            return data
        # 少数实现会省略 id；只要它确实是"一条响应"（带 result / error）就接受，
        # 否则判定为不属于本次请求。
        if "id" not in data and ("result" in data or "error" in data):
            return data
        return None

    async def _request_http(self, method: str, params: dict, *, timeout: float) -> Any:
        if self._closed:
            raise MCPError(
                "closed", f"连接不可用（method={method}）", server=self.server_name
            )
        async with self._lock:
            req_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            try:
                status, headers, body = await asyncio.wait_for(
                    asyncio.to_thread(self._post_jsonrpc, payload, timeout=timeout),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as e:
                raise MCPError(
                    "timeout",
                    f"{method} 超时（{timeout}s）",
                    server=self.server_name,
                    detail={"timeout_seconds": timeout, "url": self.config.url},
                ) from e
            except MCPError:
                raise
            except Exception as e:
                raise MCPError(
                    "http_error",
                    f"{method} 请求失败: {type(e).__name__}: {e}",
                    server=self.server_name,
                    detail={"url": self.config.url},
                ) from e

            if status in (401, 403):
                raise MCPError(
                    "auth",
                    f"{method} 鉴权失败（HTTP {status}）：请到设置页检查该平台的凭据",
                    server=self.server_name,
                    detail={"status": status, "body": _short_body(body)},
                )
            if status >= 400:
                raise MCPError(
                    "http_error",
                    f"{method} 返回 HTTP {status}: {_short_body(body)}",
                    server=self.server_name,
                    detail={"status": status, "url": self.config.url},
                )

            msg = self._parse_http_body(body, headers.get("Content-Type", ""), req_id)
            if msg is None:
                # 拿到了 2xx 却没有我们这条 id 的结果 —— 如实报，不要返回空当成功
                raise MCPError(
                    "protocol",
                    f"{method} 响应里缺少 id={req_id} 的结果",
                    server=self.server_name,
                    detail={
                        "status": status,
                        "content_type": headers.get("Content-Type", ""),
                        "body": _short_body(body),
                    },
                )
            if msg.get("error") is not None:
                raise self._remote_error(method, msg.get("error"))
            return msg.get("result")

    async def _notify_http(self, method: str, params: dict) -> None:
        """HTTP 通知：发出去即可，服务端通常回 202 且无响应体。"""
        if self._closed:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            await asyncio.to_thread(
                self._post_jsonrpc, payload, timeout=self.config.timeout_seconds
            )
        except Exception:
            # 通知失败不该让整个握手/调用失败：规范里它本就没有响应可等。
            logger.debug(
                "MCP %s: 通知 %s 发送失败", self.server_name, method, exc_info=True
            )

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

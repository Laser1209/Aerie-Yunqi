"""Aerie · 云栖 — DSH stdio JSON-RPC 桥(手写,不依赖 deepseek-harness-sdk)。

L1 前后台分离模式的后台执行通道:异步拉起 DSH node 闭包子进程,经 stdio 收发
JSON-RPC 帧,把任务委托给场景 Preset 执行并回收结果。

设计要点:
- 手写 JSON-RPC 桥,绕开 SDK 的 pydantic 依赖冲突(V7)。协议已由 tools/dsh_poc.py
  实测验证:initialize / session/prompt / shutdown 三个方法 + session.event /
  session.status 通知流。
- 全程 asyncio(Aerie 硬约束),进程生命周期复用 napcat_launcher + 24h watchdog
  的崩溃拉起/熔断经验。
- 日志分级:DEBUG=帧级收发,INFO=生命周期,WARNING=重启/降级/非致命诊断,
  ERROR=崩溃/超时/熔断。所有日志 key 脱敏。

配置来源(优先级从高到低):构造函数参数 > 环境变量 > 模块默认值。
DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL 由 main.py 的 load_dotenv 注入 os.environ。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# node 闭包运行时入口(DSH 仓库 deploy 产物,V19 固化后由部署脚本保证存在)。
# 主仓库 packages/examples 的 build 产物不能直接用(V19:裸插件解析失败)。
_DEFAULT_DSH_ENTRY = Path(
    r"E:\DeepSeek Hermes\python\sdk-runtime\src\deepseek_harness_runtime"
    r"\runtime\node\node_modules\@deepseek-ai\dsh-sdk-jsonrpc-demo\lib\packaged-bin.js"
)
# 默认 cordis.yml(SDK runtime 检入的默认组合:jsonrpc server + agent core + llm-deepseek)。
_DEFAULT_CORDIS = Path(
    r"E:\DeepSeek Hermes\python\sdk-runtime\src\deepseek_harness_runtime"
    r"\runtime\cordis.yml"
)

# 崩溃重启与熔断阈值
_RESTART_LIMIT = 2
_CIRCUIT_OPEN_SECONDS = 300.0
_INITIALIZE_TIMEOUT = 60.0
_DEFAULT_DELEGATE_TIMEOUT = 600.0
_SHUTDOWN_TIMEOUT = 5.0

# 进度播报的节流窗口(秒),避免 step/tool 事件刷屏
_NOTICE_THROTTLE_SECONDS = 0.5

_NOTICE_EVENT_PREFIXES = ("step/", "tool/", "subagent/")


@dataclass(slots=True)
class DshRunResult:
    """一次委托轮次的收尾结果(对齐官方 SDK RunResult 的语义)。"""

    session_id: str
    final_response: str
    finish_reason: str | None
    events: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


class DshError(Exception):
    """DSH 桥层基础异常。"""


class DshCircuitOpen(DshError):
    """熔断中,委托被拒绝(路由应降级 LLMCaller)。"""


class DshTimeout(DshError):
    """请求超时。"""


class DshTransportClosed(DshError):
    """运行时进程 stdout 关闭 / 进程退出,通信中断。"""


class DshProtocolError(DshError):
    """JSON-RPC 协议异常(缺字段 / 帧非法)。"""


class DshCli:
    """手写 JSON-RPC 桥,异步驱动 DSH node 闭包子进程。"""

    def __init__(
        self,
        *,
        entry: str | Path | None = None,
        cordis: str | Path | None = None,
        provider: str = "deepseek-official",
        model: str = "deepseek-chat",
        session_root: str | Path | None = None,
        cwd: str | Path | None = None,
        request_timeout_s: float = _DEFAULT_DELEGATE_TIMEOUT,
    ) -> None:
        self._entry = Path(entry) if entry else Path(os.environ.get("DSH_RUNTIME_ENTRY", _DEFAULT_DSH_ENTRY))
        self._cordis = Path(cordis) if cordis else Path(os.environ.get("DSH_CORDIS_CONFIG", _DEFAULT_CORDIS))
        self._provider = provider
        self._model = model
        self._session_root = Path(session_root) if session_root else Path(os.environ.get("DSH_SESSION_ROOT", _default_session_root()))
        self._cwd = Path(cwd) if cwd else Path(os.environ.get("DSH_CWD", str(Path(__file__).resolve().parent.parent)))
        self._request_timeout_s = request_timeout_s

        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: list[str] = []
        self._restart_count = 0
        self._circuit_open_until = 0.0
        self._sessions: dict[str, str] = {}  # preset -> session_id(会话复用)
        self._seq = 0

    # ------------------------------------------------------------------ 状态

    async def status(self) -> dict:
        """返回 {running, degraded, restart_count, sessions, entry, model}。"""
        running = self._proc is not None and self._proc.returncode is None
        return {
            "running": running,
            "degraded": self._is_circuit_open(),
            "restart_count": self._restart_count,
            "sessions": dict(self._sessions),
            "entry": str(self._entry),
            "provider": self._provider,
            "model": self._model,
        }

    def _is_circuit_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    # ------------------------------------------------------------ 进程生命周期

    async def ensure_running(self, preset: str | None = None) -> None:
        """懒启动:进程不存在或已退出时拉起,并完成 initialize 握手。

        崩溃自动重启 ≤_RESTART_LIMIT 次,超过则熔断 _CIRCUIT_OPEN_SECONDS。
        """
        if self._proc is not None and self._proc.returncode is None:
            return
        if self._is_circuit_open():
            raise DshCircuitOpen(f"DSH 熔断中,剩余 {self._circuit_open_until - time.monotonic():.0f}s")

        if not self._entry.is_file():
            logger.error("[dsh] node 入口不存在: %s (需先固化 V19 的 deploy 闭包)", self._entry)
            raise DshError(f"DSH runtime entry 缺失: {self._entry}")

        node = shutil.which("node")
        if node is None:
            logger.error("[dsh] 系统无 node 可执行文件(需 >=22.19)")
            raise DshError("system node not found")

        env = self._build_env()
        logger.info(
            "[dsh] 启动运行时 entry=%s node=%s provider=%s model=%s session_root=%s",
            self._entry, node, self._provider, self._model, self._session_root,
        )
        self._proc = await asyncio.create_subprocess_exec(
            node, str(self._entry),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._cwd),
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout_loop(), name="dsh-stdout")
        self._stderr_task = asyncio.create_task(self._read_stderr_loop(), name="dsh-stderr")
        logger.info("[dsh] 子进程已拉起 pid=%s", self._proc.pid)

        try:
            await self._request(
                "initialize",
                {"cwd": str(self._cwd), "provider": self._provider, "model": self._model},
                timeout=_INITIALIZE_TIMEOUT,
            )
            logger.info("[dsh] initialize 握手成功(pid=%s)", self._proc.pid)
            self._restart_count = 0
        except Exception:
            logger.error("[dsh] initialize 握手失败,stderr 尾部:\n%s", self._stderr_diag())
            await self._teardown_proc()
            raise

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        # key 只进子进程环境,不进日志;base_url 允许打印
        env["DSH_CORDIS_CONFIG"] = str(self._cordis)
        env["DSH_SESSION_ROOT"] = str(self._session_root)
        env["DSH_CWD"] = str(self._cwd)
        env["DSH_RUNTIME_MODE"] = "node"
        return env

    async def _teardown_proc(self) -> None:
        proc, self._proc = self._proc, None
        self._fail_pending(DshTransportClosed("runtime terminated during restart"))
        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def stop(self) -> None:
        """优雅关闭:shutdown 请求 → 关 stdin → terminate → kill。"""
        proc = self._proc
        if proc is None:
            return
        logger.info("[dsh] 正在优雅关闭(pid=%s)", proc.pid)
        try:
            await self._request("shutdown", None, timeout=_SHUTDOWN_TIMEOUT)
            logger.debug("[dsh] shutdown 响应已收到")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dsh] shutdown 请求异常,回退强制终止: %s", exc)
        await self._teardown_proc()
        logger.info("[dsh] 已关闭")

    # ----------------------------------------------------------------- 委托

    async def delegate(
        self,
        task: str,
        *,
        preset: str,
        session_id: str | None = None,
        persona_brief: str | None = None,
        system_prompt: str | None = None,
        cordis: str | Path | None = None,
        on_notice: Callable[[dict], Awaitable[None]] | None = None,
        timeout_s: float | None = None,
    ) -> DshRunResult:
        """把一条工作型任务委托给 DSH 执行,阻塞直到轮次 idle。

        参数:
          task: 用户原始任务文本(作为 user content)。
          preset: 场景名(会话复用的键 + 日志溯源)。
          session_id: 显式指定续接的历史会话;None 时按 preset 默认复用/新建。
          persona_brief: 可选人格投影,作为第一条 text block 注入(仅名字/语气/称呼)。
          system_prompt: 可选协议输出约束,作为第一条 text block 注入。
          cordis: 覆盖本场景的 cordis.yml(对应 work_presets.yaml 的 dsh_cordis)。
          on_notice: 进度回调,收到 step/tool/subagent 事件时节流调用。
        """
        if self._is_circuit_open():
            raise DshCircuitOpen("DSH 熔断中")

        saved_cordis = self._cordis
        if cordis is not None:
            self._cordis = Path(cordis)
        try:
            await self.ensure_running(preset)
            if session_id is None:
                session_id = self._sessions.setdefault(preset, self._new_session_id(preset))
            else:
                # 显式续接历史会话:记录该 preset 当前会话,后续无显式指定时沿用。
                self._sessions[preset] = session_id

            content_blocks: list[dict] = []
            if system_prompt:
                content_blocks.append({"type": "text", "text": system_prompt})
            if persona_brief:
                content_blocks.append({"type": "text", "text": persona_brief})
            content_blocks.append({"type": "text", "text": task})

            logger.info(
                "[dsh] delegate preset=%s session=%s task_len=%d persona_brief=%s",
                preset, session_id, len(task), "yes" if persona_brief else "no",
            )
            t_start = time.monotonic()
            await self._request(
                "session/prompt",
                {"sessionId": session_id, "contentBlocks": content_blocks},
                timeout=timeout_s or self._request_timeout_s,
            )

            result = await self._wait_for_idle(
                session_id,
                on_notice=on_notice,
                timeout_s=timeout_s or self._request_timeout_s,
            )
            elapsed = time.monotonic() - t_start
            logger.info(
                "[dsh] delegate 完成 preset=%s session=%s finish=%s elapsed=%.2fs reply_len=%d",
                preset, session_id, result.finish_reason, elapsed, len(result.final_response),
            )
            return result
        except (DshCircuitOpen, DshError, DshTimeout, DshTransportClosed, DshProtocolError):
            raise
        except Exception as exc:  # noqa: BLE001
            # 非预期异常:尝试重启一次,失败则向上抛(路由层降级)
            logger.error("[dsh] delegate 非预期异常: %s", exc, exc_info=True)
            await self._handle_crash()
            raise DshTransportClosed(f"delegate failed: {exc}") from exc
        finally:
            self._cordis = saved_cordis

    async def _wait_for_idle(
        self,
        session_id: str,
        *,
        on_notice: Callable[[dict], Awaitable[None]] | None,
        timeout_s: float,
    ) -> DshRunResult:
        """消费通知队列直到该会话进入 idle/error,提取结果与 usage。"""
        events: list[dict] = []
        usage: dict = {}
        last_notice = 0.0
        deadline = time.monotonic() + timeout_s

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DshTimeout(f"session {session_id} 等待 idle 超时({timeout_s:.0f}s)")
            try:
                note = await asyncio.wait_for(self._notifications.get(), timeout=remaining)
            except asyncio.TimeoutError:
                raise DshTimeout(f"session {session_id} 等待 idle 超时({timeout_s:.0f}s)")

            method = note.get("method")
            params = note.get("params") or {}
            if method == "session.event" and params.get("sessionId") == session_id:
                event = params.get("event") or {}
                events.append(event)
                _merge_usage(usage, event)
                if on_notice is not None and self._should_notice(event, last_notice):
                    last_notice = time.monotonic()
                    await on_notice({"session_id": session_id, "event": event})
            elif method == "session.status" and params.get("sessionId") == session_id:
                status = params.get("status")
                logger.debug("[dsh] session.status session=%s status=%s", session_id, status)
                if status == "idle":
                    return DshRunResult(
                        session_id=session_id,
                        final_response=_final_response(events),
                        finish_reason=_finish_reason(events),
                        events=events,
                        usage=usage,
                    )
                if status == "error":
                    return DshRunResult(
                        session_id=session_id,
                        final_response=_final_response(events),
                        finish_reason="error",
                        events=events,
                        usage=usage,
                    )

    def _should_notice(self, event: dict, last_notice: float) -> bool:
        etype = str(event.get("type") or "")
        if not etype.startswith(_NOTICE_EVENT_PREFIXES):
            return False
        return time.monotonic() - last_notice >= _NOTICE_THROTTLE_SECONDS

    # ------------------------------------------------------------ 崩溃与重启

    async def _handle_crash(self) -> None:
        """进程崩溃后的重启逻辑:≤_RESTART_LIMIT 次,否则熔断。"""
        self._restart_count += 1
        logger.warning("[dsh] 检测到崩溃,第 %d 次重启(上限 %d)", self._restart_count, _RESTART_LIMIT)
        await self._teardown_proc()
        if self._restart_count > _RESTART_LIMIT:
            self._circuit_open_until = time.monotonic() + _CIRCUIT_OPEN_SECONDS
            logger.error(
                "[dsh] 重启 %d 次仍失败,熔断 %.0fs,期间路由应降级 LLMCaller",
                self._restart_count, _CIRCUIT_OPEN_SECONDS,
            )
            raise DshCircuitOpen(f"DSH 重启 {self._restart_count} 次后熔断")
        # 清空会话缓存,重启后重新 initialize
        self._sessions.clear()

    # ------------------------------------------------------------- JSON-RPC 收发

    def _new_session_id(self, preset: str) -> str:
        # session id 跨进程持久化(DSH_SESSION_ROOT),必须全局唯一;递增序号会与
        # 重启前的旧 session 碰撞(导致 session/prompt 落到已完结 session 上报 error)。
        return f"dsh-{preset}-{uuid.uuid4().hex[:12]}"

    def _next_id(self) -> str:
        self._seq += 1
        return str(self._seq)

    async def _request(self, method: str, params: object, *, timeout: float) -> dict:
        req_id = self._next_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        await self._write_frame(msg)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise DshTimeout(f"{method} 超时({timeout:.0f}s)\n{self._stderr_diag()}")
        finally:
            self._pending.pop(req_id, None)

    async def _write_frame(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise DshTransportClosed("runtime not running")
        logger.debug("[dsh] → %s", _summarize_frame(message))
        payload = json.dumps(message, separators=(",", ":")) + "\n"
        try:
            proc.stdin.write(payload.encode("utf-8"))
            await proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError) as exc:
            raise DshTransportClosed(f"write failed: {exc}") from exc

    async def _read_stdout_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        buffer = b""
        try:
            while True:
                # read() 读块,单行无 64KB 限制;readline 在超长 JSON 帧(含大段
                # reasoning 文本)上会抛 "Separator is found, but chunk is longer
                # than limit",导致整个读取循环崩溃。
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    logger.warning("[dsh] stdout EOF(进程退出或管道关闭)")
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._handle_line(line)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("[dsh] stdout 读取异常: %s", exc)
        finally:
            self._fail_pending(DshTransportClosed("runtime stdout closed"))
            if self._proc is not None and self._proc.returncode is not None:
                await self._handle_crash()

    def _handle_line(self, line: bytes) -> None:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("[dsh] stdout 非 JSON 帧忽略: %s", text[:200])
            return
        self._handle_message(message)

    def _handle_message(self, message: object) -> None:
        if not isinstance(message, dict):
            return
        msg_id = message.get("id")
        method = message.get("method")
        # 响应帧(有 id 无 method)
        if isinstance(msg_id, (str, int)) and not isinstance(method, str):
            logger.debug("[dsh] ← resp id=%s %s", msg_id, _summarize_value(message.get("result", message.get("error"))))
            fut = self._pending.get(str(msg_id))
            if fut is not None and not fut.done():
                if isinstance(message.get("error"), dict):
                    fut.set_exception(DshProtocolError(str(message["error"])))
                else:
                    fut.set_result(message.get("result"))
            return
        # 运行时发来的请求(有 id 有 method,如审批)——L1 暂不处理
        if isinstance(msg_id, (str, int)) and isinstance(method, str):
            logger.warning("[dsh] ← 收到运行时请求 method=%s id=%s(L1 不处理)", method, msg_id)
            return
        # 通知帧(无 id 有 method)
        if isinstance(method, str):
            logger.debug("[dsh] ← evt %s", _summarize_frame(message))
            try:
                self._notifications.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("[dsh] 通知队列满,丢弃一帧: %s", method)

    async def _read_stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self._stderr_tail.append(text)
                    if len(self._stderr_tail) > 400:
                        del self._stderr_tail[:-400]
                    logger.debug("[dsh:stderr] %s", text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("[dsh] stderr 读取结束: %s", exc)

    def _fail_pending(self, exc: BaseException) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    def _stderr_diag(self) -> str:
        return "\n".join(self._stderr_tail[-20:]) or "(无 stderr 输出)"


# ------------------------------------------------------------------ 工具函数

def _default_session_root() -> Path:
    try:
        from core.paths import data_dir

        return data_dir() / "dsh_sessions"
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parent.parent / "data" / "dsh_sessions"


def _final_response(events: list[dict]) -> str:
    for event in reversed(events):
        if event.get("type") != "assistant/message":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        message = data.get("message")
        content_owner = message if isinstance(message, dict) else data
        content = content_owner.get("content")
        if not isinstance(content, list):
            continue
        parts = [
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)
    return ""


def _finish_reason(events: list[dict]) -> str | None:
    for event in reversed(events):
        if event.get("type") != "turn/end":
            continue
        data = event.get("data")
        if isinstance(data, dict):
            reason = data.get("reason")
            if isinstance(reason, dict) and isinstance(reason.get("kind"), str):
                return reason["kind"]
    return None


def _merge_usage(usage: dict, event: dict) -> None:
    """从 assistant/chunk(type=usage) 或 assistant/message 事件提取 token usage。

    DSH 流式事件里 usage 落在 assistant/chunk 的 chunk.type=="usage",
    而 assistant/message 通常不含 usage 字段,故两者都要扫。
    """
    etype = event.get("type")
    data = event.get("data")
    if not isinstance(data, dict):
        return
    candidate: dict | None = None
    if etype == "assistant/chunk":
        chunk = data.get("chunk")
        if isinstance(chunk, dict) and chunk.get("type") == "usage":
            candidate = chunk.get("usage") if isinstance(chunk.get("usage"), dict) else None
    elif etype == "assistant/message":
        message = data.get("message")
        owner = message if isinstance(message, dict) else data
        candidate = owner.get("usage") if isinstance(owner.get("usage"), dict) else None
    if not isinstance(candidate, dict):
        return
    for k, v in candidate.items():
        if isinstance(v, (int, float)):
            usage[k] = usage.get(k, 0) + v


def _summarize_frame(message: dict) -> str:
    """压缩一帧为日志友好的一行(截断长文本,不泄露敏感字段)。"""
    parts: list[str] = []
    if isinstance(message.get("id"), (str, int)):
        parts.append(f"id={message['id']}")
    method = message.get("method")
    if isinstance(method, str):
        parts.append(f"method={method}")
    params = message.get("params")
    if isinstance(params, dict):
        parts.append(f"params={_summarize_value(params)}")
    result = message.get("result")
    if isinstance(result, dict):
        parts.append(f"result={_summarize_value(result)}")
    if isinstance(message.get("error"), dict):
        parts.append(f"error={message['error'].get('message')}")
    return " ".join(parts) or "(空帧)"


def _summarize_value(value: object, limit: int = 200) -> str:
    if isinstance(value, dict):
        # 脱敏:排除 api_key/token 类字段
        safe = {
            k: v for k, v in value.items()
            if not any(s in k.lower() for s in ("key", "token", "secret", "password"))
        }
        text = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
        return text if len(text) <= limit else text[:limit] + f"...({len(text)} chars)"
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"...({len(value)} chars)"
    if isinstance(value, (list, tuple)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return text if len(text) <= limit else text[:limit] + f"...({len(text)} chars)"
    return str(value)


__all__ = [
    "DshCli",
    "DshRunResult",
    "DshError",
    "DshCircuitOpen",
    "DshTimeout",
    "DshTransportClosed",
    "DshProtocolError",
]

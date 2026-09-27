"""越界写入的授权桥（1.2b）。

office 写工具是同步函数，无法在写守卫内等待用户确认；因此由
``core.llm_caller`` 的 ReAct 工具循环（异步）在拿到「越界」结果后调用本模块：

1. ``request`` 登记一次待确认请求并返回请求 ID；
2. ``emit("write_auth_required")`` 推给桌面端弹出审批卡片；
3. ``wait`` 异步等待桌面端决策（``POST /api/agent/write-approval`` 落 ``resolve``）；
4. 放行则把目标目录加入工作区临时根，并**只重试该次工具调用**（不重跑整轮）。

拒绝或超时保持原错误结果，不改变任何既有行为。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 60.0
_OUT_OF_ROOT_REASON = "outside_workspace_roots"


@dataclass
class _PendingWrite:
    path: str
    tool: str
    future: asyncio.Future


_pending: dict[str, _PendingWrite] = {}


def _enabled() -> bool:
    """读 write_approval_v1 开关；读取失败一律视为关闭（保持原行为）。"""
    try:
        from core.feature_flags import FeatureFlags

        return FeatureFlags().is_enabled("write_approval_v1") is True
    except Exception:
        logger.debug("write_approval flag read failed", exc_info=True)
        return False


def _timeout_seconds() -> float:
    """等待桌面端确认的上限，读 settings.office.write_approval_timeout_sec。"""
    try:
        from config.persona_loader import load_settings

        cfg = (load_settings() or {}).get("office") or {}
        value = cfg.get("write_approval_timeout_sec")
        if value is not None:
            return max(5.0, float(value))
    except Exception:
        logger.debug("write_approval timeout read failed", exc_info=True)
    return _DEFAULT_TIMEOUT_SECONDS


def request(path: str, tool: str) -> str:
    """登记待确认的越界写入，返回请求 ID。"""
    loop = asyncio.get_running_loop()
    req_id = f"wappr_{uuid.uuid4().hex[:12]}"
    _pending[req_id] = _PendingWrite(path=path, tool=tool, future=loop.create_future())
    return req_id


def resolve(req_id: str, approved: bool) -> bool:
    """桌面端决策回调；未知或已结束的 ID 返回 False。"""
    entry = _pending.pop(req_id, None)
    if entry is None:
        return False
    if not entry.future.done():
        entry.future.set_result(bool(approved))
    return True


async def wait(req_id: str, timeout: float | None = None) -> bool:
    """等待桌面端决策；超时/取消视为拒绝并清理该请求。"""
    entry = _pending.get(req_id)
    if entry is None:
        return False
    try:
        return await asyncio.wait_for(
            asyncio.shield(entry.future),
            timeout=timeout if timeout is not None else _timeout_seconds(),
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        _pending.pop(req_id, None)
        logger.info("越界写入授权等待结束（未确认）: %s", entry.path)
        return False


def pending() -> list[dict[str, Any]]:
    """当前待确认列表（供前端刷新后补齐展示）。"""
    return [
        {"id": req_id, "path": entry.path, "tool": entry.tool}
        for req_id, entry in list(_pending.items())
        if not entry.future.done()
    ]


def clear() -> None:
    """测试/停机清理：所有待确认一律按拒绝结束。"""
    for req_id in list(_pending):
        resolve(req_id, False)


def register_write_root(target: str) -> str | None:
    """把越界目标所在目录加入工作区临时根；成功返回该根，失败返回 None。"""
    raw = str(target or "").strip().strip('"').strip("'")
    if not raw:
        return None
    try:
        path = Path(raw).expanduser()
        root = path if path.is_dir() else path.parent
        if not str(root):
            return None
        from core.workspace import get_workspace_manager

        if get_workspace_manager().add_temp_root(str(root)):
            return str(root)
    except Exception:
        logger.exception("register_write_root failed: %s", raw)
    return None


async def maybe_retry_after_block(
    tool_registry: Any,
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    success: bool,
) -> tuple[Any, bool]:
    """工具循环钩子：越界写入 → 请求授权 → 放行则加根并只重试该次调用。"""
    if success or not isinstance(result, dict):
        return result, success
    if result.get("reason") != _OUT_OF_ROOT_REASON:
        return result, success
    if not _enabled():
        return result, success

    target = str(
        args.get("destination")
        or args.get("directory")
        or args.get("filepath")
        or ""
    ).strip()
    if not target:
        return result, success

    req_id = request(target, tool_name)
    _emit_request(req_id, target, tool_name)
    if not await wait(req_id):
        return result, success

    root = register_write_root(target)
    if root is None:
        logger.warning("写入授权已放行，但工作区根注册失败: %s", target)
        return result, success

    logger.info("越界写入已授权，重试该次工具调用: %s → %s", tool_name, root)
    try:
        retried = await tool_registry.execute(tool_name, args)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}, False
    return retried, not (isinstance(retried, dict) and "error" in retried)


def _emit_request(req_id: str, path: str, tool: str) -> None:
    try:
        from core.chat_events import emit

        emit("write_auth_required", id=req_id, path=path, tool=tool)
    except Exception:
        logger.debug("write_auth_required emit failed", exc_info=True)

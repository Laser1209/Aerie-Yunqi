"""Aerie · 云栖 — WorkProtocol 执行器(形态 B 核心契约)。

解析 DSH 产出的操作协议 JSON,分发到既有安全管线(ComputerController /
FileOrganizer / DocWriter)执行,返回逐条执行结果。

设计要点:
- 协议 Schema 校验先行,非法协议直接 ProtocolError 拒绝(不碰任何 Controller)。
- 安全由既有 Controller 内部保证(ComputerController 的 _gate 硬闸 + AccessPolicy
  四模式裁决 + _audit 审计;FileOrganizer 的 preview→execute→undo 事务链),
  本执行器不重写安全逻辑,只做协议 → 方法调用 → 结果映射。
- Controller 方法均为同步,经 asyncio.to_thread 包装避免阻塞事件循环。
- 日志埋点与 dsh_cli.py 对齐:DEBUG=逐 op 分发,INFO=协议级生命周期,WARNING=降级/未放行,ERROR=协议异常。

status 枚举(每条 op):ok | denied | pending_approval | failed
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from core.computer_control import ComputerController, ControlResult
from core.doc_writer import DocType, DocWriter, ExportFormat
from core.file_organizer import FileOrganizer, OrganizePlan

logger = logging.getLogger(__name__)

# 协议支持的 task_type
_TASK_TYPES = {"computer_control", "file_organize", "doc_write"}

# computer_control 协议的 op 枚举 → ComputerController 方法名(一一对应)
_COMPUTER_OP_METHODS: dict[str, str] = {
    "shell_execute": "shell_execute",
    "type_text": "type_text",
    "key_press": "key_press",
    "hotkey": "hotkey",
    "mouse_move": "mouse_move",
    "mouse_click": "mouse_click",
    "mouse_scroll": "mouse_scroll",
    "take_screenshot": "take_screenshot",
    "focus_window": "focus_window",
    "list_windows": "list_windows",
    "uia_action": "uia_action",
}

# doc_write 协议的 doc_type → DocType 枚举
_DOC_TYPE_MAP: dict[str, DocType] = {
    "diary": DocType.DIARY,
    "report": DocType.REPORT,
    "spec": DocType.SPEC,
    "research": DocType.RESEARCH,
    "resume": DocType.RESUME,
}


class ProtocolError(Exception):
    """WorkProtocol 非法(未知 task_type / Schema 缺失 / op 非法)。"""


@dataclass(slots=True)
class OpResult:
    """单条 op 的执行结果(对齐设计文档 §5.2)。"""

    op: str
    status: str  # ok | denied | pending_approval | failed
    detail: str
    audit_id: str = ""


class WorkProtocolExecutor:
    """解析并执行 DSH 操作协议,直调既有 Controller(不经过 tool_registry)。"""

    def __init__(
        self,
        computer: ComputerController | None = None,
        file_organizer: FileOrganizer | None = None,
        doc_writer: DocWriter | None = None,
        workspace: Any = None,
    ) -> None:
        self._computer = computer or ComputerController()
        self._file_organizer = file_organizer or FileOrganizer()
        self._doc_writer = doc_writer or DocWriter()
        # v0.4.2: 工作区写操作权限门控(与电脑操控共用权限模式)
        self._workspace = workspace

    async def execute(self, protocol: dict, *, source: str = "dsh") -> list[dict]:
        """解析协议并分发到安全管线。

        返回逐条执行结果 [{op, status, detail, audit_id}]。
        协议非法抛 ProtocolError;单条 op 执行失败不中断整批,记 failed 继续。
        """
        task_type, plan, meta = self._validate(protocol)
        logger.info(
            "[wprotocol] execute task_type=%s persona_id=%s session_id=%s source=%s goal=%s",
            task_type, meta["persona_id"], meta["session_id"], source, meta["goal"][:120],
        )

        try:
            if task_type == "computer_control":
                results = await self._execute_computer(plan, source)
            elif task_type == "file_organize":
                results = await self._execute_file(plan, source)
            else:  # doc_write
                results = await self._execute_doc(plan, source)
        except ProtocolError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("[wprotocol] 执行异常 task_type=%s: %s", task_type, exc, exc_info=True)
            raise

        ok_count = sum(1 for r in results if r.status == "ok")
        logger.info(
            "[wprotocol] execute 完成 task_type=%s total=%d ok=%d",
            task_type, len(results), ok_count,
        )
        return [
            {"op": r.op, "status": r.status, "detail": r.detail, "audit_id": r.audit_id}
            for r in results
        ]

    # ---------------------------------------------------------------- 校验

    def _validate(self, protocol: dict) -> tuple[str, Any, dict]:
        """校验协议 Schema,返回 (task_type, plan, meta)。"""
        if not isinstance(protocol, dict):
            raise ProtocolError("protocol 必须是 JSON object")

        version = protocol.get("protocol_version")
        if version != 1:
            logger.error("[wprotocol] 非法 protocol_version=%r", version)
            raise ProtocolError(f"unsupported protocol_version={version!r}(当前仅支持 1)")

        task_type = protocol.get("task_type")
        if task_type not in _TASK_TYPES:
            logger.error("[wprotocol] 未知 task_type=%r", task_type)
            raise ProtocolError(f"unknown task_type={task_type!r}")

        persona_id = protocol.get("persona_id")
        session_id = protocol.get("session_id")
        goal = protocol.get("goal")
        plan = protocol.get("plan")
        if not isinstance(persona_id, str) or not persona_id:
            raise ProtocolError("persona_id 缺失或非字符串")
        if not isinstance(session_id, str) or not session_id:
            raise ProtocolError("session_id 缺失或非字符串")
        if not isinstance(goal, str) or not goal:
            raise ProtocolError("goal 缺失或非字符串")
        if plan is None:
            raise ProtocolError("plan 缺失")

        logger.debug(
            "[wprotocol] 校验通过 task_type=%s plan=%s",
            task_type, _summarize(plan),
        )
        meta = {"persona_id": persona_id, "session_id": session_id, "goal": goal}
        return task_type, plan, meta

    # ------------------------------------------------------ 各 task_type 执行

    async def _execute_computer(self, plan: Any, source: str) -> list[OpResult]:
        ops = self._normalize_ops(plan)
        results: list[OpResult] = []
        for op in ops:
            op_name = op.get("op") if isinstance(op, dict) else None
            method = _COMPUTER_OP_METHODS.get(op_name) if isinstance(op_name, str) else None
            if method is None:
                results.append(OpResult(op=str(op_name), status="failed", detail="未知 op"))
                logger.warning("[wprotocol] 未知 computer op=%r,跳过", op_name)
                continue

            args = op.get("args") if isinstance(op, dict) else None
            args = args if isinstance(args, dict) else {}
            logger.debug(
                "[wprotocol] computer op=%s args=%s source=%s",
                op_name, _summarize(args), source,
            )
            try:
                fn = getattr(self._computer, method)
                result: ControlResult = await asyncio.to_thread(fn, **args)
                results.append(_map_control_result(op_name, result))
            except TypeError as exc:
                # args 与 Controller 方法签名不匹配 → 协议非法
                results.append(OpResult(op=op_name, status="failed", detail=f"参数不匹配: {exc}"))
                logger.error("[wprotocol] computer op=%s 参数不匹配: %s", op_name, exc)
            except Exception as exc:  # noqa: BLE001
                results.append(OpResult(op=op_name, status="failed", detail=str(exc)))
                logger.error("[wprotocol] computer op=%s 执行异常: %s", op_name, exc, exc_info=True)
        return results

    async def _execute_file(self, plan: Any, source: str) -> list[OpResult]:
        source_dir = plan.get("source_dir") if isinstance(plan, dict) else None
        if not isinstance(source_dir, str) or not source_dir:
            raise ProtocolError("file_organize 协议缺 source_dir")
        target_dir = plan.get("target_dir") if isinstance(plan, dict) else None
        logger.debug(
            "[wprotocol] file_organize source_dir=%s target_dir=%s source=%s",
            source_dir, target_dir, source,
        )

        # v0.4.2: 写操作权限门控(与电脑操控共用权限模式)
        if self._workspace is not None:
            verdict, reason = self._workspace.decide_write(source_dir)
            if verdict == "block":
                logger.warning("[wprotocol] file_organize 被权限拦截: %s", reason)
                return [OpResult(op="file_organize", status="denied", detail=f"权限拦截: {reason}")]
            if verdict == "approve":
                # L1 简化:审批未接入工作区流程,暂按放行处理并记录
                logger.info("[wprotocol] file_organize 需审批(当前自动放行): %s", reason)
                self._workspace.add_activity(
                    kind="info", preset="file-organizer",
                    detail=f"写操作需审批(自动放行): {source_dir}",
                )

        def _run() -> tuple[bool, str, str]:
            organize_plan: OrganizePlan = self._file_organizer.preview_organize(
                source_dir, target_dir=target_dir
            )
            return self._file_organizer.execute_organize(organize_plan, description="DSH 委托整理")

        try:
            ok, msg, undo_id = await asyncio.to_thread(_run)
            status = "ok" if ok else "failed"
            logger.info("[wprotocol] file_organize 结果 ok=%s undo_id=%s msg=%s", ok, undo_id, msg)
            return [OpResult(op="file_organize", status=status, detail=msg, audit_id=undo_id)]
        except Exception as exc:  # noqa: BLE001
            logger.error("[wprotocol] file_organize 执行异常: %s", exc, exc_info=True)
            return [OpResult(op="file_organize", status="failed", detail=str(exc))]

    async def _execute_doc(self, plan: Any, source: str) -> list[OpResult]:
        doc_type_raw = plan.get("doc_type") if isinstance(plan, dict) else None
        title = plan.get("title") if isinstance(plan, dict) else ""
        content = plan.get("content_md") if isinstance(plan, dict) else ""
        doc_type = _DOC_TYPE_MAP.get(str(doc_type_raw))
        if doc_type is None:
            raise ProtocolError(f"doc_write 协议非法 doc_type={doc_type_raw!r}")
        if not isinstance(title, str) or not title:
            raise ProtocolError("doc_write 协议缺 title")
        logger.debug(
            "[wprotocol] doc_write doc_type=%s title=%s content_len=%d source=%s",
            doc_type.value, title, len(content or ""), source,
        )

        def _run() -> tuple[str, str]:
            doc = self._doc_writer.create_document(doc_type, title, content=content or "")
            path = self._doc_writer.export(doc, ExportFormat.MARKDOWN)
            return str(path), path.name

        try:
            path, name = await asyncio.to_thread(_run)
            logger.info("[wprotocol] doc_write 完成 path=%s", path)
            return [OpResult(op="doc_write", status="ok", detail=path, audit_id=name)]
        except Exception as exc:  # noqa: BLE001
            logger.error("[wprotocol] doc_write 执行异常: %s", exc, exc_info=True)
            return [OpResult(op="doc_write", status="failed", detail=str(exc))]

    # ------------------------------------------------------------------ 工具

    @staticmethod
    def _normalize_ops(plan: Any) -> list[dict]:
        """computer_control 的 plan 支持 list[op] 或 {"ops": [...]}。"""
        if isinstance(plan, list):
            return [op for op in plan if isinstance(op, dict)]
        if isinstance(plan, dict) and isinstance(plan.get("ops"), list):
            return [op for op in plan["ops"] if isinstance(op, dict)]
        raise ProtocolError("computer_control 协议 plan 必须是 op 列表或含 ops 键")


def _map_control_result(op_name: str, result: ControlResult) -> OpResult:
    """把 ComputerController 返回的 ControlResult 映射为协议 status。"""
    data = result.data or {}
    if result.success:
        return OpResult(op=op_name, status="ok", detail=result.action or "")
    if data.get("blocked"):
        return OpResult(op=op_name, status="denied", detail=data.get("reason", "blocked"))
    if data.get("needs_approval"):
        return OpResult(
            op=op_name,
            status="pending_approval",
            detail=data.get("reason", "needs approval"),
            audit_id=str(data.get("call_id", "")),
        )
    return OpResult(op=op_name, status="failed", detail=result.error or "failed")


def _summarize(value: Any, limit: int = 240) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text if len(text) <= limit else text[:limit] + f"...({len(text)} chars)"


__all__ = ["WorkProtocolExecutor", "OpResult", "ProtocolError"]

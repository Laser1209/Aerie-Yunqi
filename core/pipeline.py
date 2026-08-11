"""Aerie · 云栖 v0.1.0-beta.1 — Message pipeline.

Processes incoming messages through:
  route → emotion(text scan + cumulative trigger check) → history → context(with emotion+eruption) → LLM → emotion tune → persist → emit → reply.

Phase 9: every step also writes to a 9-stage cognition trace
(route / emotion / threshold / context / brain / tools / split / postprocess / output).
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from communication.message import (
    CancellationToken,
    CancellationTooLate,
    IncomingMessage,
    OutgoingReply,
)
from communication.splitter import SemanticMessageSplitter
from core.attachment_handler import extract_markdown
from core.chat_events import emit
from core.chat_request_repository import RequestContext
from core.cognition import CognitionEngine
from core.feature_flags import FeatureFlags
from core.ids import generate_id
from core.office_mode import get_office_mode_manager, OfficeMode
from core.response_validator import ResponseValidator
from core.content_validator import ContentValidator

logger = logging.getLogger(__name__)

# Phase 14: 聊天触发生图的有效意图集合 + 语义兜底的触发信号。
# 触发信号不是"判定"，只是"是否值得花一次 LLM 语义判断"的成本闸门：
# 用户消息带视觉兴趣（看/拍/图/样子/发你…）就交给 LLM 语义判断真实意图，
# 纯寒暄（在吗/晚安）直接跳过，避免每条消息都多一次 LLM 调用拖慢回复。
_PHOTO_INTENTS = frozenset({"role_selfie", "role_in_scene", "couple_photo", "environment_object"})
_FUZZY_IMAGE_HINTS = (
    # 拍照/照片/图族
    "拍", "照", "图", "相片", "自拍", "照片", "美照", "靓照",
    # 看族（视觉确认）
    "看", "瞅", "瞧", "瞄", "看看", "想看", "给我看", "给你看",
    # 样子/形象
    "样子", "形象", "长什么样", "什么样", "啥样",
    # 发/传图动作
    "发你", "发张", "发照片", "发图", "传你", "发过来", "发过去", "给你发",
    # 生活空间载体
    "家里", "房间", "床", "厨房", "窗边", "窗外", "阳台", "衣柜",
    # 英文
    "photo", "pic", "picture", "image", "selfie",
)
# 回复判断的触发信号（更窄）：只有回复在叙述"发图/发送"这类动作才值得判断。
_REPLY_PHOTO_HINTS = (
    "拍", "照片", "自拍", "发送", "发你", "发过去", "发给你", "发过来",
    "传你", "给你看", "点了发送", "对着镜子", "发张",
)


@dataclass
class _RequestRunState:
    context: RequestContext | None
    token: CancellationToken | None
    terminal_side_effect_committed: bool = False
    canonical_completed: bool = False
    response_group_id: str | None = None
    sequence: int = 0

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence


class Pipeline:
    def __init__(
        self,
        router: Any,
        emotion_engine: Any,
        context_builder: Any,
        brain: Any,
        send_queue: Any,
        tool_registry: Any,
        db: Any,
        recall_manager: Any = None,
        cognition: CognitionEngine | None = None,
        decision_engine: Any = None,         # Phase 9: §10.2 multi-layer
        self_evolver: Any = None,            # Phase 9: capability gap detector
        settings: dict | None = None,
        identity_resolver: Any = None,
        conversation_repository: Any = None,
        context_assembler: Any = None,
        summary_planner: Any = None,
        summary_summarizer: Any = None,
        attachment_service: Any = None,
        memory_store: Any = None,
    ) -> None:
        self.router = router
        self.emotion = emotion_engine
        self.ctx_builder = context_builder
        self.brain = brain
        self.send_queue = send_queue
        self.tool_registry = tool_registry
        self.db = db
        self.recall_manager = recall_manager
        self.cognition = cognition or CognitionEngine(db)
        self.decision_engine = decision_engine
        self.self_evolver = self_evolver
        self.identity_resolver = identity_resolver
        self.conversation_repository = conversation_repository
        self.context_assembler = context_assembler
        self.summary_planner = summary_planner
        self.summary_summarizer = (
            summary_summarizer or self._default_rolling_summary
        )
        self.attachment_service = attachment_service
        self.memory_store = memory_store or getattr(context_builder, "memory", None)
        self._summary_tasks: set[asyncio.Task[Any]] = set()
        self._summary_inflight: set[str] = set()
        # 用户明确要求照片时触发的后台生图任务（fire-and-forget，文本先发、图后到）。
        self._photo_tasks: set[asyncio.Task[Any]] = set()
        self._splitter = SemanticMessageSplitter()
        # v13.9: 回复校验器（准确性 Guard + 质量 Judge）
        self.validator = ResponseValidator()
        # Task 5: Content validator — ensures replies have meaningful text after tag stripping
        self.content_validator = ContentValidator(brain)

        # v13.9.8: 任务规划器（Pipeline 主路径集成，配置开关控制）
        self._task_planner = None
        self._task_planner_enabled = False
        if settings and isinstance(settings, dict):
            agent_cfg = settings.get("agent", {})
            self._task_planner_enabled = agent_cfg.get("task_planner_enabled", False)
            max_steps = agent_cfg.get("max_plan_steps", 10)
            if self._task_planner_enabled:
                try:
                    from core.task_planner import TaskPlanner
                    self._task_planner = TaskPlanner(max_steps=max_steps)
                    logger.info("Pipeline task planner enabled (max_steps=%d)", max_steps)
                except Exception:
                    logger.exception("Failed to initialize TaskPlanner for Pipeline, task planning disabled")
                    self._task_planner = None
                    self._task_planner_enabled = False

    async def handle(
        self,
        msg: IncomingMessage | None = None,
        force_full: bool = False,
        *,
        messages: list[IncomingMessage] | None = None,
        batch_id: str | None = None,
        request_context: RequestContext | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> dict | list[dict] | None:
        """Handle one or more incoming messages end-to-end.

        Single mode (backward compatible):
            Pass msg=IncomingMessage -> returns dict with reply info

        Batch mode (Task 4):
            Pass messages=list[IncomingMessage], batch_id=str -> returns list[dict]

        Returns dict (single) or list[dict] (batch) with reply info,
        or None if skipped (BASIC stranger).
        """
        is_batch = messages is not None and len(messages) > 0 and batch_id is not None

        if is_batch:
            if len(messages) == 1:
                msg = messages[0]
            else:
                return await self._handle_batch(
                    messages=messages,
                    batch_id=batch_id,
                    force_full=force_full,
                    cancellation_token=cancellation_token,
                )

        if msg is None and request_context is None:
            raise ValueError("msg or request_context is required (or messages for batch mode)")
        if request_context is not None:
            msg = self._message_from_request_context(request_context, msg)
        assert msg is not None

        request_state = _RequestRunState(
            context=request_context,
            token=cancellation_token,
        )
        model_content = (
            request_context.effective_content
            if request_context is not None
            else msg.content
        )

        # 错别字订正：进入理解前，先用轻量模型（硅基流动 · 小米）订正明显
        # 错别字/同音字，避免主模型因一个错字误解（如 "换好了美呀" → "换好了没呀"）。
        # 订正只影响理解，不写回聊天记录（原文仍持久化）；任何失败都回退原文。
        if model_content:
            try:
                from core.typo_corrector import correct_typos
                model_content = await correct_typos(self.brain, model_content)
            except Exception:
                logger.exception("typo correction failed, fallback to original")

        (
            context_attachments,
            attachment_ids,
            attachment_snippets,
            persisted_attachments,
        ) = self._prepare_attachments(
            msg.attachments,
            request_context=request_context,
            query=model_content,
        )
        if request_context is None:
            msg.attachments = persisted_attachments

        if self.identity_resolver and request_context is None:
            self.identity_resolver.resolve_message(msg)

        # ══════════════════════════════════════════════
        # Phase 9: Begin cognition trace
        # ══════════════════════════════════════════════
        trace = self.cognition.begin(msg.user_id, msg.source, msg.content)
        route_mode = self.router.route(msg.user_id)

        # v13.9: force_full 强制启用 FULL 模式（Web UI 本地用户默认拥有完整能力）
        if force_full:
            route_mode = "FULL"

        # v13.9: BASIC 模式走轻量链路，不再完全跳过
        # 保留情绪 + LLM + 后处理 + 持久化，跳过工具 + 自进化
        if route_mode == "BASIC" and not force_full:
            logger.debug("BASIC lightweight mode for user %s", msg.user_id)
            self.cognition.record(trace, "route", {"mode": "BASIC", "skipped": False, "lightweight": True})
            result = await self._handle_basic_lightweight(
                msg,
                trace,
                route_mode,
                model_content=model_content,
                context_attachments=context_attachments,
                attachment_ids=attachment_ids,
                attachment_snippets=attachment_snippets,
                request_state=request_state,
            )
            self.cognition.commit(trace, route_mode)
            return result

        # ══════════════════════════════════════════════
        # 1. Route (stage 1)
        # ══════════════════════════════════════════════
        self.cognition.record(trace, "route", {"mode": route_mode, "skipped": False})

        # ══════════════════════════════════════════════
        # Phase 9: Multi-layer decision (§10.2) — chosen intent
        # Inputs come from the real world (mood / tools / recall budget)
        # so the predicted race matches what the executor can actually do.
        # ══════════════════════════════════════════════
        if self.decision_engine:
            try:
                dinputs = self._decision_inputs(
                    user_id=msg.user_id,
                    channel=getattr(msg, "channel", None)
                    or getattr(msg, "source", None)
                    or "qq",
                    channel_account_id=getattr(msg, "channel_account_id", None),
                    actor_id=msg.actor_id,
                )
                decision = self.decision_engine.decide_for_message(
                    user_id=msg.user_id,
                    route_mode=route_mode,
                    source=msg.source,
                    **dinputs,
                )
                self.cognition.record_decision(trace, decision)
            except Exception:
                logger.exception("decision engine error")

        # ══════════════════════════════════════════════
        # Phase 4: Auto-recall if user said something negative
        # ══════════════════════════════════════════════
        if self.recall_manager and msg.source == "qq":
            try:
                await self.recall_manager.handle_user_negative(
                    msg.user_id, msg.content, channel=msg.source,
                )
            except Exception:
                logger.exception("handle_user_negative error")

        # ══════════════════════════════════════════════
        # 2. Emotion: LLM-driven PAD analysis + cumulative threshold scan
        #    (stages 2 + 3). R7.0: switched from sync keyword-only
        #    update_trajectory to async update_trajectory_async, which
        #    additionally calls the LLM and blends the LLM PAD with
        #    the keyword path. Falls back to keyword-only if the LLM
        #    call fails or no brain is wired.
        # ══════════════════════════════════════════════
        try:
            await self.emotion.update_trajectory_async(
                msg.user_id,
                model_content,
                actor_id=msg.actor_id,
            )
        except Exception:
            logger.exception("emotion update error")

        # ══════════════════════════════════════════════
        # 3. Get history from DB
        #    Variable `history` is used consistently (not `history_rows`
        #    or `history_msgs`) for passing to ContextBuilder.build().
        # ══════════════════════════════════════════════
        history = self._load_history(msg, legacy_limit=20)

        # ══════════════════════════════════════════════
        # 4. Gather emotion info for context injection
        # ══════════════════════════════════════════════
        emotion_info = None
        eruption_info = None
        try:
            state = self.emotion.get_state(
                msg.user_id,
                actor_id=msg.actor_id,
            )
            emotion_info = {
                "label": state.get("label", "neutral"),
                "pad": state.get("pad", {}),
                "thresholds": state.get("thresholds", {}),
            }
            eruption_info = state.get("eruption")
        except Exception:
            pass

        # Phase 9: record emotion + threshold stages
        self.cognition.record(trace, "emotion", {
            "label": (emotion_info or {}).get("label"),
            "pad": (emotion_info or {}).get("pad"),
        })
        self.cognition.record(trace, "threshold", (emotion_info or {}).get("thresholds"))

        # ══════════════════════════════════════════════
        # 4.5 Phase 4: Resolve reply_to context
        # ══════════════════════════════════════════════
        reply_to_data = None
        if msg.reply_to_id:
            try:
                quoted = self.db.query_one(
                    "SELECT id, role, content FROM chat_log WHERE id = ?",
                    (msg.reply_to_id,),
                )
                if quoted:
                    reply_to_data = {
                        "id": quoted["id"],
                        "role": quoted["role"],
                        "content": quoted["content"],
                    }
            except Exception:
                pass

        # ══════════════════════════════════════════════
        # 5. Build context for LLM (stage 4)
        # ══════════════════════════════════════════════
        time_context = None
        try:
            from core.calendar_manager import CalendarManager
            time_context = CalendarManager(self.db).get_agent_snapshot(msg.user_id)
        except Exception:
            logger.warning("calendar snapshot unavailable", exc_info=True)
        context_budget_enabled = self._context_budget_enabled()
        context_budget_kwargs = (
            self._context_budget_kwargs(msg)
            if context_budget_enabled
            else {}
        )
        world_snapshot = self._call_optional_context_provider(
            "world_snapshot_provider",
        )
        relationship_snapshot = self._call_optional_context_provider(
            "relationship_snapshot_provider",
            msg.user_id,
        )
        self_model_snapshot = self._call_optional_context_provider(
            "self_model_snapshot_provider",
            world_snapshot,
            relationship_snapshot,
        )
        internal_snapshot = self._call_optional_context_provider(
            "internal_snapshot_provider",
            world_snapshot,
            relationship_snapshot,
        )
        ctx_messages = self.ctx_builder.build(
            msg.user_id,
            model_content,
            route_mode,
            history_msgs=history,
            emotion_info=emotion_info,
            eruption_info=eruption_info,
            reply_to=reply_to_data,
            attachments=context_attachments if context_attachments else None,
            time_context=time_context,
            world_snapshot=world_snapshot,
            relationship_snapshot=relationship_snapshot,
            self_model_snapshot=self_model_snapshot,
            internal_snapshot=internal_snapshot,
            **context_budget_kwargs,
        )
        ctx_messages, continuity_audit = self._assemble_continuity_context(
            base_messages=ctx_messages,
            msg=msg,
            current_user_content=model_content,
            attachment_snippets=attachment_snippets,
            request_context=request_context,
        )
        tools = self.tool_registry.get_openai_schema() if route_mode == "FULL" else None

        system_chars = len(ctx_messages[0]["content"]) if ctx_messages else 0
        history_chars = sum(len(m.get("content", "")) for m in ctx_messages[1:])
        context_record = {
            "messages": len(ctx_messages),
            "system_prompt_chars": system_chars,
            "history_chars": history_chars,
            "tools_offered": bool(tools),
        }
        audit = (
            self._context_budget_audit()
            if context_budget_enabled
            else None
        )
        if audit:
            context_record["context_budget"] = audit
        if continuity_audit:
            context_record["continuity"] = continuity_audit
        self.cognition.record(trace, "context", context_record)

        # ══════════════════════════════════════════════
        # v13.0: Office Mode 办公模式检测与增强
        # ══════════════════════════════════════════════
        office_mgr = get_office_mode_manager()
        office_ctx = office_mgr.detect(model_content, history)
        is_office = office_ctx.is_office_mode()
        # 同步办公模式判定到前端：auto 模式下按当前消息识别结果更新
        # detected_mode，前端据此决定是否显示"已完成"徽标（仅工作消息显示）。
        # 事件统一在事件发射阶段 emit（见下方 office_mode_changed），
        # 以携带完整事件契约，并遵循取消检查点语义。

        if is_office and ctx_messages:
            # 增强系统提示词
            sys_content = ctx_messages[0].get("content", "")
            ctx_messages[0]["content"] = office_mgr.augment_system_prompt(sys_content)
            system_chars = len(ctx_messages[0]["content"])

        # 记录到认知链路
        self.cognition.record(trace, "office_mode", {
            "mode": office_ctx.mode.value if office_ctx.mode else "auto",
            "detected": office_ctx.detected_mode.value if office_ctx.detected_mode else None,
            "is_office": is_office,
            "task_type": office_ctx.task_type.value if office_ctx.task_type else None,
            "confidence": office_ctx.confidence,
            "keywords": office_ctx.task_keywords,
        })

        # ══════════════════════════════════════════════
        # v13.9.8: 任务规划注入（仅 FULL 模式且启用时）
        # ══════════════════════════════════════════════
        task_plan_injected = False
        if (self._task_planner and self._task_planner_enabled
                and route_mode == "FULL"
                and model_content
                and self._task_planner.should_plan(model_content)):
            try:
                plan = self._task_planner.create_plan(model_content)
                if plan and plan.steps and len(plan.steps) > 1:
                    sys_content = ctx_messages[0].get("content", "") if ctx_messages else ""
                    ctx_messages[0]["content"] = self._inject_task_plan_into_context(sys_content, plan)
                    system_chars = len(ctx_messages[0]["content"])
                    task_plan_injected = True
                    logger.debug("Task plan injected into Pipeline context: %d steps", plan.total_steps)
            except Exception:
                logger.exception("Task planning for Pipeline failed, falling back to normal mode")

        # ══════════════════════════════════════════════
        # 6. Call LLM (stage 5)
        # ══════════════════════════════════════════════
        preferred_provider = office_mgr.get_preferred_provider() if is_office else None
        self._checkpoint_cancel(request_state, "before_model")
        response = await self.brain.chat(
            ctx_messages,
            tools=tools,
            tool_registry=self.tool_registry,
            preferred_provider=preferred_provider,
        )
        self._checkpoint_cancel(request_state, "after_model")
        raw_text = getattr(response, "text", "") or ""
        react_trace = getattr(response, "react_trace", None)
        tool_results = getattr(response, "tool_results", None) or []
        model_name = getattr(response, "model", "unknown")
        usage = getattr(response, "usage", None) or {}

        # Phase 9 Batch 6: ReAct trace comes from the brain with react_source tag.
        # If the brain tagged it as "model-no-think" / "fallback" / or no trace
        # was provided at all, synthesize a thought from the stage data we
        # already collected. This guarantees react_trace.thought is never None
        # in cognition_log (one of the Batch 6 acceptance criteria).
        react_trace = self._ensure_react_trace(
            react_trace, trace, raw_text, tool_results
        )

        # Strip  thinking block from user-visible text
        reply_text_raw = self._strip_think(raw_text)

        # Strip a leading [MM-DD HH:MM] timestamp the model may echo back
        reply_text_raw = self._strip_leading_timestamp(reply_text_raw)

        # Gate 2: LLM 主动撤回指令 — 解析 <recall>, 执行撤回, 并从正文剔除
        reply_text_raw, _recall_actual = await self._handle_recall_instruction(reply_text_raw, msg)
        if _recall_actual:
            self.cognition.record_decision_actual(trace, _recall_actual)

        self.cognition.record(trace, "brain", {
            "model": model_name,
            "tokens": usage,
            "raw_chars": len(raw_text),
            "react": react_trace,
        })
        self.cognition.record_react(trace, react_trace)

        # ══════════════════════════════════════════════
        # 7. Tools (stage 6) — record each tool call into tool_call_log
        # ══════════════════════════════════════════════
        tool_summary: list[dict] = []
        for tr in tool_results:
            try:
                rid = self.db.insert("tool_call_log", {
                    "ts": int(__import__("time").time() * 1000),
                    "user_id": msg.user_id,
                    "tool_name": tr.get("name", "unknown"),
                    "arguments": json.dumps(tr.get("arguments", {}), ensure_ascii=False),
                    "result": json.dumps(tr.get("result", {}), ensure_ascii=False)[:2000],
                    "success": 1 if tr.get("success", True) else 0,
                    "duration_ms": tr.get("duration_ms", 0),
                })
                tr["cognition_id"] = trace["id"]  # may be 0 until commit
            except Exception:
                logger.exception("tool_call_log insert error")
            tool_summary.append({
                "name": tr.get("name"),
                "success": tr.get("success", True),
                "duration_ms": tr.get("duration_ms", 0),
            })
        self.cognition.record(trace, "tools", tool_summary)

        # ══════════════════════════════════════════════
        # 8. Emotion tune + screen-action sanitize (stage 7)
        # R7.5: enforce "屏幕隔空铁律" at the output layer. Even if
        # the LLM emitted a blacklisted "在场动作" (伸手/揽/抱/靠肩/etc),
        # sanitizer.sanitize() rewrites it to a screen-side equivalent.
        # R8.1: also run OutputSelfCheck (perspective-shift / stray
        # brackets / typos) as a second line of defense.
        # ══════════════════════════════════════════════
        reply_text = self.emotion.tune(
            reply_text_raw,
            actor_id=msg.actor_id,
        )
        try:
            from core.screen_action_sanitizer import sanitize as _sanitize_action
            reply_text = _sanitize_action(reply_text)
        except Exception:
            # Sanitizer is best-effort; never break the pipeline.
            logger.exception("screen_action_sanitizer failed; using tuned text as-is")
        try:
            from core.output_self_check import OutputSelfCheck
            _self_check = OutputSelfCheck()
            _sc_result = _self_check.check(reply_text)
            if _sc_result.warnings:
                # R8.1 (Persona 9/10): 9/10 行为下 perspective_shift 略升
                # —— 直球措辞让 LLM 更容易在 1 句内同时调取"屏幕那端"和
                # "在场视角"两套表达。升级为 severity=warn 方便 cognition
                # panel 高亮，运营侧可通过此信号监控 9/10 行为下的命中率。
                self.cognition.record(trace, "self_check", {
                    "warnings": _sc_result.warnings,
                    "perspective_shift": _sc_result.perspective_shift,
                    "stray_brackets_fixed": _sc_result.stray_brackets_fixed,
                    "typo_fixes": _sc_result.typo_fixes,
                    "severity": "warn",  # R8.1: 9/10 → 默认 warn 等级
                })
            reply_text = _sc_result.cleaned_text
        except Exception:
            # Self-check is best-effort; never break the pipeline.
            logger.exception("output_self_check failed; using sanitized text as-is")

        # Task 5: Content validation — ensure reply has meaningful text after tag stripping
        content_remedied = False
        try:
            last_user_msg_for_ctx = model_content
            reply_text, content_remedied = await self.content_validator.validate_and_fix(
                reply_text,
                context={"last_user_message": last_user_msg_for_ctx},
            )
            if content_remedied:
                self.cognition.record(trace, "content_validation", {
                    "remedied": True,
                    "final_length": len(reply_text),
                })
        except Exception:
            logger.exception("content_validator failed; using current text as-is")

        self.cognition.record(trace, "postprocess", {
            "tune_label": (emotion_info or {}).get("label"),
            "eruption_mode": (eruption_info or {}).get("mode") if eruption_info else None,
            "raw_chars": len(reply_text_raw),
            "tuned_chars": len(reply_text),
            "content_remedied": content_remedied,
        })

        # ══════════════════════════════════════════════
        # 8.5 Response Validation（v13.9: Guard + Judge 双层校验）
        # ══════════════════════════════════════════════
        try:
            is_office = office_mgr.current_mode == OfficeMode.OFFICE or (
                office_ctx and office_ctx.is_office_mode()
            )
            vr = await self.validator.validate(
                reply_text,
                user_message=model_content,
                context_history=history,
                route_mode="OFFICE" if is_office else route_mode,
            )
            if vr.issues:
                self.cognition.record(trace, "validation", {
                    "passed": vr.passed,
                    "guard_passed": vr.guard_passed,
                    "judge_score": vr.judge_score,
                    "rewrite_count": vr.rewrite_count,
                    "issues": vr.issues,
                })
        except Exception:
            # 校验是 best-effort，失败不影响主流程
            logger.exception("response validation failed; best-effort skip")

        segments = self._splitter.split(reply_text) or [reply_text]
        self.cognition.record(trace, "split", {
            "segments": segments,
            "count": len(segments),
        })

        # ══════════════════════════════════════════════
        # 9. Persist user message
        # ══════════════════════════════════════════════
        user_row_id = 0
        persist_errors: list[str] = []
        try:
            self._checkpoint_cancel(request_state, "before_legacy_user")
            user_row_id = self.db.insert("chat_log", {
                "user_id": msg.user_id,
                "role": "user",
                "content": msg.content,
                "msg_type": msg.msg_type,
                "route_mode": route_mode,
                "reply_to_id": reply_to_data["id"] if reply_to_data else None,
                "reply_to_content": reply_to_data["content"] if reply_to_data else None,
                "reply_to_role": reply_to_data["role"] if reply_to_data else None,
                "attachments": json.dumps(msg.attachments, ensure_ascii=False) if msg.attachments else None,
                "actor_id": msg.actor_id,
                "channel": msg.channel,
                "channel_account_id": msg.channel_account_id,
            })
            if user_row_id:
                request_state.terminal_side_effect_committed = True
        except CancellationTooLate:
            raise
        except Exception as e:
            persist_errors.append(f"user message: {e}")
            logger.exception("db insert user msg error")

        if request_context is None:
            try:
                emit(
                    "user",
                    role="user",
                    id=user_row_id,
                    user_id=msg.user_id,
                    content=msg.content,
                    source=msg.source,
                )
            except Exception:
                pass

        # ══════════════════════════════════════════════
        # 11. Persist AI reply — split into segments, one row per segment
        # ══════════════════════════════════════════════
        ai_row_ids: list[int] = []
        try:
            for seg in segments:
                self._checkpoint_cancel(
                    request_state,
                    "before_legacy_assistant",
                )
                rid = self.db.insert("chat_log", {
                    "user_id": msg.user_id,
                    "role": "assistant",
                    "content": seg,
                    "msg_type": msg.msg_type,
                    "route_mode": route_mode,
                    "actor_id": msg.actor_id,
                    "channel": msg.channel,
                    "channel_account_id": msg.channel_account_id,
                })
                ai_row_ids.append(rid)
                if rid:
                    request_state.terminal_side_effect_committed = True
        except CancellationTooLate:
            raise
        except Exception as e:
            persist_errors.append(f"assistant message: {e}")
            logger.exception("db insert ai msg error")

        canonical_result: dict[str, str] | None = None
        if user_row_id and len(ai_row_ids) == len(segments):
            self._checkpoint_cancel(request_state, "before_canonical")
            canonical_result = self._persist_canonical_turn(
                msg,
                segments,
                request_context=request_context,
                user_legacy_chat_log_id=user_row_id or None,
                assistant_legacy_chat_log_ids=ai_row_ids,
            )
            if canonical_result is not None:
                request_state.canonical_completed = True
                request_state.response_group_id = canonical_result.get(
                    "response_group_id"
                )

        attachment_bind_error = self._after_message_persisted(
            attachment_ids=attachment_ids,
            canonical_result=canonical_result,
            user_legacy_chat_log_id=user_row_id,
            msg=msg,
            request_context=request_context,
        )

        # Phase 9: stage 9 — output
        self.cognition.record(trace, "output", {
            "ai_msg_ids": ai_row_ids,
            "user_msg_id": user_row_id,
            "source": msg.source,
            "segment_count": len(ai_row_ids),
        })

        # Phase 9: persist trace
        self.cognition.commit(trace, route_mode)

        # Phase 9: self-evolution check
        # B6: pass tool_results too so the gap detector can see WHICH tool
        # failed (not just that one did). The proposal is dropped silently
        # if no gap is detected.
        if self.self_evolver:
            try:
                self.self_evolver.maybe_propose(
                    user_id=msg.user_id,
                    user_message=msg.content,
                    react_trace=react_trace,
                    tool_results=tool_results,
                )
            except Exception:
                logger.exception("self_evolver error")

        result = {
            "reply": reply_text,
            "user_msg_id": user_row_id,
            "ai_msg_id": ai_row_ids[0] if ai_row_ids else 0,
            "ai_msg_ids": ai_row_ids,
            "segments": segments,
            "route_mode": route_mode,
            "emotion": emotion_info.get("label") if emotion_info else "unknown",
            "cognition_id": trace.get("id", 0),
            "persisted": not persist_errors,
            "canonical_completed": request_state.canonical_completed,
        }
        if request_context is not None:
            result.update(
                {
                    "request_id": request_context.request_id,
                    "conversation_id": request_context.conversation_id,
                    "turn_id": request_context.turn_id,
                }
            )
        if canonical_result:
            result["canonical"] = canonical_result
            result["response_group_id"] = canonical_result.get(
                "response_group_id"
            )
        if persist_errors:
            result["persist_error"] = "; ".join(persist_errors)
        if attachment_bind_error:
            result["attachment_bind_error"] = attachment_bind_error

        # ══════════════════════════════════════════════
        # 12. Emit assistant event for each segment (UI gets one bubble per segment)
        # Phase 9 Batch 2: persona-aware pacing.
        #   - 1st segment: immediate (0 delay) — user wants first message timely.
        #   - 2nd+ segments: persona decision tree (joy eager / sad cold-slow /
        #     eruption-mode-specific / 5% yandere erase / 3% contemplative / 10% shy).
        #   - 1.5s is the BASELINE (balanced mode), not a hard ceiling.
        # Both local (this loop) and QQ (SendQueue) use the same persona tree.
        # ══════════════════════════════════════════════
        from core.persona_pacing import compute_persona_interval
        emotion_label_local = (emotion_info.get("label") if emotion_info else "neutral") or "neutral"
        is_eruption_local = bool(eruption_info and eruption_info.get("mode"))
        threshold_summary_local = (emotion_info or {}).get("thresholds", {}) or {}
        pacing_log: list[dict] = []
        if request_context is not None:
            if self._checkpoint_cancel(request_state, "before_event"):
                result["event_sequence"] = request_state.sequence
                return result
            try:
                emit(
                    "user",
                    role="user",
                    id=user_row_id,
                    user_id=msg.user_id,
                    content=msg.content,
                    source=msg.source,
                    **self._event_contract(
                        request_state,
                        message_id=user_row_id,
                    ),
                )
            except Exception:
                pass
            # office_mode_changed：纳入统一事件契约并携带完整信封字段，
            # 前端据此决定是否显示"已完成"徽标（仅工作消息显示）。
            try:
                emit(
                    "office_mode_changed",
                    mode=office_ctx.mode.value if office_ctx.mode else "auto",
                    detected_mode=office_ctx.detected_mode.value if office_ctx.detected_mode else None,
                    **self._event_contract(
                        request_state,
                        message_id=user_row_id,
                    ),
                )
            except Exception:
                pass

        # ══════════════════════════════════════════════
        # 12.5 用户要图 → 引导句先发 → 出图并等送达 → 剩余文本再发
        # 命中出图意图时，把回复第一段作为"引导句"先发（如"你稍微等一下"、
        # "我摄像头好像坏了"这类人设式托词），让等待出图的空档有人情味；
        # 剩余段落等图片真正落到页面后再发。生图失败/超时不阻塞文本放行。
        # ══════════════════════════════════════════════
        photo_intent = ""
        try:
            photo_intent = await self._resolve_chat_photo_intent(msg, reply_text, route_mode)
        except Exception:
            logger.debug("chat photo intent resolve failed", exc_info=True)
        lead_in_count = 1 if (photo_intent and len(segments) > 1) else 0

        async def _emit_segments(start: int, end: int) -> bool:
            """emit segments[start:end]（含首段情绪/爆发标记与段间节奏）。"""
            for i in range(start, end):
                if self._checkpoint_cancel(request_state, "before_event"):
                    result["event_sequence"] = request_state.sequence
                    return False
                try:
                    emit_kwargs = {
                        "role": "assistant",
                        "id": ai_row_ids[i],
                        "user_id": msg.user_id,
                        "content": segments[i],
                        "source": msg.source,
                        **self._event_contract(
                            request_state,
                            message_id=ai_row_ids[i],
                            response_group_id=request_state.response_group_id,
                        ),
                    }
                    if i == 0:
                        if emotion_info:
                            emit_kwargs["emotion"] = emotion_info["label"]
                        if eruption_info:
                            emit_kwargs["eruption"] = eruption_info["mode"]
                    emit("assistant", **emit_kwargs)
                except Exception:
                    pass
                # 段间节奏（组内相邻段；引导句与剩余段之间的空档由出图时间填充）
                if i < end - 1:
                    interval_sec, style = compute_persona_interval(
                        segment_index=i,
                        emotion_label=emotion_label_local,
                        threshold=threshold_summary_local,
                        is_eruption=is_eruption_local,
                        segment_content=segments[i],
                    )
                    pacing_log.append({
                        "seg_idx": i,
                        "next_style": style,
                        "next_interval_ms": int(interval_sec * 1000),
                        "source": "local",
                    })
                    if msg.source == "local" and interval_sec > 0:
                        await asyncio.sleep(interval_sec)
            return True

        # 1) 先发引导句（若有）
        if lead_in_count:
            if not await _emit_segments(0, lead_in_count):
                return result
        # 2) 出图并等送达（失败/超时不阻塞后续文本）
        if photo_intent:
            try:
                await self._deliver_chat_photo(msg, request_context, photo_intent, trace)
            except Exception:
                logger.debug("chat photo deliver failed", exc_info=True)
        # 3) 再发剩余文本
        if not await _emit_segments(lead_in_count, len(segments)):
            return result

        # Record pacing decisions into the cognition trace for analysis
        # B7.2: the pipeline may not yet know what pacing the SendQueue
        # eventually applied (the QQ worker runs after commit), so use
        # the append API. For local messages the SendQueue never sees
        # the reply, so this is the ONLY write.
        if pacing_log:
            try:
                trace_id = trace.get("id") or 0
                if trace_id and self.cognition is not None:
                    self.cognition.append_pacing_decisions(
                        trace_id, pacing_log
                    )
                # keep the in-memory trace in sync for any consumers
                # that read it before the DB is updated.
                stage_output = dict(trace.get("stages", {}).get("output") or {})
                merged = list(stage_output.get("pacing_decisions") or [])
                seen = {
                    (int(x.get("seg_idx", -1)),
                     str(x.get("style") or x.get("next_style") or ""))
                    for x in merged
                }
                for item in pacing_log:
                    key = (
                        int(item.get("seg_idx", -1)),
                        str(item.get("style") or item.get("next_style") or ""),
                    )
                    if key in seen:
                        continue
                    merged.append(item)
                    seen.add(key)
                stage_output["pacing_decisions"] = merged
                trace["stages"]["output"] = stage_output
            except Exception:
                logger.exception("pacing_log persist error")

        # ══════════════════════════════════════════════
        # 13. QQ messages → SendQueue; local → skip
        # ══════════════════════════════════════════════
        if msg.source == "qq":
            reply_to_qq_mid = 0
            if msg.reply_to_id:
                try:
                    q = self.db.query_one(
                        "SELECT qq_message_id FROM chat_log WHERE id = ?",
                        (msg.reply_to_id,),
                    )
                    if q and q.get("qq_message_id"):
                        reply_to_qq_mid = int(q["qq_message_id"])
                except Exception:
                    pass

            reply = OutgoingReply(
                user_id=msg.user_id,
                content=reply_text,
                msg_id=ai_row_ids[0] if ai_row_ids else 0,
                reply_to_qq_message_id=reply_to_qq_mid,
                # Phase 9 Batch 7 (B7.2): let SendQueue write the
                # observed pacing decisions back into this trace.
                cognition_id=int(trace.get("id") or 0),
            )
            # Phase 9: attach eruption mode so SendQueue can pace faster
            if eruption_info and eruption_info.get("mode"):
                try:
                    setattr(reply, "eruption_mode", eruption_info["mode"])
                except Exception:
                    pass
            if self._checkpoint_cancel(request_state, "before_qq_enqueue"):
                result["event_sequence"] = request_state.sequence
                return result
            self.send_queue.enqueue(reply)

        result["event_sequence"] = request_state.sequence
        return result

    async def _resolve_chat_photo_intent(
        self,
        msg: IncomingMessage,
        reply_text: str,
        route_mode: str,
    ) -> str:
        """解析本轮对话的出图意图（三层）。

        1. ``VisualIntentRouter`` 关键词快速路径（用户消息）；
        2. 关键词未命中 → 用户消息语义判断（不设关键词闸门）；
        3. 用户消息无信号但 AI 回复在叙述"发图/发你/点了发送" → 回复语义判断。

        Returns one of role_selfie/role_in_scene/couple_photo/environment_object，无则返回 ""。
        """
        if route_mode not in ("FULL", "AUTO"):
            return ""
        if not FeatureFlags().is_enabled("world_image_candidates_v1"):
            return ""
        from core.image_service import VisualIntentRouter

        prompt_text = str(msg.content or "")
        routed = VisualIntentRouter().route(prompt=prompt_text)
        intent = str(routed.get("visual_intent") or "")
        if routed.get("status") != "ok" or intent not in _PHOTO_INTENTS:
            # 关键词没命中 → 语义兜底：消息带视觉兴趣信号（看/拍/图/样子/发你…）
            # 才值得花一次 LLM 判断真实意图；纯寒暄直接跳过，避免拖慢每条回复。
            # 语义判断本身不依赖关键词，信号只是成本闸门。
            intent = ""
            if self._has_fuzzy_image_signal(prompt_text):
                try:
                    intent = await asyncio.wait_for(
                        self._judge_photo_intent(prompt_text), timeout=8
                    )
                except Exception:
                    logger.debug("chat photo intent judge timeout/failed", exc_info=True)
                    intent = ""
            # 用户消息无信号，但 AI 回复在叙述"发图/发你/点了发送"。
            reply = str(reply_text or "")
            if intent not in _PHOTO_INTENTS and self._has_reply_photo_signal(reply):
                try:
                    intent = await asyncio.wait_for(
                        self._judge_reply_photo_intent(reply), timeout=8
                    )
                except Exception:
                    logger.debug("chat photo reply judge timeout/failed", exc_info=True)
                    intent = ""
        return intent if intent in _PHOTO_INTENTS else ""

    async def _deliver_chat_photo(
        self,
        msg: IncomingMessage,
        request_context: RequestContext | None,
        intent: str,
        trace: dict | None = None,
    ) -> dict:
        """触发一次真实生图并等待送达（文本等图：图先落地，再放行后续文本）。

        复用 Phase 14 的 ``Companion.publish_image_candidate`` 完整链路（幂等 /
        安全检查 / 资产落盘 / 派发到 local_chat 或 QQ）。生图是耗时的同步 HTTP
        调用，已在线程池执行，不阻塞事件循环。用户主动要求（scene=local_send）
        不占用主动发图每日额度。失败/超时不会抛异常，由调用方决定放行文本。
        """
        from core.companion import get_companion, _image_size_for_prompt_key

        comp = get_companion()
        publisher = getattr(comp, "publish_image_candidate", None)
        if not callable(publisher):
            return {"status": "unavailable", "reason": "no_publisher"}

        user_id = str(msg.user_id or "")
        turn_key = ""
        if request_context is not None:
            turn_key = str(getattr(request_context, "turn_id", "") or "")
        if not turn_key:
            turn_key = hashlib.sha256(str(msg.content or "").encode("utf-8")).hexdigest()[:16]
        idempotency_key = f"chat-photo:{user_id}:{turn_key}"
        channel = "qq" if str(msg.channel or "") == "qq" else "local_chat"
        candidate = {
            "candidate_id": f"chat-photo-{user_id}-{int(time.time())}",
            "idempotency_key": idempotency_key,
            "scene": "local_send",
            "owner_id": user_id,
            "channel": channel,
            "target": user_id,
            "prompt_key": intent,
            "reason_code": "user_requested",
            "source": "manual",
            "score": 1.0,
            "size": _image_size_for_prompt_key(intent),
        }
        try:
            result = await asyncio.wait_for(publisher(candidate), timeout=120)
        except Exception:
            logger.warning(
                "[ChatPhoto] deliver failed/timed out idem=%s", idempotency_key,
                exc_info=True,
            )
            return {"status": "failed", "reason": "deliver_error"}
        result = result if isinstance(result, dict) else {}
        logger.info(
            "[ChatPhoto] delivered status=%s reason=%s channel=%s consumed=%s idem=%s",
            result.get("status"), result.get("reason"), result.get("channel"),
            bool(result.get("consumed")), idempotency_key,
        )
        self._record_chat_photo_tool(msg, candidate, result, trace)
        return result

    def _record_chat_photo_tool(
        self,
        msg: IncomingMessage,
        candidate: dict,
        result: dict,
        trace: dict | None,
    ) -> None:
        """把一次聊天要图建模成一条图片工具记录：写 tool_call_log + 追写 trace tools 阶段。

        生图不经过 LLM 的 ``tool_results``，需独立记录，供大脑中枢 trace 展示
        "本次调用了图片工具"。失败也记录（success=False），便于追踪。
        """
        success = result.get("status") in (
            "ok", "success", "sent", "delivered", "published", "dispatched",
        ) or bool(result.get("consumed"))
        image_path = (
            result.get("image_path") or result.get("file_path")
            or result.get("url") or result.get("path") or ""
        )
        tool_entry = {
            "name": "generate_image",
            "success": bool(success),
            "duration_ms": int(result.get("duration_ms") or 0),
            "arguments": {
                "prompt_key": candidate.get("prompt_key"),
                "size": candidate.get("size"),
                "channel": candidate.get("channel"),
                "target": candidate.get("target"),
                "idempotency_key": candidate.get("idempotency_key"),
            },
            "result": {
                "status": result.get("status"),
                "image_path": str(image_path),
                "reason_code": candidate.get("reason_code"),
            },
        }
        # 1) tool_call_log
        try:
            self.db.insert("tool_call_log", {
                "ts": int(__import__("time").time() * 1000),
                "user_id": msg.user_id,
                "tool_name": tool_entry["name"],
                "arguments": json.dumps(tool_entry["arguments"], ensure_ascii=False),
                "result": json.dumps(tool_entry["result"], ensure_ascii=False)[:2000],
                "success": 1 if success else 0,
                "duration_ms": tool_entry["duration_ms"],
                "cognition_id": (trace or {}).get("id") or 0,
            })
        except Exception:
            logger.exception("chat photo tool_call_log insert error")
        # 2) trace tools 阶段（在 handle 尚未 commit 时直接合并到内存 trace）
        if trace is not None and self.cognition is not None:
            try:
                existing = trace.get("stages", {}).get("tools") or []
                if not isinstance(existing, list):
                    existing = []
                existing = [t for t in existing
                            if not (isinstance(t, dict) and t.get("name") == "generate_image")]
                existing.append(tool_entry)
                self.cognition.record(trace, "tools", existing)
            except Exception:
                logger.debug("chat photo trace tools record failed", exc_info=True)

    @staticmethod
    def _has_fuzzy_image_signal(text: str) -> bool:
        """消息是否带视觉兴趣信号（看/拍/图/样子/发你…）。

        只是"是否值得花一次 LLM 语义判断"的成本闸门，不是判定本身。
        """
        t = str(text or "").lower()
        return any(h in t for h in _FUZZY_IMAGE_HINTS)

    @staticmethod
    def _has_reply_photo_signal(text: str) -> bool:
        """AI 回复是否在叙述"发图/发送"动作（更窄的信号，用于回复语义判断）。"""
        t = str(text or "").lower()
        return any(h in t for h in _REPLY_PHOTO_HINTS)

    async def _judge_photo_intent(self, text: str) -> str:
        """关键词未命中时的语义兜底：让 LLM 判断消息是否要求生成/发送图片。

        Returns one of: role_selfie / role_in_scene / couple_photo /
        environment_object / ""（不是图片请求）。
        """
        brain = getattr(self, "brain", None)
        if brain is None:
            return ""
        try:
            prompt = (
                "你是视觉意图判断器。判断用户这句话是否隐含「想看到你（AI 恋人）世界里的某个具体视觉载体」"
                "的意图——即希望用一张图片来满足这份分享欲。不要只盯“拍照/照片”字眼，"
                "关键看有没有一个具体的“想看”对象（你本人/你的穿着/你的家/某个物体）。"
                "只输出一个 JSON 对象，不要输出任何其他内容：\n"
                '{"visual_intent": "role_selfie" | "role_in_scene" | "couple_photo" | "environment_object" | "none"}\n'
                "含义：\n"
                "role_selfie=想看你的样子/自拍/穿着形象，如“看看你”“你长什么样”“你衣服是什么样子”“拍拍照我看看”；\n"
                "role_in_scene=想看你在某个场景/地点里，如“看看你在家的样子”“你窗边什么样子”；\n"
                "couple_photo=想看你和用户的合照/合影；\n"
                "environment_object=想看你的生活空间或某个具体物体/环境，如“让我看看你家里什么样子”"
                "“我看看你的床什么样子”“看看你厨房”；\n"
                "none=只是问候/抽象询问/没有具体视觉载体，如“看看你最近怎么样”“照顾好自己”“看一下这个文件”；"
                "用户想看他自己家的东西（我家/我的床）也判 none，因为你没有他世界的画面。\n"
                "判定要点：有「想看/看看/让我看/给我看 + 具体载体（你的/家里/床/房间/衣服/现在/某物）」"
                "就有出图意图；只有“看”但没有具体想看的对象，或纯抽象关心，判 none。"
            )
            resp = await brain.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": str(text or "")},
                ],
                temperature=0.1,
            )
            raw = str(getattr(resp, "text", "") or "")
            raw = self._strip_think(raw)
            m = re.search(r'"visual_intent"\s*:\s*"([^"]+)"', raw)
            if not m:
                logger.debug("[ChatPhoto] semantic judge unparseable: %r", raw[:120])
                return ""
            intent = m.group(1).strip()
            logger.info("[ChatPhoto] semantic judge intent=%s msg=%r", intent, str(text or "")[:40])
            return intent
        except Exception:
            logger.debug("[ChatPhoto] semantic judge failed", exc_info=True)
            return ""

    async def _judge_reply_photo_intent(self, text: str) -> str:
        """回复语义兜底：判断 AI 回复是否在"叙述并执行发送一张图片"。

        Returns one of: role_selfie / role_in_scene / couple_photo /
        environment_object / ""（不是发图）。
        """
        brain = getattr(self, "brain", None)
        if brain is None:
            return ""
        try:
            prompt = (
                "你是视觉意图判断器。判断这段 AI 回复是否在「描述并执行发送一张图片」——"
                "即她正在把一张自拍/场景照/合照/环境照发给用户"
                "（如“随手对着镜子拍的”“点了发送”“发给你”“这张照片给你看”“我刚拍了张发你”）。\n"
                "只输出一个 JSON 对象，不要输出任何其他内容：\n"
                '{"visual_intent": "role_selfie" | "role_in_scene" | "couple_photo" | "environment_object" | "none"}\n'
                "含义：role_selfie=在发自己的自拍/照片；role_in_scene=在发某个场景里的自己；"
                "couple_photo=在发合照；environment_object=在发某个环境/物体。\n"
                "判定要点：只有回复明确在叙述“正在/即将把一张图发出去”才返回对应意图；"
                "回忆过去、描述别人的照片、或只是口头说说（如“你上次拍的照片真好看”）判 none。"
            )
            resp = await brain.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": str(text or "")},
                ],
                temperature=0.1,
            )
            raw = str(getattr(resp, "text", "") or "")
            raw = self._strip_think(raw)
            m = re.search(r'"visual_intent"\s*:\s*"([^"]+)"', raw)
            if not m:
                logger.debug("[ChatPhoto] reply judge unparseable: %r", raw[:120])
                return ""
            intent = m.group(1).strip()
            logger.info("[ChatPhoto] reply judge intent=%s reply=%r", intent, str(text or "")[:40])
            return intent
        except Exception:
            logger.debug("[ChatPhoto] reply judge failed", exc_info=True)
            return ""

    # ── Helpers ────────────────────────────────────────
    def _call_optional_context_provider(self, name: str, *args) -> Any:
        provider = getattr(self, name, None)
        if not callable(provider):
            return None
        try:
            return provider(*args)
        except Exception:
            logger.warning("%s unavailable", name, exc_info=True)
            return None

    def _message_from_request_context(
        self,
        request_context: RequestContext,
        msg: IncomingMessage | None,
    ) -> IncomingMessage:
        identity = request_context.identity
        source = (
            msg.source
            if msg is not None
            else ("local" if identity.channel == "desktop" else identity.channel)
        )
        return IncomingMessage(
            user_id=identity.user_id,
            content=request_context.input_content,
            msg_type=msg.msg_type if msg is not None else "private",
            source=source or "local",
            raw_event=dict(msg.raw_event) if msg is not None else {},
            reply_to_id=request_context.reply_to_id,
            attachments=list(request_context.attachments),
            actor_id=identity.actor_id,
            channel=identity.channel,
            channel_account_id=identity.channel_account_id,
        )

    def _context_attachments(
        self,
        attachments: list[dict],
        *,
        request_context: RequestContext | None,
    ) -> list[dict]:
        if request_context is None:
            return attachments

        prepared: list[dict] = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            trusted = {
                key: value
                for key, value in attachment.items()
                if key not in {"content", "markdown", "path"}
            }
            markdown = self._extract_trusted_attachment_markdown(trusted)
            if markdown:
                trusted["markdown"] = markdown
            prepared.append(trusted)
        return prepared

    def _prepare_attachments(
        self,
        attachments: list[dict],
        *,
        request_context: RequestContext | None,
        query: str | None = None,
    ) -> tuple[list[dict], list[str], list[str], list[dict]]:
        source = list(attachments or [])
        desktop_ids: list[str] = []
        item_ids: list[str | None] = []
        for attachment in source:
            if not isinstance(attachment, dict):
                item_ids.append(None)
                continue
            attachment_id = attachment.get("attachmentId")
            alias = attachment.get("id")
            if attachment_id is None and alias is None:
                item_ids.append(None)
                continue
            if attachment_id is None:
                attachment_id = alias
            if alias is not None and alias != attachment_id:
                raise ValueError("desktop attachment id mismatch")
            if (
                not isinstance(attachment_id, str)
                or not attachment_id.strip()
                or attachment_id != attachment_id.strip()
                or attachment_id in desktop_ids
            ):
                raise ValueError("invalid desktop attachment id")
            desktop_ids.append(attachment_id)
            item_ids.append(attachment_id)

        if not desktop_ids:
            prepared = self._context_attachments(
                source,
                request_context=request_context,
            )
            return prepared, [], [], source

        resolver = getattr(
            self.attachment_service,
            "resolve_ready_for_send",
            None,
        )
        if not callable(resolver):
            raise ValueError("desktop attachment service is unavailable")
        records = resolver(desktop_ids)
        by_id = {
            str(record.get("attachmentId") or record.get("id") or ""): record
            for record in records
            if isinstance(record, dict)
        }
        if set(by_id) != set(desktop_ids):
            raise ValueError("desktop attachment resolution was incomplete")

        context_attachments: list[dict] = []
        persisted_attachments: list[dict] = []
        for attachment, attachment_id in zip(source, item_ids):
            if attachment_id is not None:
                trusted = dict(by_id[attachment_id])
                context_attachments.append(trusted)
                persisted_attachments.append(trusted)
                continue
            if not isinstance(attachment, dict):
                continue
            trusted_legacy = self._context_attachments(
                [attachment],
                request_context=request_context,
            )
            context_attachments.extend(trusted_legacy)
            persisted_attachments.append(dict(attachment))

        snippets: list[str] = []
        snippet_loader = getattr(self.attachment_service, "context_snippets", None)
        if callable(snippet_loader):
            try:
                snippets = list(
                    snippet_loader(desktop_ids, max_chars=4000, query=query) or []
                )
            except Exception:
                logger.exception(
                    "desktop attachment snippets unavailable; using metadata only"
                )
        return (
            context_attachments,
            desktop_ids,
            snippets,
            persisted_attachments,
        )

    def _assemble_continuity_context(
        self,
        *,
        base_messages: list[dict],
        msg: IncomingMessage,
        current_user_content: str,
        attachment_snippets: list[str],
        request_context: RequestContext | None,
    ) -> tuple[list[dict], dict[str, Any] | None]:
        assembler = self.context_assembler
        if assembler is None or not base_messages:
            return base_messages, None
        system_prompt = str(base_messages[0].get("content") or "")
        memories = self._retrieve_memory_snippets(
            msg,
            current_user_content,
        )
        try:
            assembled = assembler.assemble(
                system_prompt=system_prompt,
                current_user_content=current_user_content,
                actor_id=msg.actor_id,
                channel=msg.channel,
                channel_account_id=msg.channel_account_id,
                user_id=msg.user_id,
                conversation_id=(
                    request_context.conversation_id
                    if request_context is not None
                    else None
                ),
                memories=memories,
                attachment_snippets=attachment_snippets,
            )
            messages = getattr(assembled, "messages", None)
            audit = getattr(assembled, "audit", None)
            if not isinstance(messages, list) or not messages:
                raise ValueError("continuity assembler returned no messages")
            return messages, dict(audit) if isinstance(audit, dict) else None
        except Exception:
            logger.exception(
                "continuity context assembly failed; using legacy context"
            )
            return base_messages, None

    def _retrieve_memory_snippets(
        self,
        msg: IncomingMessage,
        query: str,
    ) -> list[str]:
        retrieve = getattr(self.memory_store, "retrieve", None)
        if not callable(retrieve):
            return []
        try:
            rows = retrieve(
                msg.user_id,
                query,
                5,
                actor_id=msg.actor_id,
            )
        except Exception:
            logger.debug("continuity memory retrieval failed", exc_info=True)
            return []
        snippets: list[str] = []
        for row in rows or []:
            if not isinstance(row, dict):
                try:
                    row = dict(row)
                except Exception:
                    continue
            content = str(row.get("content") or "").strip()
            if content:
                snippets.append(content)
        return snippets

    def _extract_trusted_attachment_markdown(
        self,
        attachment: dict[str, Any],
    ) -> str | None:
        url = str(attachment.get("url") or "")
        if not url:
            return None
        normalized = unquote(url).replace("\\", "/").lstrip("/")
        parts = normalized.split("/")
        if len(parts) != 2 or parts[0] != "uploads":
            return None
        filename = parts[1]
        if not filename or filename in {".", ".."} or "/" in filename:
            return None
        upload_base = Path(__file__).resolve().parent.parent / "uploads"
        upload_path = upload_base / filename
        return extract_markdown(upload_path, upload_base=upload_base)

    def _checkpoint_cancel(
        self,
        request_state: _RequestRunState,
        boundary: str,
    ) -> bool:
        token = request_state.token
        if token is None:
            return False
        token.throw_if_cancelled(
            boundary=boundary,
            terminal_side_effect_committed=(
                request_state.terminal_side_effect_committed
            ),
            completed=request_state.canonical_completed,
        )
        return bool(request_state.canonical_completed and token.cancelled)

    def _event_contract(
        self,
        request_state: _RequestRunState,
        *,
        message_id: int,
        response_group_id: str | None = None,
    ) -> dict[str, Any]:
        context = request_state.context
        if context is None:
            return {}
        return {
            "event_id": generate_id("event"),
            "request_id": context.request_id,
            "conversation_id": context.conversation_id,
            "turn_id": context.turn_id,
            "message_id": str(message_id),
            "response_group_id": response_group_id,
            "sequence": request_state.next_sequence(),
            "channel": context.identity.channel,
        }

    def _decision_inputs(
        self,
        *,
        user_id: int,
        channel: str,
        channel_account_id: str | None,
        actor_id: str | None,
    ) -> dict[str, Any]:
        """Real-world inputs for the decision engine race.

        The engine used to predict from an empty snapshot (neutral mood, no
        tools, recall always possible), which made the race diverge from the
        real executors. Feed it the current mood, eruption, tool availability
        and RecallManager budget so prediction ≈ what can actually execute.
        """
        inputs: dict[str, Any] = {
            "emotion_label": "neutral",
            "active_eruption": None,
            "user_busy": False,
            "tools_offered": False,
            "recall_available": True,
        }
        try:
            state = self.emotion.get_state(user_id, actor_id=actor_id)
            inputs["emotion_label"] = state.get("label") or "neutral"
            inputs["active_eruption"] = state.get("eruption")
        except Exception:
            logger.debug("decision inputs: emotion state unavailable", exc_info=True)
        try:
            inputs["tools_offered"] = bool(self.tool_registry)
        except Exception:
            pass
        if self.recall_manager is not None:
            try:
                can, _why = self.recall_manager.can_recall(
                    user_id,
                    channel=channel,
                    channel_account_id=channel_account_id,
                )
                inputs["recall_available"] = can
            except Exception:
                logger.debug("decision inputs: recall budget unavailable", exc_info=True)
        return inputs

    # ══════════════════════════════════════════════
    # Gate 2: LLM 主动撤回指令 (recall_instruction)
    # ══════════════════════════════════════════════
    def _recall_instruction_enabled(self) -> bool:
        try:
            return FeatureFlags().is_enabled("recall_llm_instruction_v1")
        except Exception:
            return False

    def _llm_recall_trigger_enabled(self) -> bool:
        """recall.triggers 是否允许 LLM 主动撤回 (不再死配置).

        命中 send_after_thinking / regret_correction 任一即视为开启。
        """
        try:
            triggers = set(self.recall_manager.config.triggers or [])
        except Exception:
            triggers = set()
        return bool(triggers & {"send_after_thinking", "regret_correction"})

    async def _handle_recall_instruction(
        self,
        raw_text: str,
        msg: IncomingMessage,
    ) -> tuple[str, dict | None]:
        """从 LLM 原始输出中解析并执行 <recall> 指令.

        返回 (剔除撤回指令标签后的正文, 撤回执行结果) —— 正文绝不发送
        给用户; 结果 dict 用于回写决策赛马的"实际执行" (无指令/禁用时
        为 None)。受 feature flag 与 RecallManager 预算
        (window/cooldown/session) 双重约束, 不越权撤回。
        """
        if not self.recall_manager or not self._recall_instruction_enabled():
            return raw_text, None
        if not raw_text:
            return raw_text, None
        # 激活 persona.yaml 的 recall.triggers（不再死配置）:
        # 仅当配置允许「LLM 主动撤回」类触发器时才消费 <recall> 指令。
        if not self._llm_recall_trigger_enabled():
            return raw_text, None
        from core.recall_instruction import (
            extract_recall_instruction,
            strip_recall_instruction,
            execute_recall_instruction,
        )
        inst = extract_recall_instruction(raw_text)
        if inst is None:
            return raw_text, None
        channel = getattr(msg, "channel", None) or getattr(msg, "source", None) or "qq"
        account = getattr(msg, "channel_account_id", None)
        result: dict[str, Any] | None = None
        try:
            result = await execute_recall_instruction(
                self.recall_manager,
                channel=channel,
                channel_account_id=account,
                user_id=msg.user_id,
                reason=inst.reason or "llm_instruction",
            )
            if result.get("status") == "ok":
                self._mark_recalled_message(result, msg)
            logger.info(
                "LLM recall instruction executed: reason=%r status=%s channel=%s",
                inst.reason, result.get("status"), channel,
            )
        except Exception:
            logger.exception("LLM recall instruction execution failed")
        actual: dict[str, Any] | None = None
        if result is not None:
            actual = {
                "intent": "recall",
                "source": "llm_instruction",
                "triggered": True,
                "executed": result.get("status") == "ok",
                "status": result.get("status"),
                "reason": inst.reason or "llm_instruction",
                "budget_gate": (
                    "ok" if result.get("status") == "ok"
                    else (result.get("reason") or "unknown")
                ),
                "channel": channel,
            }
        return strip_recall_instruction(raw_text), actual

    def _mark_recalled_message(self, result: dict, msg: IncomingMessage) -> None:
        """LLM <recall> 撤回成功后, 本地落库 + 发 recall 事件.

        与 Companion.recall_message 保持一致的标记/事件契约: 前端收到
        recall 事件后把对应气泡替换为居中的"<人设名> 撤回了一条消息"。
        QQ 平台侧由 NapCat 原生显示撤回提示, 这里仅同步本地聊天记录。
        """
        msg_id = result.get("msg_id")
        if msg_id:
            try:
                self.db.update(
                    "chat_log",
                    {
                        "is_recalled": 1,
                        "recalled_at": datetime.now().isoformat(timespec="seconds"),
                        "msg_state": "recalled",
                    },
                    "id = ?",
                    (msg_id,),
                )
            except Exception:
                logger.exception("LLM recall mark failed msg_id=%s", msg_id)
        try:
            from core.chat_events import emit as _emit
            _emit(
                "recall",
                id=msg_id,
                user_id=msg.user_id,
                role="assistant",
                channel=result.get("channel", "local"),
            )
        except Exception:
            logger.exception("LLM recall event emit failed")

    async def _handle_basic_lightweight(
        self,
        msg: IncomingMessage,
        trace: dict,
        route_mode: str,
        *,
        model_content: str,
        context_attachments: list[dict],
        attachment_ids: list[str],
        attachment_snippets: list[str],
        request_state: _RequestRunState,
    ) -> dict | None:
        """BASIC 模式轻量对话链路。

        保留：情绪识别 + 历史上下文 + LLM 回复 + 后处理 + 持久化 + emit
        跳过：工具调用 + 自进化 + 决策引擎 + 完整认知追踪
        """
        # 1. 情绪更新（轻量：仅关键词路径，不调 LLM PAD 以省 Token）
        try:
            self.emotion.update_trajectory(
                msg.user_id,
                model_content,
                actor_id=msg.actor_id,
            )
        except Exception:
            logger.exception("BASIC emotion update error")

        # 获取情绪状态（用于回复语气调整）
        emotion_info = None
        try:
            state = self.emotion.get_state(
                msg.user_id,
                actor_id=msg.actor_id,
            )
            emotion_info = {
                "label": state.get("label", "neutral"),
                "pad": state.get("pad", {}),
            }
        except Exception:
            pass

        self.cognition.record(trace, "emotion", {
            "label": (emotion_info or {}).get("label"),
            "pad": (emotion_info or {}).get("pad"),
            "lightweight": True,
        })

        # 2. 获取历史（精简：最近 10 条）
        history = self._load_history(msg, legacy_limit=10)

        # 3. 构建上下文（BASIC 精简系统提示词）
        context_budget_enabled = self._context_budget_enabled()
        context_budget_kwargs = (
            self._context_budget_kwargs(msg)
            if context_budget_enabled
            else {}
        )
        ctx_messages = self.ctx_builder.build(
            msg.user_id,
            model_content,
            route_mode,  # "BASIC" — context_builder 会生成精简系统提示
            history_msgs=history,
            emotion_info=emotion_info,
            eruption_info=None,
            reply_to=None,
            attachments=context_attachments if context_attachments else None,
            **context_budget_kwargs,
        )
        ctx_messages, continuity_audit = self._assemble_continuity_context(
            base_messages=ctx_messages,
            msg=msg,
            current_user_content=model_content,
            attachment_snippets=attachment_snippets,
            request_context=request_state.context,
        )

        system_chars = len(ctx_messages[0]["content"]) if ctx_messages else 0
        context_record = {
            "messages": len(ctx_messages),
            "system_prompt_chars": system_chars,
            "tools_offered": False,
            "lightweight": True,
        }
        audit = (
            self._context_budget_audit()
            if context_budget_enabled
            else None
        )
        if audit:
            context_record["context_budget"] = audit
        if continuity_audit:
            context_record["continuity"] = continuity_audit
        self.cognition.record(trace, "context", context_record)

        # 4. 调 LLM（无工具，纯对话）
        self._checkpoint_cancel(request_state, "before_model")
        response = await self.brain.chat(
            ctx_messages,
            tools=None,
            tool_registry=self.tool_registry,
            preferred_provider=None,
        )
        self._checkpoint_cancel(request_state, "after_model")
        raw_text = getattr(response, "text", "") or ""
        model_name = getattr(response, "model", "unknown")
        usage = getattr(response, "usage", None) or {}

        # 剥掉  thinking 块
        reply_text_raw = self._strip_think(raw_text)

        # 剥掉模型可能回显的历史时间戳前缀 [MM-DD HH:MM]
        reply_text_raw = self._strip_leading_timestamp(reply_text_raw)

        # Gate 2: LLM 主动撤回指令 — 解析 <recall>, 执行撤回, 并从正文剔除
        reply_text_raw, _recall_actual = await self._handle_recall_instruction(reply_text_raw, msg)
        if _recall_actual:
            self.cognition.record_decision_actual(trace, _recall_actual)

        self.cognition.record(trace, "brain", {
            "model": model_name,
            "tokens": usage,
            "raw_chars": len(raw_text),
            "lightweight": True,
        })

        # 5. 情绪润色 + 自检
        reply_text = self.emotion.tune(
            reply_text_raw,
            actor_id=msg.actor_id,
        )
        try:
            from core.screen_action_sanitizer import sanitize as _sanitize_action
            reply_text = _sanitize_action(reply_text)
        except Exception:
            pass
        try:
            from core.output_self_check import OutputSelfCheck
            _self_check = OutputSelfCheck()
            _sc_result = _self_check.check(reply_text)
            reply_text = _sc_result.cleaned_text
        except Exception:
            pass

        # Task 5: Content validation for BASIC lightweight mode
        content_remedied = False
        try:
            last_user_msg_for_ctx = model_content
            reply_text, content_remedied = await self.content_validator.validate_and_fix(
                reply_text,
                context={"last_user_message": last_user_msg_for_ctx},
            )
            if content_remedied:
                self.cognition.record(trace, "content_validation", {
                    "remedied": True,
                    "final_length": len(reply_text),
                    "lightweight": True,
                })
        except Exception:
            logger.exception("BASIC content_validator failed; using current text as-is")

        self.cognition.record(trace, "postprocess", {
            "tune_label": (emotion_info or {}).get("label"),
            "raw_chars": len(reply_text_raw),
            "tuned_chars": len(reply_text),
            "lightweight": True,
            "content_remedied": content_remedied,
        })

        # 5.5 Response Validation（v13.9: BASIC 模式也做轻量校验）
        try:
            vr = await self.validator.validate(
                reply_text,
                user_message=model_content,
                context_history=history,
                route_mode=route_mode,
            )
            if vr.issues:
                self.cognition.record(trace, "validation", {
                    "passed": vr.passed,
                    "guard_passed": vr.guard_passed,
                    "judge_score": vr.judge_score,
                    "rewrite_count": vr.rewrite_count,
                    "issues": vr.issues,
                    "lightweight": True,
                })
        except Exception:
            logger.exception("BASIC validation failed; best-effort skip")

        # 6. 语义拆分
        segments = self._splitter.split(reply_text) or [reply_text]
        self.cognition.record(trace, "split", {
            "segments": segments,
            "count": len(segments),
            "lightweight": True,
        })

        # 7. 持久化用户消息
        user_row_id = 0
        persist_errors: list[str] = []
        try:
            self._checkpoint_cancel(request_state, "before_legacy_user")
            user_row_id = self.db.insert("chat_log", {
                "user_id": msg.user_id,
                "role": "user",
                "content": msg.content,
                "msg_type": msg.msg_type,
                "route_mode": route_mode,
                "attachments": json.dumps(msg.attachments, ensure_ascii=False) if msg.attachments else None,
                "actor_id": msg.actor_id,
                "channel": msg.channel,
                "channel_account_id": msg.channel_account_id,
            })
            if user_row_id:
                request_state.terminal_side_effect_committed = True
        except CancellationTooLate:
            raise
        except Exception as e:
            persist_errors.append(f"user message: {e}")
            logger.exception("db insert user msg error")

        # 8. 持久化 AI 回复
        ai_row_ids: list[int] = []
        try:
            for seg in segments:
                self._checkpoint_cancel(
                    request_state,
                    "before_legacy_assistant",
                )
                rid = self.db.insert("chat_log", {
                    "user_id": msg.user_id,
                    "role": "assistant",
                    "content": seg,
                    "msg_type": msg.msg_type,
                    "route_mode": route_mode,
                    "actor_id": msg.actor_id,
                    "channel": msg.channel,
                    "channel_account_id": msg.channel_account_id,
                })
                ai_row_ids.append(rid)
                if rid:
                    request_state.terminal_side_effect_committed = True
        except CancellationTooLate:
            raise
        except Exception as e:
            persist_errors.append(f"assistant message: {e}")
            logger.exception("db insert ai msg error")

        canonical_result: dict[str, str] | None = None
        if user_row_id and len(ai_row_ids) == len(segments):
            self._checkpoint_cancel(request_state, "before_canonical")
            canonical_result = self._persist_canonical_turn(
                msg,
                segments,
                request_context=request_state.context,
                user_legacy_chat_log_id=user_row_id or None,
                assistant_legacy_chat_log_ids=ai_row_ids,
            )
            if canonical_result is not None:
                request_state.canonical_completed = True
                request_state.response_group_id = canonical_result.get(
                    "response_group_id"
                )

        attachment_bind_error = self._after_message_persisted(
            attachment_ids=attachment_ids,
            canonical_result=canonical_result,
            user_legacy_chat_log_id=user_row_id,
            msg=msg,
            request_context=request_state.context,
        )

        self.cognition.record(trace, "output", {
            "ai_msg_ids": ai_row_ids,
            "user_msg_id": user_row_id,
            "source": msg.source,
            "segment_count": len(ai_row_ids),
            "lightweight": True,
        })

        result = {
            "reply": reply_text,
            "user_msg_id": user_row_id,
            "ai_msg_id": ai_row_ids[0] if ai_row_ids else 0,
            "ai_msg_ids": ai_row_ids,
            "segments": segments,
            "route_mode": route_mode,
            "emotion": emotion_info.get("label") if emotion_info else "unknown",
            "cognition_id": trace.get("id", 0),
            "lightweight": True,
            "persisted": not persist_errors,
            "canonical_completed": request_state.canonical_completed,
        }
        if request_state.context is not None:
            result.update(
                {
                    "request_id": request_state.context.request_id,
                    "conversation_id": request_state.context.conversation_id,
                    "turn_id": request_state.context.turn_id,
                }
            )
        if canonical_result:
            result["canonical"] = canonical_result
            result["response_group_id"] = canonical_result.get(
                "response_group_id"
            )
        if persist_errors:
            result["persist_error"] = "; ".join(persist_errors)
        if attachment_bind_error:
            result["attachment_bind_error"] = attachment_bind_error

        # 9. Emit 事件（前端展示用）
        if self._checkpoint_cancel(request_state, "before_event"):
            result["event_sequence"] = request_state.sequence
            return result
        try:
            emit(
                "user",
                role="user",
                id=user_row_id,
                user_id=msg.user_id,
                content=msg.content,
                source=msg.source,
                **self._event_contract(
                    request_state,
                    message_id=user_row_id,
                ),
            )
        except Exception:
            pass

        for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
            if self._checkpoint_cancel(request_state, "before_event"):
                result["event_sequence"] = request_state.sequence
                return result
            try:
                emit_kwargs = {
                    "role": "assistant",
                    "id": rid,
                    "user_id": msg.user_id,
                    "content": seg,
                    "source": msg.source,
                    **self._event_contract(
                        request_state,
                        message_id=rid,
                        response_group_id=request_state.response_group_id,
                    ),
                }
                if idx == 0 and emotion_info:
                    emit_kwargs["emotion"] = emotion_info["label"]
                emit("assistant", **emit_kwargs)
            except Exception:
                pass

        # 10. QQ 消息入队
        if msg.source == "qq" and ai_row_ids:
            reply = OutgoingReply(
                user_id=msg.user_id,
                content=reply_text,
                msg_id=ai_row_ids[0],
                reply_to_qq_message_id=0,
                cognition_id=int(trace.get("id") or 0),
            )
            if self._checkpoint_cancel(request_state, "before_qq_enqueue"):
                result["event_sequence"] = request_state.sequence
                return result
            self.send_queue.enqueue(reply)
        result["event_sequence"] = request_state.sequence
        return result

    def _after_message_persisted(
        self,
        *,
        attachment_ids: list[str],
        canonical_result: dict[str, str] | None,
        user_legacy_chat_log_id: int,
        msg: IncomingMessage,
        request_context: RequestContext | None,
    ) -> str | None:
        conversation_id = (
            canonical_result.get("conversation_id")
            if canonical_result is not None
            else (
                request_context.conversation_id
                if request_context is not None
                else None
            )
        )
        if conversation_id is None:
            try:
                from core.conversation_repository import resolve_conversation_id

                conversation_id = resolve_conversation_id(
                    actor_id=msg.actor_id,
                    channel=msg.channel,
                    channel_account_id=msg.channel_account_id,
                    user_id=msg.user_id,
                )
            except Exception:
                logger.debug(
                    "legacy attachment conversation id unavailable",
                    exc_info=True,
                )
        if attachment_ids and user_legacy_chat_log_id:
            message_id = self._canonical_user_message_id(canonical_result)
            if not message_id:
                message_id = str(user_legacy_chat_log_id)
            binder = getattr(self.attachment_service, "bind_message", None)
            if callable(binder):
                try:
                    binder(
                        attachment_ids,
                        message_id=str(message_id),
                        conversation_id=conversation_id,
                    )
                except Exception as exc:
                    logger.exception(
                        "desktop attachment bind failed after message persistence"
                    )
                    bind_error = type(exc).__name__
                else:
                    bind_error = None
            else:
                bind_error = "attachment_service_unavailable"
        else:
            bind_error = None

        if canonical_result is not None and conversation_id:
            self._schedule_summary_refresh(str(conversation_id))
        return bind_error

    def _canonical_user_message_id(
        self,
        canonical_result: dict[str, str] | None,
    ) -> str | None:
        if not canonical_result:
            return None
        turn_id = canonical_result.get("turn_id")
        if not turn_id:
            return None
        query_one = getattr(self.db, "query_one", None)
        if not callable(query_one):
            return None
        try:
            row = query_one(
                "SELECT message_id FROM messages "
                "WHERE turn_id = ? AND role = 'user' "
                "ORDER BY sequence ASC LIMIT 1",
                (turn_id,),
            )
        except Exception:
            logger.debug("canonical user message lookup failed", exc_info=True)
            return None
        if not row:
            return None
        try:
            return str(row["message_id"])
        except (KeyError, TypeError):
            return str(getattr(row, "message_id", "") or "") or None

    def _schedule_summary_refresh(self, conversation_id: str) -> None:
        if self.summary_planner is None or conversation_id in self._summary_inflight:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("summary refresh skipped outside an event loop")
            return
        self._summary_inflight.add(conversation_id)
        task = loop.create_task(
            self._refresh_summary(conversation_id),
            name=f"conversation-summary-{conversation_id}",
        )
        self._summary_tasks.add(task)
        task.add_done_callback(self._summary_tasks.discard)

    async def _refresh_summary(self, conversation_id: str) -> None:
        try:
            job = await asyncio.to_thread(
                self.summary_planner.prepare,
                conversation_id,
            )
            if job is None:
                return
            await asyncio.to_thread(
                self.summary_planner.complete,
                job,
                self.summary_summarizer,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "conversation summary refresh failed; existing context remains active"
            )
        finally:
            self._summary_inflight.discard(conversation_id)

    async def wait_for_background_tasks(self) -> None:
        """Wait for currently scheduled continuity work (primarily for QA)."""
        while self._summary_tasks:
            tasks = list(self._summary_tasks)
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown_background_tasks(self) -> None:
        tasks = list(self._summary_tasks) + list(self._photo_tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._summary_tasks.clear()
        self._summary_inflight.clear()
        self._photo_tasks.clear()

    @staticmethod
    def _default_rolling_summary(
        previous: str,
        messages: Any,
    ) -> str:
        max_chars = 11_500
        previous_text = " ".join(str(previous or "").split())[:5_500]
        rows = list(messages or [])
        prefix = f"previous: {previous_text}" if previous_text else ""
        separator_budget = 1 if prefix and rows else 0
        remaining = max_chars - len(prefix) - separator_budget
        per_message = max(80, remaining // max(len(rows), 1))
        lines: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                role = str(row.get("role") or "message")
                content = " ".join(str(row.get("content") or "").split())
            else:
                role = "message"
                content = " ".join(str(row or "").split())
            line = f"{role}: {content}"[:per_message]
            if line:
                lines.append(line)
        result = "\n".join(part for part in (prefix, *lines) if part)
        return result[:max_chars] or "completed conversation turn"

    def _load_history(
        self,
        msg: IncomingMessage,
        *,
        legacy_limit: int,
    ) -> list[dict]:
        if self.conversation_repository and getattr(
            self.conversation_repository,
            "enabled",
            False,
        ):
            try:
                return self.conversation_repository.recent_turn_history(
                    actor_id=msg.actor_id,
                    channel=msg.channel,
                    channel_account_id=msg.channel_account_id,
                    user_id=msg.user_id,
                    limit=legacy_limit,
                )
            except Exception:
                logger.exception("canonical history read failed; using legacy history")
        try:
            if msg.actor_id and msg.channel:
                history = self.db.query(
                    "SELECT role, content, created_at FROM chat_log "
                    "WHERE actor_id = ? AND channel = ? "
                    f"ORDER BY id DESC LIMIT {legacy_limit}",
                    (msg.actor_id, msg.channel),
                )
            else:
                history = self.db.query(
                    "SELECT role, content, created_at FROM chat_log WHERE user_id = ? "
                    f"ORDER BY id DESC LIMIT {legacy_limit}",
                    (msg.user_id,),
                )
            history.reverse()
            return history
        except Exception:
            return []

    @staticmethod
    def _context_budget_enabled() -> bool:
        try:
            return FeatureFlags().is_enabled("context_budget_v1")
        except Exception:
            return False

    @staticmethod
    def _context_budget_kwargs(msg: IncomingMessage) -> dict[str, Any]:
        return {
            "actor_id": msg.actor_id,
            "channel": msg.channel,
            "channel_account_id": msg.channel_account_id,
            "context_budget_enabled": True,
        }

    def _context_budget_audit(self) -> dict[str, Any] | None:
        getter = getattr(self.ctx_builder, "get_last_context_audit", None)
        if not callable(getter):
            return None
        try:
            audit = getter()
        except Exception:
            return None
        if not isinstance(audit, dict) or not audit.get("enabled"):
            return None
        allowed = {
            "enabled",
            "actor_id",
            "channel",
            "channel_account_id",
            "memory_hits",
            "knowledge_hits",
            "history_messages",
            "merged_history_messages",
            "dropped_history_messages",
            "truncated_system",
            "estimated_tokens",
            "total_chars",
            "system_prompt_chars",
        }
        return {key: audit[key] for key in allowed if key in audit}

    def _persist_canonical_turn(
        self,
        msg: IncomingMessage,
        segments: list[str],
        *,
        request_context: RequestContext | None = None,
        user_legacy_chat_log_id: int | None = None,
        assistant_legacy_chat_log_ids: list[int] | None = None,
    ) -> dict[str, str] | None:
        if not self.conversation_repository or not getattr(
            self.conversation_repository,
            "enabled",
            False,
        ):
            return None
        request_id = (
            request_context.request_id
            if request_context is not None
            else generate_id("req")
        )
        try:
            return self.conversation_repository.persist_turn(
                request_id=request_id,
                user_id=msg.user_id,
                actor_id=msg.actor_id,
                channel=msg.channel,
                channel_account_id=msg.channel_account_id,
                user_content=msg.content,
                user_attachments=msg.attachments,
                assistant_segments=segments,
                user_legacy_chat_log_id=user_legacy_chat_log_id,
                assistant_legacy_chat_log_ids=assistant_legacy_chat_log_ids,
                conversation_id=(
                    request_context.conversation_id
                    if request_context is not None
                    else None
                ),
                turn_id=(
                    request_context.turn_id
                    if request_context is not None
                    else None
                ),
            )
        except Exception:
            if request_context is not None:
                raise
            logger.exception("canonical conversation mirror write failed")
            return None

    @staticmethod
    def _extract_react(text: str) -> dict:
        """Backward-compat shim: delegate to brain._build_react_from_text.

        Kept so any external caller (or older test) that still calls
        Pipeline._extract_react continues to work. New code should read
        the react_trace directly off the BrainResponse.
        """
        from core.llm_caller import _build_react_from_text
        return _build_react_from_text(text, tool_calls_present=False)

    @staticmethod
    def _inject_task_plan_into_context(system_prompt: str, plan) -> str:
        """将任务计划注入到系统提示词中，引导 Agent 按步骤执行。"""
        if not plan or not plan.steps or len(plan.steps) <= 1:
            return system_prompt

        steps_text = "\n".join([
            f"  {s.step_id}. {s.title}：{s.description}"
            for s in plan.steps
        ])

        plan_suffix = f"""

---

【任务执行计划 · Task Execution Plan】
当前任务类型：{plan.task_type.value if hasattr(plan.task_type, 'value') else str(plan.task_type)}
任务目标：{plan.title}

=== 执行步骤 ===
{steps_text}

=== 执行要求 ===
1. 严格按照上述步骤顺序执行，不要跳步
2. 每步执行完用工具验证结果，确认无误再进入下一步
3. 遇到问题及时调整，但不要偏离整体目标
4. 全部完成后给用户一个清晰的总结

记住：你是一个靠谱的执行者。稳比快重要，每一步都要有结果。
"""

        return system_prompt + plan_suffix

    @staticmethod
    def _strip_think(text: str) -> str:
        """Remove  thinking… response block from user-visible text."""
        import re
        return re.sub(r" thinking.*? response", "", text, flags=re.DOTALL).strip()

    _HIST_LABEL_RE = re.compile(r"\[\d{2}-\d{2} ?\d{2}:\d{2}\]\s*")

    @classmethod
    def _strip_leading_timestamp(cls, text: str) -> str:
        """Strip any ``[MM-DD HH:MM] `` timestamp markers the model may echo.

        History messages are prefixed with this label so the LLM can tell when
        each turn happened (see context_builder._hist_label). Some models
        imitate that format and sprinkle timestamps into their own reply
        (leading and mid-text alike), which would otherwise leak into the
        user-visible message. The ``[MM-DD HH:MM]`` shape is unique enough to
        this injected marker that we remove every occurrence; the user's
        companion text never legitimately uses this exact bracket format.
        """
        if not text:
            return text
        return cls._HIST_LABEL_RE.sub("", text).strip()

    @staticmethod
    def _ensure_react_trace(
        react_trace: dict | None,
        trace: dict,
        raw_text: str,
        tool_results: list,
    ) -> dict:
        """Guarantee a non-None react_trace with react_source tag.

        Priority:
          1. If ``react_trace`` already has ``react_source == "model"`` and a
             real ``thought`` → return as-is (real LLM <think>).
          2. If ``react_trace`` is missing, "model-no-think", "fallback", or
             has a null thought → synthesize a thought from the stage data
             the pipeline has already collected (route / emotion /
             threshold / context / brain / split).
          3. Preserve ``react_source`` from the brain when synthesizing
             (downgrade "model" → "synthesized-from-model" if no thought).
        """
        if (
            react_trace
            and react_trace.get("react_source") == "model"
            and (react_trace.get("thought") or "").strip()
        ):
            return react_trace

        synthesized = Pipeline._synthesize_react(trace, raw_text, tool_results)
        if react_trace:
            # Preserve any non-null fields the brain did provide (e.g. action
            # came from tool_calls) but override the thought with our
            # synthesis and tag the source.
            merged = dict(react_trace)
            merged["thought"] = synthesized["thought"]
            merged["observation"] = synthesized.get("observation") or merged.get("observation")
            if merged.get("react_source") in ("model-no-think", "fallback", None):
                merged["react_source"] = "synthesized"
            elif not merged.get("thought"):
                merged["react_source"] = "synthesized-from-model"
            return merged
        return synthesized

    @staticmethod
    def _synthesize_react(
        trace: dict,
        raw_text: str,
        tool_results: list,
    ) -> dict:
        """Build a react trace from the stage data the pipeline already has.

        This is a *fallback* for when the LLM did not emit a <think> block.
        It is honest about being a reconstruction (not a real thought) so
        the brain-center UI can show the source label truthfully.
        """
        stages = trace.get("stages", {}) or {}
        route = stages.get("route") or {}
        emotion = stages.get("emotion") or {}
        threshold = stages.get("threshold") or {}
        ctx = stages.get("context") or {}
        brain_stage = stages.get("brain") or {}
        split = stages.get("split") or {}

        user_message = (trace.get("user_message") or "").strip()
        short_msg = user_message[:30] + ("…" if len(user_message) > 30 else "")

        label = (emotion.get("label") or "neutral")
        pad = emotion.get("pad") or {}
        p = pad.get("pleasure", 0.0)
        a = pad.get("arousal", 0.0)
        d = pad.get("dominance", 0.0)

        def _slot(name: str) -> float:
            slot = (threshold.get(name) or {})
            try:
                return float(slot.get("value", 0.0))
            except Exception:
                return 0.0

        slots = (
            f"忍耐 {_slot('patience'):.0f}/不安 {_slot('anxiety'):.0f}"
            f"/渴望 {_slot('desire'):.0f}/温柔 {_slot('tenderness'):.0f}"
        )

        msgs_count = ctx.get("messages", 0)
        model_name = brain_stage.get("model", "unknown")
        seg_count = split.get("count", 0)
        total_chars = sum(len(s) for s in (split.get("segments") or []))

        action = "tool_call" if tool_results else "reply"
        observation_bits = [
            f"segments={seg_count}",
            f"total_chars={total_chars}",
        ]
        if tool_results:
            observation_bits.append("tools=" + ",".join(
                t.get("name", "?") for t in tool_results
            ))

        thought = (
            f"看到「{short_msg}」→ 路由 {route.get('mode', 'AUTO')} → "
            f"情绪 {label} (P{p:.2f}/A{a:.2f}/D{d:.2f}) → "
            f"{slots} → 上下文 {msgs_count} 条历史 → "
            f"调起 LLM {model_name} → 拆为 {seg_count} 段"
        )

        return {
            "thought": thought,
            "action": action,
            "observation": " | ".join(observation_bits),
            "react_source": "synthesized",
        }

    # ══════════════════════════════════════════════════════════════
    # Task 4: Batch processing support
    # ══════════════════════════════════════════════════════════════

    async def _handle_batch(
        self,
        messages: list[IncomingMessage],
        batch_id: str,
        *,
        force_full: bool = False,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict]:
        """Handle a batch of messages end-to-end.

        Batch processing stages:
          1. Route: based on all messages in batch
          2. Emotion: comprehensive update to avoid jitter
          3. History: loaded once, reused for entire batch
          4. Context: merged messages with sequence numbers
          5. LLMCaller: single LLM call with batch prompt
          6. Postprocess: per-reply sanitization and checks
          7. Output: per-message persistence with batch_id
          8. Send: OutgoingReply list with sequence_index
        """
        logger.info(
            "Batch %s: processing %d messages",
            batch_id,
            len(messages),
        )

        request_state = _RequestRunState(
            context=None,
            token=cancellation_token,
        )

        first_msg = messages[0]
        user_id = first_msg.user_id
        actor_id = first_msg.actor_id
        channel = first_msg.channel
        channel_account_id = first_msg.channel_account_id
        source = first_msg.source
        msg_type = first_msg.msg_type

        combined_content = "\n".join(m.content for m in messages)

        all_attachments: list[dict] = []
        for m in messages:
            all_attachments.extend(m.attachments or [])
        (
            context_attachments,
            attachment_ids,
            attachment_snippets,
            persisted_attachments,
        ) = self._prepare_attachments(
            all_attachments,
            request_context=None,
            query=combined_content,
        )

        if self.identity_resolver:
            for m in messages:
                try:
                    self.identity_resolver.resolve_message(m)
                except Exception:
                    pass

        trace = self.cognition.begin(user_id, source, combined_content)
        self.cognition.record(trace, "batch", {
            "batch_id": batch_id,
            "message_count": len(messages),
        })

        route_mode = self.router.route(user_id)
        if force_full or source == "local":
            route_mode = "FULL"
        self.cognition.record(trace, "route", {"mode": route_mode, "batch": True})

        if self.decision_engine:
            try:
                dinputs = self._decision_inputs(
                    user_id=user_id,
                    channel=channel,
                    channel_account_id=channel_account_id,
                    actor_id=actor_id,
                )
                decision = self.decision_engine.decide_for_message(
                    user_id=user_id,
                    route_mode=route_mode,
                    source=source,
                    **dinputs,
                )
                self.cognition.record_decision(trace, decision)
            except Exception:
                logger.exception("[Batch %s] decision engine error", batch_id)

        if self.recall_manager and source == "qq":
            try:
                for m in messages:
                    await self.recall_manager.handle_user_negative(
                        user_id, m.content, channel=source,
                    )
            except Exception:
                logger.exception("[Batch %s] handle_user_negative error", batch_id)

        try:
            await self.emotion.update_trajectory_async(
                user_id,
                combined_content,
                actor_id=actor_id,
            )
        except Exception:
            logger.exception("[Batch %s] emotion update error", batch_id)

        history = self._load_history(first_msg, legacy_limit=20)

        emotion_info = None
        eruption_info = None
        try:
            state = self.emotion.get_state(user_id, actor_id=actor_id)
            emotion_info = {
                "label": state.get("label", "neutral"),
                "pad": state.get("pad", {}),
                "thresholds": state.get("thresholds", {}),
            }
            eruption_info = state.get("eruption")
        except Exception:
            pass

        self.cognition.record(trace, "emotion", {
            "label": (emotion_info or {}).get("label"),
            "pad": (emotion_info or {}).get("pad"),
            "batch": True,
        })
        self.cognition.record(trace, "threshold", (emotion_info or {}).get("thresholds"))

        time_context = None
        try:
            from core.calendar_manager import CalendarManager
            time_context = CalendarManager(self.db).get_agent_snapshot(user_id)
        except Exception:
            logger.warning("[Batch %s] calendar snapshot unavailable", batch_id, exc_info=True)
        context_budget_enabled = self._context_budget_enabled()
        context_budget_kwargs = (
            self._context_budget_kwargs(first_msg)
            if context_budget_enabled
            else {}
        )
        world_snapshot = self._call_optional_context_provider("world_snapshot_provider")
        relationship_snapshot = self._call_optional_context_provider(
            "relationship_snapshot_provider",
            user_id,
        )
        self_model_snapshot = self._call_optional_context_provider(
            "self_model_snapshot_provider",
            world_snapshot,
            relationship_snapshot,
        )
        internal_snapshot = self._call_optional_context_provider(
            "internal_snapshot_provider",
            world_snapshot,
            relationship_snapshot,
        )

        batch_user_content = self._build_batch_user_content(messages)

        ctx_messages = self.ctx_builder.build(
            user_id,
            batch_user_content,
            route_mode,
            history_msgs=history,
            emotion_info=emotion_info,
            eruption_info=eruption_info,
            reply_to=None,
            attachments=context_attachments if context_attachments else None,
            time_context=time_context,
            world_snapshot=world_snapshot,
            relationship_snapshot=relationship_snapshot,
            self_model_snapshot=self_model_snapshot,
            internal_snapshot=internal_snapshot,
            **context_budget_kwargs,
        )

        if ctx_messages:
            last_user_idx = -1
            for i in range(len(ctx_messages) - 1, -1, -1):
                if ctx_messages[i].get("role") == "user":
                    last_user_idx = i
                    break
            if last_user_idx >= 0:
                ctx_messages[last_user_idx]["content"] = batch_user_content

        ctx_messages, continuity_audit = self._assemble_continuity_context(
            base_messages=ctx_messages,
            msg=first_msg,
            current_user_content=batch_user_content,
            attachment_snippets=attachment_snippets,
            request_context=None,
        )
        tools = self.tool_registry.get_openai_schema() if route_mode == "FULL" else None

        system_chars = len(ctx_messages[0]["content"]) if ctx_messages else 0
        history_chars = sum(len(m.get("content", "")) for m in ctx_messages[1:])
        context_record = {
            "messages": len(ctx_messages),
            "system_prompt_chars": system_chars,
            "history_chars": history_chars,
            "tools_offered": bool(tools),
            "batch": True,
            "batch_size": len(messages),
        }
        audit = self._context_budget_audit() if context_budget_enabled else None
        if audit:
            context_record["context_budget"] = audit
        if continuity_audit:
            context_record["continuity"] = continuity_audit
        self.cognition.record(trace, "context", context_record)

        office_mgr = get_office_mode_manager()
        office_ctx = office_mgr.detect(combined_content, history)
        is_office = office_ctx.is_office_mode()
        # 同步办公模式判定到前端（与主处理路径一致），见 office_mode_changed。
        emit(
            "office_mode_changed",
            mode=office_ctx.mode.value if office_ctx.mode else "auto",
            detected_mode=office_ctx.detected_mode.value if office_ctx.detected_mode else None,
        )

        if is_office and ctx_messages:
            sys_content = ctx_messages[0].get("content", "")
            ctx_messages[0]["content"] = office_mgr.augment_system_prompt(sys_content)
            system_chars = len(ctx_messages[0]["content"])

        self.cognition.record(trace, "office_mode", {
            "mode": office_ctx.mode.value if office_ctx.mode else "auto",
            "detected": office_ctx.detected_mode.value if office_ctx.detected_mode else None,
            "is_office": is_office,
            "task_type": office_ctx.task_type.value if office_ctx.task_type else None,
            "confidence": office_ctx.confidence,
            "keywords": office_ctx.task_keywords,
        })

        self._checkpoint_cancel(request_state, "before_model")
        response = await self.brain.chat(
            ctx_messages,
            tools=tools,
            tool_registry=self.tool_registry,
            preferred_provider=office_mgr.get_preferred_provider() if is_office else None,
        )
        self._checkpoint_cancel(request_state, "after_model")
        raw_text = getattr(response, "text", "") or ""
        react_trace = getattr(response, "react_trace", None)
        tool_results = getattr(response, "tool_results", None) or []
        model_name = getattr(response, "model", "unknown")
        usage = getattr(response, "usage", None) or {}

        react_trace = self._ensure_react_trace(react_trace, trace, raw_text, tool_results)
        reply_text_raw = self._strip_think(raw_text)

        # Strip a leading [MM-DD HH:MM] timestamp the model may echo back
        reply_text_raw = self._strip_leading_timestamp(reply_text_raw)

        self.cognition.record(trace, "brain", {
            "model": model_name,
            "tokens": usage,
            "raw_chars": len(raw_text),
            "react": react_trace,
            "batch": True,
        })
        self.cognition.record_react(trace, react_trace)

        tool_summary: list[dict] = []
        for tr in tool_results:
            try:
                self.db.insert("tool_call_log", {
                    "ts": int(__import__("time").time() * 1000),
                    "user_id": user_id,
                    "tool_name": tr.get("name", "unknown"),
                    "arguments": json.dumps(tr.get("arguments", {}), ensure_ascii=False),
                    "result": json.dumps(tr.get("result", {}), ensure_ascii=False)[:2000],
                    "success": 1 if tr.get("success", True) else 0,
                    "duration_ms": tr.get("duration_ms", 0),
                })
            except Exception:
                logger.exception("[Batch %s] tool_call_log insert error", batch_id)
            tool_summary.append({
                "name": tr.get("name"),
                "success": tr.get("success", True),
                "duration_ms": tr.get("duration_ms", 0),
            })
        self.cognition.record(trace, "tools", tool_summary)

        parsed_replies = self._parse_batch_replies(reply_text_raw, len(messages), batch_id)

        if len(parsed_replies) != len(messages):
            logger.warning(
                "[Batch %s] LLM returned %d replies for %d messages, falling back to single processing",
                batch_id,
                len(parsed_replies),
                len(messages),
            )
            results = []
            for i, m in enumerate(messages):
                try:
                    single_result = await self.handle(
                        msg=m,
                        force_full=force_full,
                        cancellation_token=cancellation_token,
                    )
                    if single_result:
                        single_result["batch_id"] = batch_id
                        single_result["sequence_index"] = i
                        single_result["batch_fallback"] = True
                        results.append(single_result)
                except Exception:
                    logger.exception("[Batch %s] fallback single processing failed for message %d", batch_id, i)
            self.cognition.commit(trace, route_mode)
            return results

        results: list[dict] = []
        all_ai_row_ids: list[int] = []
        all_user_row_ids: list[int] = []
        qq_outgoing_replies: list[OutgoingReply] = []
        local_emit_items: list[dict] = []

        for seq_idx, (msg, reply_text_raw_single) in enumerate(zip(messages, parsed_replies)):
            try:
                # Gate 2: 批内逐条解析 <recall>, 执行撤回 (按该条 msg 的 channel), 并从正文剔除
                reply_text_raw_single, _recall_actual = await self._handle_recall_instruction(
                    reply_text_raw_single, msg
                )
                if _recall_actual:
                    _recall_actual["sequence_index"] = seq_idx
                    self.cognition.record_decision_actual(trace, _recall_actual)
                reply_text = self.emotion.tune(reply_text_raw_single, actor_id=actor_id)
                try:
                    from core.screen_action_sanitizer import sanitize as _sanitize_action
                    reply_text = _sanitize_action(reply_text)
                except Exception:
                    logger.exception("[Batch %s] screen_action_sanitizer failed for seq %d", batch_id, seq_idx)
                try:
                    from core.output_self_check import OutputSelfCheck
                    _self_check = OutputSelfCheck()
                    _sc_result = _self_check.check(reply_text)
                    if _sc_result.warnings:
                        self.cognition.record(trace, "self_check", {
                            "warnings": _sc_result.warnings,
                            "perspective_shift": _sc_result.perspective_shift,
                            "stray_brackets_fixed": _sc_result.stray_brackets_fixed,
                            "typo_fixes": _sc_result.typo_fixes,
                            "severity": "warn",
                            "sequence_index": seq_idx,
                        })
                    reply_text = _sc_result.cleaned_text
                except Exception:
                    logger.exception("[Batch %s] output_self_check failed for seq %d", batch_id, seq_idx)

                # Task 5: Content validation for batch mode (per-reply)
                content_remedied = False
                try:
                    reply_text, content_remedied = await self.content_validator.validate_and_fix(
                        reply_text,
                        context={"last_user_message": msg.content},
                        batch_id=batch_id,
                        sequence_index=seq_idx,
                    )
                    if content_remedied:
                        self.cognition.record(trace, "content_validation", {
                            "remedied": True,
                            "final_length": len(reply_text),
                            "batch": True,
                            "sequence_index": seq_idx,
                        })
                except Exception:
                    logger.exception("[Batch %s] content_validator failed for seq %d", batch_id, seq_idx)

                try:
                    vr = await self.validator.validate(
                        reply_text,
                        user_message=msg.content,
                        context_history=history,
                        route_mode="OFFICE" if is_office else route_mode,
                    )
                    if vr.issues:
                        self.cognition.record(trace, "validation", {
                            "passed": vr.passed,
                            "guard_passed": vr.guard_passed,
                            "judge_score": vr.judge_score,
                            "rewrite_count": vr.rewrite_count,
                            "issues": vr.issues,
                            "sequence_index": seq_idx,
                        })
                except Exception:
                    logger.exception("[Batch %s] validation failed for seq %d", batch_id, seq_idx)

                segments = self._splitter.split(reply_text) or [reply_text]

                user_row_id = 0
                try:
                    self._checkpoint_cancel(request_state, "before_legacy_user")
                    user_row_id = self._insert_chat_log_safe(
                        role="user",
                        user_id=msg.user_id,
                        content=msg.content,
                        msg_type=msg.msg_type,
                        route_mode=route_mode,
                        reply_to_id=msg.reply_to_id,
                        attachments=json.dumps(msg.attachments, ensure_ascii=False) if msg.attachments else None,
                        actor_id=msg.actor_id,
                        channel=msg.channel,
                        channel_account_id=msg.channel_account_id,
                        batch_id=batch_id,
                        sequence_index=seq_idx,
                    )
                    if user_row_id:
                        request_state.terminal_side_effect_committed = True
                except CancellationTooLate:
                    raise
                except Exception:
                    logger.exception("[Batch %s] db insert user msg error seq=%d", batch_id, seq_idx)

                ai_row_ids: list[int] = []
                try:
                    for seg in segments:
                        self._checkpoint_cancel(request_state, "before_legacy_assistant")
                        rid = self._insert_chat_log_safe(
                            role="assistant",
                            user_id=msg.user_id,
                            content=seg,
                            msg_type=msg.msg_type,
                            route_mode=route_mode,
                            actor_id=msg.actor_id,
                            channel=msg.channel,
                            channel_account_id=msg.channel_account_id,
                            batch_id=batch_id,
                            sequence_index=seq_idx,
                        )
                        ai_row_ids.append(rid)
                        all_ai_row_ids.append(rid)
                        if rid:
                            request_state.terminal_side_effect_committed = True
                except CancellationTooLate:
                    raise
                except Exception:
                    logger.exception("[Batch %s] db insert ai msg error seq=%d", batch_id, seq_idx)

                all_user_row_ids.append(user_row_id)

                result = {
                    "reply": reply_text,
                    "user_msg_id": user_row_id,
                    "ai_msg_id": ai_row_ids[0] if ai_row_ids else 0,
                    "ai_msg_ids": ai_row_ids,
                    "segments": segments,
                    "route_mode": route_mode,
                    "emotion": emotion_info.get("label") if emotion_info else "unknown",
                    "cognition_id": trace.get("id", 0),
                    "persisted": user_row_id > 0 and len(ai_row_ids) == len(segments),
                    "canonical_completed": False,
                    "batch_id": batch_id,
                    "sequence_index": seq_idx,
                }
                results.append(result)

                if source == "local":
                    user_emit_data = {
                        "event_type": "user",
                        "kwargs": {
                            "role": "user",
                            "id": user_row_id,
                            "user_id": msg.user_id,
                            "content": msg.content,
                            "source": source,
                        }
                    }
                    local_emit_items.append({
                        "seq_idx": seq_idx,
                        "seg_idx": -1,
                        "type": "user",
                        "data": user_emit_data,
                        "reply_text": "",
                        "emotion": emotion_info.get("label") if emotion_info else None,
                        "is_eruption": bool(eruption_info and eruption_info.get("mode")),
                        "thresholds": (emotion_info or {}).get("thresholds", {}) or {},
                        "is_last_in_message": False,
                    })
                    for seg_idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
                        emit_kwargs = {
                            "role": "assistant",
                            "id": rid,
                            "user_id": msg.user_id,
                            "content": seg,
                            "source": source,
                        }
                        if seg_idx == 0:
                            if emotion_info:
                                emit_kwargs["emotion"] = emotion_info["label"]
                            if eruption_info:
                                emit_kwargs["eruption"] = eruption_info["mode"]
                        local_emit_items.append({
                            "seq_idx": seq_idx,
                            "seg_idx": seg_idx,
                            "type": "assistant",
                            "data": {"event_type": "assistant", "kwargs": emit_kwargs},
                            "reply_text": seg,
                            "emotion": emotion_info.get("label") if emotion_info else None,
                            "is_eruption": bool(eruption_info and eruption_info.get("mode")),
                            "thresholds": (emotion_info or {}).get("thresholds", {}) or {},
                            "is_last_in_message": seg_idx == len(segments) - 1,
                        })

                if source == "qq" and ai_row_ids:
                    reply_to_qq_mid = 0
                    if msg.reply_to_id:
                        try:
                            q = self.db.query_one(
                                "SELECT qq_message_id FROM chat_log WHERE id = ?",
                                (msg.reply_to_id,),
                            )
                            if q and q.get("qq_message_id"):
                                reply_to_qq_mid = int(q["qq_message_id"])
                        except Exception:
                            pass
                    outgoing = OutgoingReply(
                        user_id=msg.user_id,
                        content=reply_text,
                        msg_id=ai_row_ids[0],
                        reply_to_qq_message_id=reply_to_qq_mid,
                        cognition_id=int(trace.get("id") or 0),
                        batch_id=batch_id,
                        sequence_index=seq_idx,
                    )
                    if eruption_info and eruption_info.get("mode"):
                        try:
                            setattr(outgoing, "eruption_mode", eruption_info["mode"])
                        except Exception:
                            pass
                    qq_outgoing_replies.append(outgoing)

            except Exception:
                logger.exception("[Batch %s] error processing message seq=%d", batch_id, seq_idx)

        if qq_outgoing_replies:
            self.send_queue.enqueue_batch(qq_outgoing_replies)

        if local_emit_items:
            await self._emit_local_batch_with_pacing(local_emit_items, batch_id, user_id)

        self.cognition.record(trace, "postprocess", {
            "tune_label": (emotion_info or {}).get("label"),
            "eruption_mode": (eruption_info or {}).get("mode") if eruption_info else None,
            "batch": True,
            "reply_count": len(parsed_replies),
        })
        self.cognition.record(trace, "split", {
            "batch": True,
            "per_message_segments": [len(r.get("segments", [])) for r in results],
        })
        self.cognition.record(trace, "output", {
            "ai_msg_ids": all_ai_row_ids,
            "user_msg_ids": all_user_row_ids,
            "source": source,
            "batch": True,
            "batch_id": batch_id,
            "message_count": len(messages),
            "result_count": len(results),
        })
        self.cognition.commit(trace, route_mode)

        if self.self_evolver:
            try:
                self.self_evolver.maybe_propose(
                    user_id=user_id,
                    user_message=combined_content,
                    react_trace=react_trace,
                    tool_results=tool_results,
                )
            except Exception:
                logger.exception("[Batch %s] self_evolver error", batch_id)

        logger.info(
            "Batch %s: completed, %d results",
            batch_id,
            len(results),
        )
        return results

    def _insert_chat_log_safe(self, **kwargs) -> int:
        """Safely insert into chat_log, gracefully handling missing columns.

        First tries with all provided fields (including batch_id/sequence_index).
        If that fails due to column issues, retries without the new batch fields.
        """
        batch_fields = {"batch_id", "sequence_index"}
        try:
            return self.db.insert("chat_log", kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            if any(field in err_msg for field in ["no column named", "has no column", "unknown column", "batch_id"]):
                logger.debug("chat_log may not have batch columns yet, retrying without batch fields")
                safe_kwargs = {k: v for k, v in kwargs.items() if k not in batch_fields}
                return self.db.insert("chat_log", safe_kwargs)
            raise

    @staticmethod
    def _build_batch_user_content(messages: list[IncomingMessage]) -> str:
        """Build the user content block for batch processing.

        Format:
            [用户连续发送了多条消息，请按顺序分别回复每条消息]
            --- 消息 1 ---
            {message1_content}
            --- 消息 2 ---
            {message2_content}
            ...

            请按以下格式回复：
            === 回复 1 ===
            (对消息1的回复，包含对话正文、动作、心理)
            === 回复 2 ===
            (对消息2的回复)
            ...
        """
        lines = ["[用户连续发送了多条消息，请按顺序分别回复每条消息]"]
        for i, msg in enumerate(messages, 1):
            lines.append(f"--- 消息 {i} ---")
            lines.append(msg.content)
        lines.append("")
        lines.append("请按以下格式回复：")
        for i in range(1, len(messages) + 1):
            lines.append(f"=== 回复 {i} ===")
            lines.append(f"(对消息{i}的回复，包含对话正文、动作、心理)")
        return "\n".join(lines)

    @staticmethod
    def _parse_batch_replies(raw_text: str, expected_count: int, batch_id: str) -> list[str]:
        """Parse LLM batch response into individual replies.

        Expected format:
            === 回复 1 ===
            (reply content)
            === 回复 2 ===
            (reply content)
            ...

        Robust handling:
        - Flexible separator matching
        - Trims whitespace
        - Handles missing/extra separators gracefully
        """
        import re

        separator_pattern = re.compile(r"===\s*回复\s*(\d+)\s*===", re.MULTILINE)

        matches = list(separator_pattern.finditer(raw_text))
        if not matches:
            logger.warning("[Batch %s] no reply separators found in LLM response", batch_id)
            return []

        replies = [""] * expected_count

        for i, match in enumerate(matches):
            try:
                reply_num = int(match.group(1)) - 1
            except (ValueError, IndexError):
                reply_num = i

            if reply_num < 0 or reply_num >= expected_count:
                continue

            start = match.end()
            if i + 1 < len(matches):
                end = matches[i + 1].start()
                content = raw_text[start:end]
            else:
                content = raw_text[start:]

            content = content.strip()
            content = re.sub(r"^[\s\n\r]+|[\s\n\r]+$", "", content)
            replies[reply_num] = content

        replies = [r for r in replies if r]
        return replies

    async def _emit_local_batch_with_pacing(
        self,
        emit_items: list[dict],
        batch_id: str,
        user_id: int,
    ) -> None:
        import random
        import re
        from config.persona_loader import get_message_batching_config
        from core.persona_pacing import compute_persona_interval

        cfg = get_message_batching_config()
        base_interval = cfg["base_interval_seconds"]
        cps = cfg["chars_per_second"]
        min_interval = cfg["min_interval_seconds"]
        max_interval = cfg["max_interval_seconds"]

        def _strip_tags(text: str) -> str:
            if not text:
                return text
            text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<action>.*?</action>', '', text, flags=re.DOTALL | re.IGNORECASE)
            return text.strip()

        last_seq_idx = -1
        last_seg_idx = -1
        last_item_type = None
        is_first_assistant_segment = True

        for item in emit_items:
            seq_idx = item.get("seq_idx", 0)
            seg_idx = item.get("seg_idx", -1)
            item_type = item.get("type")
            item_data = item.get("data", {})
            reply_text = item.get("reply_text", "")
            emotion_label = item.get("emotion") or "neutral"
            is_eruption = item.get("is_eruption", False)
            threshold_summary = item.get("thresholds", {}) or {}
            is_last_in_message = item.get("is_last_in_message", False)

            need_interval = False
            interval = 0.0
            interval_reason = ""

            if item_type == "assistant":
                if is_first_assistant_segment:
                    is_first_assistant_segment = False
                    need_interval = False
                else:
                    if seq_idx == last_seq_idx and last_item_type == "assistant":
                        interval, style = compute_persona_interval(
                            segment_index=last_seg_idx,
                            emotion_label=emotion_label,
                            threshold=threshold_summary,
                            is_eruption=is_eruption,
                            segment_content=reply_text,
                        )
                        need_interval = interval > 0
                        interval_reason = f"intra-msg seg (style={style})"
                    elif seq_idx > last_seq_idx:
                        plain = _strip_tags(reply_text)
                        char_count = len(plain)
                        if char_count > 0:
                            char_interval = base_interval + (char_count / max(cps, 1))
                            jitter = random.uniform(0.7, 1.3)
                            interval = char_interval * jitter
                            interval = max(min_interval, min(interval, max_interval))
                            need_interval = True
                            interval_reason = "inter-msg batch"

            if need_interval and interval > 0:
                logger.debug(
                    "local batch emit pacing: batch_id=%s seq=%d seg=%d reason=%s interval=%.3fs",
                    batch_id, seq_idx, seg_idx, interval_reason, interval,
                )
                await asyncio.sleep(interval)

            try:
                event_type = item_data.get("event_type", "")
                kwargs = item_data.get("kwargs", {})
                emit(event_type, **kwargs)
            except Exception:
                logger.debug(
                    "local batch emit failed: batch_id=%s seq=%d seg=%d type=%s",
                    batch_id, seq_idx, seg_idx, item_type,
                    exc_info=True,
                )

            last_seq_idx = seq_idx
            last_seg_idx = seg_idx
            last_item_type = item_type

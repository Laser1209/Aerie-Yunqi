"""Aerie · 云栖 v0.1.0-beta.1 — Message pipeline.

Processes incoming messages through:
  route → emotion(text scan + cumulative trigger check) → history → context(with emotion+eruption) → LLM → emotion tune → persist → emit → reply.

Phase 9: every step also writes to a 9-stage cognition trace
(route / emotion / threshold / context / brain / tools / split / postprocess / output).
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Any

from communication.message import IncomingMessage, OutgoingReply
from communication.splitter import SemanticMessageSplitter
from core.chat_events import emit
from core.cognition import CognitionEngine
from core.office_mode import get_office_mode_manager, OfficeMode
from core.response_validator import ResponseValidator

logger = logging.getLogger(__name__)


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
        self._splitter = SemanticMessageSplitter()
        # v13.9: 回复校验器（准确性 Guard + 质量 Judge）
        self.validator = ResponseValidator()

    async def handle(
        self, msg: IncomingMessage, force_full: bool = False
    ) -> dict | None:
        """Handle one incoming message end-to-end.

        Returns dict with reply info, or None if skipped (BASIC stranger).
        """
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
            result = await self._handle_basic_lightweight(msg, trace, route_mode)
            self.cognition.commit(trace, route_mode)
            return result

        # ══════════════════════════════════════════════
        # 1. Route (stage 1)
        # ══════════════════════════════════════════════
        self.cognition.record(trace, "route", {"mode": route_mode, "skipped": False})

        # ══════════════════════════════════════════════
        # Phase 9: Multi-layer decision (§10.2) — chosen intent
        # ══════════════════════════════════════════════
        if self.decision_engine:
            try:
                decision = self.decision_engine.decide_for_message(
                    user_id=msg.user_id,
                    route_mode=route_mode,
                    source=msg.source,
                )
                self.cognition.record_decision(trace, decision)
            except Exception:
                logger.exception("decision engine error")

        # ══════════════════════════════════════════════
        # Phase 4: Auto-recall if user said something negative
        # ══════════════════════════════════════════════
        if self.recall_manager and msg.source == "qq":
            try:
                await self.recall_manager.handle_user_negative(msg.user_id, msg.content)
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
            await self.emotion.update_trajectory_async(msg.user_id, msg.content)
        except Exception:
            logger.exception("emotion update error")

        # ══════════════════════════════════════════════
        # 3. Get history from DB
        #    Variable `history` is used consistently (not `history_rows`
        #    or `history_msgs`) for passing to ContextBuilder.build().
        # ══════════════════════════════════════════════
        history = []
        try:
            history = self.db.query(
                "SELECT role, content FROM chat_log WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                (msg.user_id,),
            )
            history.reverse()
        except Exception:
            pass

        # ══════════════════════════════════════════════
        # 4. Gather emotion info for context injection
        # ══════════════════════════════════════════════
        emotion_info = None
        eruption_info = None
        try:
            state = self.emotion.get_state(msg.user_id)
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
        ctx_messages = self.ctx_builder.build(
            msg.user_id,
            msg.content,
            route_mode,
            history_msgs=history,
            emotion_info=emotion_info,
            eruption_info=eruption_info,
            reply_to=reply_to_data,
            attachments=msg.attachments if msg.attachments else None,
        )
        tools = self.tool_registry.get_openai_schema() if route_mode == "FULL" else None

        system_chars = len(ctx_messages[0]["content"]) if ctx_messages else 0
        history_chars = sum(len(m.get("content", "")) for m in ctx_messages[1:])
        self.cognition.record(trace, "context", {
            "messages": len(ctx_messages),
            "system_prompt_chars": system_chars,
            "history_chars": history_chars,
            "tools_offered": bool(tools),
        })

        # ══════════════════════════════════════════════
        # v13.0: Office Mode 办公模式检测与增强
        # ══════════════════════════════════════════════
        office_mgr = get_office_mode_manager()
        office_ctx = office_mgr.detect(msg.content, history)
        is_office = office_ctx.is_office_mode()

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
        # 6. Call LLM (stage 5)
        # ══════════════════════════════════════════════
        preferred_provider = office_mgr.get_preferred_provider() if is_office else None
        response = await self.brain.chat(
            ctx_messages,
            tools=tools,
            tool_registry=self.tool_registry,
            preferred_provider=preferred_provider,
        )
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

        # Strip <think> block from user-visible text
        reply_text_raw = self._strip_think(raw_text)

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
        reply_text = self.emotion.tune(reply_text_raw)
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
        self.cognition.record(trace, "postprocess", {
            "tune_label": (emotion_info or {}).get("label"),
            "eruption_mode": (eruption_info or {}).get("mode") if eruption_info else None,
            "raw_chars": len(reply_text_raw),
            "tuned_chars": len(reply_text),
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
        try:
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
            })
        except Exception:
            logger.exception("db insert user msg error")

        # ══════════════════════════════════════════════
        # 10. Emit user event
        # ══════════════════════════════════════════════
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
                rid = self.db.insert("chat_log", {
                    "user_id": msg.user_id,
                    "role": "assistant",
                    "content": seg,
                    "msg_type": msg.msg_type,
                    "route_mode": route_mode,
                })
                ai_row_ids.append(rid)
        except Exception:
            logger.exception("db insert ai msg error")

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
        for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
            try:
                emit_kwargs = {
                    "role": "assistant",
                    "id": rid,
                    "user_id": msg.user_id,
                    "content": seg,
                    "source": msg.source,
                }
                if idx == 0:
                    if emotion_info:
                        emit_kwargs["emotion"] = emotion_info["label"]
                    if eruption_info:
                        emit_kwargs["eruption"] = eruption_info["mode"]
                emit("assistant", **emit_kwargs)
            except Exception:
                pass

            # Decide pacing for the NEXT gap (only if there is a next segment)
            if idx < len(segments) - 1:
                interval_sec, style = compute_persona_interval(
                    segment_index=idx,
                    emotion_label=emotion_label_local,
                    threshold=threshold_summary_local,
                    is_eruption=is_eruption_local,
                    segment_content=seg,
                )
                pacing_log.append({
                    "seg_idx": idx,
                    "next_style": style,
                    "next_interval_ms": int(interval_sec * 1000),
                    "source": "local",
                })
                if msg.source == "local" and interval_sec > 0:
                    await asyncio.sleep(interval_sec)

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
            self.send_queue.enqueue(reply)

        return {
            "reply": reply_text,
            "user_msg_id": user_row_id,
            "ai_msg_id": ai_row_ids[0] if ai_row_ids else 0,
            "ai_msg_ids": ai_row_ids,
            "segments": segments,
            "route_mode": route_mode,
            "emotion": emotion_info.get("label") if emotion_info else "unknown",
            "cognition_id": trace.get("id", 0),
        }

    # ── Helpers ────────────────────────────────────────
    async def _handle_basic_lightweight(
        self,
        msg: IncomingMessage,
        trace: dict,
        route_mode: str,
    ) -> dict | None:
        """BASIC 模式轻量对话链路。

        保留：情绪识别 + 历史上下文 + LLM 回复 + 后处理 + 持久化 + emit
        跳过：工具调用 + 自进化 + 决策引擎 + 完整认知追踪
        """
        # 1. 情绪更新（轻量：仅关键词路径，不调 LLM PAD 以省 Token）
        try:
            self.emotion.update_trajectory(msg.user_id, msg.content)
        except Exception:
            logger.exception("BASIC emotion update error")

        # 获取情绪状态（用于回复语气调整）
        emotion_info = None
        try:
            state = self.emotion.get_state(msg.user_id)
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
        history = []
        try:
            history = self.db.query(
                "SELECT role, content FROM chat_log WHERE user_id = ? ORDER BY id DESC LIMIT 10",
                (msg.user_id,),
            )
            history.reverse()
        except Exception:
            pass

        # 3. 构建上下文（BASIC 精简系统提示词）
        ctx_messages = self.ctx_builder.build(
            msg.user_id,
            msg.content,
            route_mode,  # "BASIC" — context_builder 会生成精简系统提示
            history_msgs=history,
            emotion_info=emotion_info,
            eruption_info=None,
            reply_to=None,
            attachments=None,
        )

        system_chars = len(ctx_messages[0]["content"]) if ctx_messages else 0
        self.cognition.record(trace, "context", {
            "messages": len(ctx_messages),
            "system_prompt_chars": system_chars,
            "tools_offered": False,
            "lightweight": True,
        })

        # 4. 调 LLM（无工具，纯对话）
        response = await self.brain.chat(
            ctx_messages,
            tools=None,
            tool_registry=self.tool_registry,
            preferred_provider=None,
        )
        raw_text = getattr(response, "text", "") or ""
        model_name = getattr(response, "model", "unknown")
        usage = getattr(response, "usage", None) or {}

        # 剥掉 <think> 块
        reply_text_raw = self._strip_think(raw_text)

        self.cognition.record(trace, "brain", {
            "model": model_name,
            "tokens": usage,
            "raw_chars": len(raw_text),
            "lightweight": True,
        })

        # 5. 情绪润色 + 自检
        reply_text = self.emotion.tune(reply_text_raw)
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

        self.cognition.record(trace, "postprocess", {
            "tune_label": (emotion_info or {}).get("label"),
            "raw_chars": len(reply_text_raw),
            "tuned_chars": len(reply_text),
            "lightweight": True,
        })

        # 5.5 Response Validation（v13.9: BASIC 模式也做轻量校验）
        try:
            vr = await self.validator.validate(
                reply_text,
                user_message=msg.content,
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
        try:
            user_row_id = self.db.insert("chat_log", {
                "user_id": msg.user_id,
                "role": "user",
                "content": msg.content,
                "msg_type": msg.msg_type,
                "route_mode": route_mode,
            })
        except Exception:
            logger.exception("db insert user msg error")

        # 8. 持久化 AI 回复
        ai_row_ids: list[int] = []
        try:
            for seg in segments:
                rid = self.db.insert("chat_log", {
                    "user_id": msg.user_id,
                    "role": "assistant",
                    "content": seg,
                    "msg_type": msg.msg_type,
                    "route_mode": route_mode,
                })
                ai_row_ids.append(rid)
        except Exception:
            logger.exception("db insert ai msg error")

        self.cognition.record(trace, "output", {
            "ai_msg_ids": ai_row_ids,
            "user_msg_id": user_row_id,
            "source": msg.source,
            "segment_count": len(ai_row_ids),
            "lightweight": True,
        })

        # 9. Emit 事件（前端展示用）
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

        for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
            try:
                emit_kwargs = {
                    "role": "assistant",
                    "id": rid,
                    "user_id": msg.user_id,
                    "content": seg,
                    "source": msg.source,
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
            self.send_queue.enqueue(reply)

        return {
            "reply": reply_text,
            "user_msg_id": user_row_id,
            "ai_msg_id": ai_row_ids[0] if ai_row_ids else 0,
            "ai_msg_ids": ai_row_ids,
            "segments": segments,
            "route_mode": route_mode,
            "emotion": emotion_info.get("label") if emotion_info else "unknown",
            "cognition_id": trace.get("id", 0),
            "lightweight": True,
        }

    @staticmethod
    def _extract_react(text: str) -> dict:
        """Backward-compat shim: delegate to brain._build_react_from_text.

        Kept so any external caller (or older test) that still calls
        Pipeline._extract_react continues to work. New code should read
        the react_trace directly off the BrainResponse.
        """
        from core.brain import _build_react_from_text
        return _build_react_from_text(text, tool_calls_present=False)

    @staticmethod
    def _strip_think(text: str) -> str:
        """Remove <think>…</think> block from user-visible text."""
        import re
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

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

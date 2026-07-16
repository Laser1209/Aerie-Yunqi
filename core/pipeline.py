"""Aerie · 云栖 v9.0 — Message pipeline.

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
        if route_mode == "BASIC" and not force_full:
            logger.debug("BASIC skip for user %s", msg.user_id)
            # Still record the route decision for transparency
            self.cognition.record(trace, "route", {"mode": "BASIC", "skipped": True})
            self.cognition.commit(trace, route_mode)
            return None

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
        # 2. Emotion: PAD analysis + cumulative threshold scan (stages 2 + 3)
        # ══════════════════════════════════════════════
        try:
            self.emotion.update_trajectory(msg.user_id, msg.content)
        except Exception:
            logger.exception("emotion update error")

        # ══════════════════════════════════════════════
        # 3. Get history from DB
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
        # 6. Call LLM (stage 5)
        # ══════════════════════════════════════════════
        response = await self.brain.chat(ctx_messages, tools=tools)
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
        # 8. Emotion tune + split (stages 7 + 8)
        # ══════════════════════════════════════════════
        reply_text = self.emotion.tune(reply_text_raw)
        self.cognition.record(trace, "postprocess", {
            "tune_label": (emotion_info or {}).get("label"),
            "eruption_mode": (eruption_info or {}).get("mode") if eruption_info else None,
            "raw_chars": len(reply_text_raw),
            "tuned_chars": len(reply_text),
        })

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
        if self.self_evolver:
            try:
                self.self_evolver.maybe_propose(msg.user_id, msg.content, react_trace)
            except Exception:
                logger.exception("self_evolver error")

        # ══════════════════════════════════════════════
        # 12. Emit assistant event for each segment (UI gets one bubble per segment)
        # Phase 9: local source is paced by emotion-aware intervals;
        #          QQ source still goes through SendQueue which has its own pacing.
        # ══════════════════════════════════════════════
        from core.message_pacing import compute_interval
        emotion_label_local = (emotion_info.get("label") if emotion_info else "neutral") or "neutral"
        is_eruption_local = bool(eruption_info and eruption_info.get("mode"))
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
            if msg.source == "local" and idx < len(segments) - 1:
                await asyncio.sleep(compute_interval(emotion_label_local, is_eruption_local))

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

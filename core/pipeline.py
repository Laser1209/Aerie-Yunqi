"""Aerie · 云栖 v9.0 — Message pipeline.

Processes incoming messages through:
  route → emotion(text scan + cumulative trigger check) → history → context(with emotion+eruption) → LLM → emotion tune → persist → emit → reply.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Any

from communication.message import IncomingMessage, OutgoingReply
from communication.splitter import SemanticMessageSplitter
from core.chat_events import emit

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
    ) -> None:
        self.router = router
        self.emotion = emotion_engine
        self.ctx_builder = context_builder
        self.brain = brain
        self.send_queue = send_queue
        self.tool_registry = tool_registry
        self.db = db
        self.recall_manager = recall_manager
        self._splitter = SemanticMessageSplitter()

    async def handle(
        self, msg: IncomingMessage, force_full: bool = False
    ) -> dict | None:
        """Handle one incoming message end-to-end.

        Returns dict with reply info, or None if skipped (BASIC stranger).
        """
        route_mode = self.router.route(msg.user_id)
        if route_mode == "BASIC" and not force_full:
            logger.debug("BASIC skip for user %s", msg.user_id)
            return None

        # ══════════════════════════════════════════════
        # Phase 4: Auto-recall if user said something negative
        # ══════════════════════════════════════════════
        if self.recall_manager and msg.source == "qq":
            try:
                await self.recall_manager.handle_user_negative(msg.user_id, msg.content)
            except Exception:
                logger.exception("handle_user_negative error")

        # ══════════════════════════════════════════════
        # 1. Emotion: PAD analysis + cumulative threshold scan
        # ══════════════════════════════════════════════
        try:
            self.emotion.update_trajectory(msg.user_id, msg.content)
        except Exception:
            logger.exception("emotion update error")

        # ══════════════════════════════════════════════
        # 2. Get history from DB
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
        # 3. Gather emotion info for context injection
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

        # ══════════════════════════════════════════════
        # 3.5 Phase 4: Resolve reply_to context
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
        # 4. Build context for LLM
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

        # ══════════════════════════════════════════════
        # 5. Call LLM
        # ══════════════════════════════════════════════
        response = await self.brain.chat(ctx_messages, tools=tools)
        reply_text = self.emotion.tune(response.text)

        # ══════════════════════════════════════════════
        # 6. Persist user message
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
        # 7. Emit user event
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
        # 8. Persist AI reply — split into segments, one row per segment
        # ══════════════════════════════════════════════
        segments = self._splitter.split(reply_text) or [reply_text]
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

        # ══════════════════════════════════════════════
        # 9. Emit assistant event for each segment (UI gets one bubble per segment)
        # ══════════════════════════════════════════════
        for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
            try:
                emit_kwargs = {
                    "role": "assistant",
                    "id": rid,
                    "user_id": msg.user_id,
                    "content": seg,
                    "source": msg.source,
                }
                # Attach emotion / eruption labels to the first segment only
                if idx == 0:
                    if emotion_info:
                        emit_kwargs["emotion"] = emotion_info["label"]
                    if eruption_info:
                        emit_kwargs["eruption"] = eruption_info["mode"]
                emit("assistant", **emit_kwargs)
            except Exception:
                pass

        # ══════════════════════════════════════════════
        # 10. QQ messages → SendQueue; local → skip
        # ══════════════════════════════════════════════
        if msg.source == "qq":
            # Phase 4: if user message had a reply_to_id, look up the qq_message_id
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
            self.send_queue.enqueue(reply)

        return {
            "reply": reply_text,
            "user_msg_id": user_row_id,
            "ai_msg_id": ai_row_ids[0] if ai_row_ids else 0,
            "ai_msg_ids": ai_row_ids,
            "segments": segments,
            "route_mode": route_mode,
            "emotion": emotion_info.get("label") if emotion_info else "unknown",
        }

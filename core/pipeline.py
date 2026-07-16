"""Aerie · 云栖 v9.0 — Message pipeline.

Processes incoming messages through: route → context → LLM → emotion → persist → emit → reply.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any

from communication.message import IncomingMessage, OutgoingReply
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
    ) -> None:
        self.router = router
        self.emotion = emotion_engine
        self.ctx_builder = context_builder
        self.brain = brain
        self.send_queue = send_queue
        self.tool_registry = tool_registry
        self.db = db

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

        # Update emotion
        try:
            self.emotion.update_trajectory(msg.user_id, msg.content)
        except Exception:
            pass

        # Get history from DB
        history = []
        try:
            history = self.db.query(
                "SELECT role, content FROM chat_log WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                (msg.user_id,),
            )
            history.reverse()
        except Exception:
            pass

        # Build context for LLM
        ctx_messages = self.ctx_builder.build(
            msg.user_id, msg.content, route_mode, history,
        )
        tools = self.tool_registry.get_openai_schema() if route_mode == "FULL" else None

        # Call LLM
        response = await self.brain.chat(ctx_messages, tools=tools)
        reply_text = self.emotion.tune(response.text)

        # Persist user message
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

        # Emit user event
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

        # Persist AI reply
        ai_row_id = 0
        try:
            ai_row_id = self.db.insert("chat_log", {
                "user_id": msg.user_id,
                "role": "assistant",
                "content": reply_text,
                "msg_type": msg.msg_type,
                "route_mode": route_mode,
            })
        except Exception:
            logger.exception("db insert ai msg error")

        # Emit assistant event
        try:
            emit(
                "assistant",
                role="assistant",
                id=ai_row_id,
                user_id=msg.user_id,
                content=reply_text,
                source=msg.source,
            )
        except Exception:
            pass

        # QQ messages → SendQueue; local messages → skip
        if msg.source == "qq":
            reply = OutgoingReply(
                user_id=msg.user_id,
                content=reply_text,
                msg_id=ai_row_id,
            )
            self.send_queue.enqueue(reply)

        return {
            "reply": reply_text,
            "user_msg_id": user_row_id,
            "ai_msg_id": ai_row_id,
            "route_mode": route_mode,
        }

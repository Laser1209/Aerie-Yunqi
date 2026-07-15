"""Aerie · 云栖 v9.0 — 5-stage Pipeline.

Stage 1: Route  (FULL / AUTO / BASIC)
Stage 2: Emotion perception
Stage 3: Context build (system + memory + kb + history)
Stage 4: Brain + Tools reasoning
Stage 5: Emotion coloring + splitter + send queue
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from communication.message import IncomingMessage, MessageType, OutgoingReply, RouteMode
from communication.recall_manager import RecallManager
from communication.router import Router
from communication.send_queue import SendQueue
from core.brain import Brain
from core.context_builder import ContextBuilder
from core.database import Database
from core.emotion_engine import EmotionEngine
from core.function_calling import execute_tool_call
from core.tool_registry import ToolRegistry


logger = logging.getLogger(__name__)


class Pipeline:
    """5-stage message handling pipeline."""

    def __init__(
        self,
        router: Router,
        emotion_engine: EmotionEngine,
        context_builder: ContextBuilder,
        brain: Brain,
        send_queue: SendQueue,
        tool_registry: Optional[ToolRegistry] = None,
        recall_manager: Optional[RecallManager] = None,
        db: Optional[Database] = None,
    ) -> None:
        self.router = router
        self.emotion = emotion_engine
        self.context_builder = context_builder
        self.brain = brain
        self.queue = send_queue
        self.tools = tool_registry
        self.recall_manager = recall_manager
        self.db = db or Database()

    async def handle(self, msg: IncomingMessage) -> dict:
        """Run the full pipeline for an incoming message."""
        if msg.is_empty:
            return {"status": "skipped_empty"}

        # 0. Recall check (cheap, do first)
        if self.recall_manager and msg.is_negative:
            try:
                await self.recall_manager.handle_user_negative(msg.user_id, msg.content)
            except Exception:
                pass

        # 1. Route
        route = self.router.route_message(msg)

        # Persist user message
        try:
            self.db.insert(
                "chat_log",
                {
                    "user_id": msg.user_id,
                    "role": "user",
                    "content": msg.content,
                    "msg_type": msg.msg_type.value,
                    "route_mode": route.value,
                    "parse_error": 1 if msg.parse_error else 0,
                },
            )
        except Exception:
            pass

        if route == RouteMode.BASIC:
            return await self._handle_basic(msg)
        if route == RouteMode.AUTO_REPLY:
            return await self._handle_auto_reply(msg)
        return await self._handle_full(msg, route)

    async def _handle_full(self, msg: IncomingMessage, route: RouteMode) -> dict:
        # 2. Emotion perception
        intent = self._classify_intent(msg.content)
        emotion_event = self._emotion_event_for_intent(intent)
        if emotion_event:
            self.emotion.trigger(emotion_event, user_id=msg.user_id, intensity=1.0)
        mood = self.emotion.get_current_mood(msg.user_id)
        pad = self.emotion.get_state(msg.user_id).as_dict()

        # 3. Context build
        history = self._recent_history(msg.user_id, limit=8)
        messages = self.context_builder.build(
            user_id=msg.user_id,
            user_msg=msg,
            route_mode=route,
            history=history,
            mood=mood,
            pad=pad,
        )

        # 4. Brain + Tools
        tool_schemas = self.tools.to_schemas() if self.tools else None
        resp = await self.brain.think(
            messages=messages,
            scene="chat",
            user_id=msg.user_id,
            tools=tool_schemas,
        )

        tool_results: list[str] = []
        if resp.tool_calls and self.tools:
            for tc in resp.tool_calls:
                try:
                    result = await execute_tool_call(
                        self.tools, tc["name"], tc.get("arguments", "{}")
                    )
                    tool_results.append(result if isinstance(result, str) else str(result))
                except Exception as e:
                    tool_results.append(f"[tool error: {e}]")
            # Re-prompt with tool results
            if tool_results:
                messages.append({
                    "role": "tool",
                    "content": "\n".join(tool_results),
                })
                resp = await self.brain.think(
                    messages=messages,
                    scene="chat_tool_followup",
                    user_id=msg.user_id,
                )

        content = (resp.content or "").strip() or "……嗯。"

        # 5. Emotion color + split + enqueue
        reply = self._color_reply(msg.user_id, content, mood)
        self.queue.enqueue(reply, splitter=True)

        # Persist assistant message
        try:
            self.db.insert(
                "chat_log",
                {
                    "user_id": msg.user_id,
                    "role": "assistant",
                    "content": content,
                    "msg_type": MessageType.PRIVATE.value,
                    "route_mode": route.value,
                    "scene": "emotional" if mood in ("sad", "anger", "fear") else "daily",
                },
            )
        except Exception:
            pass

        return {
            "status": "ok",
            "route": route.value,
            "mood": mood,
            "reply": content,
            "tool_calls": len(resp.tool_calls or []),
        }

    async def _handle_auto_reply(self, msg: IncomingMessage) -> dict:
        # Simple canned reply for friends
        content = "在。"
        reply = OutgoingReply(
            user_id=msg.user_id,
            content=content,
            scene="daily",
            msg_type=MessageType.PRIVATE,
        )
        self.queue.enqueue(reply, splitter=False)
        try:
            self.db.insert(
                "chat_log",
                {
                    "user_id": msg.user_id,
                    "role": "assistant",
                    "content": content,
                    "msg_type": MessageType.PRIVATE.value,
                    "route_mode": RouteMode.AUTO_REPLY.value,
                },
            )
        except Exception:
            pass
        return {"status": "ok", "route": "AUTO", "reply": content}

    async def _handle_basic(self, msg: IncomingMessage) -> dict:
        return {"status": "skipped_basic"}

    def _classify_intent(self, text: str) -> str:
        text = text or ""
        if any(kw in text for kw in ["喜欢你", "想你", "爱", "miss"]):
            return "praise"
        if any(kw in text for kw in ["别", "闭嘴", "烦", "滚", "stop"]):
            return "complaint"
        if any(kw in text for kw in ["?", "？", "怎么", "为什么"]):
            return "question"
        if any(kw in text for kw in ["打开", "播放", "查询", "提醒"]):
            return "command"
        return "chat"

    def _emotion_event_for_intent(self, intent: str) -> str | None:
        return {
            "praise": "user_praise",
            "complaint": "user_cold",
            "question": None,
            "command": None,
            "chat": None,
        }.get(intent)

    def _recent_history(self, user_id: int, limit: int = 8) -> list[dict]:
        rows = self.db.query(
            "SELECT role, content FROM chat_log WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        # Reverse to chronological order
        return list(reversed(rows))

    def _color_reply(self, user_id: int, content: str, mood: str) -> OutgoingReply:
        # Trim overly long output (>2000 chars split will handle it)
        scene = "emotional" if mood in ("sad", "anger", "fear") else "daily"
        return OutgoingReply(
            user_id=user_id,
            content=content,
            scene=scene,
            mood=mood,
            msg_type=MessageType.PRIVATE,
        )

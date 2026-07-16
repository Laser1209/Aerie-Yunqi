"""Aerie · 云栖 v9.0 — Companion: orchestrator for all backend modules."""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from communication.message import IncomingMessage, OutgoingReply
from communication.qq_client import QQClient
from communication.recall_manager import RecallManager
from communication.router import Router
from communication.send_queue import SendQueue
from communication.splitter import SemanticMessageSplitter
from core.brain import Brain
from core.context_builder import ContextBuilder
from core.database import Database
from core.emotion_engine import EmotionEngine
from core.emotion_threshold import get_threshold_engine, CumulativeEmotionEngine
from core.pipeline import Pipeline
from core.push_scheduler import PushScheduler
from core.tool_registry import ToolRegistry
from config.persona_loader import load_settings, load_proactive_config
from knowledge.kb import KnowledgeBase
from memory.memory_store import LongTermMemory
from tools import register_all_tools

logger = logging.getLogger(__name__)

_COMPANION = None


def get_companion():
    return _COMPANION


class Companion:
    def __init__(self, settings: dict | None = None) -> None:
        global _COMPANION
        self.settings = settings or load_settings()

        # Data layer
        self.db = Database()

        # Core engines
        self.emotion = EmotionEngine(self.db)
        self.brain = Brain()
        self.memory = LongTermMemory(self.db)
        self.knowledge = KnowledgeBase(self.db)

        # Cumulative threshold engine (shared singleton)
        self.threshold_engine = get_threshold_engine()

        # Tool registry
        self.tool_registry = ToolRegistry(self.db)
        register_all_tools(self.tool_registry)

        # Communication
        qq_cfg = self.settings.get("qq", {}) if isinstance(self.settings, dict) else {}
        self.qq = QQClient(qq_cfg)
        self.router = Router(
            self_qq=int(qq_cfg.get("self_qq", 0)),
            friends_qq=qq_cfg.get("friends_qq", []),
        )
        self.splitter = SemanticMessageSplitter()

        # Phase 4: Recall manager hooks into SendQueue
        self.recall_manager = RecallManager(qq_client=self.qq)
        self.queue = SendQueue(
            sender=self._send_to_qq,
            splitter=self.splitter,
            recall_manager=self.recall_manager,
            db=self.db,
            qq_with_segments=self._send_qq_with_reply,
        )

        # Pipeline
        self.pipeline = Pipeline(
            router=self.router,
            emotion_engine=self.emotion,
            context_builder=ContextBuilder(self.memory, self.knowledge),
            brain=self.brain,
            send_queue=self.queue,
            tool_registry=self.tool_registry,
            db=self.db,
        )

        # Push scheduler
        proactive_cfg = load_proactive_config()
        self.push_scheduler = PushScheduler(proactive_cfg)
        self.push_scheduler.set_dispatcher(self._dispatch_push)

        self._started = False
        self._daily_decay_task: asyncio.Task | None = None
        self._push_task: asyncio.Task | None = None
        _COMPANION = self

    async def start(self) -> None:
        if self._started:
            return
        self.queue.start()
        self.qq.set_message_handler(self._on_qq_message)
        # Connect to NapCat WS (passive — won't start NapCat)
        asyncio.create_task(self.qq.connect())
        # Start daily emotion decay scheduler
        self._daily_decay_task = asyncio.create_task(self._run_daily_decay())
        # Start push scheduler
        self._push_task = asyncio.create_task(self.push_scheduler.start())
        self._started = True
        logger.info("Companion started")

    async def stop(self) -> None:
        if not self._started:
            return
        if self._push_task:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
        if self._daily_decay_task:
            self._daily_decay_task.cancel()
            try:
                await self._daily_decay_task
            except asyncio.CancelledError:
                pass
        try:
            await self.queue.stop()
        except Exception:
            pass
        try:
            await self.qq.stop()
        except Exception:
            pass
        self._started = False
        logger.info("Companion stopped")

    async def _send_to_qq(self, reply: OutgoingReply) -> bool:
        return await self.qq.send_message(reply.user_id, reply.content)

    async def _send_qq_with_reply(
        self, user_id: int, content: str, reply_to_qq_message_id: int
    ) -> bool:
        """Send a QQ message with a reply segment referencing the original message."""
        segments = [
            {"type": "reply", "data": {"id": int(reply_to_qq_message_id)}},
            {"type": "text", "data": {"text": content}},
        ]
        return await self.qq.send_message_with_segments(user_id, segments)

    async def recall_qq_message(self, msg_id: int) -> dict[str, Any]:
        """Recall an AI message by chat_log.id. Syncs to QQ + local DB."""
        try:
            row = self.db.query_one(
                "SELECT id, user_id, role, qq_message_id FROM chat_log WHERE id = ?",
                (msg_id,),
            )
            if not row:
                return {"status": "error", "reason": "not_found"}
            if row["role"] != "assistant":
                return {"status": "error", "reason": "only_assistant_can_be_recalled_via_this_endpoint"}
            if not row.get("qq_message_id"):
                return {"status": "error", "reason": "no_qq_message_id"}

            ok = await self.recall_manager.try_recall(
                row["user_id"], reason="manual_api"
            )
            if ok.get("status") == "ok":
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
                from core.chat_events import emit as _emit
                _emit(
                    "recall",
                    id=msg_id,
                    user_id=row["user_id"],
                    role="assistant",
                )
                return {"status": "ok", "msg_id": msg_id, "qq_recalled": ok.get("qq_recalled", False)}
            return {"status": "error", "reason": ok.get("reason", "unknown")}
        except Exception as e:
            logger.exception("recall_qq_message error")
            return {"status": "error", "reason": str(e)}

    async def _on_qq_message(self, msg: IncomingMessage) -> None:
        if self.pipeline:
            try:
                await self.pipeline.handle(msg)
            except Exception:
                logger.exception("pipeline.handle error")

    async def _run_daily_decay(self) -> None:
        """Background task: apply daily emotion decay at midnight."""
        while True:
            # Sleep until next midnight
            now = datetime.now()
            next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_seconds = (next_midnight - now).total_seconds()
            if wait_seconds > 0:
                try:
                    await asyncio.sleep(wait_seconds)
                except asyncio.CancelledError:
                    return

            # Apply decay
            try:
                self.threshold_engine.daily_decay()
                logger.info("Daily emotion decay applied")
            except Exception:
                logger.exception("daily decay error")

            # Also decay long-term memory importance
            try:
                self.memory.decay()
            except Exception:
                pass

            # Small pause to avoid double-fire
            await asyncio.sleep(60)

    async def _dispatch_push(self, scene_name: str, scene_cfg: dict) -> bool:
        """Called by PushScheduler when a scene triggers.
        
        Generates push content via Brain and sends via QQ client.
        Returns True on success.
        """
        try:
            master_id = int(self.settings.get("qq", {}).get("self_qq", 0))
            if not master_id:
                logger.warning("[Push] No master QQ configured")
                return False

            template = scene_cfg.get("template", "")
            mood_aware = scene_cfg.get("mood_aware", False)

            mood = "neutral"
            if mood_aware:
                state = self.emotion.get_state(master_id)
                mood = state.get("label", "neutral")

            # Fill template variables
            kwargs = {}
            now = datetime.now()
            kwargs["date"] = now.strftime("%Y年%m月%d日")

            content = await self.brain.generate_push(
                template=template,
                mood=mood,
                **kwargs,
            )

            if not content:
                return False

            # Send via QQ
            success = await self.qq.send_message(master_id, content)
            if success:
                logger.info("[Push] Sent scene=%s: %s", scene_name, content[:50])
            return success
        except Exception:
            logger.exception("[Push] dispatch error: %s", scene_name)
            return False

    async def check_idle(self, user_id: int, idle_seconds: float) -> bool:
        """Called externally when user is detected idle beyond threshold.
        
        Triggers idle_care scene if configured.
        """
        self.push_scheduler.trigger("idle_care")

    async def check_threshold_break(self) -> None:
        """Called when cumulative emotion threshold is exceeded.
        
        Triggers emotion_comfort scene if configured.
        """
        self.push_scheduler.trigger("emotion_comfort")

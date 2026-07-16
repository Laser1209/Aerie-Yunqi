"""Aerie · 云栖 v9.0 — Companion: orchestrator for all backend modules."""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from communication.message import IncomingMessage, OutgoingReply
from communication.qq_client import QQClient
from communication.router import Router
from communication.send_queue import SendQueue
from communication.splitter import SemanticMessageSplitter
from core.brain import Brain
from core.context_builder import ContextBuilder
from core.database import Database
from core.emotion_engine import EmotionEngine
from core.emotion_threshold import get_threshold_engine, CumulativeEmotionEngine
from core.pipeline import Pipeline
from core.tool_registry import ToolRegistry
from config.persona_loader import load_settings
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
        self.queue = SendQueue(sender=self._send_to_qq, splitter=self.splitter)

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

        self._started = False
        self._daily_decay_task: asyncio.Task | None = None
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
        self._started = True
        logger.info("Companion started")

    async def stop(self) -> None:
        if not self._started:
            return
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

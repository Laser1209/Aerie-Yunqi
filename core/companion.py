"""Aerie · 云栖 v9.0 — Companion: orchestrator for all backend modules.

This is the central runtime that wires together Brain, EmotionEngine,
QQClient, SendQueue, Pipeline, ProactiveMessenger, and CronScheduler.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

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
from core.emotion_threshold import CumulativeEmotionEngine
from core.napcat_launcher import get_launcher
from core.pipeline import Pipeline
from core.tool_registry import ToolRegistry
from config.persona_loader import load_proactive, load_settings
from knowledge.kb import KnowledgeBase
from memory.memory_store import LongTermMemory
from proactive.messenger import ProactiveMessenger
from proactive.policy import PushPolicy
from tools import register_all_tools


logger = logging.getLogger(__name__)


# Module-level singleton accessor used by tools.
_COMPANION: Optional["Companion"] = None


def get_companion() -> Optional["Companion"]:
    return _COMPANION


class Companion:
    """Master orchestrator."""

    def __init__(self, settings: Optional[dict] = None) -> None:
        global _COMPANION
        self.settings = settings or load_settings()
        self.db = Database()
        # Core engines
        self.emotion = EmotionEngine(self.db)
        self.cum_emotion = CumulativeEmotionEngine(self.db)
        self.token_tracker = None  # Set after Brain init
        self.brain: Optional[Brain] = None
        self.memory = LongTermMemory(self.db)
        self.knowledge = KnowledgeBase(self.db)
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
        self.queue: Optional[SendQueue] = None
        self.pipeline: Optional[Pipeline] = None
        self.recall: Optional[RecallManager] = None
        # Proactive
        self.policy = PushPolicy()
        self.messenger: Optional[ProactiveMessenger] = None
        self.scheduler = None
        self._started = False
        _COMPANION = self

    async def start(self) -> None:
        """Initialize all subsystems."""
        if self._started:
            return
        # Brain
        self.brain = Brain(tracker=None)
        self.token_tracker = self.brain.tracker
        # Send queue
        self.queue = SendQueue(sender=self._send_to_qq, splitter=self.splitter)
        self.queue.start()
        # Recall manager
        self.recall = RecallManager(self.qq)
        # Pipeline
        self.pipeline = Pipeline(
            router=self.router,
            emotion_engine=self.emotion,
            context_builder=ContextBuilder(self.memory, self.knowledge),
            brain=self.brain,
            send_queue=self.queue,
            tool_registry=self.tool_registry,
            recall_manager=self.recall,
            db=self.db,
        )
        self.qq.set_message_handler(self._on_qq_message)
        # Proactive messenger
        self.messenger = ProactiveMessenger(
            policy=self.policy,
            brain=self.brain,
            emotion_engine=self.emotion,
            send_queue=self.queue,
            db=self.db,
        )
        # Scheduler
        from scheduler.cron import CronScheduler
        self.scheduler = CronScheduler(
            messenger=self.messenger,
            master_id=int(self.settings.get("qq", {}).get("self_qq", 0)),
        )
        self.scheduler.start()
        # Auto-bootstrap NapCat (best-effort, non-blocking on failure)
        napcat_cfg = self.settings.get("napcat", {}) if isinstance(self.settings, dict) else {}
        if napcat_cfg.get("auto_start", True):
            asyncio.create_task(self._bootstrap_napcat(napcat_cfg))
        else:
            asyncio.create_task(self.qq.connect())
        self._started = True
        logger.info("Companion started")

    async def _bootstrap_napcat(self, napcat_cfg: dict) -> None:
        """Ensure NapCat is running, then connect the QQ WebSocket client."""
        try:
            launcher = get_launcher(self.settings)
            launcher.refresh_status()
            if not launcher._status.ws_port_open:
                logger.info("NapCat not running, attempting to start launcher")
                prefer_user = bool(napcat_cfg.get("prefer_user_launcher", True))
                result = await launcher.start(prefer_user=prefer_user, wait_port=True)
                if not result.get("port_open"):
                    logger.warning(
                        "NapCat launcher started but WS port %s is not yet open: %s",
                        launcher.ws_port, result.get("message"),
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning("NapCat bootstrap failed: %s", e)
        # Either way, attempt to connect the QQ WS — it will retry.
        await self.qq.connect()

    async def stop(self) -> None:
        if not self._started:
            return
        try:
            if self.scheduler:
                self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        try:
            if self.queue:
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
        try:
            ok = await self.qq.send_message(reply.user_id, reply.content, render_mode=reply.render_mode)
            if ok and self.recall:
                self.recall.on_message_sent(reply.user_id, reply.content)
            return ok
        except Exception as e:
            logger.warning("send_to_qq failed: %s", e)
            return False

    async def _on_qq_message(self, msg: IncomingMessage) -> None:
        if self.pipeline:
            try:
                await self.pipeline.handle(msg)
            except Exception as e:
                logger.exception("pipeline.handle error: %s", e)

    async def push_proactive(self, scene: str, template: str, **kwargs: Any) -> dict:
        if not self.messenger:
            return {"status": "messenger_not_ready"}
        master_id = int(self.settings.get("qq", {}).get("self_qq", 0))
        return await self.messenger.push(scene, master_id, template, **kwargs)

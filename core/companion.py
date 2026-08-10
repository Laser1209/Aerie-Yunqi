"""Aerie · 云栖 v0.1.0-beta.1 — Companion: orchestrator for all backend modules."""

from __future__ import annotations
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from communication.message import IncomingMessage, OutgoingReply
from communication.qq_client import QQClient
from communication.recall_manager import RecallManager
from communication.router import Router
from communication.send_queue import SendQueue
from communication.splitter import SemanticMessageSplitter
from config.persona_loader import load_behavior_config
from core.llm_caller import LLMCaller
from core.cognition import CognitionEngine
from core.decision import MultiLayerDecision
from core.computer_control import ComputerController, PermissionLevel
from core.conversation_continuity import (
    ContextAssembler,
    ConversationSummaryRepository,
    SummaryRefreshPlanner,
)
from core.conversation_repository import ConversationRepository
from core.chat_events import emit
from core.chat_request_repository import ChatRequestRepository
from core.chat_request_service import ChatRequestService
from core.chat_request_worker import ChatRequestWorker
from core.permission_manager import FineGrainedPermissionManager
from core.context_builder import ContextBuilder
from core.database import Database
from core.desktop_attachments import DesktopAttachmentService
from core.emotion_engine import EmotionEngine
from core.emotion_state_store import EmotionStateStore
from core.emotion_threshold import get_threshold_engine
from core.internal_state import InternalStateEngine
from core.feature_flags import FeatureFlags
from core.ids import generate_id
from core.identity import IdentityRepository, IdentityResolver
from core.pipeline import Pipeline
from core.paths import data_dir
from core.primary_identity import PrimaryIdentityResolver
from core.push_event_engine import get_event_engine
from core.push_scheduler import PushScheduler
from core.qq_whitelist import QQWhitelistManager
from core.self_evolver import SelfEvolver
from core.tool_registry import ToolRegistry
from core.world_port import build_world_port
from config.persona_loader import load_settings, load_proactive_config
from knowledge.kb import KnowledgeBase
from core.knowledge_indexer import resolve_embedding_fn
from memory.layers import LayeredMemory
from memory.layers.sync_adapter import LayeredMemorySyncAdapter
from core.message_batcher import MessageBatcher
from core.message_orchestrator import RecallJudge
from tools import register_all_tools

logger = logging.getLogger(__name__)

_COMPANION = None


def _api_base_url() -> str:
    """Backend origin the Electron renderer must use to load uploaded images.

    The renderer window is loaded from ``file://`` (not the backend origin),
    so any image src in a chat bubble has to be an absolute URL pointing at
    the API server that serves ``/uploads``.
    """
    port = os.environ.get("AERIE_BACKEND_PORT") or "7890"
    return f"http://127.0.0.1:{port}"


def _resolve_companion_data_path(settings: dict | None) -> Path:
    if (os.environ.get("AERIE_DATA_DIR") or "").strip():
        return data_dir()
    paths_cfg = settings.get("paths", {}) if isinstance(settings, dict) else {}
    if isinstance(paths_cfg, dict) and paths_cfg.get("data"):
        return Path(str(paths_cfg["data"]))
    return data_dir()


def get_companion():
    return _COMPANION


class Companion:
    def __init__(
        self,
        settings: dict | None = None,
        *,
        database: Any = None,
        runtime_config_service: Any = None,
    ) -> None:
        global _COMPANION
        self.settings = settings or load_settings()
        self.runtime_config_service = runtime_config_service
        self.feature_flags = FeatureFlags(
            runtime_config_service=runtime_config_service,
        )
        self.primary_identity_resolver = PrimaryIdentityResolver(
            runtime_config_service=runtime_config_service,
        )

        # R0.3.7: load centralized behavior config (single source of truth).
        self.behavior_cfg = load_behavior_config()
        # 世界配置 = 行为默认 + settings.yaml world 覆盖（用户可在设置页调位置/节奏）。
        self.world_config = dict(self.behavior_cfg.get("world_simulation", {}) or {})
        _settings_world = (self.settings or {}).get("world", {}) or {}
        if isinstance(_settings_world, dict):
            self.world_config.update({k: v for k, v in _settings_world.items() if v is not None})
        self.world_port = build_world_port(
            feature_flags=self.feature_flags,
            world_config=self.world_config,
            relationship_config=self.behavior_cfg.get("relationship", {}),
        )

        # Data layer
        self.db = database or Database()
        self.identity_repository = IdentityRepository(self.db)
        self.identity_resolver = IdentityResolver.from_feature_flags(
            self.identity_repository,
            self.feature_flags,
        )
        self.conversation_repository = ConversationRepository(
            self.db,
            enabled=self.feature_flags.is_enabled("conversation_model_v1"),
        )
        self.conversation_summary_repository = ConversationSummaryRepository(
            self.db,
        )
        self.summary_refresh_planner = SummaryRefreshPlanner(
            self.conversation_summary_repository,
        )
        self.context_assembler = ContextAssembler(
            self.conversation_repository,
            self.conversation_summary_repository,
            max_total_chars=24_000,
            recent_message_limit=24,
        )

        self.data_path = _resolve_companion_data_path(self.settings)
        attachment_root = Path(
            os.environ.get(
                "AERIE_DESKTOP_ATTACHMENT_ROOT",
                str(self.data_path / "desktop_attachments"),
            )
        )
        try:
            self.desktop_attachment_service = DesktopAttachmentService(
                self.db,
                storage_root=attachment_root,
            )
        except Exception:
            logger.exception("desktop attachment service initialization failed")
            self.desktop_attachment_service = None

        # ── Core engines (single instantiation — no duplicates) ──
        # Phase 9 Batch 1: emotion state store persists PAD + threshold
        # snapshots for 24h/7d/30d history curves on the dashboard.
        # OWNER: companion.py — always pass this instance to downstream modules.
        self.state_store = EmotionStateStore(self.db)        # R7.0: build the brain first so EmotionEngine can call back into
        # it for LLM-driven PAD inference. The keyword path is still
        # always available as a fallback when the LLM call fails.
        # OWNER: companion.py — always pass this instance to downstream modules.
        self.brain = LLMCaller()
        # R0.3.7: pass behavior_cfg so EmotionEngine reads PAD centers
        # and threshold slots from config/persona_behavior.yaml.
        self.emotion = EmotionEngine(
            self.db,
            state_store=self.state_store,
            behavior_cfg=self.behavior_cfg,
            brain=self.brain,
        )
        self._emotion_last_sampled_at = int(time.time() * 1000)
        # P1-D.5.3: 生产记忆切换到四层 LayeredMemory，并注入 embedding_fn（优先
        # ChromaDB 本地 ONNX 离线 embedding），实现向量语义检索。
        # 用同步适配器桥接旧 LongTermMemory 接口，context_builder/pipeline 无需改动。
        self._layered_memory = LayeredMemory(
            db=self.db,
            chroma_persist_dir=os.getenv("AERIE_CHROMA_DIR", "data/chroma"),
            embedding_fn=resolve_embedding_fn(),
        )
        self.memory = LayeredMemorySyncAdapter(self._layered_memory)
        self.knowledge = KnowledgeBase(self.db)

        # Phase 9 Batch 7 (B7.2): single cognition engine instance,
        # shared by the pipeline (writes traces) and SendQueue (writes
        # pacing_decisions back to those traces). This guarantees the
        # local-path write and the QQ-path write target the same row.
        self.cognition = CognitionEngine(self.db)

        # Cumulative threshold engine — driven by the same behavior_cfg
        # so the engine picks up persona_behavior.yaml thresholds on
        # first call (R0.3.7).
        self.threshold_engine = get_threshold_engine(self.behavior_cfg)

        # R6.6: warm-up the threshold engine from the latest non-zero
        # snapshot so the dashboard never shows a "0 → initial_value"
        # jump after a restart. Without this, the user sees the bar
        # flicker from 0 to 60 (initial_value) every time the backend
        # boots, which looks like the engine "just turned on" and not
        # like a real emotion continuation.
        self._warmup_threshold_from_history()

        # Phase 15 Batch 3 (B3.1): deterministic internal-state model
        # (needs / fatigue / neurochemical-like computed metrics). Read by
        # the dashboard's 内在状态 page; never a medical measurement.
        self.internal_state = InternalStateEngine()

        # Tool registry
        # v13.9: 全局共享的 ComputerController 单例，确保权限设置全局生效
        self.computer_controller = ComputerController()
        # v13.9: 细粒度权限管理器（目录授权 + 操作分类 + 高危确认）
        self.permission_manager = FineGrainedPermissionManager()
        self.tool_registry = ToolRegistry(self.db)
        # ⚠️ 重要：必须在 register_all_tools 之前设置 _COMPANION，
        # 否则 compute_tools 等通过 get_companion() 获取依赖的工具会注册失败
        _COMPANION = self
        register_all_tools(self.tool_registry)
        # v13.9: 任务规划引擎 + 执行引擎 + 异步任务
        from core.task_planner import TaskPlanner
        from core.task_executor import TaskExecutor
        from core.async_task_manager import AsyncTaskManager
        self.task_planner = TaskPlanner()
        self.task_executor = TaskExecutor(tool_registry=self.tool_registry)
        self.async_task_manager = AsyncTaskManager(max_concurrent=3)
        self._register_async_task_handlers()

        # Phase 9 Batch 6: Self-evolution engine (capability-gap detector)
        self.self_evolver = SelfEvolver(
            db=self.db,
            tool_registry=self.tool_registry,
            brain=self.brain,
        )

        # Communication
        qq_cfg = self.settings.get("qq", {}) if isinstance(self.settings, dict) else {}
        primary_selection = self.get_primary_user_selection()
        self.qq = QQClient(qq_cfg)
        # v13.9: QQ whitelist manager
        self.qq_whitelist = QQWhitelistManager(self.db)
        self.qq.set_whitelist(self.qq_whitelist)
        self.router = Router(
            self_qq=primary_selection.user_id if primary_selection else -1,
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
            # Phase 9 Batch 7 (B7.2): pass the same cognition engine
            # the pipeline uses, so the worker can append its observed
            # pacing_decisions back to the originating trace.
            cognition=self.cognition,
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
            self_evolver=self.self_evolver,
            cognition=self.cognition,
            decision_engine=MultiLayerDecision(),
            settings=self.settings,
            identity_resolver=self.identity_resolver,
            conversation_repository=self.conversation_repository,
            context_assembler=self.context_assembler,
            summary_planner=self.summary_refresh_planner,
            attachment_service=self.desktop_attachment_service,
            memory_store=self.memory,
        )
        self.pipeline.world_snapshot_provider = self._world_snapshot_for_context
        self.pipeline.relationship_snapshot_provider = self._relationship_snapshot_for_context
        self.pipeline.self_model_snapshot_provider = self._self_model_snapshot_for_context
        self.pipeline.internal_snapshot_provider = self._internal_snapshot_for_context
        self.chat_request_queue_requested = self.feature_flags.is_enabled(
            "chat_request_queue_v1",
        )
        chat_request_deps_ready = (
            self.feature_flags.is_enabled("migration_framework_v1")
            and self.feature_flags.is_enabled("conversation_model_v1")
        )
        self.chat_request_queue_ready = False
        self.chat_request_queue_error: str | None = None
        self.chat_request_repository: Any = None
        self.chat_request_service: Any = None
        self.chat_request_worker: Any = None
        if self.chat_request_queue_requested:
            if not chat_request_deps_ready:
                self.chat_request_queue_error = "queue_dependencies_unavailable"
            else:
                self.chat_request_repository = ChatRequestRepository(self.db)
                self.chat_request_service = ChatRequestService(
                    repository=self.chat_request_repository,
                    identity_repository=self.identity_repository,
                    attachment_service=self.desktop_attachment_service,
                )
                self.chat_request_worker = ChatRequestWorker(
                    repository=self.chat_request_repository,
                    pipeline=self.pipeline,
                    emit=emit,
                    clock=lambda: datetime.now(timezone.utc),
                )
                self.chat_request_service.set_worker(self.chat_request_worker)
                self.chat_request_queue_ready = True

        # Message batcher (Task 7: batch request processing)
        self.message_batcher: MessageBatcher | None = None
        try:
            self.message_batcher = MessageBatcher()
            self.message_batcher.register_callback(self._on_message_batch_ready)
            logger.info("MessageBatcher initialized and callback registered")
        except Exception:
            logger.exception("MessageBatcher init failed; batching disabled")
            self.message_batcher = None

        # Gate 5: 撤回判断联动 (RecallJudge)
        self.recall_judge: RecallJudge | None = None
        try:
            self.recall_judge = RecallJudge(
                self.recall_manager,
                window_seconds=self.recall_manager.config.window_seconds,
            )
        except Exception:
            logger.exception("RecallJudge init failed; recall judge disabled")
            self.recall_judge = None

        # Gate 4: 批次完成 → 通知 batcher 刷新该 conversation 的缓冲
        if self.chat_request_worker is not None:
            self.chat_request_worker.batch_completed_hook = self._on_batch_completed

        # Push scheduler
        proactive_cfg = load_proactive_config()
        self.push_scheduler = PushScheduler(proactive_cfg)
        # UI overlay: settings.yaml proactive.max_per_day / min_interval_min
        # override the proactive.yaml defaults (consistent with image budget).
        try:
            _pset = (self.settings or {}).get("proactive", {})
            _pol = self.push_scheduler.policy
            if isinstance(_pset, dict):
                if _pset.get("max_per_day") is not None:
                    _pol.max_per_day = int(_pset["max_per_day"])
                if _pset.get("min_interval_min") is not None:
                    _pol.min_interval_min = int(_pset["min_interval_min"])
        except Exception:
            logger.debug("apply proactive frequency overlay failed", exc_info=True)
        self.push_scheduler.set_dispatcher(self._dispatch_push)
        self.push_event_engine = get_event_engine()
        self.push_event_engine.bind_scheduler(self.push_scheduler)
        # R7.5+: bind a ProactiveJudge so every dispatch consults
        # 心情 / 想法 / 用户上下文 before sending.
        try:
            from core.proactive_judge import ProactiveJudge
            self.proactive_judge = ProactiveJudge(companion=self)
            self.push_scheduler.judge = self.proactive_judge
        except Exception:
            logger.exception("ProactiveJudge init failed; push will run judge-less")
            self.proactive_judge = None

        # Phase 14: lazy one-shot consumer for world ImageCandidate events.
        # It is not started as a background loop here; callers explicitly
        # invoke process_world_image_candidates_once() so the old chat/push
        # paths stay unchanged while the contract hardens behind a flag.
        self.world_image_candidate_consumer: Any = None

        self._started = False
        self._daily_decay_task: asyncio.Task | None = None
        self._push_task: asyncio.Task | None = None
        self._boot_brief_task: asyncio.Task | None = None
        # R7.5: 10s background tick for emotion dashboard liveness.
        self._emotion_tick_task: asyncio.Task | None = None
        # Block-4B R2.2: 24h desire engine (lazy-created on first start()).
        self.desire: Any = None
        # Block-4C R3.4: skill loader (lazy-created on first start()).
        self.skill_loader: Any = None
        _COMPANION = self

    async def start(self) -> None:
        if self._started:
            return
        self.queue.start()
        if self.chat_request_worker is not None:
            try:
                await self.chat_request_worker.start()
            except Exception:
                self.chat_request_queue_ready = False
                self.chat_request_queue_error = "queue_worker_start_failed"
                logger.exception("chat request worker start failed")
        self.qq.set_message_handler(self._on_qq_message)
        await self._start_push_event_engine()

        # Workstream 7: idempotently seed `dialogue` knowledge (发起腔 principles).
        try:
            from tools.seed_social_knowledge import seed_dialogue
            seed_dialogue(self.knowledge)
        except Exception:
            logger.exception("dialogue knowledge seed failed; continuing")

        # ── Phase 1: 基础设施启动 ──

        # R9.0+: subscribe to QQ state changes BEFORE connecting
        self._boot_greeting_fired = False
        self.qq.on_state_change(self._on_qq_state_change)

        # Start QQ connection in background (it will poll for port open)
        asyncio.create_task(self.qq.connect())

        # Start daily emotion decay scheduler
        self._daily_decay_task = asyncio.create_task(self._run_daily_decay())

        # R7.5: 10s background tick for emotion dashboard liveness.
        # Every 6th tick (≈60s) writes a snapshot so the history curve
        # stays alive even when no user messages arrive.
        self._emotion_tick_task = asyncio.create_task(self._emotion_tick_loop())

        # 世界真实时间推进 + 真实数据刷新（inprocess 模式下主动 tick）。
        self._world_loop_task = asyncio.create_task(self._run_world_loop())

        # Block-4B R2.2: start 24h desire engine (24h polling, not cron)
        try:
            from core.desire_engine import DesireEngine
            self.desire = DesireEngine(self, self.behavior_cfg)
            await self.desire.start()
        except Exception:
            logger.exception("desire engine start failed; continuing without it")
            self.desire = None

        # Block-4C R3.4: discover + register all 17 skills (local + data).
        try:
            from core.skill_loader import SkillLoader
            from core.skill_router import SkillRouter
            self.skill_router = SkillRouter(self.behavior_cfg)
            self.skill_loader = SkillLoader(self.tool_registry, self.skill_router)
            n_disc = self.skill_loader.discover()
            n_reg = self.skill_loader.register_all()
            logger.info("skills: %d discovered, %d registered", n_disc, n_reg)
        except Exception:
            logger.exception("skill loader init failed; continuing without skills")
            self.skill_loader = None

        # Start async task manager for background document generation etc.
        self.async_task_manager.start()
        logger.info("Async task manager started")

        # ── Phase 1b: 等待 QQ 就绪（有超时，不阻塞其他服务） ──
        qq_cfg = self.settings.get("qq", {}) if isinstance(self.settings, dict) else {}
        wait_timeout = float(qq_cfg.get("startup_wait_timeout", 30.0))
        push_pause_when_offline = bool(qq_cfg.get("push_pause_when_offline", True))
        if self.feature_flags.is_enabled("proactive_delivery_v2"):
            push_pause_when_offline = False

        logger.info("[Startup] Waiting for QQ readiness (timeout=%ss)", wait_timeout)
        qq_ready = await self.qq.wait_until_ready(timeout=wait_timeout)

        if qq_ready:
            logger.info("[Startup] QQ ready, proceeding with full startup")
            # ── Phase 2: 通信层就绪（QQ 已就绪） ──
            # (SendQueue / Router / Pipeline 已经在 __init__ 中初始化好，
            #  这里不需要额外动作）

            # ── Phase 3: 业务层启动 ──
            # Start push scheduler
            self._push_task = asyncio.create_task(self.push_scheduler.start())
            if self.qq.connectivity_test:
                self.push_scheduler.pause("qq_connectivity_test")
                logger.info("[Startup] QQ connectivity test mode; delivery is disabled")
            else:
                # Block-4A R1.5: run brief once + emit show event
                # (8s delay is inside _boot_brief itself)
                self._boot_brief_task = asyncio.create_task(self._boot_brief())

                # boot_greeting: trigger immediately (QQ is already ready)
                # Guard on _boot_greeting_fired so the state-change callback
                # (which may have fired first during connect) and this path
                # can't both launch a greeting task → would send twice.
                if not self._boot_greeting_fired:
                    self._boot_greeting_fired = True
                    asyncio.create_task(self._boot_qq_greeting())
        else:
            logger.warning(
                "[Startup] QQ not ready after %ss; starting in degraded mode "
                "(push scheduler paused)",
                wait_timeout,
            )
            # Start push scheduler but pause it immediately
            self._push_task = asyncio.create_task(self.push_scheduler.start())
            if push_pause_when_offline:
                self.push_scheduler.pause("qq_offline")

            # boot_brief_task = asyncio.create_task(self._boot_brief())

        self._started = True
        logger.info("Companion started (qq_ready=%s)", qq_ready)

    def _on_qq_state_change(self, new_state: str) -> None:
        """R9.0+: handle QQ state transitions at runtime.

        - When QQ goes offline → pause push scheduler
        - When QQ comes back online → resume push scheduler
        - First time QQ logs in → fire boot_greeting
        """
        from communication.qq_client import STATE_LOGGED_IN, STATE_DISCONNECTED

        qq_client = getattr(self, "qq", None)
        if qq_client is not None and getattr(qq_client, "connectivity_test", False):
            logger.info("[QQ State] connectivity test transition: %s", new_state)
            return

        if new_state == STATE_LOGGED_IN:
            # Resume push scheduler if it was paused due to QQ
            if self.push_scheduler.is_paused and self.push_scheduler.paused_reason == "qq_offline":
                self.push_scheduler.resume()
                logger.info("[QQ State] QQ back online; push scheduler resumed")

            # Fire boot greeting on FIRST login only
            # (if start() already fired it synchronously when QQ was ready
            #  at startup; this path covers the "QQ-started-later case)
            if not self._boot_greeting_fired:
                self._boot_greeting_fired = True
                asyncio.create_task(self._boot_qq_greeting())

        elif new_state == STATE_DISCONNECTED:
            if self.feature_flags.is_enabled("proactive_delivery_v2"):
                logger.info(
                    "[QQ State] QQ offline; local proactive delivery remains active"
                )
                return
            qq_cfg = self.settings.get("qq", {}) if isinstance(self.settings, dict) else {}
            if bool(qq_cfg.get("push_pause_when_offline", True)):
                if self.push_scheduler.is_paused:
                    return
                self.push_scheduler.pause("qq_offline")
                logger.info("[QQ State] QQ offline; push scheduler paused")

    async def process_world_image_candidates_once(
        self,
        *,
        last_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        """Consume replayed world ImageCandidate events once.

        Phase 14 keeps this explicit and pull-based: no new background loop,
        no renderer direct sidecar access, and no change to legacy image or
        proactive paths when ``world_image_candidates_v1`` is off.
        """

        consumer = self._get_world_image_candidate_consumer()
        return await consumer.consume_replay(last_seq=last_seq)

    async def publish_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Publish an AI image decision and consume it so it reaches local chat.

        This is the publisher behind "AI-generated images auto-inject into the
        local chat bubble": it appends a redacted ImageCandidate to the world
        outbox, then immediately consumes it.  The Phase 14 consumer runs the
        image workflow and, for ``local_chat``, emits an assistant bubble with
        the generated image.  If the world is disabled or the publisher is
        unavailable the call fails closed (no image, no side effect).
        """
        world_port = getattr(self, "world_port", None)
        publish = getattr(world_port, "publish_image_candidate", None)
        if not callable(publish):
            return {
                "status": "disabled",
                "reason": "world_publisher_unavailable",
                "candidate_id": str((candidate or {}).get("candidate_id") or ""),
                "acked": False,
            }

        payload = dict(candidate or {})
        try:
            result = publish(payload)
            if hasattr(result, "__await__"):
                result = await result
        except Exception:
            logger.warning("world image candidate publish failed", exc_info=True)
            return {
                "status": "failed",
                "reason": "publish_failed",
                "candidate_id": str(payload.get("candidate_id") or ""),
                "acked": False,
            }

        result = result if isinstance(result, dict) else {}
        if str(result.get("status") or "") != "accepted":
            return {
                "status": str(result.get("status") or "rejected"),
                "reason": str(result.get("reason") or "") or "publish_rejected",
                "candidate_id": str(result.get("candidate_id") or ""),
                "acked": False,
            }

        # Consume from the event we just published so the generated image
        # auto-injects into the local chat (or QQ) on this same call.
        seq = max(0, int(result.get("sequence") or 0) - 1)
        try:
            consumed = await self.process_world_image_candidates_once(last_seq=seq)
        except Exception:
            logger.warning("world image candidate consume failed after publish", exc_info=True)
            consumed = []
        return {
            "status": "published",
            "candidate_id": str(result.get("candidate_id") or ""),
            "channel": str(result.get("channel") or ""),
            "target": str(result.get("target") or ""),
            "sequence": int(result.get("sequence") or 0),
            "event_id": str(result.get("event_id") or ""),
            "consumed": consumed,
        }

    async def approve_world_image_candidate(
        self,
        approval: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle a Dashboard-originated manual ImageCandidate decision.

        The API layer has already stripped the renderer payload down to public
        approval fields.  This handler deliberately delegates to the Phase 14
        consumer so manual dashboard decisions share the same WorldPort replay,
        image workflow idempotency, ACK, and redacted audit path as automatic
        candidate consumption.
        """

        consumer = self._get_world_image_candidate_consumer()
        approve = getattr(consumer, "approve_candidate", None)
        if not callable(approve):
            return {
                "status": "backend_unavailable",
                "reason": "approval_consumer_unavailable",
                "candidate_id": str((approval or {}).get("candidate_id") or ""),
                "acked": False,
                "side_effects": {
                    "provider_called": False,
                    "asset_created": False,
                    "delivery_created": False,
                },
            }
        result = approve(dict(approval or {}))
        if hasattr(result, "__await__"):
            result = await result
        return result if isinstance(result, dict) else {
            "status": "failed",
            "reason": "invalid_approval_result",
            "candidate_id": str((approval or {}).get("candidate_id") or ""),
            "acked": False,
        }

    async def get_world_dashboard_snapshot(
        self,
        *,
        user_id: int | str = 0,
    ) -> dict[str, Any]:
        """Build a redacted snapshot for the World Dashboard.

        This is read-only.  It asks the WorldPort for public state/snapshots
        and recent events, then reduces them to Dashboard-safe metadata.  Raw
        world payloads, prompts, message text, provider details, and plugin
        config values are never returned.
        """

        world_port = getattr(self, "world_port", None)
        state_data = await _dashboard_get_world_state(world_port)
        world_summary = _dashboard_world_summary(
            state_data,
            _dashboard_safe_mapping(self._world_snapshot_for_context()),
        )
        relationship_state = _dashboard_safe_relationship(
            self._relationship_snapshot_for_context(user_id),
        )
        self_model = _dashboard_safe_self_model(
            self._self_model_snapshot_for_context(world_summary, relationship_state),
        )
        events = await _dashboard_replay_events(world_port)
        return {
            "status": "ready" if state_data or world_summary else "degraded",
            "worldSummary": world_summary,
            "relationshipState": relationship_state,
            "selfModel": self_model,
            "actionTimeline": _dashboard_action_timeline(events),
            "imageCandidates": _dashboard_image_candidates(events),
            "updatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        }

    def get_internal_state(self, user_id: int | str = 0) -> dict[str, Any]:
        """Compute the current internal-state snapshot (needs/fatigue/neuro).

        Phase 15 Batch 3 (B3.1). Deterministic, source-tracked, and always
        labelled "计算模型，非生物测量" (never a medical measurement). Read-only.
        """
        world = self._world_snapshot_for_context()
        emotion = self.get_primary_emotion_state()
        relationship = self._relationship_snapshot_for_context(
            int(user_id) if str(user_id).isdigit() else 0,
        )
        snapshot = self.internal_state.compute(world, emotion, relationship)
        snapshot.setdefault("status", "ready")
        return snapshot

    def get_internal_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the recent internal-state snapshots for the trend chart."""
        return self.internal_state.history(limit=limit)

    def _get_world_image_candidate_consumer(self) -> Any:
        existing = getattr(self, "world_image_candidate_consumer", None)
        if existing is not None:
            return existing

        from core.image_service import (
            LLMCallerImageGenerationProvider,
            LLMCallerImageVisionProvider,
            ImageWorkflow,
        )
        from core.paths import data_dir
        from core.world_image_candidates import (
            JsonWorldImageCandidateStore,
            WorldImageCandidateConsumer,
        )

        scheduler = getattr(self, "push_scheduler", None)
        push_policy = getattr(scheduler, "policy", None)
        cron = getattr(scheduler, "cron", None)
        if push_policy is None and cron is not None:
            push_policy = getattr(cron, "policy", None)

        workflow = ImageWorkflow(
            upload_base=(Path.cwd() / "uploads").resolve(),
            feature_enabled=self.feature_flags.is_enabled("image_assets_v1"),
            generation_provider=LLMCallerImageGenerationProvider(getattr(self, "brain", None)),
            vision_provider=LLMCallerImageVisionProvider(getattr(self, "brain", None)),
        )

        try:
            from core.image_budget import ImageBudget

            settings = getattr(self, "settings", None) or {}
            proactive_cfg = settings.get("proactive", {}) if isinstance(settings, dict) else {}
            image_max_per_day = int(proactive_cfg.get("image_max_per_day", 0) or 0)
            image_budget = ImageBudget(
                state_path=data_dir() / "image_budget_state.json",
                limits={"proactive": image_max_per_day},
            )
        except Exception:
            logger.debug("image budget init failed; disabling proactive limit", exc_info=True)
            image_budget = None

        def delivery_online() -> bool:
            try:
                return not bool(getattr(scheduler, "is_paused", False))
            except Exception:
                return True

        def _resolve_generated_asset_path(workflow_result: dict) -> str | None:
            asset = workflow_result.get("asset") if isinstance(workflow_result, dict) else {}
            if not isinstance(asset, dict):
                return None
            saved = str(asset.get("saved_as") or "").strip()
            if not saved or "\x00" in saved:
                return None
            base = (Path.cwd() / "uploads").resolve()
            try:
                target = (base / saved).resolve()
                target.relative_to(base)
            except (OSError, ValueError):
                return None
            return str(target) if target.is_file() else None

        async def _deliver_world_image(plan: dict, workflow_result: dict) -> bool:
            channel = str(plan.get("channel") or "").lower()
            if channel == "local_chat":
                return _deliver_local_chat_image(plan, workflow_result)
            target = str(plan.get("target") or "").strip()
            if not target.isdigit():
                primary = self.get_primary_user_selection()
                target = str(getattr(primary, "user_id", "") or "") if primary else ""
            if not target.isdigit():
                logger.warning("[WorldImage] no valid QQ target for delivery")
                return False
            image_ref = _resolve_generated_asset_path(workflow_result)
            if not image_ref:
                logger.warning("[WorldImage] generated asset missing for delivery")
                return False
            return await self.qq.send_image(int(target), image_ref)

        def _deliver_local_chat_image(plan: dict, workflow_result: dict) -> bool:
            asset = workflow_result.get("asset") if isinstance(workflow_result, dict) else {}
            url = str(asset.get("url") or "") if isinstance(asset, dict) else ""
            if not url:
                url = str(plan.get("asset_url") or "")
            if not url:
                logger.warning("[WorldImage] no asset url for local chat delivery")
                return False
            base = _api_base_url()
            image_url = url if url.startswith("http") else base + (url if url.startswith("/") else "/" + url)
            target = str(plan.get("target") or "").strip() or "master"
            message_id = generate_id("message")
            from core import chat_events

            chat_events.emit(
                "assistant",
                role="assistant",
                id=message_id,
                user_id=target,
                content=f"![图片]({image_url})",
                source="local_chat",
            )
            logger.info("[WorldImage] delivered generated image to local chat: %s", image_url)
            return True

        self.world_image_candidate_consumer = WorldImageCandidateConsumer(
            feature_flags=self.feature_flags,
            image_workflow=workflow,
            world_port=getattr(self, "world_port", None),
            push_policy=push_policy,
            proactive_judge=getattr(self, "proactive_judge", None),
            image_budget=image_budget,
            store=JsonWorldImageCandidateStore(data_dir() / "world_image_candidates.json"),
            delivery_online=delivery_online,
            sender=_deliver_world_image,
        )
        return self.world_image_candidate_consumer

    def _world_snapshot_for_context(self) -> dict | None:
        provider = getattr(self.world_port, "get_world_snapshot", None)
        if not callable(provider):
            return None
        try:
            return provider()
        except Exception:
            logger.debug("world snapshot unavailable", exc_info=True)
            return None

    def _relationship_snapshot_for_context(self, user_id: int) -> dict | None:
        provider = getattr(self.world_port, "get_relationship_snapshot", None)
        if not callable(provider):
            return None
        try:
            persona_id = self._active_persona_id()
            return provider(user_id, persona_id=persona_id)
        except Exception:
            logger.debug("relationship snapshot unavailable", exc_info=True)
            return None

    def _self_model_snapshot_for_context(
        self,
        world_snapshot: dict | None,
        relationship_snapshot: dict | None,
    ) -> dict | None:
        provider = getattr(self.world_port, "get_self_model_snapshot", None)
        if not callable(provider):
            return None
        try:
            return provider(world_snapshot, relationship_snapshot)
        except Exception:
            logger.debug("self model snapshot unavailable", exc_info=True)
            return None

    def _internal_snapshot_for_context(
        self,
        world_snapshot: dict | None,
        relationship_snapshot: dict | None,
    ) -> dict | None:
        internal = getattr(self, "internal_state", None)
        if not callable(getattr(internal, "compute", None)):
            return None
        try:
            emotion = self.get_primary_emotion_state()
            return internal.compute(world_snapshot, emotion, relationship_snapshot)
        except Exception:
            logger.debug("internal state snapshot unavailable", exc_info=True)
            return None

    def _active_persona_id(self) -> str:
        try:
            from core.persona_hub import get_persona_manager

            active = get_persona_manager().get_active() or {}
            basic = active.get("basic", {}) if isinstance(active, dict) else {}
            return str(active.get("id") or basic.get("id") or basic.get("name") or "default")
        except Exception:
            return "default"

    # ── v13.9: 异步任务处理器注册 ──────────────────────────────
    def _register_async_task_handlers(self) -> None:
        """为异步任务管理器注册真实任务处理器。"""
        mgr = self.async_task_manager

        async def task_doc_generate(data: dict, progress_cb) -> dict:
            """文档生成任务。"""
            import asyncio
            title = data.get("title", "未命名文档")
            content = data.get("content", "")
            fmt = data.get("format", "markdown")

            progress_cb(10, "准备文档生成参数", "初始化", 1, 3)
            await asyncio.sleep(0.3)

            progress_cb(40, f"生成 {fmt} 格式文档中...", "生成内容", 2, 3)
            tool_result = self.tool_registry.execute_sync(
                "document_create",
                {"title": title, "content": content, "format": fmt}
            ) if hasattr(self.tool_registry, "execute_sync") else {}

            # 用同步方式调用
            entry = self.tool_registry.get("document_create")
            if entry and entry.get("func"):
                try:
                    tool_result = entry["func"](title=title, content=content, format=fmt)
                except Exception as e:
                    tool_result = {"success": False, "error": str(e)}

            await asyncio.sleep(0.3)
            progress_cb(100, "文档生成完成", "完成", 3, 3)
            return tool_result

        async def task_data_analysis(data: dict, progress_cb) -> dict:
            """数据分析任务。"""
            import asyncio
            dataset = data.get("data", [])

            progress_cb(20, "加载数据集", "加载", 1, 4)
            await asyncio.sleep(0.2)

            progress_cb(50, "执行统计分析...", "统计", 2, 4)
            entry = self.tool_registry.get("data_stats")
            result = {}
            if entry and entry.get("func"):
                try:
                    result = entry["func"](dataset)
                except Exception as e:
                    result = {"success": False, "error": str(e)}
            await asyncio.sleep(0.2)

            progress_cb(80, "生成可视化图表...", "图表", 3, 4)
            await asyncio.sleep(0.2)

            progress_cb(100, "分析完成", "完成", 4, 4)
            return result

        async def task_file_organize(data: dict, progress_cb) -> dict:
            """文件整理任务。"""
            import asyncio
            import os
            target_dir = data.get("directory", "")
            mode = data.get("mode", "type")
            categories = data.get("categories", [])

            progress_cb(10, f"扫描目录: {target_dir}", "扫描", 1, 4)
            await asyncio.sleep(0.2)

            if not target_dir or not os.path.isdir(target_dir):
                return {"success": False, "error": "目标目录不存在"}

            entry = self.tool_registry.get("directory_list")
            if entry and entry.get("func"):
                try:
                    dir_result = entry["func"](target_dir)
                except Exception as e:
                    dir_result = {"success": False, "error": str(e)}
            else:
                dir_result = {"success": False, "error": "工具不可用"}

            progress_cb(50, "分类整理文件中...", "分类", 2, 4)
            await asyncio.sleep(0.3)

            progress_cb(80, "移动文件到目标文件夹...", "移动", 3, 4)
            await asyncio.sleep(0.2)

            progress_cb(100, "整理完成", "完成", 4, 4)
            return {"success": True, "mode": mode, "organized": dir_result.get("total_count", 0)}

        # 注册任务处理器
        mgr.register_task_func("doc_generate", task_doc_generate)
        mgr.register_task_func("data_analysis", task_data_analysis)
        mgr.register_task_func("file_organize", task_file_organize)
        logger.info("registered 3 async task handlers")

    # ── R6.6: warm-up threshold engine from history ───────────────
    def _warmup_threshold_from_history(self) -> None:
        """Restore the primary Actor's cumulative slots from its latest snapshot."""
        try:
            primary = self.get_primary_identity()
            if not primary:
                return
            master_id, identity = primary
            row = self.state_store.latest(
                master_id,
                actor_id=identity.actor_id,
            )
            if not row:
                return
            self.emotion.restore_threshold_snapshot(
                row,
                actor_id=identity.actor_id,
            )
            logger.info(
                "threshold warm-up restored for actor=%s",
                identity.actor_id,
            )
        except Exception:
            logger.debug("threshold warm-up skipped (no history or table missing)")

    async def _start_push_event_engine(self) -> None:
        try:
            self.push_event_engine.bind_scheduler(self.push_scheduler)
            await self.push_event_engine.start()
        except Exception:
            logger.exception("push event engine start failed; continuing without it")

    async def _stop_push_event_engine(self) -> None:
        try:
            await self.push_event_engine.stop()
        except Exception:
            logger.exception("push event engine stop error")

    async def stop(self) -> None:
        if not self._started:
            return
        await self._stop_push_event_engine()
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
        if self._boot_brief_task:
            self._boot_brief_task.cancel()
            try:
                await self._boot_brief_task
            except asyncio.CancelledError:
                pass
        if self._emotion_tick_task:
            self._emotion_tick_task.cancel()
            try:
                await self._emotion_tick_task
            except asyncio.CancelledError:
                pass
        if getattr(self, "_world_loop_task", None):
            self._world_loop_task.cancel()
            try:
                await self._world_loop_task
            except asyncio.CancelledError:
                pass
        if self.desire:
            try:
                await self.desire.stop()
            except Exception:
                logger.exception("desire stop error")
        if self.chat_request_worker is not None:
            try:
                await self.chat_request_worker.stop()
            except Exception:
                logger.exception("chat request worker stop error")
        try:
            await self.pipeline.shutdown_background_tasks()
        except Exception:
            logger.exception("pipeline background task cleanup error")
        try:
            await self.queue.stop()
        except Exception:
            pass
        try:
            await self.qq.stop()
        except Exception:
            pass

        # ── Resource cleanup ──
        try:
            await self.computer_controller.cleanup()
        except Exception:
            logger.exception("computer_controller cleanup error")

        self._started = False
        logger.info("Companion stopped")

    # ── Block-4A R1.5: boot brief hook ───────────────────────────
    async def _boot_brief(self) -> None:
        """Block-4A R1.5: 8s after start, lazily generate today's brief.

        If today's brief already exists, skip (preserves morning_brief_9am
        cron idempotency). After generation, dispatch via the morning_brief_9am
        scene (uses custom_dispatcher="brief" path) and emit a chat event so
        the Electron renderer can pop the iframe.
        """
        try:
            await asyncio.sleep(8)
            from core import brief_fetcher
            today = datetime.now().strftime("%Y-%m-%d")
            if brief_fetcher.load_brief(today):
                logger.info("boot_brief: today's brief exists, skip")
                return
            logger.info("boot_brief: generating brief for %s", today)
            sections = await brief_fetcher.run_all()
            try:
                md = await self.brain.compose_brief(sections)
            except Exception as e:
                logger.warning("boot_brief: compose_brief failed: %s", e)
                md = ""
            brief_fetcher.save_brief(today, sections, html=md)
            # Dispatch via push scheduler (uses custom_dispatcher=brief branch).
            try:
                await self.push_scheduler.trigger("morning_brief_9am")
            except Exception:
                logger.exception("boot_brief: push dispatch failed")
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("boot_brief failed")

    # ── R7.5+: boot QQ greeting hook ─────────────────────
    async def _boot_qq_greeting(self) -> None:
        """R8.0+: 应用启动后主动给用户 QQ 发一条消息。

        行为:
          1. 等 8s,让 NapCat WS / 后端 / 情绪 / 隐藏槽位就绪
          2. idempotency: 距上次发送 < 4h 则跳过(防每次重启都刷屏)
             R8.0+ 变更: 从"当天一次"改为"60s 窗口"(每次启动都欢迎);
             现按需求改为"4 小时内只欢迎一次"(跨重启生效)
          3. force=True 触发 boot_greeting scene (绕过 ProactiveJudge + PushPolicy)
          4. 成功后写 flag,失败不写(下次启动可重试)
        """
        flag_dir = self.data_path
        flag_dir.mkdir(parents=True, exist_ok=True)
        # 4h 窗口 — flag 用 mtime 判断, 不区分日期
        flag_path = flag_dir / "boot_greeting_last_sent.flag"
        greeting_window = 4 * 3600.0  # 4 hours

        # ── 步骤 1: idempotency (4h 内不重复欢迎) ──
        if flag_path.exists():
            try:
                import time
                mtime = flag_path.stat().st_mtime
                elapsed = time.time() - mtime
                if elapsed < greeting_window:
                    logger.info(
                        "boot_qq_greeting: sent %.0fs ago (< 4h window), skip",
                        elapsed,
                    )
                    return
            except Exception:
                logger.debug("boot_qq_greeting: flag mtime check failed", exc_info=True)

        try:
            # ── 步骤 2: 等 QQ 真正登录就绪 ──
            # R8.1+: 之前用固定 sleep(8) 只能保证 WS 层连接 (后端 <-> NapCat),
            # 无法保证 QQ 账号已登录到腾讯服务器, 导致 boot_greeting 被
            # NapCat "假发送" (WS 返回 ok 但消息实际未投递). 改为等待
            # is_logged_in 信号 (lifecycle.connect 事件或 get_login_info 成功).
            # 超时则跳过本次 greeting, 下次重启再试, 不硬发.
            logged_in = await self.qq.wait_for_login(timeout=15.0)
            if not logged_in:
                logger.warning(
                    "boot_qq_greeting: QQ not logged in after 15s, skip this "
                    "launch (will retry on next restart)",
                )
                return
            # 登录刚就绪时 NapCat 内部可能还在同步消息队列, 给一点缓冲.
            await asyncio.sleep(2)

            # ── 步骤 3: 再次检查 (防等待期间另一进程已发) ──
            if flag_path.exists():
                try:
                    import time
                    elapsed = time.time() - flag_path.stat().st_mtime
                    if elapsed < greeting_window:
                        logger.info(
                            "boot_qq_greeting: sent during wait window, skip",
                        )
                        return
                except Exception:
                    pass

            # ── 步骤 4: 触发 boot_greeting scene ──
            # judge_override 让 ProactiveJudge 强制放行(中位数基线即可)
            # R8.0+: force=True bypasses ProactiveJudge and PushPolicy
            # so the greeting fires unconditionally on every launch.
            # R8.2+: 不再硬编码"看头像"死梗 — 按时段选通用问候, 并注入
            # 当天真实上下文(待办数 / 天气), 让 LLM 有依据地润色。
            greeting = self._boot_greeting_template()
            todo_frag = self._boot_todo_fragment()
            try:
                weather_frag = await asyncio.wait_for(
                    self._boot_weather_fragment(), timeout=6.0
                )
            except Exception:
                weather_frag = ""
            template = (
                f"{greeting}今天{datetime.now():%Y年%m月%d日}，"
                f"{todo_frag}{weather_frag}".strip()
            )
            ok = await self.push_scheduler._dispatch(
                "boot_greeting",
                {
                    "template": template,
                    "custom_dispatcher": "boot_greeting",
                    "mood_aware": True,
                    "exempt_quiet": True,
                    "force": True,
                    "judge_override": {
                        "desire_score": 60.0,
                        "emotion_score": 60.0,
                        "context_score": 50.0,
                        "environment_score": 50.0,
                    },
                },
            )

            if ok:
                # 写 flag
                try:
                    flag_path.write_text(
                        datetime.now().isoformat(timespec="seconds"),
                        encoding="utf-8",
                    )
                except Exception:
                    logger.exception("boot_qq_greeting: failed to write flag")
                logger.info(
                    "boot_qq_greeting: sent OK, flag=%s", flag_path,
                )
            else:
                logger.warning(
                    "boot_qq_greeting: dispatch returned False (judge or policy suppressed)",
                )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("boot_qq_greeting failed")

    # ── R8.2+: boot greeting 内容构建 ─────────────────────────
    @staticmethod
    def _boot_greeting_template() -> str:
        """R8.2+: 按时段选择开机问候的通用开场(替代硬编码死梗)。

        仅返回问候语, 具体日期/待办/天气由调用方拼接成完整模板,
        再交给 LLMCaller.generate_push 润色。
        """
        hour = datetime.now().hour
        if 5 <= hour < 11:
            return "早安宝贝，新的一天我陪你。"
        if 11 <= hour < 14:
            return "中午好宝贝，忙了一上午，记得好好吃饭。"
        if 14 <= hour < 18:
            return "下午好宝贝，我一直都在。"
        if 18 <= hour < 23:
            return "晚上好宝贝，今天辛苦啦。"
        return "夜深了宝贝，该休息了。"

    @staticmethod
    def _boot_todo_fragment() -> str:
        """R8.2+: 开机问候附带真实待办数; 0 件时给正向反馈。失败则返回空。"""
        try:
            from core import todo_manager
            remaining = int(todo_manager.stats().get("remaining") or 0)
        except Exception:
            logger.exception("boot_greeting: todo stats failed")
            return ""
        if remaining <= 0:
            return "今天的事都做完啦，真棒。"
        return f"你还有 {remaining} 件事待办。"

    @staticmethod
    async def _boot_weather_fragment() -> str:
        """R8.2+: 开机问候附带今日天气; 获取失败则返回空, 不阻塞问候。"""
        try:
            from core import weather_service
            w = await weather_service.fetch_weather_for_current_location()
            city = str(w.get("city") or "").strip()
            desc = str(w.get("desc") or "").strip()
            temp = str(w.get("temp") or "").strip()
            if not desc or desc in ("—", "获取失败"):
                return ""
            parts = [f"{city}今天{desc}"]
            if temp and temp not in ("—", ""):
                parts.append(f"{temp}度")
            return "，".join(parts) + "。"
        except Exception:
            logger.exception("boot_greeting: weather fetch failed")
            return ""

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

    async def recall_message(self, msg_id: int) -> dict[str, Any]:
        """Recall an AI message by chat_log.id (通用, 按 channel 分派).

        - QQ 消息: RecallManager.try_recall → NapCat delete_msg 真实撤回
        - 本地消息: DB 标记 is_recalled=1 + 前端事件 (无真实协议撤回)
        """
        try:
            row = self.db.query_one(
                "SELECT id, user_id, role, channel, channel_account_id, qq_message_id "
                "FROM chat_log WHERE id = ?",
                (msg_id,),
            )
            if not row:
                return {"status": "error", "reason": "not_found"}
            if row["role"] != "assistant":
                return {"status": "error", "reason": "only_assistant_can_be_recalled_via_this_endpoint"}

            channel = row.get("channel") or (
                "qq" if row.get("qq_message_id") else "local"
            )
            account = row.get("channel_account_id") or str(row["user_id"])
            ok = await self.recall_manager.try_recall(
                row["user_id"], reason="manual_api",
                channel=channel, channel_account_id=account,
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
                return {
                    "status": "ok", "msg_id": msg_id,
                    "qq_recalled": ok.get("qq_recalled", False), "channel": channel,
                }
            return {"status": "error", "reason": ok.get("reason", "unknown")}
        except Exception as e:
            logger.exception("recall_message error")
            return {"status": "error", "reason": str(e)}

    async def _on_qq_message(self, msg: IncomingMessage) -> None:
        relationship_observer = getattr(
            getattr(self, "world_port", None),
            "relationship",
            None,
        )
        if relationship_observer is not None:
            try:
                emotion_pad = self.get_primary_emotion_state().get("pad", {})
                relationship_observer.observe_user_message(
                    user_id=msg.user_id,
                    persona_id=self._active_persona_id(),
                    text=msg.content,
                    pleasure=emotion_pad.get("P"),
                )
            except Exception:
                logger.debug("relationship observation failed", exc_info=True)

        if self.desire:
            try:
                self.desire.mark_user_active()
            except Exception:
                logger.debug("desire.mark_user_active failed")
        try:
            self.push_event_engine.record_user_activity()
        except Exception:
            logger.debug("push event activity record failed", exc_info=True)

        await self._submit_incoming_message(msg)

    async def _submit_incoming_message(self, msg: IncomingMessage) -> None:
        if self.message_batcher is not None:
            try:
                await self.message_batcher.submit_message(msg)
                return
            except Exception:
                logger.exception("message batcher submit failed, falling back to direct pipeline")

        if self.pipeline:
            try:
                force_full = (msg.source == "local")
                await self.pipeline.handle(msg, force_full=force_full)
            except Exception:
                logger.exception("pipeline.handle error")

    async def submit_local_message(self, msg: IncomingMessage) -> None:
        if self.desire:
            try:
                self.desire.mark_user_active()
            except Exception:
                logger.debug("desire.mark_user_active failed")
        try:
            self.push_event_engine.record_user_activity()
        except Exception:
            logger.debug("push event activity record failed", exc_info=True)

        await self._submit_incoming_message(msg)

    async def process_local_message_sync(self, msg: IncomingMessage) -> dict | None:
        if self.desire:
            try:
                self.desire.mark_user_active()
            except Exception:
                logger.debug("desire.mark_user_active failed")
        try:
            self.push_event_engine.record_user_activity()
        except Exception:
            logger.debug("push event activity record failed", exc_info=True)

        if self.pipeline:
            try:
                force_full = (msg.source == "local")
                return await self.pipeline.handle(msg, force_full=force_full)
            except Exception:
                logger.exception("pipeline.handle sync error for local message")
                return None
        return None

    async def _on_message_batch_ready(
        self,
        messages: list[IncomingMessage],
        batch_id: str,
    ) -> None:
        logger.info(
            "Processing message batch %s: %d messages",
            batch_id,
            len(messages),
        )
        # Gate 5: 撤回判断联动 —— 新批到达且上一批已产出时, 决定是否撤回首条再合并重算
        if self.recall_judge is not None and messages:
            first = messages[0]
            if self.recall_manager is not None:
                # 仅当新批非首条 (上一批已产出) 时才判定; 首条无"前批"可撤
                try:
                    key = (first.channel or "qq", first.channel_account_id or str(first.user_id))
                    has_prev = key in self.recall_manager._last_sent
                except Exception:
                    has_prev = False
                if has_prev:
                    decision = self.recall_judge.should_recall_prev(
                        prev_reply="",
                        new_msg=first.content,
                        channel=first.channel or "qq",
                        channel_account_id=first.channel_account_id,
                        user_id=first.user_id,
                    )
                    if decision.recall:
                        logger.info(
                            "RecallJudge: recall previous reply (%s), user=%s",
                            decision.reason,
                            first.user_id,
                        )
                        try:
                            await self.recall_manager.try_recall(
                                first.user_id,
                                reason="recall_judge",
                                channel=first.channel or "qq",
                                channel_account_id=first.channel_account_id,
                            )
                        except Exception:
                            logger.exception("recall_judge try_recall failed")
        if self.chat_request_queue_ready and self.chat_request_service is not None:
            try:
                self.chat_request_service.submit_batch(messages, batch_id)
                logger.info(
                    "Batch %s submitted to request queue (%d messages)",
                    batch_id,
                    len(messages),
                )
                return
            except Exception:
                logger.exception(
                    "Failed to submit batch %s to request queue, falling back to direct pipeline",
                    batch_id,
                )

        if self.pipeline:
            try:
                if len(messages) == 1:
                    force_full = (messages[0].source == "local")
                    await self.pipeline.handle(messages[0], force_full=force_full)
                else:
                    await self.pipeline.handle(messages=messages, batch_id=batch_id)
            except Exception:
                logger.exception(
                    "pipeline.handle batch error: batch_id=%s",
                    batch_id,
                )
            finally:
                # Gate 4: 直接路径同步处理完 → 通知 batcher 刷新缓冲
                await self._on_batch_completed(messages[0] if messages else None)

    async def _on_batch_completed(self, first_message) -> None:
        """Gate 4: 批次完成后通知 batcher, 让缓冲消息作为新批处理."""
        if self.message_batcher is None or first_message is None:
            return
        try:
            conv_id = MessageBatcher.get_conversation_id(first_message)
            await self.message_batcher.on_batch_completed(conv_id)
        except Exception:
            logger.exception("on_batch_completed bridge failed")

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
                primary = self.get_primary_identity()
                if primary:
                    _, identity = primary
                    self.emotion.daily_decay(
                        actor_id=identity.actor_id,
                    )
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

    def get_primary_identity(self):
        """Return the validated primary user id and normalized identity."""
        selection = self.get_primary_user_selection()
        if selection is None:
            return None
        master_id = selection.user_id
        return (
            master_id,
            self.identity_resolver.resolve(
                "qq",
                str(master_id),
            ),
        )

    def get_primary_user_selection(self):
        """Return the effective primary user and its non-secret source."""
        resolver = getattr(self, "primary_identity_resolver", None)
        if resolver is None:
            resolver = PrimaryIdentityResolver(
                runtime_config_service=getattr(
                    self,
                    "runtime_config_service",
                    None,
                ),
            )
            self.primary_identity_resolver = resolver
        return resolver.resolve(
            settings=getattr(self, "settings", None),
            runtime_config_service=getattr(
                self,
                "runtime_config_service",
                None,
            ),
        )

    def get_primary_emotion_state(self) -> dict:
        """Return emotion state for the configured primary Actor."""
        primary = self.get_primary_identity()
        if not primary:
            now = int(time.time() * 1000)
            return {
                "status": "unavailable",
                "error": "primary identity is not configured",
                "primaryUserId": None,
                "sampledAt": None,
                "latestPersistedAt": None,
                "serverNow": now,
                "stale": True,
            }
        master_id, identity = primary
        state = dict(self.emotion.get_state(
            master_id,
            actor_id=identity.actor_id,
        ))
        state["primaryUserId"] = master_id
        sampled_at = getattr(self, "_emotion_last_sampled_at", None)
        state_store = getattr(self, "state_store", None)
        if state_store is not None:
            state.update(state_store.freshness_metadata(
                master_id,
                actor_id=identity.actor_id,
                sampled_at=sampled_at,
            ))
        else:
            now = int(time.time() * 1000)
            state.update({
                "sampledAt": sampled_at,
                "latestPersistedAt": None,
                "serverNow": now,
                "stale": sampled_at is None or now - sampled_at > 10_000,
            })
        return state

    async def _run_world_loop(self) -> None:
        """世界真实时间推进 + 真实数据刷新（inprocess 模式）。

        每 ``tick_interval_sec`` 主动调用 world_port.tick() 让世界随真实时钟
        推进；每 ``reality_refresh_sec`` 拉取一次真实天气/附近地点/实时事件
        并注入模拟（best-effort，失败静默回退到确定性默认）。
        """
        wp = getattr(self, "world_port", None)
        # 仅 inprocess 世界（有 .world 且支持 set_reality）启用心跳。
        if not wp or not hasattr(wp, "world") or not callable(getattr(wp, "set_reality", None)):
            return
        cfg = getattr(self, "world_config", {}) or {}
        tick_sec = max(5, int(cfg.get("tick_interval_sec") or 300))
        refresh_sec = max(tick_sec, int(cfg.get("reality_refresh_sec") or 1800))
        city = str(cfg.get("location") or "").strip()
        last_refresh = 0.0
        while True:
            try:
                # 真实时间推进：即使没有消息，世界也随时钟演进。
                wp.tick()
                if not city:
                    # 未配置世界位置 → 用自动定位解析一次。
                    try:
                        from core.location_resolver import resolve_location_async
                        loc = await resolve_location_async()
                        city = str(loc.get("city") or "").strip()
                        if city:
                            cfg["location"] = city
                    except Exception:
                        city = ""
                now = asyncio.get_event_loop().time()
                if now - last_refresh >= refresh_sec:
                    # 每次刷新重新读取世界位置，让设置页改动无需重启即可生效。
                    try:
                        from config.persona_loader import load_settings
                        _reloaded = (load_settings() or {}).get("world", {}) or {}
                        if isinstance(_reloaded, dict) and str(_reloaded.get("location") or "").strip():
                            city = str(_reloaded["location"]).strip()
                        elif not city:
                            city = str(cfg.get("location") or "").strip()
                    except Exception:
                        city = str(cfg.get("location") or "").strip()
                    if city:
                        from core.world_reality import fetch_reality
                        reality = await fetch_reality(city)
                        wp.set_reality(reality)
                        wp.tick()
                    last_refresh = now
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("world loop tick failed", exc_info=True)
            await asyncio.sleep(tick_sec)

    async def _emotion_tick_loop(self) -> None:
        """R7.5+: background tick loop for emotion dashboard liveness.

        Three independent cadences on a shared 1-second base tick:

        * **PAD (3 s)** — runs ``idle_tick()`` so P/A/D drift via EMA +
          noise. Matches the dashboard's 3 s poll so the flow bars
          (dP/dt, dA/dt, dD/dt) show a non-zero derivative on most
          fetches.
        * **Threshold (30 s)** — runs ``tick_decay(30)`` so each slot
          loses ``decay_per_day / 2880`` per call. Integrated over 24 h
          this equals ``decay_per_day`` (the configured daily rate);
          the 30 s spacing keeps the user-perceived "speed of decay"
          calm instead of the previous every-10-s collapse.
        * **Snapshot (60 s)** — writes an ``idle_tick`` snapshot so the
          24h / 7d / 30d curves keep filling in even with zero user
          traffic.

        All errors are swallowed — this is decorative, never fatal.
        """
        pad_ticks = 0
        thr_ticks = 0
        snap_ticks = 0
        try:
            while True:
                await asyncio.sleep(1)
                pad_ticks += 1
                thr_ticks += 1
                snap_ticks += 1
                try:
                    primary = self.get_primary_identity()
                    if not primary:
                        continue
                    master_id, identity = primary
                    if pad_ticks >= 3:
                        pad_ticks = 0
                        self.emotion.idle_tick(
                            actor_id=identity.actor_id,
                        )
                        self._emotion_last_sampled_at = int(time.time() * 1000)
                    if thr_ticks >= 30:
                        thr_ticks = 0
                        self.emotion.tick_decay(
                            30.0,
                            actor_id=identity.actor_id,
                        )
                except Exception as e:
                    logger.debug("emotion tick error: %s", e)
                if snap_ticks >= 60:
                    snap_ticks = 0
                    try:
                        st = self.get_primary_emotion_state()
                        if not st:
                            continue
                        self.state_store.snapshot(
                            master_id,
                            {"label": st.get("label"), "pad": st.get("pad")},
                            st.get("thresholds", {}),
                            trigger_event="idle_tick",
                            actor_id=identity.actor_id,
                        )
                    except Exception as e:
                        logger.debug("emotion snapshot error: %s", e)
        except asyncio.CancelledError:
            return

    async def _dispatch_push(self, scene_name: str, scene_cfg: dict) -> bool:
        """Generate one proactive message and deliver it independently."""
        try:
            primary_selection = self.get_primary_user_selection()
            if primary_selection is None:
                logger.warning("[Push] No primary user configured")
                return False
            master_id = primary_selection.user_id
            delivery_v2 = self.feature_flags.is_enabled("proactive_delivery_v2")

            mood = "neutral"
            if scene_cfg.get("mood_aware"):
                state = self.get_primary_emotion_state()
                mood = state.get("label", "neutral")

            # Workstream 6: retrieve `dialogue` knowledge as generation
            # principles (how to talk) and inject into the push prompt.
            # These are NEVER recited into the message itself.
            knowledge_fragment = ""
            try:
                query = f"{scene_name} {scene_cfg.get('template', '')} 发起"
                hits = self.knowledge.search(query, limit=3, category="dialogue")
                if hits:
                    principles = [
                        str(row.get("content", "")).strip()
                        for row in hits
                        if str(row.get("content", "")).strip()
                    ]
                    if principles:
                        knowledge_fragment = (
                            "发起话术原则（吸收为你的说法风格，不要说教/复述）：\n"
                            + "\n".join(f"- {p}" for p in principles)
                            + "\n"
                        )
            except Exception as e:
                logger.debug("[Push] dialogue knowledge retrieval failed: %s", e)

            content = await self.brain.generate_push(
                template=scene_cfg.get("template", ""),
                mood=mood,
                tone_hint=scene_cfg.get("tone_hint"),
                judge_context=scene_cfg.get("judge_context"),
                knowledge_fragment=knowledge_fragment,
                date=datetime.now().strftime("%Y年%m月%d日"),
            )
            if not content:
                return False

            if not delivery_v2:
                success = await self.qq.send_message(master_id, content)
                if success:
                    logger.info("[Push] Sent legacy QQ scene=%s", scene_name)
                return success

            delivered = False
            delivery_results = {
                "qq": "offline",
                "desktop": "failed",
                "notification": "failed",
            }
            if master_id and getattr(self.qq, "is_logged_in", False):
                try:
                    qq_sent = await self.qq.send_message(master_id, content)
                    delivery_results["qq"] = "sent" if qq_sent else "failed"
                    delivered = bool(qq_sent)
                except Exception:
                    delivery_results["qq"] = "failed"
                    logger.warning("[Push] QQ delivery failed scene=%s", scene_name, exc_info=True)
            elif not master_id:
                delivery_results["qq"] = "skipped"

            from core import chat_events

            message_id: int | str = generate_id("message")
            try:
                message_id = self.db.insert(
                    "chat_log",
                    {
                        "user_id": master_id,
                        "role": "assistant",
                        "content": content,
                        "msg_type": "proactive",
                        "route_mode": "PROACTIVE",
                        "scene": scene_name,
                    },
                )
            except Exception:
                logger.warning(
                    "[Push] proactive persistence failed scene=%s",
                    scene_name,
                    exc_info=True,
                )

            try:
                chat_events.emit(
                    "assistant",
                    role="assistant",
                    id=message_id,
                    user_id=master_id,
                    content=content,
                    source="proactive",
                    scene=scene_name,
                    channel="desktop",
                )
                delivery_results["desktop"] = "queued"
                delivered = True
            except Exception:
                logger.warning("[Push] desktop delivery failed scene=%s", scene_name, exc_info=True)

            proactive_settings = self.settings.get("proactive", {})
            notify_system = bool(
                proactive_settings.get("system_notifications", True)
            )
            try:
                chat_events.emit(
                    "proactive_message",
                    title="云栖",
                    text=content,
                    content=content,
                    scene=scene_name,
                    tone=scene_cfg.get("tone_hint"),
                    notify_system=notify_system,
                    channel="notification",
                )
                delivery_results["notification"] = (
                    "queued" if notify_system else "disabled"
                )
                delivered = True
            except Exception:
                logger.warning("[Push] notification delivery failed scene=%s", scene_name, exc_info=True)

            try:
                chat_events.emit(
                    "proactive_delivery",
                    scene=scene_name,
                    results=delivery_results,
                    channel="delivery",
                )
            except Exception:
                logger.warning(
                    "[Push] delivery telemetry failed scene=%s",
                    scene_name,
                    exc_info=True,
                )

            if delivered:
                logger.info("[Push] Delivered scene=%s", scene_name)
            return delivered
        except Exception:
            logger.exception("[Push] dispatch error: %s", scene_name)
            return False

    async def check_idle(self, user_id: int, idle_seconds: float) -> bool:
        """Called externally when user is detected idle beyond threshold.

        Triggers idle_care scene if configured.
        """
        return await self.push_scheduler.trigger("idle_care")

    async def check_threshold_break(self) -> bool:
        """Called when cumulative emotion threshold is exceeded.

        Triggers emotion_comfort scene if configured.
        """
        return await self.push_scheduler.trigger("emotion_comfort")


async def _dashboard_get_world_state(world_port: Any) -> dict[str, Any]:
    if world_port is None:
        return {}
    getter = getattr(world_port, "get_state", None)
    if not callable(getter):
        return {}
    try:
        value = getter()
        if hasattr(value, "__await__"):
            value = await value
        to_public = getattr(value, "to_public_dict", None)
        if callable(to_public):
            value = to_public()
        return value if isinstance(value, dict) else {}
    except Exception:
        logger.debug("world dashboard state unavailable", exc_info=True)
        return {}


async def _dashboard_replay_events(world_port: Any) -> list[Any]:
    replay = getattr(world_port, "replay_events", None)
    if not callable(replay):
        return []
    try:
        try:
            events = replay(last_seq=0)
        except TypeError:
            events = replay()
        if hasattr(events, "__await__"):
            events = await events
        return list(events or [])[:25]
    except Exception:
        logger.debug("world dashboard event replay unavailable", exc_info=True)
        return []


def _dashboard_world_summary(
    state: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    merged = {}
    if isinstance(state, dict):
        merged.update(state)
    if isinstance(snapshot, dict):
        merged.update(snapshot)
    return _dashboard_pick(
        merged,
        (
            ("status", "status"),
            ("source", "source"),
            ("instanceId", "instance_id", "instanceId"),
            ("protocol", "protocol"),
            ("protocolVersion", "protocol_version", "protocolVersion"),
            ("phase", "phase"),
            ("location", "location"),
            ("activity", "activity"),
            ("weather", "weather", "weather_mood"),
            ("weatherMood", "weather_mood", "weather"),
            ("sequence", "sequence"),
            ("revision", "revision"),
            ("paused", "paused"),
            ("generatedAt", "generated_at", "generatedAt"),
            ("capabilities", "capabilities"),
        ),
    )


def _dashboard_safe_relationship(value: dict[str, Any] | None) -> dict[str, Any]:
    # 兼容两类数据形态：
    #   A. RelationshipEngine 的嵌套状态（agent_to_user / user_to_agent / security / conflict）
    #   B. 扁平化的关系字段（warmth / trust / affinity / tension / ...）
    # 统一映射为仪表盘公开字段，避免因 key 不匹配而整段丢失（G3）。
    data = _dashboard_safe_mapping(value)
    if not data:
        return {}
    agent_to_user = _dashboard_safe_mapping(data.get("agent_to_user"))
    user_to_agent = _dashboard_safe_mapping(data.get("user_to_agent"))
    user_emotion = _dashboard_safe_mapping(data.get("user_emotion"))

    candidates: list[tuple[str, Any]] = [
        ("user_id", data.get("user_id") or data.get("userId")),
        ("persona_id", data.get("persona_id") or data.get("personaId")),
        # 嵌套形态优先，扁平形态兜底
        ("attachment", agent_to_user.get("attachment") or data.get("attachment")),
        ("agentTrust", agent_to_user.get("trust") or data.get("agentTrust")),
        ("care", agent_to_user.get("care") or data.get("care")),
        ("warmth", user_to_agent.get("warmth") or data.get("warmth")),
        ("engagement", user_to_agent.get("engagement") or data.get("engagement")),
        ("userTrust", user_to_agent.get("trust") or data.get("userTrust")),
        ("trust", data.get("trust") or agent_to_user.get("trust")),
        ("security", data.get("security")),
        ("conflict", data.get("conflict")),
        ("affinity", data.get("affinity")),
        ("tension", data.get("tension")),
        ("familiarity", data.get("familiarity")),
        ("closeness", data.get("closeness")),
        ("summary", data.get("summary")),
        ("userEmotionLabel", user_emotion.get("label")),
        ("userEmotionValence", user_emotion.get("valence")),
        ("source", data.get("source")),
        ("revision", data.get("revision")),
        ("updated_at", data.get("updated_at") or data.get("updatedAt")),
    ]
    public: dict[str, Any] = {}
    for output_key, raw in candidates:
        public_value = _dashboard_public_scalar(raw)
        if public_value not in ("", None, [], {}):
            public[output_key] = public_value
    return public


def _dashboard_safe_self_model(value: dict[str, Any] | None) -> dict[str, Any]:
    return _dashboard_pick(
        _dashboard_safe_mapping(value),
        (
            ("mood", "mood"),
            ("energy", "energy"),
            ("focus", "focus"),
            ("stability", "stability"),
            ("summary", "summary"),
            ("updated_at", "updated_at", "updatedAt"),
        ),
    )


def _dashboard_action_timeline(events: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events[:25]:
        payload = _dashboard_event_payload(event)
        payload_keys = payload.get("payload_keys") or payload.get("payloadKeys")
        if not isinstance(payload_keys, list):
            payload_keys = sorted(str(key) for key in payload.keys())
        row = {
            "eventId": _dashboard_safe_text(getattr(event, "event_id", "") or ""),
            "topic": _dashboard_safe_text(getattr(event, "topic", "") or ""),
            "eventType": _dashboard_safe_text(getattr(event, "event_type", "") or ""),
            "sequence": _dashboard_event_sequence(event),
            "occurredAt": _dashboard_safe_text(getattr(event, "occurred_at", "") or ""),
            "payloadKeys": _dashboard_public_payload_keys(payload_keys),
        }
        digest = payload.get("payload_sha256") or payload.get("payloadSha256")
        if digest:
            row["payloadSha256"] = _dashboard_safe_text(digest, 120)
        rows.append(row)
    return rows


def _dashboard_image_candidates(events: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events[:25]:
        topic = str(getattr(event, "topic", "") or "")
        event_type = str(getattr(event, "event_type", "") or "")
        if topic not in {"image_candidates", "message.candidates", "world.image_candidates"} and event_type not in {"world.image_candidate.published", "image_candidate.published"}:
            continue
        payload = _dashboard_event_payload(event)
        candidate = _dashboard_pick(
            payload,
            (
                ("candidateId", "candidate_id", "candidateId", "id"),
                ("idempotencyKey", "idempotency_key", "idempotencyKey"),
                ("scene", "scene"),
                ("ownerId", "owner_id", "ownerId"),
                ("channel", "channel"),
                ("target", "target"),
                ("promptKey", "prompt_key", "promptKey"),
                ("reasonCode", "reason_code", "reasonCode"),
                ("source", "source"),
                ("score", "score"),
                ("expiresAt", "expires_at", "expiresAt"),
                ("createdAt", "created_at", "createdAt"),
                ("payloadKeys", "payload_keys", "payloadKeys"),
                ("sensitiveKeys", "sensitive_keys", "sensitiveKeys"),
                ("sensitiveSha256", "sensitive_sha256", "sensitiveSha256"),
            ),
        )
        candidate["sequence"] = _dashboard_event_sequence(event)
        candidate["eventId"] = _dashboard_safe_text(getattr(event, "event_id", "") or "")
        rows.append(candidate)
    return rows


def _dashboard_event_payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", {})
    return payload if isinstance(payload, dict) else {}


def _dashboard_event_sequence(event: Any) -> int:
    try:
        return int(getattr(event, "sequence", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _dashboard_public_payload_keys(keys: list[Any]) -> list[str]:
    public: list[str] = []
    for key in keys[:25]:
        text = _dashboard_safe_text(key, 120)
        lowered = text.lower()
        if "raw" in lowered or "prompt" in lowered or "token" in lowered or "credential" in lowered:
            continue
        public.append(text)
    return public


def _dashboard_safe_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dashboard_pick(
    data: dict[str, Any],
    fields: tuple[tuple[str, ...], ...],
) -> dict[str, Any]:
    public: dict[str, Any] = {}
    source = data if isinstance(data, dict) else {}
    for field in fields:
        output_key, *input_keys = field
        raw = _dashboard_first(source, input_keys)
        public_value = _dashboard_public_scalar(raw)
        if public_value not in ("", None, [], {}):
            public[output_key] = public_value
    return public


def _dashboard_first(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _dashboard_public_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, list | tuple):
        return [_dashboard_safe_text(item, 120) for item in value[:25]]
    if value is None:
        return ""
    return _dashboard_safe_text(value)


def _dashboard_safe_text(value: Any, limit: int = 200) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]

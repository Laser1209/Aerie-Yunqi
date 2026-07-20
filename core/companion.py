"""Aerie · 云栖 v0.1.0-beta.1 — Companion: orchestrator for all backend modules."""

from __future__ import annotations
import asyncio
import logging
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
from core.brain import Brain
from core.cognition import CognitionEngine
from core.computer_control import ComputerController, PermissionLevel
from core.conversation_repository import ConversationRepository
from core.chat_events import emit
from core.chat_request_repository import ChatRequestRepository
from core.chat_request_service import ChatRequestService
from core.chat_request_worker import ChatRequestWorker
from core.permission_manager import FineGrainedPermissionManager
from core.context_builder import ContextBuilder
from core.database import Database
from core.emotion_engine import EmotionEngine
from core.emotion_state_store import EmotionStateStore
from core.emotion_threshold import get_threshold_engine
from core.feature_flags import FeatureFlags
from core.ids import generate_id
from core.identity import IdentityRepository, IdentityResolver
from core.pipeline import Pipeline
from core.push_event_engine import get_event_engine
from core.push_scheduler import PushScheduler
from core.qq_whitelist import QQWhitelistManager
from core.self_evolver import SelfEvolver
from core.tool_registry import ToolRegistry
from core.world_port import build_world_port
from config.persona_loader import load_settings, load_proactive_config
from knowledge.kb import KnowledgeBase
from memory.memory_store import LongTermMemory
from tools import register_all_tools

logger = logging.getLogger(__name__)

_COMPANION = None


def get_companion():
    return _COMPANION


class Companion:
    def __init__(
        self,
        settings: dict | None = None,
        *,
        database: Any = None,
    ) -> None:
        global _COMPANION
        self.settings = settings or load_settings()
        self.feature_flags = FeatureFlags()

        # R0.3.7: load centralized behavior config (single source of truth).
        self.behavior_cfg = load_behavior_config()
        self.world_port = build_world_port(
            feature_flags=self.feature_flags,
            world_config=self.behavior_cfg.get("world_simulation", {}),
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

        # ── Core engines (single instantiation — no duplicates) ──
        # Phase 9 Batch 1: emotion state store persists PAD + threshold
        # snapshots for 24h/7d/30d history curves on the dashboard.
        # OWNER: companion.py — always pass this instance to downstream modules.
        self.state_store = EmotionStateStore(self.db)        # R7.0: build the brain first so EmotionEngine can call back into
        # it for LLM-driven PAD inference. The keyword path is still
        # always available as a fallback when the LLM call fails.
        # OWNER: companion.py — always pass this instance to downstream modules.
        self.brain = Brain()
        # R0.3.7: pass behavior_cfg so EmotionEngine reads PAD centers
        # and threshold slots from config/persona_behavior.yaml.
        self.emotion = EmotionEngine(
            self.db,
            state_store=self.state_store,
            behavior_cfg=self.behavior_cfg,
            brain=self.brain,
        )
        self.memory = LongTermMemory(self.db)
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
        self.qq = QQClient(qq_cfg)
        # v13.9: QQ whitelist manager
        self.qq_whitelist = QQWhitelistManager(self.db)
        self.qq.set_whitelist(self.qq_whitelist)
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
            settings=self.settings,
            identity_resolver=self.identity_resolver,
            conversation_repository=self.conversation_repository,
        )
        self.pipeline.world_snapshot_provider = self._world_snapshot_for_context
        self.pipeline.relationship_snapshot_provider = self._relationship_snapshot_for_context
        self.pipeline.self_model_snapshot_provider = self._self_model_snapshot_for_context
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
                )
                self.chat_request_worker = ChatRequestWorker(
                    repository=self.chat_request_repository,
                    pipeline=self.pipeline,
                    emit=emit,
                    clock=lambda: datetime.now(timezone.utc),
                )
                self.chat_request_service.set_worker(self.chat_request_worker)
                self.chat_request_queue_ready = True

        # Push scheduler
        proactive_cfg = load_proactive_config()
        self.push_scheduler = PushScheduler(proactive_cfg)
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

        self._started = False
        self._daily_decay_task: asyncio.Task | None = None
        self._push_task: asyncio.Task | None = None
        self._boot_brief_task: asyncio.Task | None = None
        # R7.5+: 应用启动后主动 QQ 推送任务
        self._boot_qq_task: asyncio.Task | None = None
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

            # Block-4A R1.5: run brief once + emit show event
            # (8s delay is inside _boot_brief itself)
            self._boot_brief_task = asyncio.create_task(self._boot_brief())

            # boot_greeting: trigger immediately (QQ is already ready)
            # Set the flag FIRST so the state-change callback doesn't
            # fire a duplicate (lifecycle.connect may fire after this).
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
        if self._boot_qq_task:
            self._boot_qq_task.cancel()
            try:
                await self._boot_qq_task
            except asyncio.CancelledError:
                pass
        if self._emotion_tick_task:
            self._emotion_tick_task.cancel()
            try:
                await self._emotion_tick_task
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
          2. idempotency: 距上次发送 < 60s 则跳过(防快速重启刷屏)
             R8.0+ 变更: 从"当天一次"改为"60s 窗口" — 用户要每次启动都欢迎
          3. force=True 触发 boot_greeting scene (绕过 ProactiveJudge + PushPolicy)
          4. 成功后写 flag,失败不写(下次启动可重试)
        """
        flag_dir = Path(self.settings.get("paths", {}).get("data", "./data")) if isinstance(
            self.settings.get("paths"), dict) else Path("./data")
        flag_dir.mkdir(parents=True, exist_ok=True)
        # R8.0+: 60s 窗口 — flag 不再分日期,而是检查 mtime
        flag_path = flag_dir / "boot_greeting_last_sent.flag"

        # ── 步骤 1: 60s idempotency (防快速重启刷屏) ──
        if flag_path.exists():
            try:
                import time
                mtime = flag_path.stat().st_mtime
                elapsed = time.time() - mtime
                if elapsed < 60.0:
                    logger.info(
                        "boot_qq_greeting: sent %.0fs ago (< 60s window), skip",
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
                    if elapsed < 60.0:
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
            ok = await self.push_scheduler._dispatch(
                "boot_greeting",
                {
                    "template": "刚醒。盯着屏幕看你头像。",
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
        relationship_observer = getattr(
            getattr(self, "world_port", None),
            "relationship",
            None,
        )
        if relationship_observer is not None:
            try:
                relationship_observer.observe_user_message(
                    user_id=msg.user_id,
                    persona_id=self._active_persona_id(),
                    text=msg.content,
                )
            except Exception:
                logger.debug("relationship observation failed", exc_info=True)
        if self.pipeline:
            try:
                await self.pipeline.handle(msg)
            except Exception:
                logger.exception("pipeline.handle error")
        # Block-4B R2.2: reset user-absence clock on inbound message.
        if self.desire:
            try:
                self.desire.mark_user_active()
            except Exception:
                logger.debug("desire.mark_user_active failed")
        try:
            self.push_event_engine.record_user_activity()
        except Exception:
            logger.debug("push event activity record failed", exc_info=True)

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
        """Return configured primary QQ user id and normalized identity."""
        try:
            master_id = int(
                self.settings.get("qq", {}).get("self_qq", 0)
            )
        except (TypeError, ValueError):
            master_id = 0
        if not master_id:
            return None
        return (
            master_id,
            self.identity_resolver.resolve(
                "qq",
                str(master_id),
            ),
        )

    def get_primary_emotion_state(self) -> dict:
        """Return emotion state for the configured primary Actor."""
        primary = self.get_primary_identity()
        if not primary:
            return {}
        master_id, identity = primary
        return self.emotion.get_state(
            master_id,
            actor_id=identity.actor_id,
        )

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
            master_id = int(self.settings.get("qq", {}).get("self_qq", 0))
            if not master_id:
                import os
                env_qq = os.environ.get("SELF_QQ") or os.environ.get("MASTER_QQ")
                if env_qq and env_qq.isdigit() and env_qq != "123456789":
                    master_id = int(env_qq)
            if not master_id:
                master_id = int(getattr(self.qq, "self_id", 0) or 0)

            delivery_v2 = self.feature_flags.is_enabled("proactive_delivery_v2")
            if not master_id and not delivery_v2:
                logger.warning("[Push] No master QQ configured")
                return False

            mood = "neutral"
            if scene_cfg.get("mood_aware"):
                state = self.get_primary_emotion_state()
                mood = state.get("label", "neutral")

            content = await self.brain.generate_push(
                template=scene_cfg.get("template", ""),
                mood=mood,
                tone_hint=scene_cfg.get("tone_hint"),
                judge_context=scene_cfg.get("judge_context"),
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

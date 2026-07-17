"""Aerie · 云栖 v9.0 — Companion: orchestrator for all backend modules."""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
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
from core.context_builder import ContextBuilder
from core.database import Database
from core.emotion_engine import EmotionEngine
from core.emotion_state_store import EmotionStateStore
from core.emotion_threshold import get_threshold_engine
from core.pipeline import Pipeline
from core.push_scheduler import PushScheduler
from core.self_evolver import SelfEvolver
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

        # R0.3.7: load centralized behavior config (single source of truth).
        self.behavior_cfg = load_behavior_config()

        # Data layer
        self.db = Database()

        # Core engines
        # Phase 9 Batch 1: emotion state store persists PAD + thresholds
        # so the dashboard can show 24h/7d/30d history curves.
        self.state_store = EmotionStateStore(self.db)
        # R7.0: build the brain first so EmotionEngine can call back into
        # it for LLM-driven PAD inference. The keyword path is still
        # always available as a fallback when the LLM call fails.
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
        self.tool_registry = ToolRegistry(self.db)
        register_all_tools(self.tool_registry)

        # Phase 9 Batch 6: Self-evolution engine (capability-gap detector)
        self.self_evolver = SelfEvolver(
            db=self.db,
            tool_registry=self.tool_registry,
            brain=self.brain,
        )

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
        )

        # Push scheduler
        proactive_cfg = load_proactive_config()
        self.push_scheduler = PushScheduler(proactive_cfg)
        self.push_scheduler.set_dispatcher(self._dispatch_push)
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
        self.qq.set_message_handler(self._on_qq_message)
        # Connect to NapCat WS (passive — won't start NapCat)
        asyncio.create_task(self.qq.connect())
        # Start daily emotion decay scheduler
        self._daily_decay_task = asyncio.create_task(self._run_daily_decay())
        # R7.5: 10s background tick for emotion dashboard liveness.
        # Every 6th tick (≈60s) writes a snapshot so the history curve
        # stays alive even when no user messages arrive.
        self._emotion_tick_task = asyncio.create_task(self._emotion_tick_loop())
        # Start push scheduler
        self._push_task = asyncio.create_task(self.push_scheduler.start())
        # Block-4A R1.5: 8s boot delay then run brief once + emit show event
        self._boot_brief_task = asyncio.create_task(self._boot_brief())
        # R7.5+: 8s boot delay then push a QQ greeting to the user.
        # Idempotent: file flag at data/boot_greeting_sent_<date>.flag
        # blocks re-sends within the same calendar day.
        self._boot_qq_task = asyncio.create_task(self._boot_qq_greeting())
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
        self._started = True
        logger.info("Companion started")

    # ── R6.6: warm-up threshold engine from history ───────────────
    def _warmup_threshold_from_history(self) -> None:
        """Restore the 4 cumulative slot values from the latest non-zero snapshot.

        Without this, every backend restart would reset slot.value back to
        the initial_value (60/15/35/25) configured in persona_behavior.yaml,
        masking whatever real emotion state the user had built up. The fix:
        read the most recent emotion_state_snapshot row, and if any of the
        four slot values is non-zero, copy them into the live engine.
        """
        try:
            row = self.db.query_one(
                "SELECT patience_value, anxiety_value, desire_value, tenderness_value "
                "FROM emotion_state_snapshot "
                "ORDER BY id DESC LIMIT 1"
            )
            if not row:
                return
            slots = self.threshold_engine.slots
            updates = {
                "patience":   float(row.get("patience_value")   or 0.0),
                "anxiety":    float(row.get("anxiety_value")    or 0.0),
                "desire":     float(row.get("desire_value")     or 0.0),
                "tenderness": float(row.get("tenderness_value") or 0.0),
            }
            for name, val in updates.items():
                if name in slots and val > 0:
                    slots[name].value = val
            logger.info(
                "threshold warm-up restored: %s",
                {k: v for k, v in updates.items() if v > 0},
            )
        except Exception:
            # Warm-up is best-effort: a missing table is not fatal.
            logger.debug("threshold warm-up skipped (no history or table missing)")

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
                md = await Brain().compose_brief(sections)
            except Exception as e:
                logger.warning("boot_brief: compose_brief failed: %s", e)
                md = ""
            brief_fetcher.save_brief(today, sections, html=md)
            # Dispatch via push scheduler (uses custom_dispatcher=brief branch).
            try:
                await self.push_scheduler.trigger_scene("morning_brief_9am")
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
            # ── 步骤 2: 等 NapCat + 后端就绪 ──
            await asyncio.sleep(8)

            # ── 步骤 3: 再次检查 (防 8s 内另一进程已发) ──
            if flag_path.exists():
                try:
                    import time
                    elapsed = time.time() - flag_path.stat().st_mtime
                    if elapsed < 60.0:
                        logger.info(
                            "boot_qq_greeting: sent during sleep window, skip",
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
                    if pad_ticks >= 3:
                        pad_ticks = 0
                        self.emotion.idle_tick()
                    if thr_ticks >= 30:
                        thr_ticks = 0
                        self.emotion.threshold_engine.tick_decay(30.0)
                except Exception as e:
                    logger.debug("emotion tick error: %s", e)
                if snap_ticks >= 60:
                    snap_ticks = 0
                    try:
                        from core.emotion_state_store import EmotionStateStore
                        st = self.emotion.get_state(0)
                        EmotionStateStore(self.db).snapshot(
                            0,
                            {"label": st.get("label"), "pad": st.get("pad")},
                            st.get("thresholds", {}),
                            trigger_event="idle_tick",
                        )
                    except Exception as e:
                        logger.debug("emotion snapshot error: %s", e)
        except asyncio.CancelledError:
            return

    async def _dispatch_push(self, scene_name: str, scene_cfg: dict) -> bool:
        """Called by PushScheduler when a scene triggers.

        Generates push content via Brain and sends via QQ client.
        Returns True on success.

        R7.5+: forwards the ProactiveJudge's ``tone_hint`` and
        ``judge_context`` to ``Brain.generate_push`` so the LLM-side
        prompt picks up the per-scene tone (warm_with_light_flirt /
        collapse_seeking / ...) and the screen-aware rewriting rules
        rather than the legacy static mood. Falls back to
        ``scene_cfg.get("mood_aware")``-driven mood when no judge
        context is present.
        """
        try:
            master_id = int(self.settings.get("qq", {}).get("self_qq", 0))
            if not master_id:
                # R7.5+: fallback to SELF_QQ env (NapCat login user).
                import os
                env_qq = os.environ.get("SELF_QQ") or os.environ.get("MASTER_QQ")
                if env_qq and env_qq.isdigit() and env_qq != "123456789":
                    master_id = int(env_qq)
            if not master_id:
                # R7.5+: last resort — ask the QQ client what its own id is
                # (learned from OneBot11 self_id field on first inbound msg).
                sid = getattr(self.qq, "self_id", 0)
                if sid:
                    master_id = int(sid)
            if not master_id:
                logger.warning("[Push] No master QQ configured (settings.yaml qq.self_qq + SELF_QQ env + qq.self_id all empty)")
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

            # R7.5+: judge-driven tone (preferred) beats mood_aware mood.
            tone_hint = scene_cfg.get("tone_hint")
            judge_context = scene_cfg.get("judge_context")

            content = await self.brain.generate_push(
                template=template,
                mood=mood,
                tone_hint=tone_hint,
                judge_context=judge_context,
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

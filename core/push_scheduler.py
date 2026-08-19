"""Aerie · 云栖 v0.1.0-beta.1 — Cron-based proactive push scheduler.

Parses proactive.yaml, schedules 9 scenes via cron expressions,
and dispatches push messages through the Companion's QQ client.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
from datetime import datetime, time, date, timedelta
from pathlib import Path
from typing import Any

from core.paths import data_dir

logger = logging.getLogger(__name__)


class PushPolicy:
    """Enforce push frequency limits and quiet periods."""

    def __init__(self, config: dict) -> None:
        proactive = config.get("proactive", {})
        self.enabled = proactive.get("enabled", True)
        self.max_per_day = proactive.get("max_per_day", 5)
        self.min_interval_min = proactive.get("min_interval_min", 30)
        self.quiet_start_str = proactive.get("quiet_start", "23:30")
        self.quiet_end_str = proactive.get("quiet_end", "07:00")
        self.exempt_scenes = proactive.get("exempt_scenes", [
            "morning_brief", "goodnight", "anniversary",
        ])

        # v2 soft budget: max_per_day is a soft target (状态驱动可上可下),
        # hard_cap is the unconditional fuse. pending_plans carry hourly
        # PulsePlanner plans (rolling, each new hour replaces the previous).
        self.soft_budget = float(proactive.get("soft_budget", 0) or 0)
        self.hard_cap = int(proactive.get("hard_cap", 0) or 0)
        if self.hard_cap <= 0:
            self.hard_cap = max(int(self.max_per_day * 1.5), 20)
        self.pending_plans: list[dict[str, Any]] = []

        # Parse quiet period
        self.quiet_start = self._parse_time(self.quiet_start_str)
        self.quiet_end = self._parse_time(self.quiet_end_str)

        # State
        self.pause_until: datetime | None = None
        self.daily_count = 0
        self.last_push_at: datetime | None = None
        self.today = date.today()
        self.mute_until: datetime | None = None
        self.scene_blocks: dict[str, dict[str, Any]] = {}
        self.feedback: dict[str, dict[str, Any]] = {}
        self.scene_last_sent: dict[str, datetime] = {}
        self.state_path = self._resolve_state_path(proactive)
        self._load_state()

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if not value:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_state_path(proactive: dict) -> Path | None:
        raw = (
            proactive.get("state_path")
            or os.environ.get("AERIE_PROACTIVE_POLICY_STATE")
        )
        if not raw:
            return None
        path = Path(str(raw))
        if path.is_absolute():
            return path
        return data_dir() / path

    def _load_state(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("proactive policy state could not be loaded", exc_info=True)
            return
        if not isinstance(state, dict):
            return
        if "enabled" in state:
            self.enabled = bool(state.get("enabled"))
        self.daily_count = int(state.get("daily_count") or 0)
        self.today = self._parse_date(state.get("today")) or date.today()
        self.last_push_at = self._parse_datetime(state.get("last_push_at"))
        self.mute_until = self._parse_datetime(state.get("mute_until"))
        raw_blocks = state.get("scene_blocks") or {}
        if isinstance(raw_blocks, dict):
            for scene, block in raw_blocks.items():
                if not isinstance(block, dict):
                    continue
                until = self._parse_datetime(block.get("until"))
                if not until:
                    continue
                self.scene_blocks[str(scene)] = {
                    "until": until,
                    "reason": str(block.get("reason") or "postponed"),
                }
        raw_feedback = state.get("feedback") or {}
        if isinstance(raw_feedback, dict):
            self.feedback = {
                str(scene): dict(value)
                for scene, value in raw_feedback.items()
                if isinstance(value, dict)
            }
        raw_scene_last = state.get("scene_last_sent") or {}
        if isinstance(raw_scene_last, dict):
            for scene, ts in raw_scene_last.items():
                dt_val = self._parse_datetime(ts)
                if dt_val:
                    self.scene_last_sent[str(scene)] = dt_val

    def _state_payload(self) -> dict[str, Any]:
        def dt(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "enabled": bool(self.enabled),
            "daily_count": int(self.daily_count),
            "today": self.today.isoformat(),
            "last_push_at": dt(self.last_push_at),
            "mute_until": dt(self.mute_until),
            "scene_blocks": {
                scene: {
                    "until": dt(block.get("until")),
                    "reason": block.get("reason") or "postponed",
                }
                for scene, block in self.scene_blocks.items()
            },
            "feedback": self.feedback,
            "scene_last_sent": {
                scene: dt(ts) for scene, ts in self.scene_last_sent.items()
            },
        }

    def _persist(self) -> None:
        if not self.state_path:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_name(self.state_path.name + ".tmp")
            tmp.write_text(
                json.dumps(
                    self._state_payload(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            tmp.replace(self.state_path)
        except Exception:
            logger.warning("proactive policy state could not be saved", exc_info=True)

    def _expire_elapsed_blocks(self, now: datetime) -> None:
        changed = False
        if self.mute_until and now >= self.mute_until:
            self.mute_until = None
            changed = True
        for scene, block in list(self.scene_blocks.items()):
            until = block.get("until")
            if isinstance(until, datetime) and now >= until:
                self.scene_blocks.pop(scene, None)
                changed = True
        if changed:
            self._persist()

    def snapshot(self) -> dict[str, Any]:
        return self._state_payload()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        self.enabled = bool(enabled)
        self._persist()
        return self.snapshot()

    def mute(self, hours: float = 12.0) -> dict[str, Any]:
        self.mute_until = datetime.now() + timedelta(hours=float(hours))
        self._persist()
        return {
            "muted_until": self.mute_until.isoformat(),
        }

    def clear_mute(self) -> dict[str, Any]:
        self.mute_until = None
        self._persist()
        return self.snapshot()

    def postpone(self, scene: str, hours: float = 2.0) -> dict[str, Any]:
        return self._set_scene_block(scene, hours, "postponed")

    def _set_scene_block(
        self,
        scene: str,
        hours: float,
        reason: str,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        until = datetime.now() + timedelta(hours=float(hours))
        scene_id = str(scene)
        self.scene_blocks[scene_id] = {
            "until": until,
            "reason": reason,
        }
        if persist:
            self._persist()
        return {
            "scene": scene_id,
            "reason": reason,
            "until": until.isoformat(),
        }

    def record_feedback(
        self,
        scene: str,
        action: str,
        *,
        hours: float | None = None,
    ) -> dict[str, Any]:
        scene_id = str(scene)
        normalized = str(action or "").strip().lower()
        entry = self.feedback.setdefault(
            scene_id,
            {
                "positive": 0,
                "negative": 0,
                "last_action": "",
            },
        )
        if normalized in {"positive", "like", "ok"}:
            entry["positive"] = int(entry.get("positive") or 0) + 1
            entry["last_action"] = normalized
            block = self.scene_blocks.get(scene_id)
            if block and block.get("reason") == "feedback_cooldown":
                self.scene_blocks.pop(scene_id, None)
            self._persist()
            return {
                "scene": scene_id,
                "action": normalized,
                "positive_count": entry["positive"],
                "negative_count": int(entry.get("negative") or 0),
            }

        if normalized in {"mute", "muted"}:
            result = self.mute(hours or 12.0)
            result.update(
                {
                    "scene": scene_id,
                    "action": normalized,
                    "positive_count": int(entry.get("positive") or 0),
                    "negative_count": int(entry.get("negative") or 0),
                }
            )
            return result

        if normalized in {"postpone", "later"}:
            result = self.postpone(scene_id, hours or 2.0)
            result.update(
                {
                    "action": normalized,
                    "positive_count": int(entry.get("positive") or 0),
                    "negative_count": int(entry.get("negative") or 0),
                }
            )
            return result

        # Default unknown/non-positive feedback to a scene-level cooldown.
        entry["negative"] = int(entry.get("negative") or 0) + 1
        entry["last_action"] = normalized or "negative"
        cooldown_hours = float(hours) if hours is not None else min(
            24.0,
            max(1.0, 2.0 ** max(0, entry["negative"] - 1)),
        )
        result = self._set_scene_block(
            scene_id,
            cooldown_hours,
            "feedback_cooldown",
            persist=False,
        )
        self._persist()
        result.update(
            {
                "action": normalized or "negative",
                "positive_count": int(entry.get("positive") or 0),
                "negative_count": entry["negative"],
            }
        )
        return result

    @staticmethod
    def _parse_time(s: str) -> time:
        parts = s.strip().split(":")
        return time(int(parts[0]), int(parts[1]))

    def can_push(self, scene: str) -> tuple[bool, str]:
        """Check if a push is allowed. Returns (allowed, reason)."""
        now_dt = datetime.now()
        self._expire_elapsed_blocks(now_dt)
        if not self.enabled:
            return False, "globally_disabled"
        if self.mute_until and now_dt < self.mute_until:
            return False, "muted"
        block = self.scene_blocks.get(scene)
        if block:
            until = block.get("until")
            if isinstance(until, datetime) and now_dt < until:
                return False, str(block.get("reason") or "postponed")
        if self.pause_until and now_dt < self.pause_until:
            return False, "paused"
        today = date.today()
        if today != self.today:
            self.daily_count = 0
            self.today = today
            self.scene_last_sent.clear()
            self._persist()
        if self.hard_cap > 0 and self.daily_count >= self.hard_cap:
            return False, "hard_cap"
        soft_target = self.soft_budget_target()
        if soft_target > 0 and self.daily_count >= soft_target:
            # v2: soft budget is advisory only — hard_cap is the real fuse.
            return True, "soft_budget_over"
        now_time = now_dt.time()
        in_quiet = False
        if self.quiet_start <= self.quiet_end:
            in_quiet = self.quiet_start <= now_time <= self.quiet_end
        else:
            # overnight range: e.g. 23:30 - 07:00
            in_quiet = now_time >= self.quiet_start or now_time <= self.quiet_end
        if in_quiet and scene not in self.exempt_scenes:
            return False, "quiet_period"
        if self.last_push_at and scene not in self.exempt_scenes:
            elapsed = (now_dt - self.last_push_at).total_seconds() / 60
            if elapsed < self.min_interval_min:
                return False, "interval"
        # Per-scene minimum interval: 60 min default for non-exempt scenes
        scene_min_interval = self.min_interval_min * 2 if scene not in self.exempt_scenes else 0
        last_scene = self.scene_last_sent.get(scene)
        if last_scene and scene not in self.exempt_scenes:
            elapsed_scene = (now_dt - last_scene).total_seconds() / 60
            if elapsed_scene < scene_min_interval:
                return False, f"scene_interval:{scene}"
        return True, "ok"

    def soft_budget_target(self) -> float:
        """今日软预算目标（0 表示未启用软预算）。"""
        if self.soft_budget > 0:
            return self.soft_budget
        return float(self.max_per_day or 0)

    def set_pending_plans(self, plans: list[dict]) -> None:
        """整点重算后覆盖 pending 计划（滚动覆盖，不带旧计划）。"""
        self.pending_plans = [p for p in plans if isinstance(p, dict) and p.get("at")]

    def pop_due_plans(self, now: datetime | None = None) -> list[dict]:
        """取出已到期的 pending 计划并清空对应项。"""
        now = now or datetime.now()
        due: list[dict] = []
        kept: list[dict] = []
        for p in self.pending_plans:
            try:
                at = p["at"]
                at_dt = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
            except (KeyError, TypeError, ValueError):
                continue
            if at_dt <= now:
                due.append(p)
            else:
                kept.append(p)
        self.pending_plans = kept
        return due

    def record(self, scene: str) -> None:
        now = datetime.now()
        self.daily_count += 1
        self.last_push_at = now
        self.scene_last_sent[scene] = now
        self._persist()


class CronScheduler:
    """Parse and schedule cron-based push scenes from proactive.yaml."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.scenes: dict[str, dict] = config.get("scenes", {})
        self.policy = PushPolicy(config)
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._dispatcher = None  # type: callable | None
        # v2: hourly rolling planner + routine anchor shifting (optional)
        self.pulse_planner: Any = None      # PulsePlanner
        self.pulse_state_provider: Any = None  # callable() -> snapshot dict
        self.routine_learner: Any = None  # RoutineLearner
        # R7.5+: optional ProactiveJudge. If bound, _dispatch will consult
        # it before calling the user dispatcher; otherwise falls back to
        # the historical cron-only path.
        self.judge: Any = None
        # Optional: last Decision snapshot for observability (e2e + tests).
        self.last_decision: Any = None
        # R9.0+: soft gate — pause all pushes when QQ is offline
        self._paused = False
        self._paused_reason = ""
        self._resume_event = asyncio.Event()

    def pause(self, reason: str = "manual") -> None:
        """Pause all cron and trigger scenes.

        Running sleeps will wake up on the next iteration and re-check.
        Idempotent — calling pause() when already paused just updates
        the reason.
        """
        self._paused = True
        self._paused_reason = reason
        logger.info("[PushScheduler] Paused: %s", reason)

    def resume(self) -> None:
        """Resume all scenes. Idempotent."""
        if self._paused:
            self._paused = False
            self._paused_reason = ""
            self._resume_event.set()
            self._resume_event.clear()
            logger.info("[PushScheduler] Resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def paused_reason(self) -> str:
        return self._paused_reason

    def set_dispatcher(self, dispatcher) -> None:
        """Set the async dispatcher: dispatcher(scene_name, scene_config)."""
        self._dispatcher = dispatcher

    def set_pulse_planner(self, planner: Any, state_provider: Any = None) -> None:
        """Bind the hourly PulsePlanner + optional snapshot provider."""
        self.pulse_planner = planner
        self.pulse_state_provider = state_provider

    def set_routine_learner(self, learner: Any) -> None:
        """Bind RoutineLearner for cron anchor shifting (wake/sleep)."""
        self.routine_learner = learner

    async def start(self) -> None:
        self._running = True
        for scene_name, scene_cfg in self.scenes.items():
            cron_expr = scene_cfg.get("cron")
            trigger = scene_cfg.get("trigger")

            if cron_expr:
                task = asyncio.create_task(
                    self._run_cron_scene(scene_name, scene_cfg, cron_expr),
                    name=f"push-{scene_name}",
                )
                self._tasks.append(task)
                logger.info(
                    "[PushScheduler] Registered cron scene: %s (cron=%s)",
                    scene_name, cron_expr,
                )
            elif trigger:
                logger.info(
                    "[PushScheduler] Registered trigger scene: %s (trigger=%s)",
                    scene_name, trigger,
                )

        # v2: hourly rolling planner (整点自检) + pending-pulse processor.
        if self.pulse_planner is not None:
            task = asyncio.create_task(
                self._run_hourly_planner(), name="push-pulse-hourly",
            )
            self._tasks.append(task)
        task = asyncio.create_task(
            self._run_pending_processor(), name="push-pending",
        )
        self._tasks.append(task)

        logger.info("[PushScheduler] Started with %d scenes", len(self._tasks))

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def _anchor_next_time(self, scene_name: str, scene_cfg: dict, now: datetime | None = None) -> datetime | None:
        """作息锚点搬移：wake/sleep 场景跟随 RoutineLearner 作息窗口。

        scene_cfg.get("anchor") in ("wake", "sleep") 且作息有效时，
        返回下一个锚点时点；否则 None（走原 cron）。
        """
        anchor = scene_cfg.get("anchor")
        if not anchor or self.routine_learner is None:
            return None
        try:
            window = self.routine_learner.window()
        except Exception:
            logger.debug("[PushScheduler] learner window unavailable", exc_info=True)
            return None
        base = None
        if anchor == "wake" and window.wake_time:
            base = window.wake_time
        elif anchor == "sleep" and window.sleep_time:
            base = window.sleep_time
        if base is None:
            return None
        now = now or datetime.now()
        cand = datetime.combine(now.date(), base)
        if anchor == "sleep":
            use = cand - timedelta(minutes=45)
        else:
            use = cand + timedelta(minutes=15)
        if use <= now:
            use += timedelta(days=1)
        return use

    async def _run_hourly_planner(self) -> None:
        """整点滚动自检：推算下一小时计划并滚动覆盖 pending_plans。"""
        while self._running:
            try:
                now = datetime.now()
                wait = 3600 - (now.minute * 60 + now.second + now.microsecond / 1e6)
                await asyncio.sleep(wait + 1)
                if not self._running or self._paused:
                    continue
                if self.pulse_planner is None:
                    continue
                state: dict = {}
                if self.pulse_state_provider:
                    try:
                        state = self.pulse_state_provider()
                    except Exception:
                        logger.exception("[PushScheduler] pulse state provider failed")
                        continue
                plans = self.pulse_planner.plan_next_hour(state)
                self.policy.set_pending_plans([p.to_dict() for p in plans])
                logger.info("[PushScheduler] hourly plan filled: %d", len(plans))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("[PushScheduler] hourly planner error")
                await asyncio.sleep(60)

    async def _run_pending_processor(self) -> None:
        """每分钟检查 pending 计划，到点的经 policy 校验后触发。"""
        while self._running:
            try:
                due = self.policy.pop_due_plans()
                for plan in due:
                    scene = str(plan.get("scene") or "idle_care")
                    scene_cfg = dict(self.scenes.get(scene) or {})
                    payload = plan.get("payload") or {}
                    scene_cfg.update(payload if isinstance(payload, dict) else {})
                    force = bool(scene_cfg.get("force"))
                    if not force:
                        ok, reason = self.policy.can_push(scene)
                        if not ok:
                            logger.info("[PushScheduler] pending %s skipped: %s", scene, reason)
                            continue
                    if self._dispatcher:
                        logger.info("[PushScheduler] dispatching pending plan scene=%s", scene)
                        await self._dispatcher(scene, scene_cfg)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("[PushScheduler] pending processor error")
            await asyncio.sleep(60)

    async def _run_cron_scene(
        self, scene_name: str, scene_cfg: dict, cron_expr: str,
    ) -> None:
        """Continuously schedule and dispatch a cron-based scene.

        Uses a simple self-rolled cron parser instead of depending on croniter.
        Supports: minute hour day_of_month month day_of_week
        """
        while self._running:
            try:
                # R9.0+: soft gate — if paused, wait for resume
                if self._paused:
                    await self._resume_event.wait()
                    if not self._running:
                        return
                    continue

                anchored = self._anchor_next_time(scene_name, scene_cfg)
                next_time = anchored or self._next_cron_time(cron_expr)
                wait_seconds = (next_time - datetime.now()).total_seconds()
                if wait_seconds < 0:
                    wait_seconds = 60  # already past, retry in 1 min
                if wait_seconds > 86400:
                    wait_seconds = 86400  # cap at 1 day max sleep

                # Sleep in small chunks so pause can take effect quickly
                slept = 0.0
                while slept < wait_seconds:
                    if self._paused or not self._running:
                        break
                    chunk = min(5.0, wait_seconds - slept)
                    await asyncio.sleep(chunk)
                    slept += chunk

                if not self._running:
                    return
                if self._paused:
                    continue

                await self._dispatch(scene_name, scene_cfg)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("[PushScheduler] Error in cron scene %s", scene_name)
                await asyncio.sleep(60)

    async def trigger_scene(self, scene_name: str) -> bool:
        """Force-trigger a trigger-type scene (idle_care, emotion_comfort)."""
        scene_cfg = self.scenes.get(scene_name)
        if not scene_cfg:
            return False
        return await self._dispatch(scene_name, scene_cfg)

    async def _dispatch(self, scene_name: str, scene_cfg: dict) -> bool:
        """Check policy and dispatch the push message.

        R7.5+: when ``self.judge`` is bound, evaluate the scene with the
        ProactiveJudge first. The Decision's tone + context_snapshot are
        forwarded to the dispatcher as ``tone_hint`` / ``judge_context``
        keys, so the LLM-side push generator can adapt wording. If the
        Decision carries a ``suppress_reason``, the push is silently
        skipped and ``last_decision`` is recorded for observability.

        Block-4A R1.5: support ``custom_dispatcher`` to bypass the default
        scene-based template path. Currently supported values:
          - "brief":     run brief_fetcher + compose_brief, then emit
                         "brief:show" event so the Electron renderer pops
                         the iframe. Does NOT push a QQ text message.
        R8.0+: ``scene_cfg.get("force")`` (default False) makes the scene
          bypass ProactiveJudge, PushPolicy.can_push, and daily_count
          tracking. Intended for "boot greeting" / "first message" use
          cases where the user explicitly wants unconditional send on
          every launch (not timer-driven, not policy-gated).
        """
        # R9.0+: soft gate — if paused, skip all dispatches
        # (force=True scenes also respect pause, since pause is for
        #  connectivity issues, not policy control)
        if self._paused:
            logger.debug(
                "[PushScheduler] Skipped %s: scheduler paused (%s)",
                scene_name, self._paused_reason,
            )
            return False

        force = bool(scene_cfg.get("force"))

        # ── R7.5+: Proactive judge gate ──
        decision = None
        if self.judge is not None and not force:
            try:
                decision = self.judge.evaluate(
                    scene_name,
                    context_override=scene_cfg.get("judge_override"),
                )
                self.last_decision = decision
                if decision.suppress_reason:
                    logger.debug(
                        "[PushScheduler] Judge suppressed %s: %s (score=%s)",
                        scene_name, decision.suppress_reason, decision.score,
                    )
                    return False
            except Exception:
                logger.exception(
                    "[PushScheduler] ProactiveJudge failed; falling through"
                )

        can_push, reason = self.policy.can_push(scene_name)
        if not can_push and not force:
            logger.debug(
                "[PushScheduler] Skipped %s: %s", scene_name, reason,
            )
            return False

        # Block-4A R1.5: custom_dispatcher branch
        cd = scene_cfg.get("custom_dispatcher")
        if cd == "brief":
            return await self._dispatch_brief(scene_name, scene_cfg)
        if cd == "desire_care":
            return await self._dispatch_desire_text(
                scene_name, scene_cfg, kind="care", decision=decision,
            )
        if cd == "desire_voice":
            return await self._dispatch_desire_text(
                scene_name, scene_cfg, kind="voice", decision=decision,
            )
        if cd == "boot_greeting":
            # R7.5+: 应用启动后主动 QQ 推送
            return await self._dispatch_desire_text(
                scene_name, scene_cfg, kind="care", decision=decision,
            )

        if not self._dispatcher:
            logger.warning("[PushScheduler] No dispatcher set for %s", scene_name)
            return False

        # Forward judge context to the dispatcher so generate_push can
        # pick up the tone (warm_with_light_flirt / collapse_seeking / ...).
        forward_cfg = dict(scene_cfg)
        if decision is not None:
            forward_cfg["tone_hint"] = decision.tone
            forward_cfg["judge_context"] = decision.context_snapshot

        try:
            success = await self._dispatcher(scene_name, forward_cfg)
            if success:
                self.policy.record(scene_name)
                logger.info(
                    "[PushScheduler] Sent: %s (tone=%s score=%s)",
                    scene_name, decision.tone if decision else "?",
                    decision.score if decision else "?",
                )
                return True
        except Exception:
            logger.exception("[PushScheduler] Dispatch error: %s", scene_name)
        return False

    async def _dispatch_brief(self, scene_name: str, scene_cfg: dict) -> bool:
        """Block-4A R1.5: brief dispatcher.

        Re-uses today's brief JSON (already generated by boot hook or 9am
        cron), emits a ``brief:show`` SSE event, and pushes a single short
        QQ teaser. Idempotent: if today's brief doesn't exist yet, fetch
        synchronously.
        """
        try:
            from core import brief_fetcher
            from core.llm_caller import LLMCaller
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            cached = brief_fetcher.load_brief(today)
            if not cached:
                sections = await brief_fetcher.run_all()
                md = await LLMCaller().compose_brief(sections)
                brief_fetcher.save_brief(today, sections, html=md)
            # Emit the brief:show event so renderer can pop iframe.
            try:
                from core.chat_events import emit
                emit("brief:show", date=today, ts=int(datetime.now().timestamp()))
            except Exception:
                logger.debug("emit brief:show failed")
            self.policy.record(scene_name)
            logger.info("[PushScheduler] brief dispatched: %s", today)
            return True
        except Exception:
            logger.exception("_dispatch_brief failed")
            return False

    async def _dispatch_desire_text(
        self,
        scene_name: str,
        scene_cfg: dict,
        kind: str,
        decision: Any | None = None,
    ) -> bool:
        """Block-4B R2.2: route desire-engine triggers to short text push.

        Uses LLMCaller.generate_push for tone; if dispatcher (QQ client) is
        available, sends a single short message. Records on policy so the
        daily cap is honored.

        R7.5+: when a ProactiveJudge Decision is provided, its
        ``tone_hint`` is forwarded to the dispatcher so generate_push
        picks up the per-scene tone (longing / collapse / ...).

        R8.1+: reads ``force`` from scene_cfg locally — the force flag
        in ``_dispatch`` is a local var and does not propagate. force=True
        bypasses ``policy.record`` so boot greetings don't pollute
        daily_count / cooldown.
        """
        force = bool(scene_cfg.get("force", False))
        try:
            template = scene_cfg.get("template", "")
            if kind == "voice":
                template = template or "想听你声音。"
            else:
                template = template or "在干嘛。"
            if not self._dispatcher:
                logger.warning("[PushScheduler] desire dispatcher missing")
                return False
            forward = {**scene_cfg, "template": template}
            if decision is not None:
                forward["tone_hint"] = decision.tone
                forward["judge_context"] = decision.context_snapshot
            ok = await self._dispatcher(scene_name, forward)
            if ok and not force:
                # R8.0+: only record on policy for non-forced dispatches,
                # so boot greetings don't pollute the daily_count / cooldown
                # that gates timer-driven scenes.
                self.policy.record(scene_name)
            return ok
        except Exception:
            logger.exception("_dispatch_desire_text failed")
            return False

    @staticmethod
    def _next_cron_time(cron_expr: str) -> datetime:
        """Compute the next datetime matching a cron expression.

        Supported fields: minute hour day month weekday.
        Wildcards (*) and lists (e.g. 30 6,7 * * *) are supported.
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")

        def parse_field(field: str, default_range: tuple[int, int]) -> list[int]:
            if field == "*":
                mn, mx = default_range
                return list(range(mn, mx + 1))
            values = []
            for item in field.split(","):
                if "-" in item:
                    lo, hi = item.split("-")
                    values.extend(range(int(lo), int(hi) + 1))
                else:
                    values.append(int(item))
            return sorted(values)

        minutes = parse_field(parts[0], (0, 59))
        hours = parse_field(parts[1], (0, 23))
        days = parse_field(parts[2], (1, 31))
        months = parse_field(parts[3], (1, 12))
        weekdays = parse_field(parts[4], (0, 6))

        now = datetime.now().replace(second=0, microsecond=0)
        # Try same day, next minute through hour
        for attempt in range(525600):  # max 1 year of minutes
            candidate = now + timedelta(minutes=attempt + 1)
            if candidate.minute not in minutes:
                continue
            if candidate.hour not in hours:
                continue
            if candidate.day not in days:
                continue
            if candidate.month not in months:
                continue
            if weekdays != list(range(0, 7)):
                if candidate.weekday() not in weekdays:
                    continue
            return candidate

        # Fallback: tomorrow at first matching minute
        return now + timedelta(days=1)


class PushScheduler:
    """High-level scheduler: holds CronScheduler + manages dispatch to QQ."""

    def __init__(self, config: dict) -> None:
        self.cron = CronScheduler(config)

    def set_dispatcher(self, dispatcher) -> None:
        self.cron.set_dispatcher(dispatcher)

    def set_pulse_planner(self, planner: Any, state_provider: Any = None) -> None:
        """v2: 透传整点 PulsePlanner 绑定到底层 CronScheduler。"""
        self._pulse_planner = planner
        self._pulse_state_provider = state_provider
        self.cron.set_pulse_planner(planner, state_provider)

    def set_routine_learner(self, learner: Any) -> None:
        """v2: 透传作息学习器绑定到底层 CronScheduler。"""
        self._routine_learner = learner
        self.cron.set_routine_learner(learner)

    def pause(self, reason: str = "manual") -> None:
        """Pause all push scenes (cron + trigger)."""
        self.cron.pause(reason)

    def resume(self) -> None:
        """Resume all push scenes."""
        self.cron.resume()

    @property
    def running(self) -> bool:
        return self.cron._running

    @property
    def scenes(self) -> dict[str, dict]:
        return self.cron.scenes

    @property
    def policy(self) -> PushPolicy:
        return self.cron.policy

    @property
    def is_paused(self) -> bool:
        return self.cron.is_paused

    @property
    def paused_reason(self) -> str:
        return self.cron.paused_reason

    async def start(self) -> None:
        await self.cron.start()

    async def stop(self) -> None:
        await self.cron.stop()

    async def trigger(self, scene_name: str) -> bool:
        return await self.cron.trigger_scene(scene_name)

    async def reload_config(self, new_config: dict) -> None:
        """Hot-reload proactive config: restart cron tasks with new settings.

        Stops all running cron tasks, updates config + scenes + policy,
        then restarts the scheduler. The dispatcher and judge bindings
        are preserved.
        """
        logger.info("[PushScheduler] reloading config...")
        was_running = self.cron._running
        if was_running:
            await self.cron.stop()
        self.cron.config = new_config
        self.cron.scenes = new_config.get("scenes", {})
        self.cron.policy = PushPolicy(new_config)
        if was_running:
            await self.cron.start()
        logger.info(
            "[PushScheduler] config reloaded: %d scenes",
            len(self.cron.scenes),
        )

    async def _dispatch(self, scene_name: str, scene_cfg: dict) -> bool:
        """R7.5+: 透传 CronScheduler._dispatch,用于启动 hook 等
        不经 cron / trigger 路径的 scene 触发。
        """
        return await self.cron._dispatch(scene_name, scene_cfg)

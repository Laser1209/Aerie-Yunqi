"""Aerie · 云栖 v0.1.0-beta.1 — Cron-based proactive push scheduler.

Parses proactive.yaml, schedules 9 scenes via cron expressions,
and dispatches push messages through the Companion's QQ client.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, time, date, timedelta
from typing import Any

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

        # Parse quiet period
        self.quiet_start = self._parse_time(self.quiet_start_str)
        self.quiet_end = self._parse_time(self.quiet_end_str)

        # State
        self.pause_until: datetime | None = None
        self.daily_count = 0
        self.last_push_at: datetime | None = None
        self.today = date.today()

    @staticmethod
    def _parse_time(s: str) -> time:
        parts = s.strip().split(":")
        return time(int(parts[0]), int(parts[1]))

    def can_push(self, scene: str) -> tuple[bool, str]:
        """Check if a push is allowed. Returns (allowed, reason)."""
        if not self.enabled:
            return False, "globally_disabled"
        if self.pause_until and datetime.now() < self.pause_until:
            return False, "paused"
        today = date.today()
        if today != self.today:
            self.daily_count = 0
            self.today = today
        if self.daily_count >= self.max_per_day:
            return False, "daily_limit"
        now = datetime.now().time()
        in_quiet = False
        if self.quiet_start <= self.quiet_end:
            in_quiet = self.quiet_start <= now <= self.quiet_end
        else:
            # overnight range: e.g. 23:30 - 07:00
            in_quiet = now >= self.quiet_start or now <= self.quiet_end
        if in_quiet and scene not in self.exempt_scenes:
            return False, "quiet_period"
        if self.last_push_at and scene not in self.exempt_scenes:
            elapsed = (datetime.now() - self.last_push_at).total_seconds() / 60
            if elapsed < self.min_interval_min:
                return False, "interval"
        return True, "ok"

    def record(self, scene: str) -> None:
        self.daily_count += 1
        self.last_push_at = datetime.now()


class CronScheduler:
    """Parse and schedule cron-based push scenes from proactive.yaml."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.scenes: dict[str, dict] = config.get("scenes", {})
        self.policy = PushPolicy(config)
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._dispatcher = None  # type: callable | None
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

        logger.info("[PushScheduler] Started with %d scenes", len(self._tasks))

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

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

                next_time = self._next_cron_time(cron_expr)
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
            from core.brain import Brain
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            cached = brief_fetcher.load_brief(today)
            if not cached:
                sections = await brief_fetcher.run_all()
                md = await Brain().compose_brief(sections)
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

        Uses Brain.generate_push for tone; if dispatcher (QQ client) is
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

    def pause(self, reason: str = "manual") -> None:
        """Pause all push scenes (cron + trigger)."""
        self.cron.pause(reason)

    def resume(self) -> None:
        """Resume all push scenes."""
        self.cron.resume()

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

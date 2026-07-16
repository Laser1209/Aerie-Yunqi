"""Aerie · 云栖 v9.0 — Cron-based proactive push scheduler.

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
                next_time = self._next_cron_time(cron_expr)
                wait_seconds = (next_time - datetime.now()).total_seconds()
                if wait_seconds < 0:
                    wait_seconds = 60  # already past, retry in 1 min
                if wait_seconds > 86400:
                    wait_seconds = 86400  # cap at 1 day max sleep
                await asyncio.sleep(wait_seconds)

                if not self._running:
                    return

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
        """Check policy and dispatch the push message."""
        can_push, reason = self.policy.can_push(scene_name)
        if not can_push:
            logger.debug(
                "[PushScheduler] Skipped %s: %s", scene_name, reason,
            )
            return False

        if not self._dispatcher:
            logger.warning("[PushScheduler] No dispatcher set for %s", scene_name)
            return False

        try:
            success = await self._dispatcher(scene_name, scene_cfg)
            if success:
                self.policy.record(scene_name)
                logger.info("[PushScheduler] Sent: %s", scene_name)
                return True
        except Exception:
            logger.exception("[PushScheduler] Dispatch error: %s", scene_name)
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

    async def start(self) -> None:
        await self.cron.start()

    async def stop(self) -> None:
        await self.cron.stop()

    async def trigger(self, scene_name: str) -> bool:
        return await self.cron.trigger_scene(scene_name)

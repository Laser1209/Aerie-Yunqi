"""Aerie · 云栖 v9.0 — APScheduler-based cron scheduler for proactive push.

Reads scene definitions from config/proactive.yaml and registers
a Cron job for each scene that defines a `cron` field.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.persona_loader import load_proactive
from proactive.messenger import ProactiveMessenger


logger = logging.getLogger(__name__)


class CronScheduler:
    """Schedule and dispatch proactive scenes via APScheduler."""

    def __init__(
        self,
        messenger: ProactiveMessenger,
        master_id: int,
        config: Optional[dict] = None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self.messenger = messenger
        self.master_id = int(master_id)
        self.config = config or load_proactive()
        self.timezone = timezone
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._started = False

    def _wrap_async(self, scene_id: str, template: str, mood_aware: bool):
        """Return a sync callable that schedules the async push."""
        def _trigger():
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            if loop.is_running():
                asyncio.create_task(
                    self.messenger.push(scene_id, self.master_id, template)
                )
            else:
                loop.run_until_complete(
                    self.messenger.push(scene_id, self.master_id, template)
                )
        return _trigger

    def start(self) -> None:
        if self._started:
            return
        scenes = self.config.get("scenes", {})
        for scene_id, scene_cfg in scenes.items():
            cron_expr = scene_cfg.get("cron")
            template = scene_cfg.get("template", "")
            if not cron_expr or not template:
                continue
            try:
                self.scheduler.add_job(
                    self._wrap_async(scene_id, template, scene_cfg.get("mood_aware", False)),
                    CronTrigger.from_crontab(cron_expr, timezone=self.timezone),
                    id=scene_id,
                    replace_existing=True,
                )
                logger.info("scheduled scene %s with cron %s", scene_id, cron_expr)
            except Exception as e:
                logger.error("failed to schedule %s: %s", scene_id, e)
        # Daily decay at 04:00
        try:
            from core.emotion_threshold import CumulativeEmotionEngine
            cum_engine = getattr(self.messenger, "cum_engine", None)
            if cum_engine is not None:
                self.scheduler.add_job(
                    lambda: cum_engine.daily_decay(self.master_id),
                    CronTrigger.from_crontab("0 4 * * *", timezone=self.timezone),
                    id="daily_decay",
                    replace_existing=True,
                )
        except Exception:
            pass
        self.scheduler.start()
        self._started = True

    def shutdown(self, wait: bool = False) -> None:
        if self._started:
            self.scheduler.shutdown(wait=wait)
            self._started = False

    def list_jobs(self) -> list[dict]:
        jobs: list[dict] = []
        for j in self.scheduler.get_jobs():
            jobs.append({
                "id": j.id,
                "next_run": str(j.next_run_time) if j.next_run_time else None,
                "trigger": str(j.trigger),
            })
        return jobs

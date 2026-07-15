"""定时任务调度器

APScheduler 驱动的自动化服务：
- 每日早 8:00 简报推送
- 晚间 23:00 晚安问候
- 每小时天气更新
- 主动关怀检查
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger


class TaskScheduler:
    """APScheduler 定时任务管理"""

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._on_brief: Optional[Callable[[], Awaitable[None]]] = None
        self._on_goodnight: Optional[Callable[[int], Awaitable[None]]] = None
        self._on_weather: Optional[Callable[[], Awaitable[None]]] = None
        self._running = False

    def set_callbacks(
        self,
        on_brief: Optional[Callable[[], Awaitable[None]]] = None,
        on_goodnight: Optional[Callable[[int], Awaitable[None]]] = None,
        on_weather: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        self._on_brief = on_brief
        self._on_goodnight = on_goodnight
        self._on_weather = on_weather

    async def start(self):
        self._running = True
        self._register_jobs()
        self._scheduler.start()
        logger.info("定时任务调度器已启动")

    def _register_jobs(self):
        # 每日早 8:00 — 简报推送
        if self._on_brief:
            self._scheduler.add_job(
                self._wrap(self._on_brief),
                CronTrigger(hour=8, minute=0),
                id="daily_brief",
                name="每日简报",
                replace_existing=True,
            )
            logger.info("已注册: 每日简报 (08:00)")

        # 每晚 23:00 — 晚安问候
        if self._on_goodnight:
            self._scheduler.add_job(
                self._wrap_goodnight(),
                CronTrigger(hour=23, minute=0),
                id="goodnight",
                name="晚安问候",
                replace_existing=True,
            )
            logger.info("已注册: 晚安问候 (23:00)")

        # 每小时 — 天气更新
        if self._on_weather:
            self._scheduler.add_job(
                self._wrap(self._on_weather),
                CronTrigger(minute=0),
                id="hourly_weather",
                name="天气更新",
                replace_existing=True,
            )
            logger.info("已注册: 每小时天气更新")

    def _wrap(self, coro_func):
        """包装异步回调"""
        async def wrapper():
            try:
                await coro_func()
            except Exception as e:
                logger.exception(f"定时任务执行异常: {e}")
        return wrapper

    def _wrap_goodnight(self):
        """晚安问候包装（需要 user_id）"""
        async def wrapper():
            try:
                await self._on_goodnight(0)  # user_id=0 代表主人
            except Exception as e:
                logger.exception(f"晚安问候异常: {e}")
        return wrapper

    def add_one_shot(
        self,
        coro_func,
        seconds: float,
        job_id: str = "",
    ):
        """添加一次性延迟任务"""
        async def wrapper():
            try:
                await coro_func()
            except Exception as e:
                logger.exception(f"一次性任务异常: {e}")

        self._scheduler.add_job(
            wrapper,
            "interval",
            seconds=seconds,
            id=job_id or f"oneshot_{datetime.now().timestamp()}",
            max_instances=1,
            coalesce=True,
        )
        logger.debug(f"已注册一次性任务: {seconds}s 后执行")

    def remove_job(self, job_id: str):
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

    @property
    def jobs(self) -> List[Dict[str, Any]]:
        result = []
        for job in self._scheduler.get_jobs():
            result.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            })
        return result

    async def stop(self):
        self._running = False
        self._scheduler.shutdown(wait=False)
        logger.info("定时任务调度器已停止")

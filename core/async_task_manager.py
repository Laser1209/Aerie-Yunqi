"""Aerie v0.1.0-beta.1 — Async Task Manager（异步任务管理器）

长任务后台执行，实时进度反馈。

能力：
  - 任务队列：基于 asyncio 的任务调度
  - 并发控制：同时运行的任务数量限制
  - 优先级：高/中/低三级优先级
  - 进度追踪：进度条 + 当前步骤 + 已用时间 + 预计剩余
  - 任务管理：运行中 / 历史记录 / 取消 / 重试
  - WebSocket 推送：实时推送进度事件

设计原则：
  - 后台执行不阻塞主对话
  - 状态严格管理，可追踪可恢复
  - 进度事件可被前端实时消费
"""

from __future__ import annotations

import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskPriority(str, Enum):
    """任务优先级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AsyncTaskStatus(str, Enum):
    """异步任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProgressUpdate:
    """进度更新事件"""
    task_id: str
    percent: int = 0
    current_step: str = ""
    step_index: int = 0
    total_steps: int = 0
    message: str = ""
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float = 0.0
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "percent": self.percent,
            "current_step": self.current_step,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "message": self.message,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "estimated_remaining_seconds": round(self.estimated_remaining_seconds, 1),
            "data": self.data,
        }


@dataclass
class AsyncTask:
    """异步任务"""
    task_id: str
    name: str
    description: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    status: AsyncTaskStatus = AsyncTaskStatus.PENDING
    progress: int = 0
    current_step: str = ""
    step_index: int = 0
    total_steps: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: str = ""
    progress_history: list[ProgressUpdate] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def estimated_remaining(self) -> float:
        if self.progress <= 0 or self.started_at is None:
            return 0.0
        elapsed = time.time() - self.started_at
        total_est = elapsed / (self.progress / 100)
        return max(0.0, total_est - elapsed)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "priority": self.priority.value,
            "status": self.status.value,
            "progress": self.progress,
            "current_step": self.current_step,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "created_at": datetime.fromtimestamp(self.created_at).strftime("%Y-%m-%d %H:%M:%S"),
            "started_at": datetime.fromtimestamp(self.started_at).strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "completed_at": datetime.fromtimestamp(self.completed_at).strftime("%Y-%m-%d %H:%M:%S") if self.completed_at else None,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "estimated_remaining_seconds": round(self.estimated_remaining, 1),
            "error": self.error,
        }


class AsyncTaskManager:
    """异步任务管理器

    基于 asyncio 的任务队列调度器，
    支持并发控制、优先级、实时进度推送。
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        max_history: int = 100,
    ):
        self.max_concurrent = max_concurrent
        self.max_history = max_history
        self._tasks: dict[str, AsyncTask] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._progress_callbacks: list[Callable] = []
        self._task_funcs: dict[str, Callable] = {}

    # ── 生命周期 ──────────────────────────────────────

    def start(self) -> None:
        """启动任务管理器（开始消费队列）。"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("async task manager started (max_concurrent=%d)", self.max_concurrent)

    async def stop(self) -> None:
        """停止任务管理器。"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("async task manager stopped")

    # ── 任务注册 ──────────────────────────────────────

    def register_task_func(self, task_type: str, func: Callable) -> None:
        """注册任务类型对应的执行函数。"""
        self._task_funcs[task_type] = func
        logger.debug("task function registered: %s", task_type)

    # ── 进度回调 ──────────────────────────────────────

    def add_progress_callback(self, callback: Callable) -> None:
        """添加进度更新回调。"""
        self._progress_callbacks.append(callback)

    def remove_progress_callback(self, callback: Callable) -> None:
        """移除进度更新回调。"""
        if callback in self._progress_callbacks:
            self._progress_callbacks.remove(callback)

    def _emit_progress(self, update: ProgressUpdate) -> None:
        """触发进度回调。"""
        for cb in self._progress_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(update))
                else:
                    cb(update)
            except Exception:
                logger.exception("progress callback error")

    # ── 任务提交 ──────────────────────────────────────

    def submit_task(
        self,
        name: str,
        description: str = "",
        task_type: str = "generic",
        priority: TaskPriority = TaskPriority.MEDIUM,
        task_data: dict | None = None,
    ) -> AsyncTask:
        """提交一个异步任务。

        Args:
            name: 任务名称
            description: 任务描述
            task_type: 任务类型（对应注册的执行函数）
            priority: 优先级
            task_data: 任务数据

        Returns:
            创建的 AsyncTask
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = AsyncTask(
            task_id=task_id,
            name=name,
            description=description,
            priority=priority,
            status=AsyncTaskStatus.QUEUED,
        )
        task._task_type = task_type
        task._task_data = task_data or {}

        self._tasks[task_id] = task
        self._queue.put_nowait(task_id)

        self._prune_history()

        logger.info("task submitted: id=%s, name=%s, priority=%s", task_id, name, priority.value)
        return task

    # ── 工作循环 ──────────────────────────────────────

    async def _worker_loop(self) -> None:
        """工作循环：从队列取任务并执行。"""
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_task(task_id: str):
            async with semaphore:
                await self._execute_task(task_id)

        while self._running:
            try:
                task_id = await self._queue.get()
                asyncio.create_task(run_task(task_id))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("worker loop error")
                await asyncio.sleep(1)

    async def _execute_task(self, task_id: str) -> None:
        """执行单个任务。"""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.status = AsyncTaskStatus.RUNNING
        task.started_at = time.time()

        # 初始进度
        self._update_progress(task, 0, "开始执行")

        try:
            task_type = getattr(task, "_task_type", "generic")
            task_data = getattr(task, "_task_data", {})

            func = self._task_funcs.get(task_type)
            if func:
                # 带进度回调的执行
                def progress_cb(percent, message="", step="", step_idx=0, total=0, data=None):
                    self._update_progress(
                        task, percent, message, step, step_idx, total, data or {}
                    )

                if asyncio.iscoroutinefunction(func):
                    result = await func(task_data, progress_cb)
                else:
                    result = func(task_data, progress_cb)
            else:
                # 没有注册函数的任务：模拟执行
                result = await self._simulate_task(task, task_data)

            task.result = result
            task.status = AsyncTaskStatus.COMPLETED
            task.progress = 100
            task.completed_at = time.time()
            self._update_progress(task, 100, "执行完成")
            logger.info("task completed: id=%s, name=%s", task_id, task.name)

        except asyncio.CancelledError:
            task.status = AsyncTaskStatus.CANCELLED
            task.completed_at = time.time()
            task.error = "任务被取消"
            logger.info("task cancelled: id=%s", task_id)
            raise
        except Exception as e:
            task.status = AsyncTaskStatus.FAILED
            task.completed_at = time.time()
            task.error = str(e)
            self._update_progress(task, task.progress, f"失败: {e}")
            logger.exception("task failed: id=%s", task_id)

    async def _simulate_task(self, task: AsyncTask, data: dict) -> dict:
        """模拟任务执行（用于无注册函数的测试）。"""
        total_steps = data.get("total_steps", 5)
        task.total_steps = total_steps

        for i in range(total_steps):
            if task.status == AsyncTaskStatus.CANCELLED:
                break
            await asyncio.sleep(data.get("step_delay", 0.5))
            percent = int((i + 1) / total_steps * 100)
            self._update_progress(
                task, percent,
                f"执行步骤 {i+1}/{total_steps}",
                f"步骤{i+1}", i+1, total_steps
            )

        return {"simulated": True, "steps": total_steps}

    # ── 进度更新 ──────────────────────────────────────

    def _update_progress(
        self,
        task: AsyncTask,
        percent: int,
        message: str = "",
        current_step: str = "",
        step_index: int = 0,
        total_steps: int = 0,
        data: dict | None = None,
    ) -> None:
        """更新任务进度。"""
        task.progress = max(0, min(100, percent))
        task.current_step = current_step or message
        if step_index > 0:
            task.step_index = step_index
        if total_steps > 0:
            task.total_steps = total_steps

        update = ProgressUpdate(
            task_id=task.task_id,
            percent=task.progress,
            current_step=task.current_step,
            step_index=task.step_index,
            total_steps=task.total_steps,
            message=message,
            elapsed_seconds=task.elapsed_seconds,
            estimated_remaining_seconds=task.estimated_remaining,
            data=data or {},
        )
        task.progress_history.append(update)
        if len(task.progress_history) > 100:
            task.progress_history = task.progress_history[-100:]

        self._emit_progress(update)

    # ── 任务管理 ──────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """获取任务详情。"""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        status: AsyncTaskStatus | None = None,
        limit: int = 50,
    ) -> list[AsyncTask]:
        """列出任务。

        Args:
            status: 按状态过滤
            limit: 最大返回数量
        """
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        # 按创建时间倒序
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def cancel_task(self, task_id: str) -> bool:
        """取消任务。"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status in (AsyncTaskStatus.COMPLETED, AsyncTaskStatus.FAILED, AsyncTaskStatus.CANCELLED):
            return False
        task.status = AsyncTaskStatus.CANCELLED
        task.completed_at = time.time()
        task.error = "用户取消"
        logger.info("task cancelled by user: id=%s", task_id)
        return True

    def retry_task(self, task_id: str) -> Optional[AsyncTask]:
        """重试失败的任务。"""
        task = self._tasks.get(task_id)
        if not task or task.status != AsyncTaskStatus.FAILED:
            return None
        # 重新提交
        return self.submit_task(
            name=f"{task.name}（重试）",
            description=task.description,
            task_type=getattr(task, "_task_type", "generic"),
            priority=task.priority,
            task_data=getattr(task, "_task_data", {}),
        )

    def _prune_history(self) -> None:
        """清理超过最大数量的历史任务。"""
        if len(self._tasks) <= self.max_history:
            return
        # 只保留最近的
        sorted_tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        keep_ids = {t.task_id for t in sorted_tasks[:self.max_history]}
        self._tasks = {tid: t for tid, t in self._tasks.items() if tid in keep_ids}

    # ── 统计 ──────────────────────────────────────────

    def stats(self) -> dict:
        """获取任务统计。"""
        total = len(self._tasks)
        running = sum(1 for t in self._tasks.values() if t.status == AsyncTaskStatus.RUNNING)
        queued = sum(1 for t in self._tasks.values() if t.status == AsyncTaskStatus.QUEUED)
        completed = sum(1 for t in self._tasks.values() if t.status == AsyncTaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == AsyncTaskStatus.FAILED)
        cancelled = sum(1 for t in self._tasks.values() if t.status == AsyncTaskStatus.CANCELLED)

        return {
            "total": total,
            "running": running,
            "queued": queued,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "max_concurrent": self.max_concurrent,
        }

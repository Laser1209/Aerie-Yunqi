"""Aerie · 云栖 v13.9.8 — 异步反思队列 (S1 M1.3).

将 self_evolver 的提案触发从主流程中彻底解耦，
使用 asyncio.Queue 实现生产者-消费者模式，确保用户响应零阻塞。

设计原则:
  - 生产者: Agent.reflect() 只负责把反思任务塞进队列，立即返回
  - 消费者: 后台 worker 协程逐条处理反思任务，调用 self_evolver
  - 背压: 队列满时丢弃旧任务，保证主流程不被拖慢
  - 持久化: 处理结果写入 reflection_log 表，供 Cognition Panel 查看
  - 幂等: 同一条消息不会重复触发反思（按 user_id + msg_ts 去重）
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 队列最大容量 —— 超过则丢弃最旧的反思任务
_MAX_QUEUE_SIZE = 100
# 单次批量处理最大数量
_BATCH_SIZE = 5
# Worker 空闲时的轮询间隔 (秒)
_IDLE_INTERVAL = 0.5


@dataclass
class ReflectionTask:
    """反思任务 —— 放入队列的工作单元."""
    user_id: int
    user_message: str
    react_trace: dict
    tool_results: list[dict]
    source: str = "agent"
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()

    @property
    def dedup_key(self) -> str:
        """去重键: 同一用户同一秒内的消息视为同一条."""
        return f"{self.user_id}:{int(self.created_at)}"


class ReflectionQueue:
    """
    异步反思队列 —— 生产者-消费者模式。

    用法::

        queue = ReflectionQueue(self_evolver, db)
        await queue.start()

        # 生产者侧 (Agent.reflect 中调用)
        await queue.enqueue(task)

        # 关闭
        await queue.stop()
    """

    def __init__(self, self_evolver: Any, db: Any = None) -> None:
        self._evolver = self_evolver
        self._db = db
        self._queue: asyncio.Queue[ReflectionTask] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._processed: int = 0
        self._dropped: int = 0
        self._dedup: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def processed_count(self) -> int:
        return self._processed

    @property
    def dropped_count(self) -> int:
        return self._dropped

    # ── Lifecycle ────────────────────────────────────

    async def start(self) -> None:
        """启动 worker 协程."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("ReflectionQueue started (max_size=%d)", _MAX_QUEUE_SIZE)

    async def stop(self) -> None:
        """停止 worker 协程，等待队列排空."""
        if not self._running:
            return
        self._running = False
        if self._worker_task:
            try:
                # 等待最多 5 秒让队列排空
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
            self._worker_task = None
        logger.info(
            "ReflectionQueue stopped (processed=%d, dropped=%d, remaining=%d)",
            self._processed, self._dropped, self._queue.qsize(),
        )

    # ── Producer API ─────────────────────────────────

    async def enqueue(self, task: ReflectionTask) -> bool:
        """
        将反思任务加入队列。

        Returns:
            True = 成功入队; False = 队列满被丢弃
        """
        if not self._running:
            return False

        # 去重检查
        dedup_key = task.dedup_key
        async with self._lock:
            if dedup_key in self._dedup:
                logger.debug("reflection task dedup hit: %s", dedup_key)
                return False
            self._dedup.add(dedup_key)

        try:
            self._queue.put_nowait(task)
            return True
        except asyncio.QueueFull:
            # 队列满了: 丢弃最旧的一条，再放新的
            self._dropped += 1
            try:
                old = self._queue.get_nowait()
                self._queue.task_done()
                async with self._lock:
                    self._dedup.discard(old.dedup_key)
                logger.warning("ReflectionQueue full, dropped oldest task")
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(task)
                return True
            except asyncio.QueueFull:
                self._dropped += 1
                return False

    # ── Worker ───────────────────────────────────────

    async def _worker_loop(self) -> None:
        """后台 worker: 持续从队列取任务并执行反思."""
        while self._running or not self._queue.empty():
            try:
                batch: list[ReflectionTask] = []
                # 尝试取一条，有一定等待时间
                try:
                    first = await asyncio.wait_for(
                        self._queue.get(), timeout=_IDLE_INTERVAL
                    )
                    batch.append(first)
                except asyncio.TimeoutError:
                    continue

                # 尽量多取几条，凑成一批
                while len(batch) < _BATCH_SIZE and not self._queue.empty():
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # 批量处理
                for task in batch:
                    try:
                        await self._process_one(task)
                    except Exception:
                        logger.exception("reflection task processing error")
                    finally:
                        self._queue.task_done()
                        self._processed += 1
                        async with self._lock:
                            self._dedup.discard(task.dedup_key)

            except Exception:
                logger.exception("reflection worker loop error")
                await asyncio.sleep(_IDLE_INTERVAL)

    async def _process_one(self, task: ReflectionTask) -> None:
        """处理单条反思任务."""
        if not self._evolver:
            return

        proposal_id = None
        error_msg = None
        try:
            result = self._evolver.maybe_propose(
                user_id=task.user_id,
                user_message=task.user_message,
                react_trace=task.react_trace,
                tool_results=task.tool_results,
            )
            proposal_id = result
        except Exception as e:
            error_msg = str(e)
            logger.exception("self_evolver.maybe_propose error")

        # 持久化到 reflection_log
        if self._db is not None:
            try:
                self._db.insert("reflection_log", {
                    "ts": int(task.created_at * 1000),
                    "user_id": task.user_id,
                    "source": task.source,
                    "react_trace": json.dumps(task.react_trace, ensure_ascii=False)[:2000],
                    "tool_count": len(task.tool_results or []),
                    "proposal_id": proposal_id,
                    "error": error_msg,
                    "processed_at": int(time.time() * 1000),
                })
            except Exception:
                logger.exception("reflection_log insert error")

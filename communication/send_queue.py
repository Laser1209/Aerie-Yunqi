"""Aerie · 云栖 v9.0 — Anthropomorphic send queue.

A SendQueue holds pending OutgoingReply segments and processes them
with realistic inter-message delay (rhythm control).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable, Optional

from communication.message import OutgoingReply, MessageType
from communication.splitter import SemanticMessageSplitter


# Scene → (min, max) inter-segment delay in seconds
INTERVAL_RANGES = {
    "urgent": (0.5, 1.5),
    "emotional": (5.0, 10.0),
    "daily": (8.0, 15.0),
    "report": (3.0, 6.0),
    "proactive": (20.0, 40.0),
}

# Lower number = higher priority (sent first)
PRIORITY_MAP = {
    "urgent": 1,
    "emotional": 2,
    "daily": 3,
    "report": 4,
    "proactive": 5,
}


class Priority(IntEnum):
    URGENT = 1
    EMOTIONAL = 2
    DAILY = 3
    REPORT = 4
    PROACTIVE = 5


@dataclass(order=True)
class QueuedMessage:
    """A message waiting in the priority queue."""

    priority: int
    sequence: int
    reply: OutgoingReply = field(compare=False)
    segment_index: int = field(default=0, compare=False)
    total_segments: int = field(default=1, compare=False)
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time() if asyncio._get_running_loop() else 0.0, compare=False)


class SendQueue:
    """Async priority-based send queue with anthropomorphic delays."""

    def __init__(
        self,
        sender: Callable[[OutgoingReply], Awaitable[bool]],
        splitter: Optional[SemanticMessageSplitter] = None,
        intervals: Optional[dict] = None,
    ) -> None:
        self.sender = sender
        self.splitter = splitter or SemanticMessageSplitter()
        self.intervals = {**INTERVAL_RANGES, **(intervals or {})}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._sequence = 0
        self._stopped = asyncio.Event()
        self._worker_task: Optional[asyncio.Task] = None
        self._stats = {
            "enqueued": 0,
            "sent": 0,
            "failed": 0,
        }

    def enqueue(self, reply: OutgoingReply, splitter: bool = True) -> int:
        """Enqueue a reply; optionally split long content into multiple segments.

        Returns the number of segments enqueued.
        """
        if splitter and reply.content:
            parts = self.splitter.split(reply.content, reply.scene)
        else:
            parts = [reply.content] if reply.content else []

        if not parts:
            return 0

        priority = PRIORITY_MAP.get(reply.scene, 3)
        enq_count = 0
        for i, part in enumerate(parts):
            seg_reply = OutgoingReply(
                user_id=reply.user_id,
                content=part,
                msg_type=reply.msg_type,
                group_id=reply.group_id,
                scene=reply.scene,
                mood=reply.mood,
                recall_eligible=reply.recall_eligible,
                auto_recall_after_seconds=reply.auto_recall_after_seconds,
                related_message_id=reply.related_message_id,
                render_mode=reply.render_mode,
                content_type=reply.content_type,
                metadata={**reply.metadata, "segment_index": i},
            )
            self._sequence += 1
            msg = QueuedMessage(
                priority=priority,
                sequence=self._sequence,
                reply=seg_reply,
                segment_index=i,
                total_segments=len(parts),
            )
            self._queue.put_nowait(msg)
            enq_count += 1
            self._stats["enqueued"] += 1
        return enq_count

    async def _process_one(self, msg: QueuedMessage) -> None:
        # Apply inter-segment delay (rhythm)
        if msg.segment_index > 0:
            min_s, max_s = self.intervals.get(msg.reply.scene, (3.0, 8.0))
            delay = random.uniform(min_s, max_s)
            await asyncio.sleep(delay)
        try:
            ok = await self.sender(msg.reply)
            if ok:
                self._stats["sent"] += 1
            else:
                self._stats["failed"] += 1
        except Exception:
            self._stats["failed"] += 1

    async def _worker(self) -> None:
        while not self._stopped.is_set():
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            await self._process_one(msg)
            self._queue.task_done()

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._stopped.clear()
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        self._stopped.set()
        if self._worker_task:
            await self._worker_task

    def stats(self) -> dict:
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
        }

"""Aerie · 云栖 v9.0 — Send queue with frequency control and human-like pacing.

Only receives QQ replies; local chat-bar replies skip this queue.
"""

from __future__ import annotations
import asyncio
import logging
from collections import deque
from typing import Awaitable, Callable

from communication.message import OutgoingReply
from communication.splitter import SemanticMessageSplitter

logger = logging.getLogger(__name__)

SenderFn = Callable[[OutgoingReply], Awaitable[bool]]

_DEFAULT_MIN_INTERVAL = 1.2     # seconds between messages
_DEFAULT_MAX_QUEUE = 20


class SendQueue:
    def __init__(
        self,
        sender: SenderFn,
        splitter: SemanticMessageSplitter | None = None,
        min_interval: float = _DEFAULT_MIN_INTERVAL,
        recall_manager: Any = None,
        db: Any = None,
        qq_with_segments: Any = None,
    ) -> None:
        self._sender = sender
        self._splitter = splitter or SemanticMessageSplitter()
        self._min_interval = min_interval
        self._recall_manager = recall_manager
        self._db = db
        self._qq_segments = qq_with_segments
        self._queue: deque[OutgoingReply] = deque()
        self._task: asyncio.Task | None = None
        self._running = False

    def enqueue(self, reply: OutgoingReply) -> None:
        """Add a reply to the send queue (QQ messages only)."""
        if len(self._queue) >= _DEFAULT_MAX_QUEUE:
            logger.warning("Send queue full, dropping reply to %s", reply.user_id)
            return
        self._queue.append(reply)

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        """Consume queue with pacing."""
        while self._running:
            if not self._queue:
                await asyncio.sleep(0.5)
                continue

            reply = self._queue.popleft()
            segments = self._splitter.split(reply.content)
            first_in_batch = True
            use_segments_sender = (
                reply.reply_to_qq_message_id
                and self._qq_segments is not None
            )
            for seg in segments:
                reply.content = seg
                ok = False
                try:
                    if first_in_batch and use_segments_sender:
                        ok = await self._qq_segments(
                            reply.user_id,
                            seg,
                            reply.reply_to_qq_message_id,
                        )
                    else:
                        ok = await self._sender(reply)
                    if not ok:
                        logger.warning("QQ send failed for user %s", reply.user_id)
                    # Phase 4: hook into recall manager on first segment
                    if first_in_batch and ok and self._recall_manager:
                        try:
                            self._recall_manager.record_sent(
                                user_id=reply.user_id,
                                content=reply.content,
                                msg_id=reply.msg_id,
                                segments=segments,
                            )
                        except Exception:
                            pass
                    first_in_batch = False
                except Exception:
                    logger.exception("send worker error")
                await asyncio.sleep(self._min_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

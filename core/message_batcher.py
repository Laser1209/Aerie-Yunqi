"""Aerie · 云栖 v0.1.0-beta.1 — Message batcher with time-window and size-limit support.

Collects incoming messages within a configurable time window per conversation,
then triggers a registered callback for batch processing.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable, Awaitable

from communication.message import IncomingMessage
from config.persona_loader import get_message_batching_config

logger = logging.getLogger(__name__)

BatchCallback = Callable[[list[IncomingMessage], str], Awaitable[None]]


class _ConversationBatch:
    """Internal state for a single conversation's active batch."""

    __slots__ = (
        "conversation_id",
        "batch_id",
        "messages",
        "timer_task",
        "lock",
    )

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.batch_id: str = uuid.uuid4().hex
        self.messages: list[IncomingMessage] = []
        self.timer_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()


class MessageBatcher:
    """Async message batcher singleton with time-window and max-batch-size support.

    Collects messages per conversation_id:
    - First message starts an asyncio timer (window_seconds)
    - Messages arriving within the window join the same batch
    - When the window expires OR max_batch_size is reached, the batch
      is submitted to all registered callbacks
    - If batching is disabled (enabled=False), messages are submitted
      immediately as single-message batches
    """

    _instance: MessageBatcher | None = None
    _instance_lock = asyncio.Lock()

    def __new__(cls) -> MessageBatcher:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._callbacks: list[BatchCallback] = []
        self._active_batches: dict[str, _ConversationBatch] = {}
        self._global_lock = asyncio.Lock()
        self._config = get_message_batching_config()
        logger.info(
            "MessageBatcher initialized: enabled=%s, window=%.2fs, max_size=%d",
            self._config["enabled"],
            self._config["window_seconds"],
            self._config["max_batch_size"],
        )

    @classmethod
    async def get_instance(cls) -> MessageBatcher:
        """Get or create the singleton instance (async-safe double-checked locking)."""
        if cls._instance is None:
            async with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. For testing only."""
        cls._instance = None

    def register_callback(self, callback: BatchCallback) -> None:
        """Register an async callback to be invoked when a batch is ready.

        Callback signature:
            async def callback(messages: list[IncomingMessage], batch_id: str) -> None
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            logger.debug("Registered batch callback (total: %d)", len(self._callbacks))

    def unregister_callback(self, callback: BatchCallback) -> None:
        """Remove a previously registered callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            logger.debug("Unregistered batch callback (total: %d)", len(self._callbacks))

    def reload_config(self) -> None:
        """Reload batching configuration from settings."""
        self._config = get_message_batching_config()
        logger.info(
            "MessageBatcher config reloaded: enabled=%s, window=%.2fs, max_size=%d",
            self._config["enabled"],
            self._config["window_seconds"],
            self._config["max_batch_size"],
        )

    @staticmethod
    def get_conversation_id(message: IncomingMessage) -> str:
        """Derive a unique conversation_id from an IncomingMessage.

        Format: "{channel}:{channel_account_id}" or "qq:{user_id}" as fallback.
        This ensures isolation between different users/channels.
        """
        if message.channel and message.channel_account_id:
            return f"{message.channel}:{message.channel_account_id}"
        return f"{message.source}:{message.user_id}"

    async def submit_message(self, message: IncomingMessage) -> None:
        """Submit a message for batching.

        If batching is disabled, the message is immediately passed to callbacks
        as a single-message batch.
        """
        conversation_id = self.get_conversation_id(message)

        if not self._config["enabled"]:
            await self._dispatch_batch([message], uuid.uuid4().hex)
            return

        async with self._global_lock:
            batch = self._active_batches.get(conversation_id)
            if batch is None:
                batch = _ConversationBatch(conversation_id)
                self._active_batches[conversation_id] = batch
                logger.debug("New batch started for %s: %s", conversation_id, batch.batch_id)

        async with batch.lock:
            batch.messages.append(message)
            msg_count = len(batch.messages)
            logger.debug(
                "Message added to batch %s (conv=%s): count=%d, content=%r",
                batch.batch_id,
                conversation_id,
                msg_count,
                message.content[:50],
            )

            if msg_count >= self._config["max_batch_size"]:
                await self._finalize_batch(batch, reason="max_size")
            elif batch.timer_task is None:
                batch.timer_task = asyncio.create_task(
                    self._window_timer(batch),
                    name=f"batch-timer-{batch.batch_id[:8]}",
                )
                logger.debug(
                    "Timer started for batch %s: %.2fs window",
                    batch.batch_id,
                    self._config["window_seconds"],
                )

    async def _window_timer(self, batch: _ConversationBatch) -> None:
        """Wait for the configured window, then finalize the batch on timeout."""
        try:
            await asyncio.sleep(self._config["window_seconds"])
            async with batch.lock:
                if batch.messages:
                    await self._finalize_batch(batch, reason="timeout")
        except asyncio.CancelledError:
            logger.debug("Timer cancelled for batch %s", batch.batch_id)
            raise

    async def _finalize_batch(self, batch: _ConversationBatch, reason: str) -> None:
        """Finalize and dispatch a batch, cleaning up state."""
        if batch.timer_task is not None and not batch.timer_task.done():
            batch.timer_task.cancel()

        messages = list(batch.messages)
        batch_id = batch.batch_id

        async with self._global_lock:
            self._active_batches.pop(batch.conversation_id, None)

        batch.messages.clear()
        batch.timer_task = None

        logger.info(
            "Batch %s finalized (conv=%s, reason=%s, size=%d)",
            batch_id,
            batch.conversation_id,
            reason,
            len(messages),
        )

        await self._dispatch_batch(messages, batch_id)

    async def _dispatch_batch(self, messages: list[IncomingMessage], batch_id: str) -> None:
        """Dispatch a ready batch to all registered callbacks."""
        if not messages:
            logger.warning("Attempted to dispatch empty batch %s, skipping", batch_id)
            return

        if not self._callbacks:
            logger.warning(
                "No callbacks registered for batch %s (size=%d); dropping",
                batch_id,
                len(messages),
            )
            return

        logger.debug(
            "Dispatching batch %s to %d callback(s), size=%d",
            batch_id,
            len(self._callbacks),
            len(messages),
        )

        for callback in list(self._callbacks):
            try:
                await callback(messages, batch_id)
            except Exception:
                logger.exception(
                    "Batch callback failed for batch %s", batch_id
                )

    async def flush_all(self) -> None:
        """Immediately finalize all active batches. Useful for graceful shutdown."""
        logger.info("Flushing all active batches...")
        async with self._global_lock:
            batches = list(self._active_batches.values())
            self._active_batches.clear()

        for batch in batches:
            async with batch.lock:
                if batch.messages:
                    if batch.timer_task is not None and not batch.timer_task.done():
                        batch.timer_task.cancel()
                    messages = list(batch.messages)
                    batch.messages.clear()
                    batch.timer_task = None
                    logger.info(
                        "Flushing batch %s (conv=%s, size=%d)",
                        batch.batch_id,
                        batch.conversation_id,
                        len(messages),
                    )
                    await self._dispatch_batch(messages, batch.batch_id)

        logger.info("All active batches flushed")

    async def get_active_batch_count(self) -> int:
        """Return the number of currently active (open) batches."""
        async with self._global_lock:
            return len(self._active_batches)

    async def get_active_conversations(self) -> list[str]:
        """Return list of conversation_ids with active batches."""
        async with self._global_lock:
            return list(self._active_batches.keys())


def get_message_batcher() -> MessageBatcher:
    """Synchronous accessor for the MessageBatcher singleton.

    Note: This returns the instance if already created; otherwise creates it
    synchronously (safe since __init__ only sets up state, no awaits needed).
    For async safety in initialization, use MessageBatcher.get_instance() instead.
    """
    if MessageBatcher._instance is None:
        MessageBatcher._instance = MessageBatcher()
    return MessageBatcher._instance

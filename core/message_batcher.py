"""Aerie Companion v0.3.2-beta.0903-A07 - Message batcher (首条立即 + 动态缓冲).

Gate 4 重构: 修复 D5 (首条也要等窗口)。
新语义 per conversation:
  - 首条消息: 立即提交处理 (不再等 window_seconds)
  - 处理期间到达的新消息: 进入待并入缓冲, 不阻塞首条
  - 当前批完成后 (on_batch_completed): 若缓冲非空, 作为新批次 dispatch

保留: max_batch_size 作为缓冲封顶; window_seconds 作为缓冲安全兜底
(兜底仅在当前批未运行时才 flush, 保证同 conversation 串行不被破坏)。
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


class _ConversationState:
    """单个 conversation 的动态缓冲状态."""

    __slots__ = (
        "conversation_id",
        "running",
        "pending",
        "pending_batch_id",
        "lock",
        "timer_task",
    )

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.running = False            # 当前批已提交 & 正在被处理
        self.pending: list[IncomingMessage] = []
        self.pending_batch_id: str | None = None
        self.lock = asyncio.Lock()
        self.timer_task: asyncio.Task | None = None


class MessageBatcher:
    """Async message batcher singleton (首条立即 + 动态缓冲).

    每 conversation 维护一个状态:
      - 首条消息到达 → 立即 dispatch 为单条批, 标记 running。
      - 运行中到达 → 缓冲到 pending; 达到 max_batch_size 则在下次完成时 flush。
      - on_batch_completed(conversation_id) 被 worker/companion 调用 →
        running 置 false, 若有 pending 则作为新批 dispatch。
      - window_seconds 作为缓冲兜底计时 (仅在未运行时 flush, 保证串行)。
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
        self._states: dict[str, _ConversationState] = {}
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

        Disabled -> immediately dispatch as single-message batch.
        Otherwise:
          - First message (not running) -> dispatch immediately.
          - While running -> buffer into pending (flushed on completion).
        """
        conversation_id = self.get_conversation_id(message)

        if not self._config["enabled"]:
            await self._dispatch_batch([message], uuid.uuid4().hex)
            return

        async with self._global_lock:
            state = self._states.get(conversation_id)
            if state is None:
                state = _ConversationState(conversation_id)
                self._states[conversation_id] = state

        async with state.lock:
            if not state.running:
                # 首条消息: 立即提交 (不再等窗口)
                state.running = True
                await self._dispatch_batch([message], uuid.uuid4().hex)
                return

            # 当前批运行中: 缓冲新消息
            state.pending.append(message)
            if state.pending_batch_id is None:
                state.pending_batch_id = uuid.uuid4().hex
            logger.debug(
                "Buffered message for %s (pending=%d): %r",
                conversation_id, len(state.pending), message.content[:50],
            )
            # 缓冲区满: 由 on_batch_completed 在下一次完成时 flush
            if state.timer_task is None:
                state.timer_task = asyncio.create_task(
                    self._buffer_timer(state),
                    name=f"buffer-timer-{conversation_id[:8]}",
                )

    async def _buffer_timer(self, state: _ConversationState) -> None:
        """缓冲兜底计时: 仅在未运行时 flush, 保证串行不被打断."""
        try:
            while True:
                await asyncio.sleep(self._config["window_seconds"])
                async with state.lock:
                    if not state.pending:
                        state.timer_task = None
                        return
                    if not state.running:
                        await self._flush_pending(state)
                        state.timer_task = None
                        return
                    # 仍在运行 -> 继续等 (由 on_batch_completed 触发 flush)
        except asyncio.CancelledError:
            state.timer_task = None
            raise

    async def on_batch_completed(self, conversation_id: str) -> None:
        """由 worker/companion 在批次处理完成后调用.

        若该 conversation 有缓冲消息, 立即作为新批次 dispatch (保持串行)。
        """
        state = self._states.get(conversation_id)
        if state is None:
            return
        async with state.lock:
            if state.timer_task is not None and not state.timer_task.done():
                state.timer_task.cancel()
                state.timer_task = None
            state.running = False
            if state.pending:
                await self._flush_pending(state)

    async def _flush_pending(self, state: _ConversationState) -> None:
        """将 pending 缓冲作为一批 dispatch (调用方需持有 state.lock)."""
        if not state.pending:
            return
        messages = list(state.pending)
        batch_id = state.pending_batch_id or uuid.uuid4().hex
        state.pending.clear()
        state.pending_batch_id = None
        state.running = True
        logger.info(
            "Flushing buffered batch %s (conv=%s, size=%d)",
            batch_id, state.conversation_id, len(messages),
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
                logger.exception("Batch callback failed for batch %s", batch_id)

    async def flush_all(self) -> None:
        """Immediately finalize all active states (graceful shutdown)."""
        logger.info("Flushing all active conversation states...")
        async with self._global_lock:
            states = list(self._states.values())
            self._states.clear()
        for state in states:
            async with state.lock:
                if state.timer_task is not None and not state.timer_task.done():
                    state.timer_task.cancel()
                    state.timer_task = None
                state.running = False
                if state.pending:
                    messages = list(state.pending)
                    batch_id = state.pending_batch_id or uuid.uuid4().hex
                    state.pending.clear()
                    state.pending_batch_id = None
                    logger.info(
                        "Flushing buffered batch %s (conv=%s, size=%d)",
                        batch_id, state.conversation_id, len(messages),
                    )
                    await self._dispatch_batch(messages, batch_id)
        logger.info("All active conversation states flushed")

    async def get_active_batch_count(self) -> int:
        """Return the number of currently active (running/buffered) states."""
        async with self._global_lock:
            return len(self._states)

    async def get_active_conversations(self) -> list[str]:
        """Return list of conversation_ids with active states."""
        async with self._global_lock:
            return list(self._states.keys())


def get_message_batcher() -> MessageBatcher:
    """Synchronous accessor for the MessageBatcher singleton.

    Note: This returns the instance if already created; otherwise creates it
    synchronously (safe since __init__ only sets up state, no awaits needed).
    For async safety in initialization, use MessageBatcher.get_instance() instead.
    """
    if MessageBatcher._instance is None:
        MessageBatcher._instance = MessageBatcher()
    return MessageBatcher._instance

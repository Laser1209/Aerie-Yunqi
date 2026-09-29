"""Aerie Companion - Message batcher (首条聚合窗 + 运行中缓冲).

每 conversation 的批处理语义:
  - 首条消息 (空闲态) 不再零等待: 开启「首条聚合窗」, 等 T_idle 静默期。
    窗口内到达的新消息并入同批并重置静默计时, 但聚合窗总时长到 T_cap
    时强制派发 (cap 优先于 idle)。
  - 任务判定命中 (复用 core.task_loop.classify) 的消息跳过聚合窗, 立即派发。
  - 批次派发后进入 running: 运行中到达的消息缓冲到 pending,
    由 on_batch_completed 在批处理完成时作为新批立即 flush (同会话串行不打断)。
  - window_seconds 仍作为缓冲兜底计时 (仅在未运行时 flush)。

enabled=false 时保持全量立即派发的既有行为。
T_idle / T_cap 一律从配置读取
(message_batching.first_message_idle_seconds / first_message_cap_seconds),
代码里只保留 _DEFAULT_* 作兜底默认, 不做业务硬编码。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable, Awaitable

from communication.message import IncomingMessage
from config.persona_loader import get_message_batching_config

logger = logging.getLogger(__name__)

# 配置缺失时的兜底默认 (实际值由 settings.yaml 覆盖, 前端「高级设置」可调)。
_DEFAULT_IDLE_SECONDS = 3.0
_DEFAULT_CAP_SECONDS = 8.0

BatchCallback = Callable[[list[IncomingMessage], str], Awaitable[None]]


def _coerce_seconds(config: dict, key: str, default: float) -> float:
    """从配置读取秒数; 缺失或非法时回退到默认值 (不允许负值)。"""
    try:
        return max(0.0, float(config.get(key, default)))
    except (TypeError, ValueError):
        return default


class _ConversationState:
    """单个 conversation 的动态缓冲状态."""

    __slots__ = (
        "conversation_id",
        "running",
        "aggregating",
        "pending",
        "pending_batch_id",
        "lock",
        "timer_task",
        "idle_deadline",
        "cap_deadline",
        "agg_wake",
    )

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.running = False             # 当前批已提交 & 正在被处理
        self.aggregating = False         # 首条聚合窗进行中 (未派发)
        self.pending: list[IncomingMessage] = []
        self.pending_batch_id: str | None = None
        self.lock = asyncio.Lock()
        self.timer_task: asyncio.Task | None = None
        self.idle_deadline = 0.0         # 聚合窗静默期截止时刻 (新消息会推后)
        self.cap_deadline = 0.0          # 聚合窗总时长截止时刻 (不随新消息推后)
        self.agg_wake: asyncio.Event | None = None


class MessageBatcher:
    """Async message batcher singleton (首条聚合窗 + 运行中缓冲).

    每 conversation 维护一个状态:
      - 空闲态首条消息 → 开启聚合窗, 等 T_idle 静默或 T_cap 上限后派发。
      - 聚合窗内新消息 → 并入同批并重置静默计时 (总时长仍受 T_cap 约束)。
      - 运行中到达 → 缓冲到 pending; 由 on_batch_completed 触发 flush。
      - 任务消息 → 跳过聚合窗, 立即派发。
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
        self._apply_config(get_message_batching_config())

    def _apply_config(self, config: dict) -> None:
        """缓存配置并解析聚合窗秒数 (cap 钳到 >= idle, 保证必然收敛)。"""
        self._config = config
        self._idle_seconds = _coerce_seconds(
            config, "first_message_idle_seconds", _DEFAULT_IDLE_SECONDS,
        )
        self._cap_seconds = max(
            self._idle_seconds,
            _coerce_seconds(config, "first_message_cap_seconds", _DEFAULT_CAP_SECONDS),
        )
        logger.info(
            "MessageBatcher config: enabled=%s, window=%.2fs, max_size=%d, "
            "idle=%.2fs, cap=%.2fs",
            self._config["enabled"],
            self._config["window_seconds"],
            self._config["max_batch_size"],
            self._idle_seconds,
            self._cap_seconds,
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
        """Reload batching configuration from settings (热加载入口)."""
        self._apply_config(get_message_batching_config())

    @staticmethod
    def get_conversation_id(message: IncomingMessage) -> str:
        """Derive a unique conversation_id from an IncomingMessage.

        Format: "{channel}:{channel_account_id}" or "qq:{user_id}" as fallback.
        This ensures isolation between different users/channels.
        """
        if message.channel and message.channel_account_id:
            return f"{message.channel}:{message.channel_account_id}"
        return f"{message.source}:{message.user_id}"

    @staticmethod
    def _is_task_message(message: IncomingMessage) -> bool:
        """复用既有任务判定入口 core.task_loop.classify, 不新造关键词表。

        命中表示这是一件「要动手的事」, 应跳过首条聚合窗立即派发。
        """
        content = (message.content or "").strip()
        if not content:
            return False
        try:
            from core.task_loop import classify

            return classify(content) is not None
        except Exception:
            logger.debug("任务判定失败, 按普通消息走聚合窗", exc_info=True)
            return False

    async def submit_message(self, message: IncomingMessage) -> None:
        """Submit a message for batching.

        Disabled -> immediately dispatch as single-message batch.
        Otherwise:
          - 空闲态普通消息 -> 开启首条聚合窗 (T_idle 静默 / T_cap 上限后派发)。
          - 任务消息 -> 跳过聚合窗, 立即派发。
          - 聚合窗内新消息 -> 并入同批并重置静默计时。
          - 运行中 -> 缓冲到 pending (由 on_batch_completed 触发 flush)。
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
            if state.running:
                self._buffer_during_run(state, message)
                return

            if state.aggregating:
                # 聚合窗内: 并入同批并重置静默计时 (总时长仍受 T_cap 约束)。
                state.pending.append(message)
                logger.debug(
                    "聚合窗追加消息 (conv=%s, pending=%d): %r",
                    conversation_id, len(state.pending), message.content[:50],
                )
                self._reset_idle_deadline(state)
                return

            # 空闲态: 任务消息跳过聚合窗, 立即派发。
            if self._is_task_message(message):
                state.running = True
                logger.info(
                    "任务消息短路聚合窗 (conv=%s): %r",
                    conversation_id, message.content[:50],
                )
                await self._dispatch_batch([message], uuid.uuid4().hex)
                return

            # 普通首条消息: 开启聚合窗。
            state.aggregating = True
            state.pending.append(message)
            state.pending_batch_id = uuid.uuid4().hex
            self._start_aggregation(state)

    def _buffer_during_run(
        self, state: _ConversationState, message: IncomingMessage,
    ) -> None:
        """当前批运行中: 缓冲新消息, 由 on_batch_completed 触发 flush。"""
        state.pending.append(message)
        if state.pending_batch_id is None:
            state.pending_batch_id = uuid.uuid4().hex
        logger.debug(
            "Buffered message for %s (pending=%d): %r",
            state.conversation_id, len(state.pending), message.content[:50],
        )
        if state.timer_task is None:
            state.timer_task = asyncio.create_task(
                self._buffer_timer(state),
                name=f"buffer-timer-{state.conversation_id[:8]}",
            )

    def _start_aggregation(self, state: _ConversationState) -> None:
        """开启首条聚合窗: 记录 idle/cap 截止时刻并启动计时任务。"""
        now = asyncio.get_running_loop().time()
        state.idle_deadline = now + self._idle_seconds
        state.cap_deadline = now + self._cap_seconds
        state.agg_wake = asyncio.Event()
        state.timer_task = asyncio.create_task(
            self._aggregation_timer(state),
            name=f"agg-timer-{state.conversation_id[:8]}",
        )

    def _reset_idle_deadline(self, state: _ConversationState) -> None:
        """新消息到达时推后静默截止时刻并唤醒计时任务 (cap 截止时刻不动)。"""
        state.idle_deadline = asyncio.get_running_loop().time() + self._idle_seconds
        if state.agg_wake is not None:
            state.agg_wake.set()

    def notify_typing(self, conversation_id: str) -> None:
        """本地通道「输入框有内容」信号: 聚合窗内用户仍在输入 → 推后静默截止。

        语义:
          - 只在聚合窗进行中生效 (空闲态无窗口可推、运行中由 flush 流程接管);
          - 只推后 idle 截止时刻, cap 总上限固定于窗口开启时刻 → 用户一直输入
            也必然在 T_cap 派发, 不会把批次饿死;
          - `enabled=false` 时无窗口概念, 直接 no-op。
        """
        if not self._config.get("enabled"):
            return
        state = self._states.get(conversation_id)
        if state is None or not state.aggregating:
            return
        self._reset_idle_deadline(state)

    async def _aggregation_timer(self, state: _ConversationState) -> None:
        """首条聚合窗计时: 静默至 T_idle 或到达 T_cap 总上限即派发。

        新消息会通过 agg_wake 唤醒本任务并推后 idle_deadline, 但 cap_deadline
        固定于窗口开启时刻, 因此 timeout 取 min(idle, cap) 保证总时长不超上限。
        """
        loop = asyncio.get_running_loop()
        try:
            while True:
                wake = state.agg_wake
                if wake is None:
                    return
                wake.clear()
                timeout = min(state.idle_deadline, state.cap_deadline) - loop.time()
                if timeout <= 0:
                    break
                try:
                    await asyncio.wait_for(wake.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
            await self._finalize_aggregation(state)
        except asyncio.CancelledError:
            state.timer_task = None
            raise

    async def _finalize_aggregation(self, state: _ConversationState) -> None:
        """聚合窗到期: 把收集到的消息作为一批派发 (调用方不持有 state.lock)。"""
        async with state.lock:
            if not state.aggregating:
                return
            state.aggregating = False
            state.timer_task = None
            state.agg_wake = None
            if not state.pending:
                return
            messages = list(state.pending)
            batch_id = state.pending_batch_id or uuid.uuid4().hex
            state.pending.clear()
            state.pending_batch_id = None
            state.running = True
            logger.info(
                "首条聚合窗派发 batch %s (conv=%s, size=%d)",
                batch_id, state.conversation_id, len(messages),
            )
            await self._dispatch_batch(messages, batch_id)

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
                state.aggregating = False
                state.agg_wake = None
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

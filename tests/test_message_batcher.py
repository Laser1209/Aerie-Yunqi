"""Tests for MessageBatcher: 首条聚合窗, 运行中缓冲, 并发隔离.

注: 阶段 3 把「首条零等待立即派发」改为「首条聚合窗」(T_idle 静默 / T_cap 上限),
因此本文件内的时序断言同步更新为「静默窗结束后派发」。
聚合窗本身的专项用例见 tests/test_message_batcher_aggregation.py。
"""

import asyncio
import pytest

from communication.message import IncomingMessage
from core.message_batcher import MessageBatcher, get_message_batcher


def _cfg(**overrides):
    """构造 message_batching 配置 (含首条聚合窗键, 小值便于快速测试)。"""
    cfg = {
        "enabled": True,
        "window_seconds": 1.5,
        "max_batch_size": 10,
        "base_interval_seconds": 0.5,
        "chars_per_second": 4,
        "min_interval_seconds": 0.3,
        "max_interval_seconds": 5.0,
        "first_message_idle_seconds": 0.1,
        "first_message_cap_seconds": 5.0,
    }
    cfg.update(overrides)
    return cfg


def _patch_config(monkeypatch, cfg):
    monkeypatch.setattr(
        "core.message_batcher.get_message_batching_config", lambda: cfg
    )


class TestMessageBatcherSingleton:
    """Test singleton pattern."""

    def setup_method(self):
        MessageBatcher.reset_instance()

    def teardown_method(self):
        MessageBatcher.reset_instance()

    @pytest.mark.asyncio
    async def test_get_instance_returns_same_object(self):
        b1 = await MessageBatcher.get_instance()
        b2 = await MessageBatcher.get_instance()
        assert b1 is b2

    def test_synchronous_getter_returns_same_object(self):
        b1 = get_message_batcher()
        b2 = get_message_batcher()
        assert b1 is b2

    @pytest.mark.asyncio
    async def test_reset_instance_creates_new_singleton(self):
        b1 = await MessageBatcher.get_instance()
        MessageBatcher.reset_instance()
        b2 = await MessageBatcher.get_instance()
        assert b1 is not b2


class TestMessageBatcherCore:
    """Test core batching functionality."""

    def setup_method(self):
        MessageBatcher.reset_instance()
        self.received_batches: list[tuple[list[IncomingMessage], str]] = []

    def teardown_method(self):
        MessageBatcher.reset_instance()

    def _make_message(
        self,
        content: str,
        user_id: int = 12345,
        channel: str = "qq",
        channel_account_id: str | None = None,
    ) -> IncomingMessage:
        return IncomingMessage(
            user_id=user_id,
            content=content,
            msg_type="private",
            source="qq",
            channel=channel,
            channel_account_id=channel_account_id or str(user_id),
        )

    async def _collect_callback(self, messages: list[IncomingMessage], batch_id: str) -> None:
        self.received_batches.append((list(messages), batch_id))
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_disabled_batching_sends_immediately(self, monkeypatch):
        """When enabled=False, messages should be dispatched as single batches immediately."""
        _patch_config(monkeypatch, _cfg(enabled=False, window_seconds=1.0))
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        msg = self._make_message("hello", user_id=111)
        await batcher.submit_message(msg)
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 1
        msgs, bid = self.received_batches[0]
        assert len(msgs) == 1
        assert msgs[0].content == "hello"
        assert len(bid) == 32

    @pytest.mark.asyncio
    async def test_first_message_waits_idle_then_dispatches(self, monkeypatch):
        """首条消息进入聚合窗: T_idle 静默后才派发 (不再零等待)。"""
        _patch_config(monkeypatch, _cfg(window_seconds=5.0))
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("msg1", user_id=222))
        await asyncio.sleep(0.03)
        assert len(self.received_batches) == 0, "首条不应立即派发"

        await asyncio.sleep(0.2)
        assert len(self.received_batches) == 1
        assert [m.content for m in self.received_batches[0][0]] == ["msg1"]
        assert len(self.received_batches[0][1]) == 32

    @pytest.mark.asyncio
    async def test_buffer_flushed_on_batch_completed(self, monkeypatch):
        """Messages arriving while a batch is running are buffered, flushed on completion."""
        _patch_config(monkeypatch, _cfg(window_seconds=5.0))
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        # first message -> aggregation window closes -> immediate single batch
        await batcher.submit_message(self._make_message("msg1", user_id=222))
        await asyncio.sleep(0.2)
        assert len(self.received_batches) == 1
        assert [m.content for m in self.received_batches[0][0]] == ["msg1"]

        # while that batch is running -> following messages buffered
        await batcher.submit_message(self._make_message("msg2", user_id=222))
        await batcher.submit_message(self._make_message("msg3", user_id=222))
        await asyncio.sleep(0.05)
        assert len(self.received_batches) == 1

        # current batch completes -> buffered messages flushed as a new batch
        await batcher.on_batch_completed("qq:222")
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 2
        assert [m.content for m in self.received_batches[1][0]] == ["msg2", "msg3"]
        assert self.received_batches[0][1] != self.received_batches[1][1]

    @pytest.mark.asyncio
    async def test_conversation_isolation(self, monkeypatch):
        """Different conversations should have independent batches."""
        _patch_config(monkeypatch, _cfg(window_seconds=5.0))
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("u1-1", user_id=100))
        await batcher.submit_message(self._make_message("u2-1", user_id=200))
        await asyncio.sleep(0.2)

        # each conversation's first message dispatched as its own batch
        assert len(self.received_batches) == 2

        # while both run, second messages are buffered per conversation
        await batcher.submit_message(self._make_message("u1-2", user_id=100))
        await batcher.submit_message(self._make_message("u2-2", user_id=200))
        await asyncio.sleep(0.05)

        # complete each conversation -> its own buffered message flushed separately
        await batcher.on_batch_completed("qq:100")
        await batcher.on_batch_completed("qq:200")
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 4
        by_user: dict[int, list[set[str]]] = {}
        for msgs, _ in self.received_batches:
            by_user.setdefault(msgs[0].user_id, []).append({m.content for m in msgs})

        assert by_user[100] == [{"u1-1"}, {"u1-2"}]
        assert by_user[200] == [{"u2-1"}, {"u2-2"}]

    @pytest.mark.asyncio
    async def test_flush_all_dispatches_all_buffered(self, monkeypatch):
        """flush_all() should immediately dispatch all pending (aggregation) messages."""
        _patch_config(monkeypatch, _cfg(window_seconds=5.0, first_message_idle_seconds=5.0))
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        # both conversations sit in the aggregation window -> nothing dispatched yet
        await batcher.submit_message(self._make_message("f1", user_id=400))
        await batcher.submit_message(self._make_message("f2", user_id=500))
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 0
        assert await batcher.get_active_batch_count() == 2

        await batcher.flush_all()
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 2
        assert await batcher.get_active_batch_count() == 0
        contents = {m.content for msgs, _ in self.received_batches for m in msgs}
        assert contents == {"f1", "f2"}

    @pytest.mark.asyncio
    async def test_batch_after_flush_starts_new_batch(self, monkeypatch):
        """After flushing, new messages should start a fresh batch."""
        _patch_config(monkeypatch, _cfg(window_seconds=0.3))
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("first", user_id=600))
        await asyncio.sleep(0.2)
        assert len(self.received_batches) == 1

        await batcher.flush_all()
        await asyncio.sleep(0.05)
        assert len(self.received_batches) == 1

        await batcher.submit_message(self._make_message("second", user_id=600))
        await asyncio.sleep(0.3)
        assert len(self.received_batches) == 2
        assert len(self.received_batches[1][0]) == 1
        assert self.received_batches[1][0][0].content == "second"

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_break_other_callbacks(self, monkeypatch):
        """If one callback raises, other callbacks should still run."""
        _patch_config(monkeypatch, _cfg(enabled=False, window_seconds=1.0))
        batcher = await MessageBatcher.get_instance()

        bad_called = []
        good_called = []

        async def bad_cb(msgs, bid):
            bad_called.append(bid)
            raise RuntimeError("boom")

        async def good_cb(msgs, bid):
            good_called.append(bid)

        batcher.register_callback(bad_cb)
        batcher.register_callback(good_cb)

        msg = self._make_message("test", user_id=700)
        await batcher.submit_message(msg)
        await asyncio.sleep(0.05)

        assert len(bad_called) == 1
        assert len(good_called) == 1

    @pytest.mark.asyncio
    async def test_get_conversation_id_uses_channel_when_available(self):
        batcher = await MessageBatcher.get_instance()
        msg = IncomingMessage(
            user_id=123,
            content="test",
            channel="discord",
            channel_account_id="user-456",
            source="discord",
        )
        cid = batcher.get_conversation_id(msg)
        assert cid == "discord:user-456"

    @pytest.mark.asyncio
    async def test_get_conversation_id_falls_back_to_source_user_id(self):
        batcher = await MessageBatcher.get_instance()
        msg = IncomingMessage(
            user_id=789,
            content="test",
            channel=None,
            channel_account_id=None,
            source="local",
        )
        cid = batcher.get_conversation_id(msg)
        assert cid == "local:789"

    @pytest.mark.asyncio
    async def test_active_batch_count_and_conversations(self, monkeypatch):
        _patch_config(monkeypatch, _cfg(window_seconds=2.0))
        batcher = await MessageBatcher.get_instance()

        assert await batcher.get_active_batch_count() == 0
        assert await batcher.get_active_conversations() == []

        await batcher.submit_message(self._make_message("x", user_id=111))
        await batcher.submit_message(self._make_message("y", user_id=222))
        await asyncio.sleep(0.05)

        assert await batcher.get_active_batch_count() == 2
        convs = await batcher.get_active_conversations()
        assert "qq:111" in convs
        assert "qq:222" in convs

    @pytest.mark.asyncio
    async def test_unregister_callback_removes_it(self, monkeypatch):
        _patch_config(monkeypatch, _cfg(enabled=False, window_seconds=1.0))
        batcher = await MessageBatcher.get_instance()
        called = []

        async def cb(msgs, bid):
            called.append(bid)

        batcher.register_callback(cb)
        batcher.unregister_callback(cb)

        await batcher.submit_message(self._make_message("test", user_id=999))
        await asyncio.sleep(0.05)
        assert len(called) == 0

    @pytest.mark.asyncio
    async def test_sequential_batches_across_completions(self, monkeypatch):
        """逐批串行: 上一批完成后, 下一条消息开启新一批并最终 flush 缓冲。"""
        _patch_config(monkeypatch, _cfg(window_seconds=5.0, max_batch_size=2))
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        # "1" -> aggregation window closes -> batch 1
        await batcher.submit_message(self._make_message("1", user_id=888))
        await asyncio.sleep(0.2)
        assert len(self.received_batches) == 1
        assert [m.content for m in self.received_batches[0][0]] == ["1"]

        # batch 1 completes -> next message starts a new window
        await batcher.on_batch_completed("qq:888")
        await batcher.submit_message(self._make_message("2", user_id=888))
        await asyncio.sleep(0.2)
        assert len(self.received_batches) == 2
        assert [m.content for m in self.received_batches[1][0]] == ["2"]

        # "3" arrives while batch 2 runs -> buffered, not dispatched
        await batcher.submit_message(self._make_message("3", user_id=888))
        await asyncio.sleep(0.05)
        assert len(self.received_batches) == 2

        # complete batch 2 -> "3" flushed as a new batch
        await batcher.on_batch_completed("qq:888")
        await asyncio.sleep(0.05)
        assert len(self.received_batches) == 3
        assert [m.content for m in self.received_batches[2][0]] == ["3"]

        assert self.received_batches[0][1] != self.received_batches[1][1]
        assert self.received_batches[1][1] != self.received_batches[2][1]

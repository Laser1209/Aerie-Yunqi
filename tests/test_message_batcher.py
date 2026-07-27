"""Tests for MessageBatcher: time windows, max batch size, conversation isolation."""

import asyncio
import pytest

from communication.message import IncomingMessage
from core.message_batcher import MessageBatcher, get_message_batcher


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
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": False,
                "window_seconds": 1.0,
                "max_batch_size": 5,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
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
    async def test_time_window_collects_multiple_messages(self, monkeypatch):
        """Messages sent within the window should be collected into one batch."""
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": True,
                "window_seconds": 0.3,
                "max_batch_size": 10,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("msg1", user_id=222))
        await asyncio.sleep(0.05)
        await batcher.submit_message(self._make_message("msg2", user_id=222))
        await asyncio.sleep(0.05)
        await batcher.submit_message(self._make_message("msg3", user_id=222))

        assert len(self.received_batches) == 0

        await asyncio.sleep(0.4)

        assert len(self.received_batches) == 1
        msgs, bid = self.received_batches[0]
        assert len(msgs) == 3
        contents = [m.content for m in msgs]
        assert contents == ["msg1", "msg2", "msg3"]
        assert len(bid) == 32

    @pytest.mark.asyncio
    async def test_max_batch_size_triggers_immediate_dispatch(self, monkeypatch):
        """When max_batch_size is reached, batch should be dispatched immediately."""
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": True,
                "window_seconds": 2.0,
                "max_batch_size": 3,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("a", user_id=333))
        await asyncio.sleep(0.01)
        await batcher.submit_message(self._make_message("b", user_id=333))
        await asyncio.sleep(0.01)
        assert len(self.received_batches) == 0

        await batcher.submit_message(self._make_message("c", user_id=333))
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 1
        msgs, bid = self.received_batches[0]
        assert len(msgs) == 3
        contents = [m.content for m in msgs]
        assert contents == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_conversation_isolation(self, monkeypatch):
        """Different conversations should have independent batches."""
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": True,
                "window_seconds": 0.3,
                "max_batch_size": 10,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("u1-1", user_id=100))
        await batcher.submit_message(self._make_message("u2-1", user_id=200))
        await batcher.submit_message(self._make_message("u1-2", user_id=100))
        await batcher.submit_message(self._make_message("u2-2", user_id=200))

        await asyncio.sleep(0.5)

        assert len(self.received_batches) == 2
        batch_sizes = sorted([len(b[0]) for b in self.received_batches])
        assert batch_sizes == [2, 2]

        conv1_contents = set()
        conv2_contents = set()
        for msgs, _ in self.received_batches:
            if msgs[0].user_id == 100:
                conv1_contents = {m.content for m in msgs}
            else:
                conv2_contents = {m.content for m in msgs}

        assert conv1_contents == {"u1-1", "u1-2"}
        assert conv2_contents == {"u2-1", "u2-2"}

    @pytest.mark.asyncio
    async def test_flush_all_dispatches_all_active_batches(self, monkeypatch):
        """flush_all() should immediately dispatch all pending batches."""
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": True,
                "window_seconds": 5.0,
                "max_batch_size": 100,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("f1", user_id=400))
        await batcher.submit_message(self._make_message("f2", user_id=500))
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 0
        assert await batcher.get_active_batch_count() == 2

        await batcher.flush_all()
        await asyncio.sleep(0.05)

        assert len(self.received_batches) == 2
        assert await batcher.get_active_batch_count() == 0

    @pytest.mark.asyncio
    async def test_batch_after_flush_starts_new_batch(self, monkeypatch):
        """After flushing, new messages should start a fresh batch."""
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": True,
                "window_seconds": 0.3,
                "max_batch_size": 10,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("first", user_id=600))
        await asyncio.sleep(0.05)
        await batcher.flush_all()
        await asyncio.sleep(0.05)
        assert len(self.received_batches) == 1

        await batcher.submit_message(self._make_message("second", user_id=600))
        await asyncio.sleep(0.5)
        assert len(self.received_batches) == 2
        assert len(self.received_batches[1][0]) == 1
        assert self.received_batches[1][0][0].content == "second"

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_break_other_callbacks(self, monkeypatch):
        """If one callback raises, other callbacks should still run."""
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": False,
                "window_seconds": 1.0,
                "max_batch_size": 5,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
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
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": True,
                "window_seconds": 2.0,
                "max_batch_size": 10,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
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
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": False,
                "window_seconds": 1.0,
                "max_batch_size": 5,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
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
    async def test_max_size_then_next_message_starts_new_batch(self, monkeypatch):
        """After a max_size batch, the next message starts a new batch with its own window."""
        monkeypatch.setattr(
            "core.message_batcher.get_message_batching_config",
            lambda: {
                "enabled": True,
                "window_seconds": 0.3,
                "max_batch_size": 2,
                "base_interval_seconds": 0.5,
                "chars_per_second": 4,
                "min_interval_seconds": 0.3,
                "max_interval_seconds": 5.0,
            },
        )
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect_callback)

        await batcher.submit_message(self._make_message("1", user_id=888))
        await batcher.submit_message(self._make_message("2", user_id=888))
        await asyncio.sleep(0.05)
        assert len(self.received_batches) == 1
        assert len(self.received_batches[0][0]) == 2

        await batcher.submit_message(self._make_message("3", user_id=888))
        await batcher.submit_message(self._make_message("4", user_id=888))
        await asyncio.sleep(0.05)
        assert len(self.received_batches) == 2
        assert len(self.received_batches[1][0]) == 2

        batch1_msgs = [m.content for m in self.received_batches[0][0]]
        batch2_msgs = [m.content for m in self.received_batches[1][0]]
        assert batch1_msgs == ["1", "2"]
        assert batch2_msgs == ["3", "4"]
        assert self.received_batches[0][1] != self.received_batches[1][1]

"""Gate 1 — RecallAdapter 端口分派与 RecallManager 隔离性测试."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from communication.recall.factory import get_recall_adapter
from communication.recall_manager import RecallManager, SentRecord


def _record(channel="qq", *, msg_id=1, qq_message_id=100):
    return SentRecord(
        user_id=1,
        content="hi",
        msg_id=msg_id,
        qq_message_id=qq_message_id,
        segments=["hi"],
        channel=channel,
        channel_account_id=str(1),
    )


class FakeQQ:
    is_connected = True

    def __init__(self, ok=True):
        self._ok = ok
        self.called = []

    async def recall_message(self, message_id):
        self.called.append(message_id)
        return self._ok


def test_qq_adapter_recall_ok():
    qq = FakeQQ(ok=True)
    adapter = get_recall_adapter("qq", qq_client=qq)
    can, why = adapter.can_recall(_record(qq_message_id=100))
    assert can and why == "ok"
    outcome = asyncio.run(adapter.recall(_record(qq_message_id=100)))
    assert outcome.recalled is True
    assert outcome.reason == "ok"
    assert qq.called == [100]
    assert adapter.local_mark_only() is False


def test_qq_adapter_no_msg_id():
    qq = FakeQQ()
    adapter = get_recall_adapter("qq", qq_client=qq)
    record = _record(qq_message_id=None)
    can, why = adapter.can_recall(record)
    assert can is False and why == "no_msg_id"
    outcome = asyncio.run(adapter.recall(record))
    assert outcome.recalled is False
    assert outcome.reason == "no_msg_id"


def test_local_adapter_local_mark():
    adapter = get_recall_adapter("local")
    assert adapter.local_mark_only() is True
    can, why = adapter.can_recall(_record(channel="local"))
    assert can and why == "ok"
    outcome = asyncio.run(adapter.recall(_record(channel="local")))
    assert outcome.recalled is True
    assert outcome.reason == "local_mark"


def test_wechat_adapter_unsupported():
    adapter = get_recall_adapter("clawbot")
    assert adapter.local_mark_only() is True
    can, why = adapter.can_recall(_record(channel="clawbot"))
    assert can is False and why == "not_implemented"
    outcome = asyncio.run(adapter.recall(_record(channel="clawbot")))
    assert outcome.recalled is False
    assert outcome.reason == "unsupported"


def test_unknown_channel_falls_back_to_local():
    adapter = get_recall_adapter("unknown-xyz")
    assert isinstance(adapter.local_mark_only(), bool)
    assert adapter.local_mark_only() is True


def test_recall_manager_channel_isolation():
    """同一 user_id 在 qq 与 local 两个 channel 互不干扰."""
    rm = RecallManager(config=None)
    # 只在 qq 记录
    rm.record_sent(1, "hello", msg_id=1, qq_message_id=100, channel="qq")
    # local 无记录 → can_recall false
    assert rm.can_recall(1, channel="local") == (False, "no_recent_message")
    # qq 有记录 → 可撤
    assert rm.can_recall(1, channel="qq")[0] is True
    # local 记录后独立
    rm.record_sent(1, "hi-local", msg_id=2, channel="local")
    assert rm.can_recall(1, channel="local")[0] is True
    # 撤回 qq 不影响 local 记录
    result = asyncio.run(rm.try_recall(1, channel="qq"))
    assert result["status"] == "ok"
    assert rm.can_recall(1, channel="local")[0] is True


def test_recall_manager_local_outcome():
    rm = RecallManager(config=None)
    rm.record_sent(1, "hello", msg_id=9, channel="local")
    result = asyncio.run(rm.try_recall(1, channel="local"))
    assert result["status"] == "ok"
    assert result["qq_recalled"] is True  # local 视为已撤回
    assert result["outcome"].reason == "local_mark"

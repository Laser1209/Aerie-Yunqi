"""Quick test for SendQueue batch interval calculation."""
import asyncio
import sys
import os
import logging

import pytest
from unittest.mock import AsyncMock

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.send_queue import SendQueue
from communication.message import OutgoingReply
from core.model_output import strip_thought_action_tags
from config.persona_loader import get_message_batching_config

_SEPARATED = "第一段在这里。\n---\n第二段在这里。\n---\n第三段在这里。"


class _FakeDb:
    """只记录 chat_log.update 调用，用于断言 qq_message_id 回填到哪一行。"""

    def __init__(self) -> None:
        self.updates: list[tuple] = []

    def query_one(self, *_args, **_kwargs):
        return None

    def update(self, table, values, where, params):
        self.updates.append((table, values, where, params))


def _no_wait(**_kwargs):
    return (0.0, "immediate")


async def mock_sender(reply: OutgoingReply) -> bool:
    return True


async def main():
    cfg = get_message_batching_config()
    print("=== Message Batching Config ===")
    for k, v in cfg.items():
        print(f"  {k}: {v}")
    print()

    sq = SendQueue(sender=mock_sender)

    test_cases = [
        ("50 chars plain", "你好呀，今天过得怎么样？我这边天气很好，正在想着你在做什么呢。" * 1),
        ("150 chars plain", "你好呀，今天过得怎么样？我这边天气很好，正在想着你在做什么呢。" * 3),
        ("50 chars with tags", "<thought>他发了三条消息</thought>你好呀，今天过得怎么样？<action>看着屏幕微笑。</action>" + "我在想你。" * 5),
        ("empty after strip", "<thought>只是思考</thought><action>只是动作</action>"),
    ]

    print("=== Interval Calculation Test (emotion_label=None -> neutral balanced) ===")
    print()

    for name, content in test_cases:
        plain = strip_thought_action_tags(content)
        char_count = len(plain)

        interval, style = sq._compute_batch_interval(
            reply_content=content,
            emotion_label=None,
            threshold_summary={},
            is_eruption=False,
            batch_id="test-batch-001",
            sequence_index=1,
        )

        print(f"Test: {name}")
        print(f"  Content preview: {content[:60]}...")
        print(f"  Plain text ({char_count} chars): {plain[:60]}...")
        print(f"  Computed interval: {interval:.3f}s")
        print(f"  Style: {style}")
        print()

    print("=== Interval vs Char Count (proportionality check) ===")
    print()
    for n in [10, 25, 50, 75, 100, 150, 200, 300]:
        text = "你" * n
        interval, style = sq._compute_batch_interval(
            reply_content=text,
            emotion_label=None,
            threshold_summary={},
            is_eruption=False,
            batch_id=f"test-{n}",
            sequence_index=1,
        )
        print(f"  {n:>4} chars -> {interval:>6.3f}s  (style={style})")

    print()
    print("=== Emotion Factor Test (50 chars) ===")
    print()
    text50 = "你" * 50
    for emotion in [None, "joy", "neutral", "sad", "fear", "anger", "affection"]:
        interval, style = sq._compute_batch_interval(
            reply_content=text50,
            emotion_label=emotion,
            threshold_summary={},
            is_eruption=False,
            batch_id=f"emotion-{emotion}",
            sequence_index=1,
        )
        print(f"  emotion={emotion or 'None':<10} -> {interval:.3f}s  ({style})")


if __name__ == "__main__":
    asyncio.run(main())


# ══════════════════════════════════════════════════════════════════
# 消息链路回归：分段回填（D5）、成功标志不是 id（D4）、
# 批量路径同切（D3）、空内容不外发（D2）
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_legacy_segments_backfill_their_own_chat_log_rows():
    """D5：落库一段一行，每段的 qq_message_id 只能回填到自己那一行。

    修复前所有段共用 `where id = 777`，后写覆盖先写，777 号行最终指向最后一段。
    """
    db = _FakeDb()
    sent: list[str] = []

    async def sender(reply: OutgoingReply) -> int:
        sent.append(reply.content)
        return 1000 + len(sent)

    queue = SendQueue(sender=sender, db=db, pacing=_no_wait)
    reply = OutgoingReply(user_id=1, content=_SEPARATED, msg_id=777)
    setattr(reply, "segment_msg_ids", [777, 778, 779])

    await queue._send_legacy_reply(reply)

    assert sent == ["第一段在这里。", "第二段在这里。", "第三段在这里。"]
    assert [u[3] for u in db.updates] == [(777,), (778,), (779,)]
    assert [u[1] for u in db.updates] == [
        {"qq_message_id": 1001},
        {"qq_message_id": 1002},
        {"qq_message_id": 1003},
    ]


@pytest.mark.asyncio
async def test_missing_segment_rows_only_backfill_first():
    """没有分段行 id 时只回填首段，绝不把整条都盖到首段那一行上。"""
    db = _FakeDb()
    queue = SendQueue(
        sender=AsyncMock(return_value=2002), db=db, pacing=_no_wait
    )
    reply = OutgoingReply(user_id=1, content=_SEPARATED, msg_id=777)

    await queue._send_legacy_reply(reply)

    assert [u[3] for u in db.updates] == [(777,)]


@pytest.mark.asyncio
async def test_success_flag_true_is_not_written_as_message_id():
    """D4：send_result=True 表示「没回 message_id」，不得写成伪 id 1。"""
    db = _FakeDb()
    queue = SendQueue(
        sender=AsyncMock(return_value=True), db=db, pacing=_no_wait
    )
    reply = OutgoingReply(user_id=1, content="你好。", msg_id=777)

    await queue._send_legacy_reply(reply)

    assert db.updates == []


@pytest.mark.asyncio
async def test_real_message_id_is_written():
    """对照组：平台回了真实 message_id 时必须落库。"""
    db = _FakeDb()
    queue = SendQueue(
        sender=AsyncMock(return_value=424242), db=db, pacing=_no_wait
    )
    reply = OutgoingReply(user_id=1, content="你好。", msg_id=777)

    await queue._send_legacy_reply(reply)

    assert db.updates == [("chat_log", {"qq_message_id": 424242}, "id = ?", (777,))]


@pytest.mark.asyncio
async def test_batch_reply_is_split_like_desktop():
    """D3：真·多消息批也要按同一 splitter 切段，QQ 收到条数与桌面一致。"""
    db = _FakeDb()
    sent: list[str] = []

    async def sender(reply: OutgoingReply) -> int:
        sent.append(reply.content)
        return 5000 + len(sent)

    queue = SendQueue(sender=sender, db=db, pacing=_no_wait)
    reply = OutgoingReply(
        user_id=1, content=_SEPARATED, msg_id=100, batch_id="b1"
    )
    setattr(reply, "segment_msg_ids", [100, 101, 102])

    await queue._send_batch_reply(reply, "b1")

    assert sent == ["第一段在这里。", "第二段在这里。", "第三段在这里。"]
    assert all("---" not in seg for seg in sent)
    assert [u[3] for u in db.updates] == [(100,), (101,), (102,)]


@pytest.mark.asyncio
async def test_batch_reply_without_content_sends_nothing():
    """D2：批量路径遇到纯分隔符/纯空白回复不得外发。"""
    sender = AsyncMock(return_value=True)
    queue = SendQueue(sender=sender, pacing=_no_wait)
    reply = OutgoingReply(
        user_id=1, content="---\n---\n---", msg_id=1, batch_id="b1"
    )

    await queue._send_batch_reply(reply, "b1")

    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_reply_without_content_sends_nothing():
    """D2：单条路径遇到纯分隔符/纯空白回复不得外发。"""
    sender = AsyncMock(return_value=True)
    queue = SendQueue(sender=sender, pacing=_no_wait)

    await queue._send_legacy_reply(
        OutgoingReply(user_id=1, content="---\n---\n---", msg_id=1)
    )
    await queue._send_legacy_reply(
        OutgoingReply(user_id=1, content="   ", msg_id=2)
    )

    sender.assert_not_awaited()

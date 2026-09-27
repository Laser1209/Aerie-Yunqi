"""Simple standalone test for MessageBatcher without pytest dependency.

注: 阶段 3 起首条消息走「聚合窗」(T_idle 静默 / T_cap 上限), 本文件的时序断言
已同步更新; 聚合窗专项用例见 tests/test_message_batcher_aggregation.py。
"""

import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.message import IncomingMessage
from core.message_batcher import MessageBatcher


def _make_msg(content, user_id=12345, channel="qq", channel_account_id=None):
    return IncomingMessage(
        user_id=user_id,
        content=content,
        msg_type="private",
        source="qq",
        channel=channel,
        channel_account_id=channel_account_id or str(user_id),
    )


def _config(**overrides):
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


@pytest.mark.asyncio
async def test_all(monkeypatch=None):
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  [PASS] {name}")
            passed += 1
        else:
            print(f"  [FAIL] {name}: {detail}")
            failed += 1

    def use_config(cfg):
        target = lambda: cfg  # noqa: E731
        if monkeypatch is not None:
            monkeypatch.setattr(
                "core.message_batcher.get_message_batching_config", target
            )
        else:
            import core.message_batcher as _mb

            _mb.get_message_batching_config = target

    # Test 1: Singleton
    print("\n=== Test 1: Singleton pattern ===")
    MessageBatcher.reset_instance()
    b1 = await MessageBatcher.get_instance()
    b2 = await MessageBatcher.get_instance()
    check("get_instance returns same object", b1 is b2)
    MessageBatcher.reset_instance()
    b3 = await MessageBatcher.get_instance()
    check("reset_instance creates new object", b1 is not b3)

    # Test 2: Disabled batching sends immediately
    print("\n=== Test 2: Disabled batching sends immediately ===")
    MessageBatcher.reset_instance()
    received = []

    async def cb1(msgs, bid):
        received.append((list(msgs), bid))

    use_config(_config(enabled=False, window_seconds=1.0))
    batcher = await MessageBatcher.get_instance()
    batcher.register_callback(cb1)
    await batcher.submit_message(_make_msg("hello", user_id=111))
    await asyncio.sleep(0.1)
    check("immediate dispatch when disabled", len(received) == 1, f"got {len(received)}")
    check("batch has 1 message", len(received[0][0]) == 1 if received else False)
    check("content matches", received[0][0][0].content == "hello" if received else False)
    check("batch_id is 32 chars hex", len(received[0][1]) == 32 if received else False)

    # Test 3: 首条聚合窗 - 窗口内的多条消息合并为一批
    print("\n=== Test 3: Aggregation window merges rapid messages ===")
    MessageBatcher.reset_instance()
    received = []

    async def cb2(msgs, bid):
        received.append((list(msgs), bid))

    use_config(_config(first_message_idle_seconds=0.2))
    batcher = await MessageBatcher.get_instance()
    batcher.register_callback(cb2)

    await batcher.submit_message(_make_msg("m1", user_id=222))
    await asyncio.sleep(0.05)
    await batcher.submit_message(_make_msg("m2", user_id=222))
    await asyncio.sleep(0.05)
    await batcher.submit_message(_make_msg("m3", user_id=222))
    check("not dispatched while aggregating", len(received) == 0, f"got {len(received)}")
    await asyncio.sleep(0.3)
    check("merged into one batch", len(received) == 1, f"got {len(received)}")
    contents = [m.content for m in received[0][0]] if received else []
    check("aggregated contents correct", contents == ["m1", "m2", "m3"], f"got {contents}")

    # Test 4: T_idle 内新消息重置计时
    print("\n=== Test 4: New message resets idle timer ===")
    MessageBatcher.reset_instance()
    received = []

    async def cb3(msgs, bid):
        received.append((list(msgs), bid))

    use_config(_config(first_message_idle_seconds=0.3))
    batcher = await MessageBatcher.get_instance()
    batcher.register_callback(cb3)

    await batcher.submit_message(_make_msg("a", user_id=333))
    await asyncio.sleep(0.15)
    await batcher.submit_message(_make_msg("b", user_id=333))
    await asyncio.sleep(0.15)
    check("timer reset keeps window open", len(received) == 0, f"got {len(received)}")
    await asyncio.sleep(0.3)
    check("dispatched after final idle", len(received) == 1, f"got {len(received)}")
    contents = [m.content for m in received[0][0]] if received else []
    check("contents a,b", contents == ["a", "b"], f"got {contents}")

    # Test 5: Conversation isolation
    print("\n=== Test 5: Conversation isolation ===")
    MessageBatcher.reset_instance()
    received = []

    async def cb4(msgs, bid):
        received.append((list(msgs), bid))

    use_config(_config(first_message_idle_seconds=0.1))
    batcher = await MessageBatcher.get_instance()
    batcher.register_callback(cb4)

    await batcher.submit_message(_make_msg("u1a", user_id=100))
    await batcher.submit_message(_make_msg("u2a", user_id=200))
    await asyncio.sleep(0.25)

    check("first batches dispatched", len(received) == 2, f"got {len(received)}")
    await batcher.submit_message(_make_msg("u1b", user_id=100))
    await batcher.submit_message(_make_msg("u2b", user_id=200))
    await batcher.on_batch_completed("qq:100")
    await batcher.on_batch_completed("qq:200")
    await asyncio.sleep(0.05)
    sizes = sorted([len(b[0]) for b in received])
    check("all batches preserve ordering", sizes == [1, 1, 1, 1], f"got {sizes}")
    u1_contents = set()
    u2_contents = set()
    for msgs, _ in received:
        if msgs[0].user_id == 100:
            u1_contents.update(m.content for m in msgs)
        else:
            u2_contents.update(m.content for m in msgs)
    check("user 1 messages isolated", u1_contents == {"u1a", "u1b"}, f"got {u1_contents}")
    check("user 2 messages isolated", u2_contents == {"u2a", "u2b"}, f"got {u2_contents}")

    # Test 6: flush_all
    print("\n=== Test 6: flush_all dispatches immediately ===")
    MessageBatcher.reset_instance()
    received = []

    async def cb5(msgs, bid):
        received.append((list(msgs), bid))

    use_config(_config(window_seconds=5.0, first_message_idle_seconds=5.0))
    batcher = await MessageBatcher.get_instance()
    batcher.register_callback(cb5)

    await batcher.submit_message(_make_msg("f1", user_id=400))
    await batcher.submit_message(_make_msg("f2", user_id=500))
    await asyncio.sleep(0.05)
    check("active count 2 before flush", await batcher.get_active_batch_count() == 2)
    check("nothing dispatched before flush", len(received) == 0)
    await batcher.flush_all()
    await asyncio.sleep(0.1)
    check("buffered flushed", len(received) == 2, f"got {len(received)}")
    check("active count 0 after flush", await batcher.get_active_batch_count() == 0)

    # Test 7: get_conversation_id
    print("\n=== Test 7: Conversation ID generation ===")
    MessageBatcher.reset_instance()
    batcher = await MessageBatcher.get_instance()
    msg_with_channel = IncomingMessage(
        user_id=123, content="test", channel="discord",
        channel_account_id="user-456", source="discord"
    )
    cid1 = batcher.get_conversation_id(msg_with_channel)
    check("uses channel:channel_account_id", cid1 == "discord:user-456", f"got {cid1}")

    msg_no_channel = IncomingMessage(
        user_id=789, content="test", channel=None,
        channel_account_id=None, source="local"
    )
    cid2 = batcher.get_conversation_id(msg_no_channel)
    check("falls back to source:user_id", cid2 == "local:789", f"got {cid2}")

    # Test 8: 上一批完成后开启新一批 + 聚合合并
    print("\n=== Test 8: New batch starts after completion ===")
    MessageBatcher.reset_instance()
    received = []

    async def cb6(msgs, bid):
        received.append((list(msgs), bid))

    use_config(_config(first_message_idle_seconds=0.1))
    batcher = await MessageBatcher.get_instance()
    batcher.register_callback(cb6)

    await batcher.submit_message(_make_msg("1", user_id=888))
    await asyncio.sleep(0.25)
    check("first batch dispatched", len(received) == 1, f"got {len(received)}")

    await batcher.on_batch_completed("qq:888")
    await batcher.submit_message(_make_msg("2", user_id=888))
    await batcher.submit_message(_make_msg("3", user_id=888))
    await batcher.submit_message(_make_msg("4", user_id=888))
    await asyncio.sleep(0.25)
    check("second batch dispatched", len(received) == 2, f"got {len(received)}")
    check("different batch_ids", len(received) == 2 and received[0][1] != received[1][1])
    b1_contents = [m.content for m in received[0][0]] if len(received) > 0 else []
    b2_contents = [m.content for m in received[1][0]] if len(received) > 1 else []
    check("batch1 is first message", b1_contents == ["1"], f"got {b1_contents}")
    check("batch2 contains aggregated messages", b2_contents == ["2", "3", "4"], f"got {b2_contents}")

    # Test 9: Callback exception doesn't break others
    print("\n=== Test 9: Callback exception isolation ===")
    MessageBatcher.reset_instance()
    bad_called = []
    good_called = []

    use_config(_config(enabled=False, window_seconds=1.0))
    batcher = await MessageBatcher.get_instance()

    async def bad_cb(msgs, bid):
        bad_called.append(bid)
        raise RuntimeError("intentional failure")

    async def good_cb(msgs, bid):
        good_called.append(bid)

    batcher.register_callback(bad_cb)
    batcher.register_callback(good_cb)
    await batcher.submit_message(_make_msg("test", user_id=700))
    await asyncio.sleep(0.1)
    check("bad callback was called", len(bad_called) == 1)
    check("good callback was called despite error", len(good_called) == 1)

    # Summary
    print("\n" + "=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(test_all(None))
    sys.exit(0 if success else 1)

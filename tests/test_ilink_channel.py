from unittest.mock import AsyncMock

import pytest

from communication.ilink.channel import ILinkChannel
from communication.ilink.models import GetUpdatesResponse
from core.ilink_state import ILinkStateStore


def message(
    message_id,
    sender,
    text,
    *,
    message_type=1,
    message_state=2,
    group_id=None,
    context_token=None,
):
    return {
        "message_id": message_id,
        "from_user_id": sender,
        "to_user_id": "bot-1",
        "client_id": f"client-{message_id}",
        "create_time_ms": 1_700_000_000_000 + message_id,
        "message_type": message_type,
        "message_state": message_state,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
        "context_token": context_token,
        "group_id": group_id,
    }


def response(cursor, *messages):
    return GetUpdatesResponse.from_dict(
        {"ret": 0, "msgs": list(messages), "get_updates_buf": cursor}
    )


def bind_owner(store):
    code = store.create_pairing_code("bot-1")
    assert store.verify_pairing("bot-1", "wx-owner", code, 3998874040)


@pytest.mark.asyncio
async def test_channel_filters_to_bound_owner_private_finished_text_and_deduplicates(tmp_path):
    store = ILinkStateStore(tmp_path / "state.db")
    bind_owner(store)
    client = AsyncMock()
    client.get_updates.side_effect = [
        response(
            "cursor-1",
            message(1, "wx-owner", "本人消息", context_token="context-1"),
            message(2, "wx-owner", "生成中", message_state=1),
            message(3, "wx-owner", "机器人消息", message_type=2),
            message(4, "wx-owner", "群消息", group_id="group-1"),
            message(5, "wx-stranger", "陌生人消息"),
        ),
        response("cursor-2", message(1, "wx-owner", "本人消息", context_token="context-1")),
    ]
    received = []
    channel = ILinkChannel(client, store, "bot-1", 3998874040, received.append)

    await channel.poll_once()
    await channel.poll_once()

    assert len(received) == 1
    incoming = received[0]
    assert incoming.user_id == 3998874040
    assert incoming.content == "本人消息"
    assert incoming.source == "ilink"
    assert incoming.channel == "ilink"
    assert incoming.channel_account_id == "wx-owner"
    assert incoming.platform_message_id == 1
    assert incoming.timestamp == pytest.approx(1_700_000_000.001)
    assert store.get_cursor("bot-1") == "cursor-2"
    assert store.get_context_token("bot-1") == "context-1"
    store.close()


@pytest.mark.asyncio
async def test_channel_pairs_first_matching_private_text_without_forwarding_it(tmp_path):
    store = ILinkStateStore(tmp_path / "state.db")
    code = store.create_pairing_code("bot-1")
    client = AsyncMock()
    client.get_updates.side_effect = [
        response("cursor-1", message(1, "wx-owner", code)),
        response("cursor-2", message(2, "wx-owner", "配对后的消息", context_token="context-2")),
    ]
    callback = AsyncMock()
    channel = ILinkChannel(client, store, "bot-1", 3998874040, callback)

    await channel.poll_once()
    assert store.get_binding("bot-1").ilink_user_id == "wx-owner"
    callback.assert_not_awaited()

    await channel.poll_once()
    callback.assert_awaited_once()
    assert callback.await_args.args[0].content == "配对后的消息"
    store.close()


@pytest.mark.asyncio
async def test_channel_retries_message_when_text_callback_fails(tmp_path):
    store = ILinkStateStore(tmp_path / "state.db")
    bind_owner(store)
    duplicate = message(1, "wx-owner", "需要重试", context_token="context-1")
    client = AsyncMock()
    client.get_updates.side_effect = [response("cursor-1", duplicate), response("cursor-1", duplicate)]
    callback = AsyncMock(side_effect=[RuntimeError("failed"), None])
    channel = ILinkChannel(client, store, "bot-1", 3998874040, callback)

    with pytest.raises(RuntimeError, match="failed"):
        await channel.poll_once()
    await channel.poll_once()

    assert callback.await_count == 2
    assert store.get_cursor("bot-1") == "cursor-1"
    store.close()


# ── 2026-09-27 修复回归：入站可观测性 / 未绑定引导 / 整批不因单条畸形而失败 ──


def test_private_finished_user_text_reports_skip_reason():
    """被过滤的用户消息必须给出可诊断原因，而不是静默返回 None。"""
    from communication.ilink.models import WeixinMessage

    ok = WeixinMessage.from_dict(message(1, "wx-owner", "在工作室吗"))
    text, reason = ILinkChannel._private_finished_user_text(ok)
    assert text == "在工作室吗"
    assert reason == ""

    generating = WeixinMessage.from_dict(message(2, "wx-owner", "生成中", message_state=1))
    assert ILinkChannel._private_finished_user_text(generating) == (
        None,
        "not_finished_private_message",
    )

    grouped = WeixinMessage.from_dict(message(3, "wx-owner", "群聊", group_id="g-1"))
    assert ILinkChannel._private_finished_user_text(grouped) == (
        None,
        "not_finished_private_message",
    )

    from_bot = WeixinMessage.from_dict(message(4, "bot-1", "回声", message_type=2))
    assert ILinkChannel._private_finished_user_text(from_bot) == (None, "not_user_message")

    no_text = WeixinMessage.from_dict(
        {
            "message_id": 5,
            "from_user_id": "wx-owner",
            "to_user_id": "bot-1",
            "client_id": "c5",
            "create_time_ms": 1,
            "message_type": 1,
            "message_state": 2,
            "item_list": [{"type": 2, "image_item": {"url": "https://x/y.png"}}],
        }
    )
    assert ILinkChannel._private_finished_user_text(no_text) == (None, "no_text_item")


@pytest.mark.asyncio
async def test_unbound_channel_replies_with_pairing_hint_once(tmp_path):
    """未绑定收到消息时回一条配对引导，且节流不刷屏。"""
    store = ILinkStateStore(tmp_path / "state.db")
    store.create_pairing_code("bot-1")
    client = AsyncMock()
    client.get_updates.side_effect = [
        response("cursor-1", message(1, "wx-owner", "在工作室吗", context_token="ctx-1")),
        response("cursor-2", message(2, "wx-owner", "还在吗", context_token="ctx-1")),
    ]
    callback = AsyncMock()
    channel = ILinkChannel(client, store, "bot-1", 3998874040, callback)

    await channel.poll_once()
    await channel.poll_once()

    # 消息本身不进对话主链路
    callback.assert_not_awaited()
    # 但用户会收到一次明确的配对引导（第二条被节流）
    assert client.send_text.await_count == 1
    args = client.send_text.await_args.args
    assert args[0] == "wx-owner"
    assert "8 位配对码" in args[1]
    assert args[2] == "ctx-1"
    store.close()


@pytest.mark.asyncio
async def test_unbound_channel_sends_no_hint_without_context_token(tmp_path):
    store = ILinkStateStore(tmp_path / "state.db")
    store.create_pairing_code("bot-1")
    client = AsyncMock()
    client.get_updates.side_effect = [
        response("cursor-1", message(1, "wx-owner", "在工作室吗")),
    ]
    channel = ILinkChannel(client, store, "bot-1", 3998874040, AsyncMock())

    await channel.poll_once()

    client.send_text.assert_not_awaited()
    store.close()


@pytest.mark.asyncio
async def test_poll_keeps_usable_messages_when_one_is_malformed(tmp_path):
    """单条畸形消息只丢自己，不能连坐整批（否则游标不推进=永久收不到）。"""
    store = ILinkStateStore(tmp_path / "state.db")
    bind_owner(store)
    malformed = {
        "message_id": 3,
        "from_user_id": "wx-owner",
        "to_user_id": "bot-1",
        "client_id": "c3",
        "create_time_ms": 1,
        "message_type": 1,
        "message_state": 2,
        "item_list": "not-an-array",  # item_list 非法
    }
    missing_sender = {
        "message_id": 4,
        "to_user_id": "bot-1",
        "client_id": "c4",
        "create_time_ms": 1,
        "message_type": 1,
        "message_state": 2,
        "item_list": [{"type": 1, "text_item": {"text": "无发送者"}}],
    }
    client = AsyncMock()
    client.get_updates.side_effect = [
        response(
            "cursor-1",
            malformed,
            message(1, "wx-owner", "好消息", context_token="ctx-1"),
            missing_sender,
        ),
    ]
    received = []
    channel = ILinkChannel(client, store, "bot-1", 3998874040, received.append)

    await channel.poll_once()

    # 可解析的那条必须照常送达，游标必须推进
    assert [m.content for m in received] == ["好消息"]
    assert store.get_cursor("bot-1") == "cursor-1"
    store.close()


def test_get_updates_response_reports_skipped_messages():
    good = message(1, "wx-owner", "好")
    parsed = GetUpdatesResponse.from_dict(
        {"ret": 0, "msgs": [{"item_list": "bad"}, good], "get_updates_buf": "c1"}
    )
    assert parsed.skipped_messages == 1
    assert len(parsed.messages) == 1
    assert parsed.messages[0].from_user_id == "wx-owner"


def test_weixin_message_tolerates_empty_client_id_and_missing_time():
    """client_id / create_time_ms 缺失或为空不该丢掉真实用户消息。"""
    from communication.ilink.models import WeixinMessage

    m = WeixinMessage.from_dict(
        {
            "message_id": 7,
            "from_user_id": "wx-owner",
            "to_user_id": "bot-1",
            "message_type": 1,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
        }
    )
    assert m.client_id == ""
    assert m.create_time_ms == 0

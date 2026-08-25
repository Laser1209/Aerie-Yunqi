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

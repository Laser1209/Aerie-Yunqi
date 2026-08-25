import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from communication.message import IncomingMessage, OutgoingReply
from communication.send_queue import SendQueue
from core.companion import Companion


def ilink_reply(content="回复", batch_id=None):
    return OutgoingReply(
        user_id=3998874040,
        content=content,
        channel="ilink",
        channel_account_id="wx-owner",
        batch_id=batch_id,
    )


@pytest.mark.asyncio
async def test_send_queue_dispatches_ilink_without_changing_qq_sender():
    qq_sender = AsyncMock(return_value=True)
    ilink_sender = AsyncMock(return_value=True)
    queue = SendQueue(
        sender=qq_sender,
        channel_senders={"ilink": ilink_sender},
        pacing=lambda **_kwargs: (0, "immediate"),
    )

    await queue._send_batch_reply(ilink_reply(batch_id="batch-1"), "batch-1")
    qq_reply = OutgoingReply(user_id=3998874040, content="QQ回复")
    await queue._send_batch_reply(qq_reply, "batch-2")

    ilink_sender.assert_awaited_once()
    assert ilink_sender.await_args.args[0].channel_account_id == "wx-owner"
    qq_sender.assert_awaited_once_with(qq_reply)


@pytest.mark.asyncio
async def test_companion_ilink_callback_uses_shared_incoming_path():
    companion = Companion.__new__(Companion)
    companion._submit_incoming_message = AsyncMock()
    incoming = IncomingMessage(
        user_id=3998874040,
        content="微信消息",
        source="ilink",
        channel="ilink",
        channel_account_id="wx-owner",
        context={"token": "context-1"},
    )

    await companion._on_ilink_message(incoming)

    companion._submit_incoming_message.assert_awaited_once_with(incoming)


@pytest.mark.asyncio
async def test_companion_ilink_lifecycle_starts_and_stops_gateway():
    companion = Companion.__new__(Companion)
    companion.settings = {"ilink": {"enabled": True}}
    companion.ilink_gateway = SimpleNamespace(
        is_configured=MagicMock(return_value=True),
        start=AsyncMock(),
        stop=AsyncMock(),
    )
    companion.ilink_state_store = MagicMock()

    await companion._start_ilink_gateway()
    await companion._stop_ilink_gateway()

    companion.ilink_gateway.start.assert_awaited_once()
    companion.ilink_gateway.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_companion_ilink_stop_is_idempotent():
    companion = Companion.__new__(Companion)
    companion.ilink_gateway = AsyncMock()
    companion.ilink_state_store = MagicMock()

    await companion._stop_ilink_gateway()
    await companion._stop_ilink_gateway()

    companion.ilink_gateway.stop.assert_awaited_once()
    companion.ilink_state_store.close.assert_called_once()


@pytest.mark.asyncio
async def test_companion_skips_unconfigured_ilink_without_blocking_startup():
    companion = Companion.__new__(Companion)
    companion.settings = {"ilink": {"enabled": True}}
    companion.ilink_gateway = SimpleNamespace(
        is_configured=MagicMock(return_value=False),
        start=AsyncMock(),
    )

    await companion._start_ilink_gateway()

    companion.ilink_gateway.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_companion_sends_ilink_reply_with_original_address_using_gateway_state():
    companion = Companion.__new__(Companion)
    companion.ilink_gateway = SimpleNamespace(send_text=AsyncMock(return_value=True))
    reply = ilink_reply()

    sent = await companion._send_to_ilink(reply)

    assert sent is True
    companion.ilink_gateway.send_text.assert_awaited_once_with(
        "wx-owner",
        "回复",
    )


@pytest.mark.asyncio
async def test_send_queue_delivers_ilink_batch_in_order():
    delivered = []

    async def ilink_sender(reply):
        delivered.append(reply.content)
        return True

    queue = SendQueue(
        sender=AsyncMock(return_value=True),
        channel_senders={"ilink": ilink_sender},
        pacing=lambda **_kwargs: (0, "immediate"),
    )
    replies = [
        ilink_reply("回复一", "batch-1"),
        ilink_reply("回复二", "batch-1"),
    ]
    replies[0].sequence_index = 0
    replies[1].sequence_index = 1

    queue.enqueue_batch(replies)
    queue._running = True
    worker = asyncio.create_task(queue._worker())
    while len(delivered) < 2:
        await asyncio.sleep(0)
    queue._running = False
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    assert delivered == ["回复一", "回复二"]

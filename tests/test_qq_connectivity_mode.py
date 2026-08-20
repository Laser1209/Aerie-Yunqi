from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from communication import qq_client as qq_client_module
from communication.qq_client import QQClient, STATE_LOGGED_IN


@pytest.mark.asyncio
async def test_connectivity_mode_discards_private_messages(monkeypatch):
    monkeypatch.delenv("AERIE_DISABLE_QQ", raising=False)
    monkeypatch.setenv("AERIE_QQ_CONNECTIVITY_TEST", "1")
    client = QQClient({"ws_port": 3001})
    handler = AsyncMock()
    client.set_message_handler(handler)

    await client._on_engine_event(
        {
            "post_type": "message",
            "message_type": "private",
            "self_id": 123456789,
            "user_id": 987654321,
            "raw_message": "private sentinel must not be parsed",
            "message": "private sentinel must not be parsed",
        }
    )

    handler.assert_not_awaited()
    assert client.self_id == 0


@pytest.mark.asyncio
async def test_connectivity_mode_rejects_all_mutating_qq_actions(monkeypatch):
    monkeypatch.delenv("AERIE_DISABLE_QQ", raising=False)
    monkeypatch.setenv("AERIE_QQ_CONNECTIVITY_TEST", "true")
    monkeypatch.setattr(qq_client_module, "_port_is_open", lambda *_args, **_kwargs: True)
    client = QQClient({"ws_port": 3001})
    client._engine._connected = True
    client._rpc_call = AsyncMock(side_effect=AssertionError("mutating RPC attempted"))

    assert await client.send_message(123, "must not send") is False
    assert await client.recall_message(456) is False
    assert await client.send_poke(123) is False
    assert await client.send_message_with_segments(
        123, [{"type": "text", "data": {"text": "must not send"}}]
    ) is False
    client._rpc_call.assert_not_awaited()


def test_companion_connectivity_mode_does_not_resume_or_greet(monkeypatch):
    from core.companion import Companion

    scheduled = []
    monkeypatch.setattr(
        "core.companion.asyncio.create_task",
        lambda coroutine: scheduled.append(coroutine),
    )
    scheduler = SimpleNamespace(
        is_paused=True,
        paused_reason="qq_offline",
        resume=lambda: (_ for _ in ()).throw(AssertionError("push resumed")),
    )
    companion = Companion.__new__(Companion)
    companion.qq = SimpleNamespace(connectivity_test=True)
    companion.push_scheduler = scheduler
    companion._boot_greeting_fired = False

    companion._on_qq_state_change(STATE_LOGGED_IN)

    assert scheduled == []
    assert companion._boot_greeting_fired is False

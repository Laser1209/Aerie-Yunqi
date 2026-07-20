import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import api_server, event_stream
from core.api_server import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_event_stream_state():
    event_stream._reset_for_tests()
    yield
    event_stream._reset_for_tests()


def _payload_from_frame(frame: str) -> dict:
    for line in frame.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    raise AssertionError(f"missing data line in frame: {frame!r}")


@pytest.mark.asyncio
async def test_stream_v1_replays_missed_events_after_last_event_id():
    event_stream.publish("assistant", {"event_id": "evt_replay_1", "content": "old"})
    event_stream.publish("assistant", {"event_id": "evt_replay_2", "content": "new"})

    gen = event_stream.stream(
        last_event_id="evt_replay_1",
        replay=True,
        include_event_id=True,
    )
    try:
        open_frame = await anext(gen)
        replay_frame = await anext(gen)
    finally:
        await gen.aclose()

    assert "stream_open" in open_frame
    assert replay_frame.startswith("id: evt_replay_2\n")
    assert _payload_from_frame(replay_frame)["event_id"] == "evt_replay_2"


@pytest.mark.asyncio
async def test_stream_v1_live_events_include_sse_id():
    gen = event_stream.stream(replay=True, include_event_id=True)
    try:
        await anext(gen)
        event_stream.publish(
            "assistant",
            {"event_id": "evt_live_1", "content": "hello"},
        )
        frame = await anext(gen)
    finally:
        await gen.aclose()

    assert frame.startswith("id: evt_live_1\n")
    assert _payload_from_frame(frame)["event_id"] == "evt_live_1"


@pytest.mark.asyncio
async def test_legacy_stream_path_keeps_data_only_frames():
    gen = event_stream.stream()
    try:
        await anext(gen)
        event_stream.publish(
            "assistant",
            {"event_id": "evt_legacy_1", "content": "legacy"},
        )
        frame = await anext(gen)
    finally:
        await gen.aclose()

    assert frame.startswith("data: ")
    assert not frame.startswith("id: ")
    assert _payload_from_frame(frame)["event_id"] == "evt_legacy_1"


def test_events_endpoint_passes_last_event_id_only_when_stream_flag_enabled(
    monkeypatch,
):
    captured = []

    async def fake_stream(**kwargs):
        captured.append(kwargs)
        yield "data: {}\n\n"

    monkeypatch.setattr(api_server, "event_stream_generator", fake_stream)
    monkeypatch.setattr(
        api_server,
        "FeatureFlags",
        lambda: SimpleNamespace(is_enabled=lambda name: name == "chat_stream_v1"),
    )

    response = client.get(
        "/api/events/stream",
        headers={"Last-Event-ID": "evt_cursor_1"},
    )

    assert response.status_code == 200
    assert captured == [
        {
            "last_event_id": "evt_cursor_1",
            "replay": True,
            "include_event_id": True,
        }
    ]


def test_events_endpoint_flag_off_keeps_legacy_stream_call(monkeypatch):
    captured = []

    async def fake_stream(**kwargs):
        captured.append(kwargs)
        yield "data: {}\n\n"

    monkeypatch.setattr(api_server, "event_stream_generator", fake_stream)
    monkeypatch.setattr(
        api_server,
        "FeatureFlags",
        lambda: SimpleNamespace(is_enabled=lambda _name: False),
    )

    response = client.get(
        "/api/events/stream",
        headers={"Last-Event-ID": "evt_cursor_ignored"},
    )

    assert response.status_code == 200
    assert captured == [{}]

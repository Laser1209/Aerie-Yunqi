"""Phase 13 world sidecar persistence, outbox, ACK, and supervisor contracts."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from core.world_port import Observation


def test_world_sidecar_store_outbox_ack_and_restart_replay(tmp_path):
    from world_service.storage.sqlite_store import WorldSidecarStore

    db_path = tmp_path / "world.db"
    store = WorldSidecarStore(db_path)
    first = store.append_event(
        topic="world.state",
        event_type="world.snapshot.updated",
        payload={"phase": "morning", "secret": "do not leak"},
        idempotency_key="tick-1",
    )
    duplicate = store.append_event(
        topic="world.state",
        event_type="world.snapshot.updated",
        payload={"phase": "morning", "secret": "changed"},
        idempotency_key="tick-1",
    )

    assert first["seq"] == 1
    assert duplicate["seq"] == first["seq"]
    assert duplicate["event_id"] == first["event_id"]
    assert "do not leak" not in json.dumps(first, ensure_ascii=False)

    pending = store.events_after(consumer_id="core", last_seq=0)
    assert [event["seq"] for event in pending] == [1]
    assert pending[0]["payload"]["payload_keys"] == ["phase", "secret"]
    assert "payload_sha256" in pending[0]["payload"]

    store.ack(consumer_id="core", seq=1)
    restarted = WorldSidecarStore(db_path)
    assert restarted.cursor("core") == 1
    assert restarted.events_after(consumer_id="core", last_seq=1) == []

    second = restarted.append_event(
        topic="world.state",
        event_type="world.snapshot.updated",
        payload={"phase": "afternoon"},
        idempotency_key="tick-2",
    )
    replay = restarted.events_after(consumer_id="core")
    assert [event["seq"] for event in replay] == [2]
    assert second["seq"] == 2


def test_world_sidecar_store_heartbeat_checkpoint_and_single_owner_tables(tmp_path):
    from world_service.storage.sqlite_store import WorldSidecarStore

    store = WorldSidecarStore(tmp_path / "world.db")
    heartbeat = store.heartbeat(status="ready", detail={"token": "secret-token"})
    checkpoint = store.checkpoint(
        checkpoint_id="cp-1",
        state={"phase": "night", "raw_text": "secret text"},
    )

    tables = store.table_names()
    assert {
        "world_state_snapshot",
        "world_outbox",
        "world_ack_cursor",
        "world_heartbeat",
        "world_checkpoint",
    }.issubset(tables)
    assert heartbeat["status"] == "ready"
    assert "secret-token" not in json.dumps(heartbeat, ensure_ascii=False)
    assert checkpoint["checkpoint_id"] == "cp-1"
    assert "secret text" not in json.dumps(checkpoint, ensure_ascii=False)


@pytest.mark.asyncio
async def test_remote_world_adapter_crash_degrades_without_blocking_chat(tmp_path):
    from core.world_adapters.remote import RemoteWorldAdapter
    from world_service.main import LocalWorldSidecarService

    service = LocalWorldSidecarService(data_dir=tmp_path)
    adapter = RemoteWorldAdapter(service, fallback_reason="sidecar_unavailable")

    state = await adapter.get_state()
    assert state.source == "remote"
    assert state.status == "running"

    service.crash()
    degraded = await adapter.get_state()
    await adapter.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "must not leak"},
            idempotency_key="obs-crash",
        )
    )

    assert degraded.status == "degraded"
    assert degraded.source == "remote"
    assert degraded.capabilities == ()


@pytest.mark.asyncio
async def test_remote_world_adapter_reconnect_replays_without_duplicates(tmp_path):
    from core.world_adapters.remote import RemoteWorldAdapter
    from world_service.main import LocalWorldSidecarService

    service = LocalWorldSidecarService(data_dir=tmp_path)
    adapter = RemoteWorldAdapter(service, consumer_id="core")
    await adapter.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "hello"},
            idempotency_key="obs-1",
        )
    )
    first = await adapter.replay_events()
    await adapter.ack(first[-1].sequence)

    restarted = LocalWorldSidecarService(data_dir=tmp_path)
    restarted_adapter = RemoteWorldAdapter(restarted, consumer_id="core")
    replay_after_ack = await restarted_adapter.replay_events()
    await restarted_adapter.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "hello"},
            idempotency_key="obs-1",
        )
    )
    replay_duplicate = await restarted_adapter.replay_events()

    assert [event.sequence for event in first] == [1]
    assert replay_after_ack == []
    assert replay_duplicate == []


def test_electron_plugin_supervisor_heartbeat_and_crash_loop_redacted():
    script = r"""
const { createPluginSupervisor } = require("./electron/src/plugin-supervisor");
const supervisor = createPluginSupervisor({ maxCrashes: 2, now: (() => {
  let t = 1000;
  return () => t += 100;
})() });
supervisor.register("aerie.world", { command: "python", token: "secret-token-value" });
supervisor.recordHeartbeat("aerie.world", { status: "ready", token: "secret-token-value" });
supervisor.recordCrash("aerie.world", { code: 1, token: "secret-token-value" });
supervisor.recordCrash("aerie.world", { code: 1 });
const status = supervisor.status("aerie.world");
if (status.state !== "fused") throw new Error("expected fused state: " + status.state);
const audit = JSON.stringify(status);
if (audit.includes("secret-token-value")) throw new Error("secret leaked");
if (status.crashCount !== 2) throw new Error("unexpected crash count");
"""
    subprocess.run(
        ["node", "-e", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        check=True,
        capture_output=True,
        text=True,
    )


def test_core_event_stream_publishes_world_event_once():
    from core import event_stream

    event_stream._reset_for_tests()
    first = event_stream.publish_world_event_once(
        {
            "event_id": "world_evt_1",
            "topic": "world.state",
            "event_type": "world.snapshot.updated",
            "seq": 9,
            "payload": {"payload_keys": ["phase"]},
        }
    )
    second = event_stream.publish_world_event_once(
        {
            "event_id": "world_evt_1",
            "topic": "world.state",
            "event_type": "world.snapshot.updated",
            "seq": 9,
            "payload": {"payload_keys": ["phase"]},
        }
    )
    replay = event_stream._events_after("missing")

    assert first is True
    assert second is False
    assert len(replay) == 1
    assert replay[0]["type"] == "world_event"

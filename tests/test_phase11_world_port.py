"""Phase 11 WorldPort host contracts."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.world_port import (
    InProcessWorldAdapter,
    NullWorldAdapter,
    Observation,
    WorldCapabilityBroker,
    build_world_port,
)


@pytest.mark.asyncio
async def test_null_world_adapter_is_safe_disabled_contract():
    port = NullWorldAdapter(reason="flag_off")

    state = await port.get_state()
    await port.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "do not leak this password"},
            idempotency_key="obs-1",
        )
    )
    await port.pause()
    await port.resume()
    after = await port.get_state()

    assert state.status == "disabled"
    assert state.source == "null"
    assert state.capabilities == ()
    assert after.revision == state.revision
    assert "password" not in json.dumps(after.to_public_dict(), ensure_ascii=False)

    events = []
    async for event in port.subscribe(["observations"]):
        events.append(event)
    assert events == []


@pytest.mark.asyncio
async def test_inprocess_world_adapter_five_interface_contract_and_redaction():
    port = InProcessWorldAdapter(instance_id="world-test")

    async def get_next_event():
        async for event in port.subscribe(["observations"]):
            return event
        raise AssertionError("subscription ended without an event")

    event_task = asyncio.create_task(get_next_event())
    await asyncio.sleep(0)

    await port.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "secret token should not appear", "mood": "warm"},
            idempotency_key="obs-2",
        )
    )
    event = await asyncio.wait_for(event_task, timeout=1)
    state = await port.get_state()

    assert event.topic == "observations"
    assert event.sequence == 1
    assert event.payload["observation_type"] == "user_message"
    assert event.payload["payload_keys"] == ["mood", "text"]
    assert "payload_sha256" in event.payload
    assert "secret token" not in json.dumps(event.to_public_dict(), ensure_ascii=False)
    assert state.status == "running"
    assert state.source == "in_process"
    assert state.revision == 1

    await port.pause()
    paused = await port.get_state()
    await port.resume()
    resumed = await port.get_state()

    assert paused.status == "paused"
    assert resumed.status == "running"
    assert resumed.revision > state.revision


@pytest.mark.asyncio
async def test_inprocess_observe_idempotency_does_not_duplicate_events():
    port = InProcessWorldAdapter(instance_id="world-idem")
    observation = Observation(
        observation_type="user_message",
        actor_id="actor-master",
        channel="desktop",
        payload={"text": "same event"},
        idempotency_key="obs-same",
    )

    await port.observe(observation)
    first = await port.get_state()
    await port.observe(observation)
    second = await port.get_state()

    assert first.revision == 1
    assert first.sequence == 1
    assert second.revision == first.revision
    assert second.sequence == first.sequence


def test_world_capability_broker_grants_only_whitelisted_capabilities_and_redacts():
    broker = WorldCapabilityBroker()

    result = broker.negotiate(
        plugin_id="aerie.world",
        requested=[
            "world.read",
            "events.subscribe",
            "qq.credential.read",
            "shell.execute",
            "world.read",
        ],
        metadata={
            "session_token": "secret-token-value",
            "port": 49152,
        },
    )

    assert result.granted == ("world.read", "events.subscribe")
    assert result.denied == ("qq.credential.read", "shell.execute")
    audit_json = json.dumps(result.audit_record, ensure_ascii=False)
    assert "secret-token-value" not in audit_json
    assert result.audit_record["metadata_keys"] == ["port", "session_token"]


def test_build_world_port_respects_world_inprocess_feature_flag():
    disabled = build_world_port(
        feature_flags=SimpleNamespace(is_enabled=lambda name: False)
    )
    enabled = build_world_port(
        feature_flags=SimpleNamespace(is_enabled=lambda name: name == "world_inprocess_v1"),
        instance_id="world-enabled",
    )

    assert isinstance(disabled, NullWorldAdapter)
    assert isinstance(enabled, InProcessWorldAdapter)


def test_electron_capability_broker_is_narrow_and_redacted():
    script = r"""
const { createCapabilityBroker } = require("./electron/src/capability-broker");
const broker = createCapabilityBroker();
const result = broker.negotiate("aerie.world", [
  "world.read",
  "events.subscribe",
  "qq.credential.read",
  "shell.execute",
  "world.read",
], { sessionToken: "secret-token-value", port: 49152 });
if (JSON.stringify(result.granted) !== JSON.stringify(["world.read", "events.subscribe"])) {
  throw new Error("unexpected granted: " + JSON.stringify(result.granted));
}
if (JSON.stringify(result.denied) !== JSON.stringify(["qq.credential.read", "shell.execute"])) {
  throw new Error("unexpected denied: " + JSON.stringify(result.denied));
}
const audit = JSON.stringify(result.audit);
if (audit.includes("secret-token-value")) {
  throw new Error("sensitive metadata value leaked");
}
"""
    subprocess.run(
        ["node", "-e", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_companion_initializes_world_port_without_starting_world_loop(phase4_db):
    from core.companion import Companion

    companion = Companion(
        settings={"qq": {"self_qq": 7, "friends": [], "startup_wait_timeout": 0.01}},
        database=phase4_db,
    )

    state = await companion.world_port.get_state()

    assert state.status == "disabled"
    assert state.source == "null"
    assert companion.pipeline is not None

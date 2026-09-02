"""Runtime config and authenticated World lifecycle acceptance tests."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import pytest

from core.runtime_config import (
    RuntimeConfigConflict,
    RuntimeConfigService,
    RuntimeConfigValidationError,
)
from core.world_adapters.remote import HttpWorldSidecarClient, RemoteWorldAdapter
from world_service.main import LocalWorldSidecarService, create_http_server


def test_runtime_config_precedence_redaction_revision_and_conflict(tmp_path):
    state_path = tmp_path / "runtime.json"
    service = RuntimeConfigService(
        state_path=state_path,
        defaults={"primary_user_id": "yaml-user"},
        env={"AERIE_PRIMARY_USER_ID": "env-user"},
    )

    assert service.get_effective("primary_user_id") == "env-user"
    assert service.snapshot()["values"]["primary_user_id"]["source"] == "environment"
    assert not state_path.exists()

    updated = service.update(
        {
            "runtime_control_v1": True,
            "world_sidecar_v1": True,
            "world_process_supervision_v1": True,
            "world_dashboard_control_v1": True,
            "world_runtime_loop_v1": True,
        },
        expected_revision=0,
    )
    assert updated["revision"] == 1
    assert state_path.exists()
    assert "env-user" in json.dumps(updated, ensure_ascii=False)

    with pytest.raises(RuntimeConfigConflict) as conflict:
        service.update({"world_sidecar_v1": False}, expected_revision=0)
    assert conflict.value.current == 1


def test_runtime_config_rejects_disabled_dependencies(tmp_path):
    service = RuntimeConfigService(state_path=tmp_path / "runtime.json", env={})
    with pytest.raises(RuntimeConfigValidationError) as error:
        service.update({"world_process_supervision_v1": True}, expected_revision=0)
    assert error.value.errors[0]["code"] == "dependency_disabled"


def test_world_24_hour_clock_pause_resume_and_checkpoint_restore(tmp_path):
    current = [datetime(2026, 7, 26, 0, 0, tzinfo=timezone.utc)]
    service = LocalWorldSidecarService(
        data_dir=tmp_path,
        clock=lambda: current[0],
        checkpoint_interval_seconds=1,
    )
    phases = []
    for hour in range(24):
        current[0] = datetime(2026, 7, 26, hour, 0, tzinfo=timezone.utc)
        phases.append(service.tick()["snapshot"]["phase"])

    assert phases[0] == "night"
    assert phases[7] == "morning"
    assert phases[13] == "noon"      # 阶段定义 noon=12:00–14:00, 13点属 noon
    assert phases[19] == "evening"
    assert phases[23] == "late_evening"
    revision = service.get_state()["revision"]
    paused = service.control("pause", expected_revision=revision, idempotency_key="pause-1")
    duplicate = service.control("pause", expected_revision=revision, idempotency_key="pause-1")
    assert paused == duplicate
    assert paused["actual"] == "paused"
    resumed = service.control("resume", expected_revision=paused["revision"], idempotency_key="resume-1")
    assert resumed["actual"] == "running"

    restarted = LocalWorldSidecarService(data_dir=tmp_path, clock=lambda: current[0])
    state = restarted.get_state()
    assert state["desired"] == "running"
    assert state["actual"] == "running"
    assert state["last_tick_at"].startswith("2026-07-26T23:00:00")


@pytest.mark.asyncio
async def test_authenticated_loopback_http_transport_and_remote_adapter(tmp_path):
    service = LocalWorldSidecarService(data_dir=tmp_path)
    server = create_http_server(service=service, token="test-token", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        client = HttpWorldSidecarClient(endpoint, token="test-token")
        hello = client.hello()
        assert hello["protocol"] == "aerie.world"
        adapter = RemoteWorldAdapter(client)
        state = await adapter.get_state()
        assert state.actual == "running"
        paused = await adapter.control(
            "pause",
            expected_revision=state.revision,
            idempotency_key="http-pause",
        )
        assert paused["accepted"] is True
        assert (await adapter.get_state()).actual == "paused"
        assert client.get_world_snapshot()["phase"]
        with pytest.raises(RuntimeError):
            HttpWorldSidecarClient(endpoint, token="wrong-token").hello()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_world_http_refuses_non_loopback_and_expired_token(tmp_path):
    service = LocalWorldSidecarService(data_dir=tmp_path)
    with pytest.raises(ValueError, match="non-loopback"):
        create_http_server(service=service, host="0.0.0.0", token="token")

    server = create_http_server(
        service=service,
        token="expired",
        port=0,
        token_expires_at_ms=100,
        auth_now_ms=lambda: 100,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        with pytest.raises(RuntimeError):
            HttpWorldSidecarClient(endpoint, token="expired").health()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

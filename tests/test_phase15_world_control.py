"""Phase 15 Batch 2: world control HTTP endpoint contracts."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from core import api_server
from core.api_server import app

client = TestClient(app)


class AsyncControlStub:
    def __init__(self):
        self.calls = []

    async def control(self, action, *, expected_revision=None, idempotency_key=""):
        self.calls.append(action)
        if action == "bogus":
            return {"accepted": False, "rejected": True, "errorCode": "unsupported_action"}
        return {
            "accepted": True,
            "rejected": False,
            "desired": "paused" if action == "pause" else "running",
            "actual": "paused" if action == "pause" else "running",
            "revision": 1,
            "adapter": "in_process",
        }


def _companion(world_port=None):
    return SimpleNamespace(world_port=world_port)


def _auth_headers():
    import os

    os.environ["AERIE_MAIN_PROCESS_TOKEN"] = "test-token"
    return {"X-Aerie-Main-Token": "test-token"}


def test_world_control_requires_auth(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(AsyncControlStub()))
    response = client.post("/api/world/control", json={"action": "pause"})
    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_world_control_pause_resume_accepted(monkeypatch):
    stub = AsyncControlStub()
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(stub))

    r1 = client.post("/api/world/control", json={"action": "pause"}, headers=_auth_headers())
    assert r1.status_code == 200
    assert r1.json()["accepted"] is True
    assert r1.json()["desired"] == "paused"

    r2 = client.post("/api/world/control", json={"action": "resume"}, headers=_auth_headers())
    assert r2.status_code == 200
    assert r2.json()["accepted"] is True
    assert r2.json()["actual"] == "running"

    assert stub.calls == ["pause", "resume"]


def test_world_control_unsupported_action_rejected(monkeypatch):
    stub = AsyncControlStub()
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(stub))

    r = client.post("/api/world/control", json={"action": "bogus"}, headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["accepted"] is False
    assert r.json()["errorCode"] == "unsupported_action"


def test_world_control_missing_action(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(AsyncControlStub()))
    r = client.post("/api/world/control", json={}, headers=_auth_headers())
    assert r.status_code == 400
    assert r.json() == {"error": "missing_action"}


def test_world_control_no_world_port(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(None))
    r = client.post("/api/world/control", json={"action": "pause"}, headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["errorCode"] == "world_unavailable"
    assert r.json()["accepted"] is False


def test_world_runtime_bind_keeps_inprocess_world(monkeypatch):
    """bind with no connection must NOT replace a running in-process world.

    Electron's world connection monitor reports connection=null every 2s while
    the sidecar plugin is disabled. Overwriting the world_port in that case
    silently kills the in-process world simulation and every image-candidate
    publish (world_disabled), so the image pipeline goes dark.
    """
    from core.world_port import InProcessWorldAdapter, NullWorldAdapter

    world_port = InProcessWorldAdapter(
        world=SimpleNamespace(),
        relationship=SimpleNamespace(),
        self_model=SimpleNamespace(),
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(world_port))

    r = client.post("/api/world/runtime/bind", json={}, headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert r.json()["adapter"] == "in_process_kept"
    assert isinstance(world_port, InProcessWorldAdapter)
    assert not isinstance(world_port, NullWorldAdapter)


def test_world_runtime_bind_null_stays_null(monkeypatch):
    """bind with no connection still maps to null when no in-process world runs."""
    from core.world_port import NullWorldAdapter

    world_port = NullWorldAdapter(reason="flag_off")
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(world_port))

    r = client.post("/api/world/runtime/bind", json={}, headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert r.json()["adapter"] == "null"
    assert isinstance(world_port, NullWorldAdapter)

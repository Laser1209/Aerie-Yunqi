"""Contracts for the mobile readonly capability facade."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from core.mobile_gateway import create_mobile_app
from core.mobile_identity import MobileIdentityStore

PEPPER = "test-pepper-at-least-32-bytes-long"


def _make_store(tmp_path) -> MobileIdentityStore:
    store = MobileIdentityStore(tmp_path / "mobile.db", pepper=PEPPER)
    store.create_account(
        username="owner",
        password="correct-horse-battery-staple",
        role="owner",
        actor_id="actor-owner",
        user_id=1001,
    )
    return store


def _login(client: TestClient, store: MobileIdentityStore) -> str:
    code = store.create_pairing_code("owner")
    response = client.post(
        "/api/mobile/v1/auth/login",
        json={
            "username": "owner",
            "password": "correct-horse-battery-staple",
            "deviceName": "test-device",
            "pairingCode": code,
        },
    )
    assert response.status_code == 200
    return f"Bearer {response.json()['accessToken']}"


@pytest.fixture
def readonly_api(tmp_path, monkeypatch):
    store = _make_store(tmp_path)
    client = TestClient(create_mobile_app(identity_store=store))
    headers = {"Authorization": _login(client, store)}

    memory_stub = MagicMock()
    memory_stub.list_by_user.return_value = [
        {
            "id": "mem-1",
            "memory_type": "long_term",
            "content": "remembered detail",
            "importance": 5,
            "created_at": "2026-08-01T00:00:00+00:00",
        }
    ]
    comp = SimpleNamespace(
        memory=memory_stub,
        get_world_dashboard_snapshot=MagicMock(
            return_value={"status": "ready", "worldSummary": {}}
        ),
    )
    monkeypatch.setattr(
        "core.companion.get_companion",
        lambda: comp,
    )
    return {"client": client, "headers": headers}


def test_readonly_requires_authentication(tmp_path):
    store = _make_store(tmp_path)
    client = TestClient(create_mobile_app(identity_store=store))
    response = client.get("/api/mobile/v1/readonly/brief")
    assert response.status_code == 401


def test_readonly_world_returns_snapshot(readonly_api):
    response = readonly_api["client"].get(
        "/api/mobile/v1/readonly/world",
        headers=readonly_api["headers"],
    )
    assert response.status_code == 200
    assert response.json()["world"]["status"] == "ready"


def test_readonly_memory_returns_layers(readonly_api):
    response = readonly_api["client"].get(
        "/api/mobile/v1/readonly/memory",
        headers=readonly_api["headers"],
    )
    assert response.status_code == 200
    layers = response.json()["layers"]
    assert "transient" in layers
    assert "long_term" in layers
    assert layers["long_term"][0]["content"] == "remembered detail"

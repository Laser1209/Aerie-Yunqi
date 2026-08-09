"""Phase 15 Batch 2: memory archive (只读记忆档案) endpoint contracts."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from core import api_server
from core.api_server import app

client = TestClient(app)


class MemoryListStub:
    def list_by_user(self, user_id, layer="long_term", limit=50, memory_type=None):
        if layer == "long_term":
            return [
                {
                    "id": "mem-1",
                    "layer": "long_term",
                    "memory_type": "fact",
                    "content": "用户喜欢猫",
                    "importance": 7.0,
                    "source": "conversation",
                    "created_at": 1780000000.0,
                    "updated_at": 1780000000.0,
                    "confidence": 0.9,
                }
            ]
        return []


def _companion(memory=None):
    return SimpleNamespace(
        memory=memory,
        get_primary_user_selection=lambda: SimpleNamespace(user_id=7),
    )


def test_memory_list_returns_structured_records_by_layer(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(MemoryListStub()))

    response = client.get("/api/memory/list")

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == 7
    assert data["total"] == 1
    assert data["layers"]["long_term"][0]["id"] == "mem-1"
    assert data["layers"]["long_term"][0]["memory_type"] == "fact"
    assert data["layers"]["long_term"][0]["importance"] == 7.0


def test_memory_list_empty_store_returns_empty_layers(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(MemoryListStub()))

    data = client.get("/api/memory/list?layer=working").json()
    assert data["layers"]["working"] == []
    assert data["total"] == 0


def test_memory_list_no_memory_backend_returns_empty(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(None))

    data = client.get("/api/memory/list").json()
    assert data == {"layers": {}, "total": 0}


def test_memory_list_no_primary_user_returns_empty(monkeypatch):
    monkeypatch.setattr(
        api_server,
        "get_companion",
        lambda: SimpleNamespace(memory=MemoryListStub()),
    )

    data = client.get("/api/memory/list").json()
    assert data == {"layers": {}, "total": 0}


def test_memory_list_unknown_layer_returns_empty(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: _companion(MemoryListStub()))

    data = client.get("/api/memory/list?layer=bogus").json()
    assert data["layers"] == {}
    assert data["total"] == 0

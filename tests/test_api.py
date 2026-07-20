"""Tests for HTTP API endpoints (FastAPI TestClient).

Tests health, emotion state, tools list, and chat endpoints.
Uses httpx or FastAPI TestClient with mocked companion.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.database import Database
from knowledge.kb import KnowledgeBase

# Mock companion before importing api_server
mock_companion = MagicMock()
mock_companion.emotion = MagicMock()
mock_companion.emotion.get_state = MagicMock(return_value={
    "label": "neutral",
    "pad": {"P": 0.0, "A": 0.0, "D": 0.0},
    "thresholds": {
        "patience": {"value": 30, "threshold": 100, "label": "忍耐值", "pct": 30},
        "anxiety": {"value": 10, "threshold": 100, "label": "不安值", "pct": 10},
        "desire": {"value": 5, "threshold": 80, "label": "渴望值", "pct": 6},
        "tenderness": {"value": 0, "threshold": 60, "label": "温柔透支值", "pct": 0},
    },
    "eruption": None,
    "panel": "伊塔·情绪面板\n...",
})
mock_companion.get_primary_emotion_state = MagicMock(
    side_effect=mock_companion.emotion.get_state
)
mock_companion.qq = MagicMock()
mock_companion.qq.is_connected = False
mock_companion.pipeline = MagicMock()
mock_companion.pipeline.handle = AsyncMock(return_value={
    "reply": "嗯。",
    "user_msg_id": 1,
    "ai_msg_id": 2,
    "route_mode": "FULL",
    "emotion": "neutral",
})
mock_companion.tool_registry = MagicMock()
mock_companion.tool_registry.get_openai_schema = MagicMock(return_value=[
    {"type": "function", "function": {"name": "get_time", "description": "获取当前时间"}},
])

with patch("core.companion.get_companion", return_value=mock_companion):
    from core import api_server
    from core.api_server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_mock_companion(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: mock_companion)
    yield


class TestHealthEndpoint:
    """Test GET /api/health."""

    def test_health_returns_200(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_has_status_key(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] in {"healthy", "degraded", "unhealthy"}

    def test_health_has_version(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["app"] == "Aerie · 云栖"
        assert data["version"] == app.version

    def test_health_has_uptime(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)

    def test_health_has_qq_status(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert "qq_connected" in data


class TestEmotionStateEndpoint:
    """Test GET /api/emotion/state."""

    def test_emotion_state_returns_200(self):
        resp = client.get("/api/emotion/state")
        assert resp.status_code == 200

    def test_emotion_state_has_label(self):
        resp = client.get("/api/emotion/state")
        data = resp.json()
        assert "label" in data
        assert data["label"] == "neutral"

    def test_emotion_state_has_pad(self):
        resp = client.get("/api/emotion/state")
        data = resp.json()
        assert "pad" in data
        assert "P" in data["pad"]

    def test_emotion_state_has_thresholds(self):
        resp = client.get("/api/emotion/state")
        data = resp.json()
        assert "thresholds" in data
        assert len(data["thresholds"]) == 4

    def test_emotion_state_has_eruption(self):
        resp = client.get("/api/emotion/state")
        data = resp.json()
        assert "eruption" in data


class TestToolsListEndpoint:
    """Test GET /api/tools/list."""

    def test_tools_list_returns_200(self):
        resp = client.get("/api/tools/list")
        assert resp.status_code == 200

    def test_tools_list_has_tools_array(self):
        resp = client.get("/api/tools/list")
        data = resp.json()
        assert "tools" in data

    def test_tools_list_has_count(self):
        resp = client.get("/api/tools/list")
        data = resp.json()
        assert "count" in data


class TestChatSendEndpoint:
    """Test POST /api/chat/send."""

    def test_chat_send_empty_returns_400(self):
        resp = client.post("/api/chat/send", json={"text": ""})
        assert resp.status_code == 400

    def test_chat_send_empty_content_returns_400(self):
        resp = client.post("/api/chat/send", json={"content": "   "})
        assert resp.status_code == 400

    def test_chat_send_with_text_returns_200(self):
        resp = client.post("/api/chat/send", json={"text": "你好", "user_id": 3998874040})
        assert resp.status_code == 200

    def test_chat_send_returns_reply(self):
        resp = client.post("/api/chat/send", json={"text": "你好", "user_id": 3998874040})
        data = resp.json()
        assert "reply" in data
        assert data["reply"] == "嗯。"

    def test_chat_send_no_user_id_uses_master(self):
        # Without user_id, it should use master QQ from config
        resp = client.post("/api/chat/send", json={"text": "你好"})
        assert resp.status_code == 200


def test_todo_mutations_emit_timeline_changed(monkeypatch):
    from core import todo_manager

    todo = {"id": "todo-7", "due_time": "2026-07-20T09:00:00"}
    old = {"id": "todo-7", "due_time": "2026-07-19T09:00:00"}
    get_todo = MagicMock(return_value=old)
    monkeypatch.setattr(todo_manager, "get_todo", get_todo, raising=False)
    monkeypatch.setattr(todo_manager, "update_todo", MagicMock(return_value=todo))
    monkeypatch.setattr(todo_manager, "delete_todo", MagicMock(return_value=True))
    monkeypatch.setattr(todo_manager, "toggle_todo", MagicMock(return_value=todo))
    emitted = []
    monkeypatch.setattr(api_server, "emit", lambda event, **payload: emitted.append((event, payload)))

    client.patch("/api/todos/todo-7", json={"due_time": todo["due_time"]})
    client.delete("/api/todos/todo-7")
    client.post("/api/todos/todo-7/toggle")

    changes = [payload for event, payload in emitted if event == "timeline_changed"]
    assert changes[0] == {"date": "2026-07-20", "kind": "todo", "action": "updated", "id": "todo:todo-7"}
    assert changes[1] == {"date": "2026-07-19", "kind": "todo", "action": "deleted", "id": "todo:todo-7"}
    assert changes[2] == {"date": "2026-07-20", "kind": "todo", "action": "toggled", "id": "todo:todo-7"}
    get_todo.assert_called_once_with("todo-7")


def test_calendar_stats_and_companion_errors_return_500(monkeypatch):
    monkeypatch.setattr(api_server._calendar, "get_stats", MagicMock(side_effect=RuntimeError("stats failed")))
    monkeypatch.setattr(api_server._calendar, "get_companion_stats", MagicMock(side_effect=RuntimeError("companion failed")))

    stats = client.get("/api/calendar/stats")
    companion = client.get("/api/calendar/companion")

    assert stats.status_code == 500
    assert stats.json()["error"] == "stats failed"
    assert companion.status_code == 500
    assert companion.json()["error"] == "companion failed"


@pytest.fixture
def api_db(monkeypatch, tmp_path):
    previous = Database._instance
    Database._instance = None
    db = Database(tmp_path / "api.db")
    monkeypatch.setattr(api_server, "_db", db)
    monkeypatch.setattr(api_server, "_knowledge", KnowledgeBase(db), raising=False)
    yield db
    Database._instance = previous


def test_chat_history_paginates_all_users_and_filters(api_db):
    for index in range(45):
        api_db.insert("chat_log", {
            "user_id": 1 if index % 2 == 0 else 2,
            "role": "user",
            "content": f"message-{index}",
        })

    pages = [client.get(f"/api/chat/history?page={page}&limit=20").json() for page in (1, 2, 3)]

    assert [page["page"] for page in pages] == [1, 2, 3]
    assert all(page["total"] == 45 and page["limit"] == 20 and page["user_id"] is None for page in pages)
    ids = [item["id"] for page in pages for item in page["history"]]
    assert len(ids) == 45
    assert len(set(ids)) == 45

    filtered = client.get("/api/chat/history?page=1&limit=50&user_id=1").json()
    assert filtered["total"] == 23
    assert filtered["user_id"] == 1
    assert {item["user_id"] for item in filtered["history"]} == {1}


def test_chat_history_rejects_invalid_pagination(api_db):
    assert client.get("/api/chat/history?page=0&limit=20").status_code == 422
    assert client.get("/api/chat/history?page=1&limit=0").status_code == 422


def test_chat_history_query_error_returns_non_2xx(monkeypatch):
    broken_db = MagicMock()
    broken_db.query_one.side_effect = RuntimeError("query failed")
    monkeypatch.setattr(api_server, "_db", broken_db)

    response = client.get("/api/chat/history")

    assert response.status_code == 500
    assert response.json()["error"] == "query failed"


def test_chat_send_passthroughs_persistence_status():
    result = {
        "reply": "仍然回复",
        "user_msg_id": 0,
        "ai_msg_id": 0,
        "persisted": False,
        "persist_error": "user message: disk full; assistant message: disk full",
    }
    mock_companion.pipeline.handle.return_value = result
    try:
        response = client.post("/api/chat/send", json={"text": "你好", "user_id": 1})
    finally:
        mock_companion.pipeline.handle.return_value = {
            "reply": "嗯。", "user_msg_id": 1, "ai_msg_id": 2,
            "route_mode": "FULL", "emotion": "neutral",
        }

    assert response.status_code == 200
    assert response.json()["reply"] == "仍然回复"
    assert response.json()["persisted"] is False
    assert "disk full" in response.json()["persist_error"]


def test_knowledge_crud_pagination_search_and_timestamps(api_db):
    first = client.post("/api/knowledge", json={
        "category": "world", "title": "Alpha", "content": "first body", "tags": "one,two",
    })
    second = client.post("/api/knowledge", json={
        "category": "task", "title": "Beta", "content": "searchable body", "tags": "three",
    })

    assert first.status_code == 201
    assert second.status_code == 201
    first_item = first.json()
    assert first_item["created_at"]
    assert first_item["updated_at"]

    listed = client.get("/api/knowledge/list?page=1&limit=1&search=searchable").json()
    assert listed["total"] == 1
    assert listed["page"] == 1
    assert listed["limit"] == 1
    assert listed["items"][0]["title"] == "Beta"
    assert listed["items"][0]["content"] == "searchable body"

    detail = client.get(f"/api/knowledge/{first_item['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Alpha"

    updated = client.put(f"/api/knowledge/{first_item['id']}", json={
        "category": "persona", "title": "Alpha updated", "content": "new body", "tags": "updated",
    })
    assert updated.status_code == 200
    assert updated.json()["updated_at"] >= first_item["updated_at"]
    assert updated.json()["title"] == "Alpha updated"

    deleted = client.delete(f"/api/knowledge/{first_item['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/knowledge/{first_item['id']}").status_code == 404


def test_knowledge_validates_required_fields_and_missing_records(api_db):
    assert client.post("/api/knowledge", json={"category": "world", "title": "", "content": "body"}).status_code == 400
    assert client.put("/api/knowledge/9999", json={
        "category": "world", "title": "missing", "content": "body",
    }).status_code == 404
    assert client.delete("/api/knowledge/9999").status_code == 404


def test_system_stats_include_backend_diagnostics(api_db):
    response = client.get("/api/stats/system")

    assert response.status_code == 200
    data = response.json()
    assert data["backend_started_at"]
    assert data["database_path"] == str(api_db.db_path.resolve())
    assert data["project_root"] == str(api_server.PROJECT_ROOT)
    assert {"uptime", "uptime_seconds", "cpu", "memory", "message_count"} <= data.keys()

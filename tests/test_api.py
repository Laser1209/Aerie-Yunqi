"""Tests for HTTP API endpoints (FastAPI TestClient).

Tests health, emotion state, tools list, and chat endpoints.
Uses httpx or FastAPI TestClient with mocked companion.
"""

from unittest.mock import MagicMock, AsyncMock, patch

from fastapi.testclient import TestClient

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
    from core.api_server import app

client = TestClient(app)


class TestHealthEndpoint:
    """Test GET /api/health."""

    def test_health_returns_200(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_has_status_key(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_has_version(self):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["app"] == "Aerie · 云栖"
        assert data["version"] == "9.0.0"

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

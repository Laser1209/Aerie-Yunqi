"""Phase 15 world dashboard backend API contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from core import api_server
from core.api_server import app


client = TestClient(app)


class _EnabledFlags:
    def is_enabled(self, name):
        assert name == "world_sidecar_v1"
        return True


def test_world_snapshot_uses_primary_identity_and_never_zero(monkeypatch):
    seen = []

    async def snapshot(*, user_id):
        seen.append(user_id)
        return {"status": "running"}

    companion = SimpleNamespace(
        get_world_dashboard_snapshot=snapshot,
        get_primary_user_selection=lambda: SimpleNamespace(user_id=24680),
        feature_flags=_EnabledFlags(),
    )
    monkeypatch.setenv("AERIE_FEATURE_WORLD_SIDECAR_V1", "false")
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.get("/api/world/dashboard/snapshot")
    rejected = client.get("/api/world/dashboard/snapshot?user_id=0")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert seen == [24680]
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "unavailable"
    assert rejected.json()["error_code"] == "invalid_user_id"
    assert seen == [24680]


def test_world_snapshot_prefers_shared_runtime_flag_over_legacy_yaml(monkeypatch):
    handler = AsyncMock(return_value={"status": "running"})
    companion = SimpleNamespace(
        feature_flags=_EnabledFlags(),
        get_world_dashboard_snapshot=handler,
        get_primary_user_selection=lambda: SimpleNamespace(user_id=13579),
    )
    monkeypatch.setenv("AERIE_FEATURE_WORLD_SIDECAR_V1", "false")
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.get("/api/world/dashboard/snapshot")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    handler.assert_awaited_once_with(user_id=13579)


def test_world_candidate_approval_flag_off_has_no_side_effects(monkeypatch):
    handler = AsyncMock(side_effect=AssertionError("handler should not run"))
    # 世界完全关闭：sidecar 与 inprocess 双 flag 均关闭，审批 handler 不应被调用。
    monkeypatch.setenv("AERIE_FEATURE_WORLD_SIDECAR_V1", "false")
    monkeypatch.setenv("AERIE_FEATURE_WORLD_INPROCESS_V1", "false")
    monkeypatch.setattr(
        api_server,
        "get_companion",
        lambda: SimpleNamespace(approve_world_image_candidate=handler),
    )

    response = client.post(
        "/api/world/candidates/approve",
        json={
            "candidate_id": "cand-1",
            "action": "approve",
            "rawPrompt": "redacted-token-should-not-leak",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "disabled",
        "candidateId": "cand-1",
        "ack": False,
        "sideEffects": {"handler_called": False},
    }
    handler.assert_not_called()
    assert "redacted-token" not in response.text
    assert "rawPrompt" not in response.text


def test_world_candidate_approval_calls_companion_with_sanitized_payload(monkeypatch):
    seen = {}

    async def approve(payload):
        seen["payload"] = payload
        return {
            "status": "queued",
            "ack": True,
            "reason": "accepted",
            "secret": "redacted-token-should-not-leak",
            "rawPrompt": "also-secret",
        }

    monkeypatch.setenv("AERIE_FEATURE_WORLD_SIDECAR_V1", "true")
    monkeypatch.setattr(
        api_server,
        "get_companion",
        lambda: SimpleNamespace(approve_world_image_candidate=approve),
    )

    response = client.post(
        "/api/world/candidates/approve",
        json={
            "candidate_id": "cand-1",
            "action": "approve",
            "idempotency_key": "idem-1",
            "reason_code": "manual_ok",
            "rawPrompt": "redacted-token-should-not-leak",
        },
    )

    assert response.status_code == 200
    assert seen["payload"] == {
        "candidate_id": "cand-1",
        "action": "approve",
        "idempotency_key": "idem-1",
        "reason_code": "manual_ok",
    }
    assert response.json() == {
        "status": "queued",
        "candidateId": "cand-1",
        "ack": True,
        "reason": "accepted",
        "sideEffects": {"handler_called": True},
    }
    assert "redacted-token" not in response.text
    assert "rawPrompt" not in response.text


def test_world_candidate_approval_missing_handler_degrades_without_404(monkeypatch):
    monkeypatch.setenv("AERIE_FEATURE_WORLD_SIDECAR_V1", "true")
    monkeypatch.setattr(api_server, "get_companion", lambda: SimpleNamespace())

    response = client.post(
        "/api/world/candidates/approve",
        json={
            "candidateId": "cand-missing",
            "action": "invalid-action",
            "idempotencyKey": "idem-missing",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "backend_unavailable",
        "candidateId": "cand-missing",
        "ack": False,
        "error_code": "approval_handler_missing",
        "sideEffects": {"handler_called": False},
    }

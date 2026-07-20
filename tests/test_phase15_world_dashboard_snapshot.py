"""Phase 15 world dashboard snapshot contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import api_server
from core.api_server import app
from core.world_port import WorldEvent, WorldSnapshot


client = TestClient(app)


def test_world_dashboard_snapshot_flag_off_has_no_side_effects(monkeypatch):
    handler_called = False

    async def forbidden_snapshot():
        nonlocal handler_called
        handler_called = True
        raise AssertionError("snapshot handler should not run")

    monkeypatch.setenv("AERIE_FEATURE_WORLD_SIDECAR_V1", "false")
    monkeypatch.setattr(
        api_server,
        "get_companion",
        lambda: SimpleNamespace(get_world_dashboard_snapshot=forbidden_snapshot),
    )

    response = client.get("/api/world/dashboard/snapshot")

    assert response.status_code == 200
    assert response.json() == {
        "status": "disabled",
        "worldSummary": {},
        "relationshipState": {},
        "selfModel": {},
        "actionTimeline": [],
        "imageCandidates": [],
        "sideEffects": {"handler_called": False},
    }
    assert handler_called is False


def test_world_dashboard_snapshot_api_returns_redacted_whitelisted_data(monkeypatch):
    async def snapshot():
        return {
            "status": "ready",
            "worldSummary": {
                "status": "running",
                "phase": "evening",
                "location": "studio",
                "activity": "drawing",
                "rawPrompt": "redacted-token-should-not-leak",
            },
            "relationshipState": {
                "persona_id": "default",
                "warmth": 0.73,
                "summary": "stable",
                "secret": "redacted-token-should-not-leak",
            },
            "selfModel": {
                "mood": "focused",
                "energy": 0.62,
                "rawThought": "redacted-token-should-not-leak",
            },
            "actionTimeline": [
                {
                    "eventId": "evt-1",
                    "topic": "observations",
                    "eventType": "world.observation.recorded",
                    "sequence": 1,
                    "payloadKeys": ["message_text", "secret"],
                    "payload": {"secret": "redacted-token-should-not-leak"},
                }
            ],
            "imageCandidates": [
                {
                    "candidateId": "cand-1",
                    "idempotencyKey": "world-cand-1",
                    "scene": "idle_care",
                    "promptKey": "evening_home",
                    "reasonCode": "world_suggested",
                    "score": 0.91,
                    "rawPrompt": "redacted-token-should-not-leak",
                }
            ],
            "secretValue": "redacted-token-should-not-leak",
        }

    monkeypatch.setenv("AERIE_FEATURE_WORLD_SIDECAR_V1", "true")
    monkeypatch.setattr(
        api_server,
        "get_companion",
        lambda: SimpleNamespace(get_world_dashboard_snapshot=snapshot),
    )

    response = client.get("/api/world/dashboard/snapshot")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["worldSummary"] == {
        "status": "running",
        "phase": "evening",
        "location": "studio",
        "activity": "drawing",
    }
    assert data["relationshipState"] == {
        "persona_id": "default",
        "warmth": 0.73,
        "summary": "stable",
    }
    assert data["selfModel"] == {"mood": "focused", "energy": 0.62}
    assert data["actionTimeline"] == [
        {
            "eventId": "evt-1",
            "topic": "observations",
            "eventType": "world.observation.recorded",
            "sequence": 1,
            "payloadKeys": ["message_text", "secret"],
        }
    ]
    assert data["imageCandidates"][0]["candidateId"] == "cand-1"
    assert "redacted-token" not in response.text
    assert "rawPrompt" not in response.text
    assert "secretValue" not in response.text


class WorldPortSnapshotStub:
    async def get_state(self):
        return WorldSnapshot(
            status="running",
            source="remote",
            instance_id="world-test",
            sequence=12,
            phase="evening",
            location="studio",
            activity="drawing",
            capabilities=("world.read", "message.candidate.publish"),
        )

    def get_world_snapshot(self):
        return {
            "status": "running",
            "phase": "evening",
            "location": "studio",
            "activity": "drawing",
            "revision": 3,
            "rawPrompt": "redacted-token-should-not-leak",
        }

    def get_relationship_snapshot(self, user_id, persona_id="default"):
        return {
            "user_id": str(user_id),
            "persona_id": persona_id,
            "warmth": 0.73,
            "trust": 0.81,
            "summary": "stable",
            "secret": "redacted-token-should-not-leak",
        }

    def get_self_model_snapshot(self, world_snapshot, relationship_snapshot):
        return {
            "mood": "focused",
            "energy": 0.62,
            "summary": "drawing quietly",
            "rawThought": "redacted-token-should-not-leak",
        }

    async def replay_events(self, *, last_seq=None):
        return [
            WorldEvent(
                event_id="world_evt_obs_1",
                topic="observations",
                event_type="world.observation.recorded",
                sequence=11,
                occurred_at="2026-07-20T19:59:00+00:00",
                payload={
                    "payload_keys": ["text", "secret"],
                    "payload_sha256": "digest-only",
                    "secret": "redacted-token-should-not-leak",
                },
            ),
            WorldEvent(
                event_id="world_evt_candidate_1",
                topic="image_candidates",
                event_type="world.image_candidate.published",
                sequence=12,
                occurred_at="2026-07-20T20:00:00+00:00",
                payload={
                    "candidate_id": "cand-1",
                    "idempotency_key": "world-cand-1",
                    "scene": "idle_care",
                    "prompt_key": "evening_home",
                    "reason_code": "world_suggested",
                    "score": 0.91,
                    "rawPrompt": "redacted-token-should-not-leak",
                },
            ),
        ]


@pytest.mark.asyncio
async def test_companion_world_dashboard_snapshot_uses_world_port_without_raw_payload():
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.world_port = WorldPortSnapshotStub()
    companion._active_persona_id = lambda: "default"

    result = await companion.get_world_dashboard_snapshot(user_id=7)
    rendered = str(result)

    assert result["status"] == "ready"
    assert result["worldSummary"]["phase"] == "evening"
    assert result["relationshipState"]["persona_id"] == "default"
    assert result["selfModel"]["mood"] == "focused"
    assert result["actionTimeline"][0]["payloadKeys"] == ["text", "secret"]
    assert result["imageCandidates"][0]["candidateId"] == "cand-1"
    assert "redacted-token" not in rendered
    assert "rawPrompt" not in rendered
    assert "rawThought" not in rendered

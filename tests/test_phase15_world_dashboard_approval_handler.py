"""Phase 15 dashboard manual approval handler contracts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.world_port import WorldEvent


class FlagStub:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def is_enabled(self, name: str) -> bool:
        return name == "world_image_candidates_v1" and self.enabled


class WorkflowStub:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_image(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "status": "completed",
            "request_id": "img-manual-ok",
            "side_effects": {
                "provider_called": True,
                "asset_created": True,
                "delivery_created": True,
            },
            "delivery_plan": {
                "delivery_plan_id": "delivery-manual-1",
                "status": "planned",
            },
        }


class WorldPortStub:
    def __init__(self, events: list[WorldEvent] | None = None) -> None:
        self.events = events or []
        self.acks: list[int] = []
        self.replay_calls: list[dict] = []

    async def replay_events(self, *, last_seq=None):
        self.replay_calls.append({"last_seq": last_seq})
        return self.events

    async def ack(self, seq: int):
        self.acks.append(seq)
        return {"consumer_id": "core", "last_seq": seq}


class PolicyStub:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def can_push(self, scene: str):
        return True, "ok"

    def record(self, scene: str) -> None:
        self.recorded.append(scene)


def _clock() -> datetime:
    return datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)


def _candidate_event() -> WorldEvent:
    return WorldEvent(
        event_id="world_evt_candidate_manual_1",
        topic="image_candidates",
        event_type="world.image_candidate.published",
        sequence=7,
        occurred_at="2026-07-20T20:00:00+00:00",
        payload={
            "candidate_id": "cand-manual-1",
            "scene": "idle_care",
            "owner_id": "master",
            "channel": "local_chat",
            "target": "desktop",
            "prompt_key": "evening_home",
            "reason_code": "world_suggested",
            "source": "generated",
            "score": 0.91,
            "expires_at": "2026-07-20T20:10:00+00:00",
            "idempotency_key": "world-cand-manual-1",
            "rawPrompt": "redacted-token-should-not-leak",
        },
    )


def _consumer(tmp_path, *, enabled: bool = True, workflow=None, port=None):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    return WorldImageCandidateConsumer(
        feature_flags=FlagStub(enabled),
        image_workflow=workflow or WorkflowStub(),
        world_port=port or WorldPortStub([_candidate_event()]),
        push_policy=PolicyStub(),
        proactive_judge=None,
        store=JsonWorldImageCandidateStore(tmp_path / "dashboard-manual.json"),
        clock=_clock,
    )


@pytest.mark.asyncio
async def test_companion_manual_approval_processes_matching_candidate_without_raw_payload(tmp_path):
    from core.companion import Companion

    workflow = WorkflowStub()
    port = WorldPortStub([_candidate_event()])
    companion = Companion.__new__(Companion)
    companion.world_image_candidate_consumer = _consumer(
        tmp_path,
        workflow=workflow,
        port=port,
    )

    result = await companion.approve_world_image_candidate(
        {
            "candidate_id": "cand-manual-1",
            "action": "approve",
            "idempotency_key": "dashboard-click-1",
            "reason_code": "manual_ok",
            "rawPrompt": "redacted-token-should-not-leak",
        }
    )

    assert result["status"] == "completed"
    assert result["acked"] is True
    assert result["candidate_id"] == "cand-manual-1"
    assert workflow.calls[0]["idempotency_key"] == "world-image:world-cand-manual-1"
    assert port.acks == [7]
    assert port.replay_calls == [{"last_seq": 0}]
    assert "redacted-token" not in str(result)
    assert "rawPrompt" not in str(result)


@pytest.mark.asyncio
async def test_companion_manual_reject_acks_without_image_workflow(tmp_path):
    from core.companion import Companion

    workflow = WorkflowStub()
    port = WorldPortStub([_candidate_event()])
    consumer = _consumer(tmp_path, workflow=workflow, port=port)
    companion = Companion.__new__(Companion)
    companion.world_image_candidate_consumer = consumer

    result = await companion.approve_world_image_candidate(
        {
            "candidate_id": "cand-manual-1",
            "action": "reject",
            "idempotency_key": "dashboard-click-reject-1",
            "reason_code": "manual_reject",
        }
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "manual_reject"
    assert result["acked"] is True
    assert workflow.calls == []
    assert port.acks == [7]
    assert consumer.store.get("world-cand-manual-1")["status"] == "rejected"


@pytest.mark.asyncio
async def test_companion_manual_postpone_leaves_candidate_unacked_for_replay(tmp_path):
    from core.companion import Companion

    workflow = WorkflowStub()
    port = WorldPortStub([_candidate_event()])
    companion = Companion.__new__(Companion)
    companion.world_image_candidate_consumer = _consumer(
        tmp_path,
        workflow=workflow,
        port=port,
    )

    result = await companion.approve_world_image_candidate(
        {
            "candidate_id": "cand-manual-1",
            "action": "postpone",
            "idempotency_key": "dashboard-click-postpone-1",
            "reason_code": "later",
        }
    )

    assert result["status"] == "postponed"
    assert result["acked"] is False
    assert workflow.calls == []
    assert port.acks == []


@pytest.mark.asyncio
async def test_companion_manual_approval_reports_not_found_without_side_effects(tmp_path):
    from core.companion import Companion

    workflow = WorkflowStub()
    companion = Companion.__new__(Companion)
    companion.world_image_candidate_consumer = _consumer(
        tmp_path,
        workflow=workflow,
        port=WorldPortStub([_candidate_event()]),
    )

    result = await companion.approve_world_image_candidate(
        {
            "candidate_id": "missing-candidate",
            "action": "approve",
            "idempotency_key": "dashboard-click-missing-1",
            "reason_code": "manual_ok",
        }
    )

    assert result["status"] == "not_found"
    assert result["acked"] is False
    assert result["side_effects"]["provider_called"] is False
    assert workflow.calls == []

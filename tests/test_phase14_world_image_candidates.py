"""Phase 14 world ImageCandidate approval, idempotency, and ACK contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.world_port import WorldEvent


class FlagStub:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def is_enabled(self, name: str) -> bool:
        return name == "world_image_candidates_v1" and self.enabled


class WorkflowStub:
    def __init__(self, status: str = "completed") -> None:
        self.status = status
        self.calls: list[dict] = []

    def generate_image(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self.status == "disabled":
            return {
                "status": "disabled",
                "side_effects": {
                    "provider_called": False,
                    "asset_created": False,
                    "delivery_created": False,
                },
                "delivery_plan": None,
            }
        if self.status == "failed":
            return {
                "status": "failed",
                "request_id": "img-failed",
                "side_effects": {
                    "provider_called": True,
                    "asset_created": False,
                    "delivery_created": False,
                },
                "delivery_plan": None,
            }
        return {
            "status": "completed",
            "request_id": "img-ok",
            "side_effects": {
                "provider_called": True,
                "asset_created": True,
                "delivery_created": True,
            },
            "delivery_plan": {
                "delivery_plan_id": "delivery-1",
                "status": "planned",
            },
        }


class WorldPortStub:
    def __init__(self, events: list[WorldEvent] | None = None) -> None:
        self.events = events or []
        self.acks: list[int] = []

    async def replay_events(self, *, last_seq=None):
        return self.events

    async def ack(self, seq: int):
        self.acks.append(seq)
        return {"consumer_id": "core", "last_seq": seq}


class PolicyStub:
    def __init__(self, allowed: bool = True, reason: str = "ok") -> None:
        self.allowed = allowed
        self.reason = reason
        self.recorded: list[str] = []

    def can_push(self, scene: str):
        return self.allowed, self.reason

    def record(self, scene: str) -> None:
        self.recorded.append(scene)


class JudgeStub:
    def __init__(self, suppress_reason: str = "") -> None:
        self.suppress_reason = suppress_reason
        self.calls: list[str] = []

    def evaluate(self, scene: str, context_override=None):
        self.calls.append(scene)
        return SimpleNamespace(
            scene=scene,
            score=81,
            tone="casual_warm",
            suppress_reason=self.suppress_reason,
            to_dict=lambda: {
                "scene": scene,
                "score": 81,
                "tone": "casual_warm",
                "suppress_reason": self.suppress_reason,
            },
        )


def _clock() -> datetime:
    return datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)


def _candidate_payload(**overrides) -> dict:
    payload = {
        "candidate_id": "cand-1",
        "scene": "idle_care",
        "owner_id": "master",
        "channel": "local_chat",
        "target": "desktop",
        "prompt_key": "evening_home",
        "reason_code": "evening_private_scene",
        "source": "generated",
        "score": 0.91,
        "expires_at": "2026-07-20T20:10:00+00:00",
        "idempotency_key": "world-cand-1",
    }
    payload.update(overrides)
    return payload


def _candidate_event(**payload_overrides) -> WorldEvent:
    return WorldEvent(
        event_id="world_evt_candidate_1",
        topic="image_candidates",
        event_type="world.image_candidate.published",
        sequence=7,
        occurred_at="2026-07-20T20:00:00+00:00",
        payload=_candidate_payload(**payload_overrides),
    )


@pytest.mark.asyncio
async def test_flag_off_closes_consumer_without_ack_or_side_effects(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(False),
        image_workflow=workflow,
        world_port=port,
        store=JsonWorldImageCandidateStore(tmp_path / "candidates.json"),
        clock=_clock,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "disabled"
    assert result["acked"] is False
    assert workflow.calls == []
    assert port.acks == []
    assert result["side_effects"]["delivery_created"] is False


@pytest.mark.asyncio
async def test_approved_candidate_calls_image_workflow_acks_and_survives_replay(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    store = JsonWorldImageCandidateStore(tmp_path / "candidates.json")
    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=store,
        clock=_clock,
    )

    first = await consumer.process_event(_candidate_event())
    restarted = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "candidates.json"),
        clock=_clock,
    )
    replay = await restarted.process_event(_candidate_event())

    assert first["status"] == "completed"
    assert first["acked"] is True
    assert port.acks == [7, 7]
    assert len(workflow.calls) == 1
    assert workflow.calls[0]["idempotency_key"] == "world-image:world-cand-1"
    assert workflow.calls[0]["prompt"] == "world_prompt:evening_home"
    assert replay["status"] == "duplicate"
    assert replay["side_effects"]["provider_called"] is False


@pytest.mark.asyncio
async def test_muted_expired_and_judge_rejected_candidates_ack_without_workflow(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    muted_port = WorldPortStub()
    muted_workflow = WorkflowStub()
    muted = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=muted_workflow,
        world_port=muted_port,
        push_policy=PolicyStub(False, "muted"),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "muted.json"),
        clock=_clock,
    )
    muted_result = await muted.process_event(_candidate_event())

    expired_port = WorldPortStub()
    expired = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=expired_port,
        store=JsonWorldImageCandidateStore(tmp_path / "expired.json"),
        clock=_clock,
    )
    expired_result = await expired.process_event(
        _candidate_event(
            candidate_id="cand-expired",
            idempotency_key="world-cand-expired",
            expires_at="2026-07-20T19:59:00+00:00",
        )
    )

    rejected_port = WorldPortStub()
    rejected_workflow = WorkflowStub()
    rejected = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=rejected_workflow,
        world_port=rejected_port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub("score_below_threshold(20<45)"),
        store=JsonWorldImageCandidateStore(tmp_path / "rejected.json"),
        clock=_clock,
    )
    rejected_result = await rejected.process_event(
        _candidate_event(candidate_id="cand-rejected", idempotency_key="world-cand-rejected")
    )

    assert muted_result["status"] == "suppressed"
    assert muted_result["reason"] == "muted"
    assert muted_port.acks == [7]
    assert muted_workflow.calls == []
    assert expired_result["status"] == "expired"
    assert expired_port.acks == [7]
    assert rejected_result["status"] == "rejected"
    assert rejected_port.acks == [7]
    assert rejected_workflow.calls == []


@pytest.mark.asyncio
async def test_offline_candidate_is_not_acked_and_has_no_side_effects(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "offline.json"),
        clock=_clock,
        delivery_online=lambda: False,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "offline"
    assert result["acked"] is False
    assert workflow.calls == []
    assert port.acks == []
    assert result["side_effects"]["provider_called"] is False


@pytest.mark.asyncio
async def test_image_workflow_disabled_does_not_ack_or_record_candidate(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    store = JsonWorldImageCandidateStore(tmp_path / "workflow-disabled.json")
    workflow = WorkflowStub(status="disabled")
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=store,
        clock=_clock,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "workflow_disabled"
    assert result["acked"] is False
    assert port.acks == []
    assert store.get("world-cand-1") is None
    assert result["side_effects"]["provider_called"] is False


@pytest.mark.asyncio
async def test_sidecar_publishes_redacted_image_candidate_for_core_replay(tmp_path):
    from core.world_adapters.remote import RemoteWorldAdapter
    from world_service.main import LocalWorldSidecarService

    service = LocalWorldSidecarService(data_dir=tmp_path)
    service.publish_image_candidate(
        {
            **_candidate_payload(),
            "prompt": "raw intimate prompt must not leak",
            "message_text": "private chat text must not leak",
        }
    )
    adapter = RemoteWorldAdapter(service, consumer_id="core")

    events = await adapter.replay_events(last_seq=0)
    raw = str(events[0].to_public_dict())

    assert events[0].event_type == "world.image_candidate.published"
    assert events[0].payload["candidate_id"] == "cand-1"
    assert events[0].payload["prompt_key"] == "evening_home"
    assert "raw intimate prompt" not in raw
    assert "private chat text" not in raw


@pytest.mark.asyncio
async def test_companion_exposes_one_shot_candidate_consumer(tmp_path):
    from core.companion import Companion
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    event = _candidate_event()
    workflow = WorkflowStub()
    port = WorldPortStub([event])
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "companion.json"),
        clock=_clock,
    )
    companion = Companion.__new__(Companion)
    companion.world_image_candidate_consumer = consumer

    results = await companion.process_world_image_candidates_once(last_seq=0)

    assert [result["status"] for result in results] == ["completed"]
    assert workflow.calls
    assert port.acks == [7]

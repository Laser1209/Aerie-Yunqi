"""P1-C.4 TDD tests for ProactiveVisualScheduler (主动消息 + 主动图片联合调度).

联合调度:
  - 从主动候选 + WorldSnapshot 生成主动消息, 并按需附带 visual_request
  - 复用 VisualIntentRouter 做图片意图路由, 不调用真实 provider
  - 同一 world_snapshot_id 不重复生成主动候选 (幂等)
  - 用户忽略后退避 (增大下次调度间隔)
  - environment_object 的 reference_assets 必须为空
  - 低置信度不调用 provider, 仅返回文字
"""
from __future__ import annotations

import pytest

from core.proactive_candidates import ProactiveCandidate, ProactiveIntent
from core.proactive_visual_scheduler import ProactiveVisualScheduler
from core.world_simulation import WorldSnapshot


def _snapshot(
    *,
    snapshot_id: str = "ws_a1",
    phase: str = "afternoon",
    activity: str = "working",
    location: str = "study",
    topics: list[str] | None = None,
) -> WorldSnapshot:
    return WorldSnapshot(
        phase=phase,
        location=location,
        activity=activity,
        energy=0.55,
        social="focused",
        nearby_objects=["laptop", "notebook"],
        available_visual_topics=topics or ["desk_view", "deep_focus"],
        instance_id=snapshot_id,
        world_snapshot_id=snapshot_id,
        tick_id=f"tick_{snapshot_id}",
        created_at="2026-07-28T06:08:36",
        timestamp=1000.0,
    )


def _candidate(
    intent: ProactiveIntent = ProactiveIntent.LIFE_SHARE,
    topic: str = "desk_view",
    score: float = 0.6,
    snapshot_id: str = "ws_a1",
) -> ProactiveCandidate:
    return ProactiveCandidate(
        intent=intent,
        topic=topic,
        score=score,
        source_snapshot_id=snapshot_id,
        reasons=["world_freshness"],
    )


def test_plan_generates_message_and_visual_request_for_visual_candidate():
    scheduler = ProactiveVisualScheduler()
    decision = scheduler.plan(
        snapshot=_snapshot(),
        candidates=[_candidate(topic="拍一下桌上的西瓜")],
    )
    assert decision is not None
    assert decision.message
    assert decision.visual_request is not None
    assert decision.visual_request["status"] == "ok"


def test_plan_returns_text_only_when_candidate_is_non_visual():
    scheduler = ProactiveVisualScheduler()
    decision = scheduler.plan(
        snapshot=_snapshot(),
        candidates=[_candidate(intent=ProactiveIntent.CARE_FOLLOWUP, topic="回访一下")],
    )
    assert decision is not None
    assert decision.message
    assert decision.visual_request is None


def test_same_world_snapshot_id_is_idempotent():
    scheduler = ProactiveVisualScheduler()
    snap = _snapshot()
    first = scheduler.plan(snapshot=snap, candidates=[_candidate()])
    second = scheduler.plan(snapshot=snap, candidates=[_candidate()])
    assert first is not None
    assert second is None, "同一 world_snapshot_id 不得重复生成"


def test_different_snapshot_allows_new_plan():
    scheduler = ProactiveVisualScheduler()
    scheduler.plan(snapshot=_snapshot(snapshot_id="ws_a1"), candidates=[_candidate()])
    later = scheduler.plan(
        snapshot=_snapshot(snapshot_id="ws_a2", topics=["evening_chill"]),
        candidates=[_candidate(snapshot_id="ws_a2")],
    )
    assert later is not None


def test_environment_object_never_mounts_reference_assets():
    scheduler = ProactiveVisualScheduler()
    decision = scheduler.plan(
        snapshot=_snapshot(),
        candidates=[_candidate(topic="拍一下桌上的西瓜")],
    )
    assert decision is not None
    vr = decision.visual_request
    assert vr["visual_intent"] == "environment_object"
    assert vr["reference_assets"] == []


def test_low_confidence_visual_intent_returns_text_without_provider():
    scheduler = ProactiveVisualScheduler(min_confidence=0.9)
    decision = scheduler.plan(
        snapshot=_snapshot(),
        candidates=[_candidate(topic="拍一下桌上的西瓜")],
    )
    assert decision is not None
    assert decision.message
    assert decision.visual_request is None, "低置信度不生成 visual_request, 不调用 provider"


def test_user_ignore_backoff_suppresses_same_snapshot_replan():
    scheduler = ProactiveVisualScheduler()
    snap = _snapshot(snapshot_id="ws_ignored")
    first = scheduler.plan(snapshot=snap, candidates=[_candidate()])
    assert first is not None
    scheduler.record_user_ignored(snapshot_id="ws_ignored")
    retry = scheduler.plan(snapshot=snap, candidates=[_candidate()])
    assert retry is None, "用户忽略后应退避, 不重复调度"

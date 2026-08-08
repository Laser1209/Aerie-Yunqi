from __future__ import annotations

from datetime import datetime, timezone


def test_due_care_followup_is_selected_and_marked_done():
    from core.companion_state import CompanionState
    from core.proactive_care_governor import ProactiveCareGovernor

    state = CompanionState()
    state.schedule_care_followup("明天复查体温", created_at=900.0, due_at=990.0)

    governor = ProactiveCareGovernor(now=lambda: 1000.0)
    decision = governor.plan_next(state)

    assert decision is not None
    assert decision.kind == "care_followup"
    assert decision.topic == "明天复查体温"
    assert decision.should_send is True
    assert state.care_followups[0].done is True


def test_pending_topic_is_resumed_after_it_has_waited_long_enough():
    from core.companion_state import CompanionState
    from core.proactive_care_governor import ProactiveCareGovernor

    state = CompanionState()
    state.add_pending_topic("继续聊旅行计划", created_at=100.0)

    governor = ProactiveCareGovernor(now=lambda: 4000.0)
    decision = governor.plan_next(state)

    assert decision is not None
    assert decision.kind == "pending_topic"
    assert decision.topic == "继续聊旅行计划"
    assert decision.should_send is True


def test_silence_greeting_uses_world_snapshot_context_without_external_calls():
    from core.companion_state import CompanionState
    from core.proactive_care_governor import ProactiveCareGovernor
    from core.world_simulation import WorldSimulation

    state = CompanionState()
    world = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 21, 30, tzinfo=timezone.utc))
    snapshot = world.tick()

    governor = ProactiveCareGovernor(now=lambda: 10000.0, silence_after_seconds=3600.0)
    decision = governor.plan_next(state, last_user_interaction_at=5000.0, world_snapshot=snapshot)

    assert decision is not None
    assert decision.kind == "silence_greeting"
    assert decision.topic == "quiet_check_in"
    assert decision.metadata["world_phase"] == "evening"
    assert decision.should_send is True


def test_daily_limit_and_min_interval_block_extra_care():
    from core.companion_state import CompanionState
    from core.proactive_care_governor import ProactiveCareGovernor

    state = CompanionState()
    state.schedule_care_followup("第一次", created_at=100.0, due_at=900.0)
    state.schedule_care_followup("第二次", created_at=100.0, due_at=901.0)

    governor = ProactiveCareGovernor(now=lambda: 1000.0, daily_limit=1, min_interval_seconds=600.0)
    first = governor.plan_next(state)
    second = governor.plan_next(state)

    assert first is not None
    assert first.kind == "care_followup"
    assert second is None
    assert state.care_followups[1].done is False


def test_user_ignore_creates_backoff_before_next_attempt():
    from core.companion_state import CompanionState
    from core.proactive_care_governor import ProactiveCareGovernor

    state = CompanionState()
    state.schedule_care_followup("药有没有按时吃", created_at=100.0, due_at=900.0)

    current = 1000.0
    governor = ProactiveCareGovernor(now=lambda: current, ignore_backoff_seconds=1800.0)
    governor.record_user_ignored("care_followup", "药有没有按时吃")

    blocked = governor.plan_next(state)
    current = 2900.0
    allowed = governor.plan_next(state)

    assert blocked is None
    assert allowed is not None
    assert allowed.kind == "care_followup"
    assert allowed.topic == "药有没有按时吃"

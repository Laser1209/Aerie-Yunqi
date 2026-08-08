from __future__ import annotations

from datetime import datetime, timezone


def _morning_snapshot():
    from core.world_simulation import WorldSimulation

    sim = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc))
    return sim.tick()


def test_generates_all_deterministic_proactive_intent_types_without_model_calls():
    from core.companion_state import CompanionState
    from core.proactive_candidates import ProactiveCandidateScorer, ProactiveIntent

    snapshot = _morning_snapshot()
    state = CompanionState(relationship_stage="close")
    state.schedule_care_followup("昨晚头痛", created_at=1000.0, due_at=1900.0)
    state.add_pending_topic("继续聊旅行计划", created_at=1100.0)
    state.add_pain_point("今天有点累", created_at=1200.0)

    candidates = ProactiveCandidateScorer(now=2000.0).generate(snapshot, state)
    intents = {candidate.intent for candidate in candidates}

    assert ProactiveIntent.LIFE_SHARE in intents
    assert ProactiveIntent.CARE_FOLLOWUP in intents
    assert ProactiveIntent.UNFINISHED_TOPIC in intents
    assert ProactiveIntent.MOOD_SHIFT in intents
    assert ProactiveIntent.ATTENTION_ACK in intents
    assert [candidate.score for candidate in candidates] == sorted(
        [candidate.score for candidate in candidates],
        reverse=True,
    )
    assert all(candidate.score >= 0.35 for candidate in candidates)
    assert all(candidate.source_snapshot_id == snapshot.world_snapshot_id for candidate in candidates)


def test_due_care_followup_and_user_preference_rank_above_life_share():
    from core.companion_state import CompanionState
    from core.proactive_candidates import ProactiveCandidateScorer, ProactiveIntent

    snapshot = _morning_snapshot()
    state = CompanionState(relationship_stage="intimate")
    state.schedule_care_followup("复查感冒", created_at=1000.0, due_at=1900.0)

    candidates = ProactiveCandidateScorer(
        now=2000.0,
        user_preferences={"preferred_intents": ["care_followup"]},
    ).generate(snapshot, state)

    assert candidates[0].intent is ProactiveIntent.CARE_FOLLOWUP
    assert candidates[0].topic == "复查感冒"
    assert candidates[0].score > next(
        candidate.score
        for candidate in candidates
        if candidate.intent is ProactiveIntent.LIFE_SHARE
    )


def test_recent_repetition_is_penalized_and_low_scores_are_filtered():
    from core.companion_state import CompanionState
    from core.proactive_candidates import ProactiveCandidateScorer, ProactiveIntent

    snapshot = _morning_snapshot()
    state = CompanionState(relationship_stage="stranger")
    state.add_pending_topic("还没讲完的书", created_at=1000.0)

    candidates = ProactiveCandidateScorer(
        now=2000.0,
        min_score=0.45,
        recent_intents=[ProactiveIntent.UNFINISHED_TOPIC, "life_share"],
    ).generate(snapshot, state)

    intents = [candidate.intent for candidate in candidates]

    assert ProactiveIntent.UNFINISHED_TOPIC not in intents
    assert ProactiveIntent.LIFE_SHARE not in intents
    assert all(candidate.score >= 0.45 for candidate in candidates)

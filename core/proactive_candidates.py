from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from core.companion_state import CompanionState
from core.world_simulation import WorldSnapshot


class ProactiveIntent(str, Enum):
    LIFE_SHARE = "life_share"
    CARE_FOLLOWUP = "care_followup"
    UNFINISHED_TOPIC = "unfinished_topic"
    MOOD_SHIFT = "mood_shift"
    ATTENTION_ACK = "attention_ack"


@dataclass
class ProactiveCandidate:
    intent: ProactiveIntent
    topic: str
    score: float
    source_snapshot_id: str
    reasons: list[str] = field(default_factory=list)


class ProactiveCandidateScorer:
    def __init__(
        self,
        *,
        now: float | None = None,
        min_score: float = 0.35,
        user_preferences: dict[str, Any] | None = None,
        recent_intents: Iterable[ProactiveIntent | str] | None = None,
    ) -> None:
        self.now = float(now) if now is not None else 0.0
        self.min_score = float(min_score)
        self.user_preferences = user_preferences or {}
        self.recent_intents = {_intent_value(item) for item in (recent_intents or [])}

    def generate(
        self,
        snapshot: WorldSnapshot,
        state: CompanionState,
    ) -> list[ProactiveCandidate]:
        candidates = self._build_candidates(snapshot, state)
        scored = [self._score(candidate, snapshot, state) for candidate in candidates]
        filtered = [candidate for candidate in scored if candidate.score >= self.min_score]
        return sorted(
            filtered,
            key=lambda candidate: (
                candidate.score,
                -_INTENT_ORDER[candidate.intent],
                candidate.topic,
            ),
            reverse=True,
        )

    def _build_candidates(
        self,
        snapshot: WorldSnapshot,
        state: CompanionState,
    ) -> list[ProactiveCandidate]:
        candidates = [
            ProactiveCandidate(
                intent=ProactiveIntent.LIFE_SHARE,
                topic=_first(snapshot.available_visual_topics, snapshot.activity),
                score=0.0,
                source_snapshot_id=snapshot.world_snapshot_id,
                reasons=["world_freshness"],
            ),
            ProactiveCandidate(
                intent=ProactiveIntent.ATTENTION_ACK,
                topic=f"{snapshot.phase}:{snapshot.activity}",
                score=0.0,
                source_snapshot_id=snapshot.world_snapshot_id,
                reasons=["world_presence"],
            ),
        ]

        due_followups = state.check_due_followups(now=self.now)
        for followup in due_followups:
            candidates.append(
                ProactiveCandidate(
                    intent=ProactiveIntent.CARE_FOLLOWUP,
                    topic=followup.topic,
                    score=0.0,
                    source_snapshot_id=snapshot.world_snapshot_id,
                    reasons=["due_followup"],
                )
            )

        for pending in state.pending_topics:
            if not pending.done:
                candidates.append(
                    ProactiveCandidate(
                        intent=ProactiveIntent.UNFINISHED_TOPIC,
                        topic=pending.topic,
                        score=0.0,
                        source_snapshot_id=snapshot.world_snapshot_id,
                        reasons=["pending_topic"],
                    )
                )
                break

        mood_topic = _latest_mood_topic(state)
        if mood_topic:
            candidates.append(
                ProactiveCandidate(
                    intent=ProactiveIntent.MOOD_SHIFT,
                    topic=mood_topic,
                    score=0.0,
                    source_snapshot_id=snapshot.world_snapshot_id,
                    reasons=["recent_mood_change"],
                )
            )

        return candidates

    def _score(
        self,
        candidate: ProactiveCandidate,
        snapshot: WorldSnapshot,
        state: CompanionState,
    ) -> ProactiveCandidate:
        score = _BASE_SCORES[candidate.intent]
        score += _world_freshness(snapshot, candidate.intent)
        score += _relationship_relevance(state.relationship_stage, candidate.intent)
        score += _emotion_change(state, candidate.intent)
        score += _preference_bonus(self.user_preferences, candidate.intent)
        score -= _recent_repeat_penalty(self.recent_intents, candidate.intent)
        candidate.score = round(max(0.0, min(1.0, score)), 4)
        return candidate


_INTENT_ORDER: dict[ProactiveIntent, int] = {
    ProactiveIntent.CARE_FOLLOWUP: 0,
    ProactiveIntent.UNFINISHED_TOPIC: 1,
    ProactiveIntent.MOOD_SHIFT: 2,
    ProactiveIntent.LIFE_SHARE: 3,
    ProactiveIntent.ATTENTION_ACK: 4,
}

_BASE_SCORES: dict[ProactiveIntent, float] = {
    ProactiveIntent.LIFE_SHARE: 0.26,
    ProactiveIntent.CARE_FOLLOWUP: 0.38,
    ProactiveIntent.UNFINISHED_TOPIC: 0.32,
    ProactiveIntent.MOOD_SHIFT: 0.3,
    ProactiveIntent.ATTENTION_ACK: 0.25,
}

_RELATIONSHIP_WEIGHTS: dict[str, float] = {
    "stranger": 0.0,
    "acquaintance": 0.03,
    "familiar": 0.06,
    "close": 0.1,
    "intimate": 0.14,
}


def _world_freshness(snapshot: WorldSnapshot, intent: ProactiveIntent) -> float:
    if not snapshot.world_snapshot_id:
        return 0.0
    if intent is ProactiveIntent.LIFE_SHARE:
        return 0.16 if snapshot.available_visual_topics else 0.08
    if intent is ProactiveIntent.ATTENTION_ACK:
        return 0.12
    return 0.06


def _relationship_relevance(stage: str, intent: ProactiveIntent) -> float:
    weight = _RELATIONSHIP_WEIGHTS.get(stage, 0.0)
    if intent is ProactiveIntent.CARE_FOLLOWUP:
        return weight + 0.06
    if intent is ProactiveIntent.UNFINISHED_TOPIC:
        return weight + 0.03
    if intent is ProactiveIntent.MOOD_SHIFT:
        return weight + 0.02
    return weight * 0.5


def _emotion_change(state: CompanionState, intent: ProactiveIntent) -> float:
    if intent is not ProactiveIntent.MOOD_SHIFT:
        return 0.0
    if state.recent_pain_points and state.recent_joy_points:
        return 0.16
    if state.recent_pain_points or state.recent_joy_points:
        return 0.12
    return 0.0


def _preference_bonus(preferences: dict[str, Any], intent: ProactiveIntent) -> float:
    preferred = {_intent_value(item) for item in preferences.get("preferred_intents", [])}
    muted = {_intent_value(item) for item in preferences.get("muted_intents", [])}
    if intent.value in muted:
        return -0.3
    if intent.value in preferred:
        return 0.18
    return 0.0


def _recent_repeat_penalty(recent_intents: set[str], intent: ProactiveIntent) -> float:
    return 0.42 if intent.value in recent_intents else 0.0


def _latest_mood_topic(state: CompanionState) -> str:
    entries: list[tuple[float, str]] = []
    entries.extend((point.created_at, point.text) for point in state.recent_pain_points)
    entries.extend((point.created_at, point.text) for point in state.recent_joy_points)
    if not entries:
        return ""
    return max(entries, key=lambda item: item[0])[1]


def _first(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


def _intent_value(value: ProactiveIntent | str) -> str:
    if isinstance(value, ProactiveIntent):
        return value.value
    return str(value)

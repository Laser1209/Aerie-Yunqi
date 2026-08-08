from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.companion_state import CompanionState


@dataclass
class ProactiveCareDecision:
    kind: str
    topic: str
    should_send: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class ProactiveCareGovernor:
    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        daily_limit: int = 3,
        min_interval_seconds: float = 1800.0,
        pending_topic_after_seconds: float = 1800.0,
        silence_after_seconds: float = 7200.0,
        ignore_backoff_seconds: float = 3600.0,
    ) -> None:
        self.now = now or time.time
        self.daily_limit = int(daily_limit)
        self.min_interval_seconds = float(min_interval_seconds)
        self.pending_topic_after_seconds = float(pending_topic_after_seconds)
        self.silence_after_seconds = float(silence_after_seconds)
        self.ignore_backoff_seconds = float(ignore_backoff_seconds)
        self._sent_count_by_day: dict[int, int] = {}
        self._last_sent_at: float | None = None
        self._ignored_at: dict[tuple[str, str], float] = {}

    def plan_next(
        self,
        state: CompanionState,
        *,
        last_user_interaction_at: float | None = None,
        world_snapshot: Any | None = None,
    ) -> ProactiveCareDecision | None:
        current = float(self.now())
        if not self._can_send(current):
            return None

        due_followup = self._pick_due_followup(state, current)
        if due_followup is not None:
            key = ("care_followup", due_followup.topic)
            if self._is_backing_off(key, current):
                return None
            due_followup.done = True
            return self._record(
                ProactiveCareDecision(
                    kind="care_followup",
                    topic=due_followup.topic,
                    metadata={"source": due_followup.source, "due_at": due_followup.due_at},
                ),
                current,
            )

        pending_topic = self._pick_pending_topic(state, current)
        if pending_topic is not None:
            key = ("pending_topic", pending_topic.topic)
            if self._is_backing_off(key, current):
                return None
            return self._record(
                ProactiveCareDecision(
                    kind="pending_topic",
                    topic=pending_topic.topic,
                    metadata={"created_at": pending_topic.created_at},
                ),
                current,
            )

        if self._silence_elapsed(last_user_interaction_at, current):
            key = ("silence_greeting", "quiet_check_in")
            if self._is_backing_off(key, current):
                return None
            return self._record(
                ProactiveCareDecision(
                    kind="silence_greeting",
                    topic="quiet_check_in",
                    metadata=self._world_metadata(world_snapshot),
                ),
                current,
            )

        return None

    def record_user_ignored(self, kind: str, topic: str) -> None:
        self._ignored_at[(str(kind), str(topic))] = float(self.now())

    def _pick_due_followup(self, state: CompanionState, current: float):
        due = state.check_due_followups(now=current)
        if not due:
            return None
        return sorted(due, key=lambda item: (item.due_at, item.created_at))[0]

    def _pick_pending_topic(self, state: CompanionState, current: float):
        candidates = [
            item
            for item in state.pending_topics
            if not item.done and current - item.created_at >= self.pending_topic_after_seconds
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.created_at)[0]

    def _can_send(self, current: float) -> bool:
        day = int(current // 86400)
        if self._sent_count_by_day.get(day, 0) >= self.daily_limit:
            return False
        if self._last_sent_at is None:
            return True
        return current - self._last_sent_at >= self.min_interval_seconds

    def _record(self, decision: ProactiveCareDecision, current: float) -> ProactiveCareDecision:
        day = int(current // 86400)
        self._sent_count_by_day[day] = self._sent_count_by_day.get(day, 0) + 1
        self._last_sent_at = current
        return decision

    def _is_backing_off(self, key: tuple[str, str], current: float) -> bool:
        ignored_at = self._ignored_at.get(key)
        if ignored_at is None:
            return False
        return current - ignored_at < self.ignore_backoff_seconds

    def _silence_elapsed(self, last_user_interaction_at: float | None, current: float) -> bool:
        if last_user_interaction_at is None:
            return False
        return current - float(last_user_interaction_at) >= self.silence_after_seconds

    def _world_metadata(self, world_snapshot: Any | None) -> dict[str, Any]:
        if world_snapshot is None:
            return {}
        return {
            "world_phase": _read_snapshot_value(world_snapshot, "phase"),
            "world_location": _read_snapshot_value(world_snapshot, "location"),
            "world_activity": _read_snapshot_value(world_snapshot, "activity"),
        }


def _read_snapshot_value(snapshot: Any, key: str) -> Any:
    if isinstance(snapshot, dict):
        return snapshot.get(key)
    return getattr(snapshot, key, None)

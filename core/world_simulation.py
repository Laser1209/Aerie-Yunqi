"""Phase 12 deterministic in-process world simulation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from core.action_registry import ActionRegistry, WorldAction


DEFAULT_WORLD_PHASES: dict[str, dict[str, Any]] = {
    "night": {
        "start": "23:00",
        "end": "06:30",
        "location": "home",
        "activity": "sleeping",
        "energy": 0.22,
        "social": "private",
    },
    "morning": {
        "start": "06:30",
        "end": "12:00",
        "location": "home",
        "activity": "planning",
        "energy": 0.70,
        "social": "private",
    },
    "afternoon": {
        "start": "12:00",
        "end": "18:00",
        "location": "study",
        "activity": "working",
        "energy": 0.58,
        "social": "focused",
    },
    "evening": {
        "start": "18:00",
        "end": "23:00",
        "location": "home",
        "activity": "relaxing",
        "energy": 0.48,
        "social": "private",
    },
}


class WorldSimulation:
    """A deterministic clock-driven snapshot generator.

    No LLM calls, no external facts, no database writes.  Given the same
    config seed and clock, a fresh simulator produces the same snapshot.
    """

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        self.config = config or {}
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.action_registry = action_registry or ActionRegistry()
        self.seed = str(self.config.get("seed") or "aerie-world")
        self._ticks = 0
        self._snapshot: dict[str, Any] = {}

    @staticmethod
    def minute(value: str) -> int:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)

    def phase_for(self, now: datetime) -> tuple[str, dict[str, Any]]:
        current = now.hour * 60 + now.minute
        phases = self.config.get("phases")
        if not isinstance(phases, dict) or not phases:
            phases = DEFAULT_WORLD_PHASES
        for name, phase in phases.items():
            if not isinstance(phase, dict):
                continue
            start = self.minute(phase.get("start", "00:00"))
            end = self.minute(phase.get("end", "23:59"))
            if start <= end and start <= current < end:
                return str(name), phase
            if start > end and (current >= start or current < end):
                return str(name), phase
        return "unknown", {
            "location": "home",
            "activity": "idle",
            "energy": 0.5,
            "social": "private",
        }

    def tick(self, action: WorldAction | None = None) -> dict[str, Any]:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        phase_name, phase = self.phase_for(now)
        activity = str(phase.get("activity", "idle"))
        action_result = None
        if action is not None:
            action_result = self.action_registry.execute(
                action,
                world_snapshot={"activity": activity},
            )
            if action_result.get("action") == "set_activity":
                activity = str(action_result.get("activity") or activity)

        self._ticks += 1
        energy = _clamp01(float(phase.get("energy", 0.5)))
        base = {
            "ts": int(now.timestamp()),
            "iso_time": now.isoformat(),
            "phase": phase_name,
            "location": str(phase.get("location", "home")),
            "activity": activity,
            "energy": energy,
            "social": str(phase.get("social", "private")),
            "source": "simulated",
            "revision": self._ticks,
            "seed_sha256": _sha256(self.seed),
        }
        base["snapshot_id"] = _sha256(
            json.dumps(
                {
                    "seed": self.seed,
                    "ts": base["ts"],
                    "phase": phase_name,
                    "revision": self._ticks,
                    "activity": activity,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        if action_result:
            base["last_action"] = action.to_public_dict()
        self._snapshot = base
        return dict(base)

    def get_snapshot(self) -> dict[str, Any]:
        if not self._snapshot:
            return self.tick()
        return dict(self._snapshot)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

"""Phase 12 computed SelfModel snapshot."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class SelfModel:
    """Derives internal state from world + relationship snapshots.

    No LLM, no secrets, no external facts.  It is deliberately calculable
    so same inputs produce the same state.
    """

    def __init__(self, *, seed: str = "aerie-self") -> None:
        self.seed = seed

    def snapshot(
        self,
        *,
        world_snapshot: dict[str, Any] | None,
        relationship_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        world = world_snapshot or {}
        relationship = relationship_snapshot or {}
        energy = _clamp01(float(world.get("energy", 0.5)))
        security = _clamp01(float(relationship.get("security", 0.5)))
        conflict = _clamp01(float(relationship.get("conflict", 0.0)))
        focus = _clamp01((energy * 0.55) + (security * 0.30) + ((1 - conflict) * 0.15))
        social_need = _clamp01((1 - security) * 0.45 + (1 - energy) * 0.20 + conflict * 0.35)
        payload = {
            "seed": self.seed,
            "phase": world.get("phase", "unknown"),
            "energy": round(energy, 4),
            "security": round(security, 4),
            "conflict": round(conflict, 4),
        }
        return {
            "source": "computed",
            "phase": world.get("phase", "unknown"),
            "energy": round(energy, 4),
            "focus": round(focus, 4),
            "social_need": round(social_need, 4),
            "stability": round(_clamp01(security * (1 - conflict)), 4),
            "state_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))

"""Internal-state modeling: needs / fatigue / neurochemical-like computed metrics.

Phase 15 Batch 3 (B3.1). The design document asks for three concepts that did
not exist anywhere in the codebase:

  - needs       : multi-dimension desires (social / companion / exploration / rest)
  - fatigue     : scalar tiredness
  - neurochemicals : dopamine / serotonin / cortisol STYLE "computed metrics"

These are deliberately **computation-only** indicators. They are NOT medical
measurements: the dashboard must always label them "计算模型，非生物测量" and
never describe them in clinical terms (red line 2).

Design principles:
  - Deterministic: given the same inputs (world snapshot + emotion + clock) the
    result is stable and reproducible, so it is testable.
  - Source-tracked: every metric carries a ``source`` tag and a ``confidence``
    in (0, 1], so the dashboard can show where a value came from.
  - Values live in [0, 1]; ranges/decay mirror the emotion-slot convention.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

# Default wake-up hour used to derive waking duration when no world activity
# history is available. Overridable via config.
_DEFAULT_WAKE_HOUR = 7.0
_DEFAULT_REST_BASE = 0.10

# Style labels (non-medical) for the neurochemical-like metrics.
_NEURO_LABELS: dict[str, str] = {
    "vitality": "活力（类多巴胺）",
    "calm": "平静（类血清素）",
    "strain": "压力（类皮质醇）",
}
_NEURO_ENABLED = ("vitality", "calm", "strain")

_NEEDS_LABELS: dict[str, str] = {
    "social": "社交",
    "companion": "陪伴",
    "exploration": "探索",
    "rest": "休息",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    if not isinstance(value, (int, float)):
        return low
    return max(low, min(high, float(value)))


def _metric(value: float, source: str, confidence: float = 0.8) -> dict[str, Any]:
    """Build a source-tracked metric object."""
    return {
        "value": round(_clamp(value), 4),
        "source": source,
        "confidence": round(_clamp(confidence), 4),
        "updated_at": int(time.time() * 1000),
    }


class InternalStateEngine:
    """Deterministic internal-state model driven by world + emotion + clock.

    The engine is stateless w.r.t. model inputs: calling ``compute`` with the
    same inputs yields the same output. It keeps a bounded in-memory ring of
    recent snapshots for the trend endpoint.
    """

    def __init__(
        self,
        *,
        wake_hour: float = _DEFAULT_WAKE_HOUR,
        rest_base: float = _DEFAULT_REST_BASE,
        history_limit: int = 200,
    ) -> None:
        self.wake_hour = float(wake_hour)
        self.rest_base = float(rest_base)
        self._history: deque[dict[str, Any]] = deque(maxlen=max(1, int(history_limit)))

    # ── model ──────────────────────────────────────────────────────────

    def compute(
        self,
        world: dict[str, Any] | None,
        emotion: dict[str, Any] | None,
        relationship: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Compute the internal-state snapshot from current inputs.

        ``world``       : world summary (activity / phase / energy) or None.
        ``emotion``     : emotion state (pad / label) or None.
        ``relationship``: relationship state (attachment / trust / etc.) or None.
        ``now``         : epoch seconds; defaults to time.time().

        The snapshot also mirrors the current PAD and relationship summary so
        the single history ring can drive all three trend charts (B3.2).
        """
        now = float(now) if now is not None else time.time()
        world = world if isinstance(world, dict) else {}
        emotion = emotion if isinstance(emotion, dict) else {}
        relationship = relationship if isinstance(relationship, dict) else {}

        activity = str(world.get("activity") or world.get("activityType") or "").lower()
        phase = str(world.get("phase") or "").lower()
        energy = _to_num(world.get("energy"))

        pad = emotion.get("pad") if isinstance(emotion.get("pad"), dict) else {}
        P = _to_num(pad.get("P", pad.get("pleasure")))
        A = _to_num(pad.get("A", pad.get("arousal")))
        D = _to_num(pad.get("D", pad.get("dominance")))

        needs = self._needs(activity, phase, P, D, energy)
        fatigue = self._fatigue(now, phase, activity)
        neuro = self._neuro(P, A, D)

        snapshot = {
            "sampledAt": int(now * 1000),
            "label": "计算模型，非生物测量",
            "needs": needs,
            "fatigue": fatigue,
            "neurochemicals": neuro,
            "pad": {"P": round(P, 4), "A": round(A, 4), "D": round(D, 4)},
            "relationship": self._relationship_summary(relationship),
        }
        self._history.append(snapshot)
        return snapshot

    def _relationship_summary(self, relationship: dict[str, Any]) -> dict[str, float] | None:
        """Narrow relationship summary for the trend chart (values in [0,1])."""
        if not relationship:
            return None
        out: dict[str, float] = {}
        for key in ("attachment", "trust", "security", "conflict"):
            value = _to_num(relationship.get(key))
            # _to_num returns 0.5 for missing values; only keep present keys.
            if relationship.get(key) is not None and relationship.get(key) != "":
                out[key] = round(_clamp(value), 4)
        return out or None

    def _needs(self, activity: str, phase: str, P: float, D: float, energy: float) -> dict[str, Any]:
        """Multi-dimension desires in [0,1].

        Driving rules (deterministic, source-tracked):
          - sleeping/resting  -> rest need drops, others edge up
          - social/chat/talk  -> social & companion need drops
          - exploration/planning -> exploration need drops
          - low pleasure (P) raises companion need; low energy raises rest need
        """
        is_sleeping = activity in ("sleep", "sleeping", "rest", "resting") or phase == "night"
        is_social = any(k in activity for k in ("talk", "chat", "social", "companion", "play"))
        is_explore = any(k in activity for k in ("explore", "plan", "travel", "walk", "work"))

        social = _clamp(0.55 - (0.5 if is_social else 0.0) + (0.25 if not is_sleeping else 0.05))
        companion = _clamp(0.55 - (0.4 if is_social else 0.0) + _clamp((0.3 - P) * 0.5))
        exploration = _clamp(0.55 - (0.5 if is_explore else 0.0) + (0.2 if is_sleeping else 0.0))
        rest = _clamp(0.5 - (0.6 if is_sleeping else 0.0) + _clamp((0.5 - energy) * 0.8))

        return {
            "social": _metric(social, "world:activity", 0.7),
            "companion": _metric(companion, "emotion:pad:P", 0.75),
            "exploration": _metric(exploration, "world:activity", 0.7),
            "rest": _metric(rest, "world:energy", 0.8),
        }

    def _fatigue(self, now: float, phase: str, activity: str) -> dict[str, Any]:
        """Scalar tiredness in [0,1], rising across a waking day.

        Waking duration is derived deterministically from the clock vs. a
        configured wake hour. Sleeping/resting decays fatigue toward the base.
        """
        is_sleeping = activity in ("sleep", "sleeping", "rest", "resting") or phase == "night"
        lt = time.localtime(now)
        hour = float(lt.tm_hour) + float(lt.tm_min) / 60.0
        if is_sleeping:
            value = self.rest_base
        else:
            # minutes since wake hour, wrapped to [0, 24)
            minutes = (hour - self.wake_hour) % 24.0
            value = 0.15 + minutes / 24.0 * 0.8  # 0.15 -> 0.95 across the day
        return _metric(value, "time:clock", 0.85)

    def _neuro(self, P: float, A: float, D: float) -> dict[str, Any]:
        """Neurochemical-STYLE computed metrics, non-medical.

          - vitality  (类多巴胺): driven by pleasure + arousal
          - calm      (类血清素): driven by dominance + pleasure
          - strain    (类皮质醇): driven by arousal when pleasure is low
        """
        vitality = _clamp(0.5 + (P - 0.5) * 0.7 + (A - 0.5) * 0.3)
        calm = _clamp(0.5 + (D - 0.5) * 0.6 + (P - 0.5) * 0.4)
        strain = _clamp(0.5 + (A - 0.5) * 0.7 + (0.5 - P) * 0.5)
        return {
            "vitality": _metric(vitality, "emotion:pad:P", 0.7),
            "calm": _metric(calm, "emotion:pad:D", 0.7),
            "strain": _metric(strain, "emotion:pad:A", 0.7),
        }

    # ── history / trends ───────────────────────────────────────────────

    def snapshot(self, world: dict[str, Any] | None, emotion: dict[str, Any] | None, now: float | None = None) -> dict[str, Any]:
        """Compute + record a snapshot (called by the API)."""
        return self.compute(world, emotion, now)

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the recent snapshot ring buffer, oldest first."""
        limit = max(1, min(int(limit), self._history.maxlen))
        return list(self._history)[-limit:]

    def clear_history(self) -> None:
        self._history.clear()


def _to_num(value: Any) -> float:
    try:
        n = float(value)
        if n != n:  # NaN
            return 0.5
        return n
    except (TypeError, ValueError):
        return 0.5


def public_neuro_labels() -> dict[str, str]:
    """Non-medical display labels for the neurochemical-style metrics."""
    return dict(_NEURO_LABELS)


def public_needs_labels() -> dict[str, str]:
    return dict(_NEEDS_LABELS)

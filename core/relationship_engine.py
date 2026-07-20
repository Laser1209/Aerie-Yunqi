"""Phase 12 deterministic, persona-scoped relationship state."""

from __future__ import annotations

import copy
import hashlib
from typing import Any


POSITIVE_HINTS = ("谢谢", "喜欢", "开心", "爱", "棒", "可靠", "温柔", "thank", "like", "love")
NEGATIVE_HINTS = ("烦", "讨厌", "滚", "别", "生气", "失望", "讨厌", "hate", "annoying")


class RelationshipEngine:
    def __init__(
        self,
        *,
        defaults: dict[str, float] | None = None,
        learning_rate: float = 0.08,
    ) -> None:
        self.defaults = {
            "attachment": 0.55,
            "trust": 0.60,
            "care": 0.65,
            "warmth": 0.50,
            "engagement": 0.50,
            "user_trust": 0.50,
            "security": 0.55,
            "conflict": 0.0,
        }
        if isinstance(defaults, dict):
            for key, value in defaults.items():
                if key in self.defaults:
                    self.defaults[key] = _clamp01(float(value))
        self.learning_rate = max(0.0, min(0.25, float(learning_rate)))
        self._states: dict[tuple[str, str], dict[str, Any]] = {}

    def get_state(self, *, user_id: int | str, persona_id: str = "default") -> dict[str, Any]:
        key = self._key(user_id, persona_id)
        if key not in self._states:
            self._states[key] = self._new_state(user_id, persona_id)
        return copy.deepcopy(self._states[key])

    def observe_user_message(
        self,
        *,
        user_id: int | str,
        persona_id: str = "default",
        text: str,
    ) -> dict[str, Any]:
        state = self.get_state(user_id=user_id, persona_id=persona_id)
        label, valence = self._estimate_valence(text)
        rate = self.learning_rate
        if valence > 0:
            state["agent_to_user"]["attachment"] = _clamp01(state["agent_to_user"]["attachment"] + rate * 0.5)
            state["agent_to_user"]["trust"] = _clamp01(state["agent_to_user"]["trust"] + rate * 0.6)
            state["agent_to_user"]["care"] = _clamp01(state["agent_to_user"]["care"] + rate * 0.4)
            state["user_to_agent"]["warmth"] = _clamp01(state["user_to_agent"]["warmth"] + rate * 0.7)
            state["user_to_agent"]["engagement"] = _clamp01(state["user_to_agent"]["engagement"] + rate * 0.4)
            state["user_to_agent"]["trust"] = _clamp01(state["user_to_agent"]["trust"] + rate * 0.5)
            state["security"] = _clamp01(state["security"] + rate * 0.4)
            state["conflict"] = _clamp01(state["conflict"] - rate * 0.5)
        elif valence < 0:
            state["agent_to_user"]["trust"] = _clamp01(state["agent_to_user"]["trust"] - rate * 0.5)
            state["user_to_agent"]["warmth"] = _clamp01(state["user_to_agent"]["warmth"] - rate * 0.6)
            state["user_to_agent"]["trust"] = _clamp01(state["user_to_agent"]["trust"] - rate * 0.5)
            state["security"] = _clamp01(state["security"] - rate * 0.5)
            state["conflict"] = _clamp01(state["conflict"] + rate)
        else:
            state["user_to_agent"]["engagement"] = _clamp01(state["user_to_agent"]["engagement"] + rate * 0.1)

        state["user_emotion"] = {
            "label": label,
            "valence": valence,
            "text_sha256": hashlib.sha256(str(text or "").encode("utf-8")).hexdigest(),
        }
        state["revision"] += 1
        self._states[self._key(user_id, persona_id)] = copy.deepcopy(state)
        return copy.deepcopy(state)

    def reset(self, *, user_id: int | str, persona_id: str = "default") -> dict[str, Any]:
        key = self._key(user_id, persona_id)
        self._states[key] = self._new_state(user_id, persona_id)
        return copy.deepcopy(self._states[key])

    def _new_state(self, user_id: int | str, persona_id: str) -> dict[str, Any]:
        return {
            "user_id": str(user_id),
            "persona_id": str(persona_id or "default"),
            "agent_to_user": {
                "attachment": self.defaults["attachment"],
                "trust": self.defaults["trust"],
                "care": self.defaults["care"],
            },
            "user_to_agent": {
                "warmth": self.defaults["warmth"],
                "engagement": self.defaults["engagement"],
                "trust": self.defaults["user_trust"],
            },
            "security": self.defaults["security"],
            "conflict": self.defaults["conflict"],
            "user_emotion": {"label": "neutral", "valence": 0.0},
            "source": "computed",
            "revision": 0,
        }

    def _estimate_valence(self, text: str) -> tuple[str, float]:
        normalized = str(text or "").lower()
        positive = any(hint in normalized for hint in POSITIVE_HINTS)
        negative = any(hint in normalized for hint in NEGATIVE_HINTS)
        if positive and not negative:
            return "positive", 0.35
        if negative and not positive:
            return "negative", -0.35
        return "neutral", 0.0

    @staticmethod
    def _key(user_id: int | str, persona_id: str) -> tuple[str, str]:
        return (str(user_id), str(persona_id or "default"))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))

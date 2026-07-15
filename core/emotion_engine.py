"""Aerie · 云栖 v9.0 — PAD three-dimensional emotion engine.

Models emotion as Pleasure-Arousal-Dominance and maps discrete events
to PAD deltas. Provides a 5-class label (joy/sad/anger/fear/neutral).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from core.database import Database


# Event type → (ΔP, ΔA, ΔD) base increments (will be scaled by intensity)
EVENT_PAD_MAP: dict[str, tuple[float, float, float]] = {
    "user_praise":   (+0.20, +0.10, +0.05),  # 用户夸她 → 愉悦上升
    "user_gift":     (+0.25, +0.15, +0.05),
    "user_attack":   (-0.30, +0.20, -0.10),  # 用户攻击 → 愤怒
    "user_cold":     (-0.15, -0.10, -0.05),  # 用户冷淡 → 失落
    "user_idle":     (-0.05, -0.05, +0.05),
    "user_miss":     (-0.10, +0.15, +0.10),  # 用户说想她 → 渴望
    "user_vulnerable":(+0.10, -0.20, -0.15), # 用户脆弱 → 温柔
    "system_error":  (-0.10, +0.10, -0.05),
    "system_recover":(+0.10, -0.05, +0.10),
    "proactive_send":(+0.05, +0.05, +0.05),
    "recall":        (-0.05, +0.15, -0.05),  # 撤回 → 害羞
    "test":          (+0.15, +0.05, 0.00),
}


@dataclass
class PADState:
    """Pleasure / Arousal / Dominance triplet in [-1, +1]."""

    pleasure: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.5
    label: str = "neutral"

    def clamp(self) -> "PADState":
        self.pleasure = max(-1.0, min(1.0, self.pleasure))
        self.arousal = max(-1.0, min(1.0, self.arousal))
        self.dominance = max(-1.0, min(1.0, self.dominance))
        return self

    def as_dict(self) -> dict:
        return {
            "pleasure": round(self.pleasure, 3),
            "arousal": round(self.arousal, 3),
            "dominance": round(self.dominance, 3),
            "label": self.label,
        }


class EmotionEngine:
    """PAD-based emotion engine with event-driven updates."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()
        # Per-user state, persisted in memory; not in DB (PAD is transient)
        self._state: dict[int, PADState] = {}

    def get_state(self, user_id: int) -> PADState:
        if user_id not in self._state:
            self._state[user_id] = PADState()
        return self._state[user_id]

    def get_current_mood(self, user_id: int) -> str:
        return self.get_state(user_id).label

    def get_label(self, pad: PADState | None = None) -> str:
        """Map a PADState to one of 5 discrete labels."""
        if pad is None:
            return "neutral"
        # Pleasure dominant → joy vs sad
        if pad.pleasure > 0.3:
            return "joy"
        if pad.pleasure < -0.3:
            if pad.arousal > 0.2:
                return "anger"
            return "sad"
        if pad.arousal > 0.4 and pad.pleasure < -0.1:
            return "fear"
        return "neutral"

    def trigger(self, event_type: str, user_id: int = 0, intensity: float = 1.0) -> PADState:
        """Update PAD based on event type and intensity."""
        if event_type not in EVENT_PAD_MAP:
            return self.get_state(user_id)
        dP, dA, dD = EVENT_PAD_MAP[event_type]
        scale = max(0.0, float(intensity))
        state = self.get_state(user_id)
        state.pleasure += dP * scale
        state.arousal += dA * scale
        state.dominance += dD * scale
        state.clamp()
        state.label = self.get_label(state)
        # Persist
        try:
            self.db.insert(
                "emotion_log",
                {
                    "user_id": user_id,
                    "event_type": event_type,
                    "intensity": scale,
                    "pleasure": state.pleasure,
                    "arousal": state.arousal,
                    "dominance": state.dominance,
                    "label": state.label,
                },
            )
        except Exception:
            pass
        return state

    def get_history(self, user_id: int, limit: int = 50) -> list[dict]:
        return self.db.query(
            "SELECT event_type, intensity, pleasure, arousal, dominance, label, created_at "
            "FROM emotion_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    def reset(self, user_id: int) -> None:
        self._state[user_id] = PADState()

"""Aerie · 云栖 v9.0 — Emotion state machine.

Rules for transitioning between Neutral / Joy / Sad / Anger / Fear,
with transition speed hints.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class EmotionLabel(str, Enum):
    NEUTRAL = "neutral"
    JOY = "joy"
    SAD = "sad"
    ANGER = "anger"
    FEAR = "fear"


# Allowed transitions
TRANSITIONS: dict[EmotionLabel, set[EmotionLabel]] = {
    EmotionLabel.NEUTRAL: {EmotionLabel.JOY, EmotionLabel.SAD, EmotionLabel.ANGER, EmotionLabel.FEAR},
    EmotionLabel.JOY:     {EmotionLabel.NEUTRAL, EmotionLabel.SAD, EmotionLabel.ANGER},
    EmotionLabel.SAD:     {EmotionLabel.NEUTRAL, EmotionLabel.FEAR, EmotionLabel.ANGER},
    EmotionLabel.ANGER:   {EmotionLabel.NEUTRAL, EmotionLabel.SAD, EmotionLabel.FEAR},
    EmotionLabel.FEAR:    {EmotionLabel.NEUTRAL, EmotionLabel.SAD, EmotionLabel.ANGER},
}

# Approximate transition speed (in seconds)
TRANSITION_SPEED: dict[tuple[EmotionLabel, EmotionLabel], str] = {
    (EmotionLabel.NEUTRAL, EmotionLabel.JOY):    "seconds",
    (EmotionLabel.NEUTRAL, EmotionLabel.SAD):    "minutes",
    (EmotionLabel.NEUTRAL, EmotionLabel.ANGER):  "seconds",
    (EmotionLabel.NEUTRAL, EmotionLabel.FEAR):   "seconds",
    (EmotionLabel.JOY, EmotionLabel.NEUTRAL):    "minutes",
    (EmotionLabel.SAD, EmotionLabel.NEUTRAL):    "hours",
    (EmotionLabel.ANGER, EmotionLabel.NEUTRAL):  "minutes",
    (EmotionLabel.FEAR, EmotionLabel.NEUTRAL):   "minutes",
}


class EmotionStateMachine:
    """State machine for emotion labels."""

    def __init__(self, initial: EmotionLabel = EmotionLabel.NEUTRAL) -> None:
        self.current: EmotionLabel = initial

    def can_transition(self, target: EmotionLabel) -> bool:
        if target == self.current:
            return True
        return target in TRANSITIONS.get(self.current, set())

    def transition(self, target: EmotionLabel) -> bool:
        if not self.can_transition(target):
            return False
        self.current = target
        return True

    def transition_speed(self, target: EmotionLabel) -> str:
        return TRANSITION_SPEED.get((self.current, target), "unknown")

    def force(self, label: EmotionLabel) -> None:
        """Force a state regardless of allowed transitions (use carefully)."""
        self.current = label

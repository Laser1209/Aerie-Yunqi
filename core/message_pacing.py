"""Aerie · 云栖 v13.9.8 — Message pacing engine.

Phase 9: 1.5s hard cap + jitter + emotion-aware base.
User clarification: 1.5s is the maximum interval, not a fixed value.
The actual interval is base ± jitter, clamped to [0.4s, 1.5s], and
the base shifts based on Ita's current emotion label so the rhythm
matches §11.2.1 (表现速查表) in OpenCloud_Companion_System_Features.md.
"""

from __future__ import annotations

import random
from typing import Optional

# Hard ceiling — user request (2026-07-16)
HARD_CAP: float = 1.5

# Hard floor — never go below 0.4s, otherwise the UI feels like a flood
HARD_FLOOR: float = 0.4

# Emotion-specific base interval (seconds). Aligned with §11.2.1:
#   joy/anger/fear  →  reply faster
#   neutral         →  relaxed default
#   sad/missing     →  slow down (matches "消息间隔变长")
#   affection       →  slightly faster, but with warmth
#   curiosity       →  engaged
EMOTION_BASE: dict[str, float] = {
    "joy": 0.55,
    "anger": 0.45,
    "fear": 0.40,
    "neutral": 0.70,
    "sad": 0.95,
    "curiosity": 0.75,
    "affection": 0.60,
    "missing": 0.85,
    "default": 0.70,
}

# Jitter envelope (± seconds)
JITTER: float = 0.30

# Eruption multiplier — when an emotion threshold just erupted,
# responses come faster (genuine impulse, less filtered)
ERUPTION_MULTIPLIER: float = 0.70


def compute_interval(
    emotion_label: Optional[str] = None,
    is_eruption: bool = False,
) -> float:
    """Compute the next segment interval based on emotion + jitter.

    Args:
        emotion_label: Current emotion label (e.g. 'joy', 'sad', 'neutral').
            Falls back to 'default' when None or unknown.
        is_eruption: True when a threshold just erupted.

    Returns:
        Interval in seconds, clamped to [HARD_FLOOR, HARD_CAP].
    """
    key = (emotion_label or "default").strip().lower() or "default"
    base = EMOTION_BASE.get(key, EMOTION_BASE["default"])
    if is_eruption:
        base = min(base * ERUPTION_MULTIPLIER, 1.0)
    jitter = random.uniform(-JITTER, JITTER)
    value = base + jitter
    return max(HARD_FLOOR, min(HARD_CAP, value))

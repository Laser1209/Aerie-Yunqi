"""Aerie · 云栖 v9.0 — Persona decision layer.

Four-tier candidate generation with weights (0.5 / 0.3 / 0.15 / 0.05).
L1 = primary, L2 = fallback, L3 = emergency, L4 = debug.
"""

from __future__ import annotations

import random
from enum import IntEnum
from typing import Any


class DecisionLayer(IntEnum):
    L1_PRIMARY = 1
    L2_FALLBACK = 2
    L3_EMERGENCY = 3
    L4_DEBUG = 4


WEIGHTS = {
    DecisionLayer.L1_PRIMARY: 0.50,
    DecisionLayer.L2_FALLBACK: 0.30,
    DecisionLayer.L3_EMERGENCY: 0.15,
    DecisionLayer.L4_DEBUG: 0.05,
}


class PersonaDecision:
    """Weighted random pick across decision layers."""

    def __init__(self, weights: dict[DecisionLayer, float] | None = None) -> None:
        self.weights = {**WEIGHTS, **(weights or {})}
        # Normalize
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def decide(
        self,
        candidates: dict[DecisionLayer, Any],
        context: dict | None = None,
        rng: random.Random | None = None,
    ) -> tuple[DecisionLayer, Any]:
        """Return (chosen_layer, chosen_candidate)."""
        rng = rng or random
        layers = list(candidates.keys())
        weights = [self.weights.get(layer, 0.0) for layer in layers]
        if sum(weights) <= 0:
            layer = layers[0] if layers else DecisionLayer.L4_DEBUG
        else:
            layer = rng.choices(layers, weights=weights, k=1)[0]
        return layer, candidates[layer]

    def layer_for(self, context: dict) -> DecisionLayer:
        """Heuristic layer selection based on context signals."""
        mood = (context or {}).get("mood", "neutral")
        is_emergency = (context or {}).get("emergency", False)
        if is_emergency:
            return DecisionLayer.L3_EMERGENCY
        if mood in ("angry", "fear"):
            return DecisionLayer.L3_EMERGENCY
        if mood in ("sad", "neutral"):
            return DecisionLayer.L2_FALLBACK
        return DecisionLayer.L1_PRIMARY

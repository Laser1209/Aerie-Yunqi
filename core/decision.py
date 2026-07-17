"""Aerie · 云栖 v9.0 — Multi-layer decision system (Phase 9: §10.2).

Implements the 4-layer weighted decision described in
OpenCloud_Companion_System_Features.md §10.2:

    L1_core_value     (weight 0.50) — hard-rule filter
    L2_personality    (weight 0.30) — persona soft scoring
    L3_mood           (weight 0.15) — current emotion influence
    L4_context        (weight 0.05) — situational micro-adjustment

For every incoming message, a small set of candidate intents is
proposed (reply / tool_call / recall / silence) and the layer
weights are applied. The chosen intent is sampled via softmax
over the weighted scores — this preserves exploration so the
same input doesn't always pick the same intent.

The full breakdown (per-layer scores + weighted scores + chosen)
is returned as a dict and persisted in cognition_log.decision_trace
so the brain-center UI can show "why Ita chose X" later.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Candidate model ───────────────────────────────────
@dataclass
class Candidate:
    """A possible intent for the current message."""
    id: str                         # stable id used in the trace
    intent: str                     # human-readable intent name
    payload: dict | None = None     # optional context


# ── Multi-layer decision engine ───────────────────────
class MultiLayerDecision:
    """Weighted 4-layer decision (L1+L2+L3+L4) with softmax sampling.

    Use ``decide_for_message(...)`` from the Pipeline — it constructs
    the candidate set and the context dict for you based on
    route_mode / source / emotion state.
    """

    WEIGHTS: dict[str, float] = {
        "L1_core": 0.50,
        "L2_personality": 0.30,
        "L3_mood": 0.15,
        "L4_context": 0.05,
    }

    # Default per-layer bias for each intent (used in L2/L4)
    _PERSONA_BIAS: dict[str, float] = {
        "reply": 0.65,
        "recall": 0.55,
        "tool_call": 0.60,
        "proactive_silence": 0.25,
        "self_evolve": 0.40,
    }
    _CONTEXT_BIAS: dict[str, float] = {
        "reply": 0.55,
        "recall": 0.50,
        "tool_call": 0.45,
        "proactive_silence": 0.40,
        "self_evolve": 0.30,
    }

    # Mood bias table (L3)
    _MOOD_BIAS: dict[str, float] = {
        "joy": 0.75, "affection": 0.80, "love": 0.85,
        "anger": 0.45, "sad": 0.35, "fear": 0.85,
        "missing": 0.65, "neutral": 0.50, "curiosity": 0.60,
    }

    def decide(
        self,
        candidates: Iterable[Candidate],
        context: dict,
    ) -> dict:
        """Run the 4-layer decision and return the trace dict.

        Returns:
            {
              "chosen": <candidate id>,
              "scores": {cid: weighted_score, ...},
              "layers": {cid: {"L1":..., "L2":..., "L3":..., "L4":...}},
              "weights": {layer: weight, ...},
              "context_snapshot": {...}
            }
        """
        cands = list(candidates)
        if not cands:
            return {
                "chosen": None,
                "scores": {},
                "layers": {},
                "weights": dict(self.WEIGHTS),
                "context_snapshot": context,
            }

        scores: dict[str, float] = {c.id: 0.0 for c in cands}
        layers: dict[str, dict[str, float]] = {
            c.id: {"L1": 0.0, "L2": 0.0, "L3": 0.0, "L4": 0.0}
            for c in cands
        }

        # Apply each layer in order
        for layer_name, fn in (
            ("L1", self._apply_core),
            ("L2", self._apply_personality),
            ("L3", self._apply_mood),
            ("L4", self._apply_context),
        ):
            partial = fn(cands, context)
            weight = self.WEIGHTS[f"L{layer_name[1]}_" if False else layer_name]
            for c in cands:
                sc = partial.get(c.id, 0.5)
                layers[c.id][layer_name] = round(sc, 4)
                scores[c.id] += weight * sc

        # Softmax sample
        chosen_id = self._softmax_pick(
            [c.id for c in cands], list(scores.values())
        )

        return {
            "chosen": chosen_id,
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "layers": layers,
            "weights": dict(self.WEIGHTS),
            "context_snapshot": {
                k: v for k, v in context.items()
                if k in ("emotion_label", "user_busy", "route_mode", "source",
                          "active_eruption", "tools_offered")
            },
        }

    # ── Layer 1: core value (hard-rule filter) ─────────
    def _apply_core(self, candidates: list[Candidate], ctx: dict) -> dict[str, float]:
        out: dict[str, float] = {}
        emotion = (ctx.get("emotion_label") or "neutral").lower()
        route = (ctx.get("route_mode") or "AUTO").upper()
        for c in candidates:
            if c.intent == "proactive_silence" and ctx.get("user_busy"):
                out[c.id] = 0.95
            elif c.intent == "recall" and emotion in ("sad", "fear", "missing"):
                out[c.id] = 0.90
            elif c.intent == "tool_call" and route != "FULL":
                out[c.id] = 0.05
            elif c.intent == "self_evolve" and route != "FULL":
                out[c.id] = 0.10
            elif c.intent == "reply":
                out[c.id] = 0.85  # baseline: reply is the default
            else:
                out[c.id] = 0.50
        return out

    # ── Layer 2: personality soft scoring ───────────────
    def _apply_personality(self, candidates: list[Candidate], ctx: dict) -> dict[str, float]:
        return {c.id: self._PERSONA_BIAS.get(c.intent, 0.5) for c in candidates}

    # ── Layer 3: mood influence ────────────────────────
    def _apply_mood(self, candidates: list[Candidate], ctx: dict) -> dict[str, float]:
        label = (ctx.get("emotion_label") or "neutral").lower()
        bias = self._MOOD_BIAS.get(label, 0.5)
        # When fear/sad, suppress tool_call & silence, push reply
        if label in ("fear", "sad"):
            return {
                c.id: (0.90 if c.intent == "reply" else 0.30)
                for c in candidates
            }
        return {c.id: bias for c in candidates}

    # ── Layer 4: situational micro-adjustment ──────────
    def _apply_context(self, candidates: list[Candidate], ctx: dict) -> dict[str, float]:
        out: dict[str, float] = {}
        tools = bool(ctx.get("tools_offered"))
        for c in candidates:
            bias = self._CONTEXT_BIAS.get(c.intent, 0.5)
            if c.intent == "tool_call" and not tools:
                bias = 0.10
            out[c.id] = bias
        return out

    # ── Sampling ───────────────────────────────────────
    def _softmax_pick(self, items: list[str], scores: list[float]) -> str:
        e = [math.exp(max(s, 0.01)) for s in scores]
        total = sum(e)
        probs = [x / total for x in e]
        return random.choices(items, weights=probs, k=1)[0]

    # ── Convenience for Pipeline ──────────────────────
    def decide_for_message(
        self,
        user_id: int,
        route_mode: str,
        source: str,
        emotion_label: str | None = None,
        user_busy: bool = False,
        tools_offered: bool = False,
        active_eruption: str | None = None,
    ) -> dict:
        """Build the candidate set + context, then run decide()."""
        cands = [
            Candidate("reply", "reply"),
            Candidate("tool_call", "tool_call", {"available": tools_offered}),
            Candidate("recall", "recall"),
            Candidate("silence", "proactive_silence"),
        ]
        ctx: dict[str, Any] = {
            "emotion_label": emotion_label or "neutral",
            "user_busy": user_busy,
            "route_mode": route_mode,
            "source": source,
            "tools_offered": tools_offered,
            "active_eruption": active_eruption,
        }
        return self.decide(cands, ctx)

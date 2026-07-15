"""Aerie · 云栖 v9.0 — BrainRandom (Markov-chain style persona randomness).

Builds a small transition matrix from recent Yita style samples and
sampling next state via softmax over weighted transitions.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Iterable, Sequence


# A small set of seed phrases Yita might use, for bootstrapping.
SEED_STATES: list[str] = [
    "过来。",
    "吃饭。",
    "睡吧。",
    "在干嘛。",
    "……嗯。",
    "别动。",
    "今天怎么样。",
    "早安。",
    "晚安。",
    "傻瓜。",
]


class BrainRandom:
    """Markov transition matrix with softmax sampling."""

    def __init__(self, seed_states: Sequence[str] | None = None, smoothing: float = 0.05):
        self.smoothing = smoothing
        self.transitions: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.states: set[str] = set(seed_states or SEED_STATES)
        if seed_states:
            for s in seed_states:
                self.states.add(s)

    def observe(self, sequence: Iterable[str]) -> None:
        """Record transitions from an observed sequence."""
        seq = list(sequence)
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            self.states.add(a)
            self.states.add(b)
            self.transitions[a][b] += 1

    def _softmax(self, weights: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
        if not weights:
            return {}
        keys = list(weights.keys())
        vals = [weights[k] / max(temperature, 1e-3) for k in keys]
        m = max(vals)
        exps = [math.exp(v - m) for v in vals]
        z = sum(exps)
        return {keys[i]: exps[i] / z for i in range(len(keys))}

    def think(self, current_state: str, history: Sequence[str] | None = None, temperature: float = 1.0) -> str:
        """Sample next state with softmax over weighted transitions."""
        if history:
            self.observe(history)
        if current_state not in self.transitions and not self.states:
            return random.choice(SEED_STATES)
        candidates: dict[str, float] = {}
        for s in self.states:
            base = self.transitions.get(current_state, {}).get(s, 0)
            candidates[s] = base + self.smoothing
        probs = self._softmax(candidates, temperature=temperature)
        if not probs:
            return random.choice(SEED_STATES)
        items = list(probs.items())
        keys = [k for k, _ in items]
        weights = [w for _, w in items]
        return random.choices(keys, weights=weights, k=1)[0]

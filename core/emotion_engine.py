"""Aerie · 云栖 v9.0 — Emotion engine (PAD model).

Pleasure-Arousal-Dominance three-dimensional emotion tracking.
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EmotionEngine:
    def __init__(self, db: Any = None) -> None:
        self.db = db
        self._state: dict[str, float] = {"P": 0.5, "A": 0.5, "D": 0.5}
        self._history: list[dict] = []

    def analyze(self, text: str) -> dict:
        """Simple keyword-based emotion analysis."""
        positive = ["谢谢", "爱你", "喜欢", "好", "棒", "厉害", "开心", "快乐", "棒棒哒"]
        negative = ["烦", "生气", "讨厌", "滚", "烂", "差", "无聊", "难过"]
        aroused = ["!", "！", "啊", "哇", "天哪", "太", "好厉害"]
        dominant = ["必须", "命令", "立刻", "马上", "给我", "去做"]

        p = 0.5
        a = 0.5
        d = 0.5

        for kw in positive:
            if kw in text:
                p += 0.05
        for kw in negative:
            if kw in text:
                p -= 0.05
        for kw in aroused:
            if kw in text:
                a += 0.05
        for kw in dominant:
            if kw in text:
                d += 0.05

        p = max(0, min(1, p))
        a = max(0, min(1, a))
        d = max(0, min(1, d))

        return {"pleasure": round(p, 3), "arousal": round(a, 3), "dominance": round(d, 3)}

    def update_trajectory(self, user_id: int, event: str) -> None:
        pad = self.analyze(event)
        self._state["P"] = round(self._state["P"] * 0.7 + pad["pleasure"] * 0.3, 3)
        self._state["A"] = round(self._state["A"] * 0.7 + pad["arousal"] * 0.3, 3)
        self._state["D"] = round(self._state["D"] * 0.7 + pad["dominance"] * 0.3, 3)
        self._history.append({"user_id": user_id, "event": event, **pad})
        logger.debug("Emotion state: P=%.2f A=%.2f D=%.2f", *self._state.values())

    def get_state(self, user_id: int = 0) -> dict:
        return dict(self._state)

    def tune(self, text: str) -> str:
        pad = self._state
        if pad["P"] < 0.3:
            text = text.rstrip("。！？") + "...(有点累了呢)"
        elif pad["P"] > 0.8:
            text = text.rstrip("。！？") + " (开心~)"
        return text

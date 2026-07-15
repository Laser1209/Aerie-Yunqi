"""Aerie · 云栖 v9.0 — Cumulative emotion threshold system.

Four hidden slots (patience / anxiety / desire / tenderness) with
permanent threshold shifts after eruption (角色磨损).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from core.database import Database


@dataclass
class EmotionSlot:
    """A single cumulative threshold slot."""

    name: str
    value: float = 0.0
    threshold: float = 100.0
    decay_per_day: float = 5.0
    threshold_history: list[float] = field(default_factory=list)
    last_decay_date: str = ""

    def is_overflow(self) -> bool:
        return self.value >= self.threshold


# Default slot configuration (tuned for Yita's persona)
DEFAULT_SLOTS: dict[str, dict] = {
    "patience":   {"threshold": 100.0, "decay_per_day": 8.0, "label": "忍耐值"},
    "anxiety":    {"threshold": 90.0,  "decay_per_day": 6.0, "label": "不安值"},
    "desire":     {"threshold": 80.0,  "decay_per_day": 4.0, "label": "渴望值"},
    "tenderness": {"threshold": 70.0,  "decay_per_day": 5.0, "label": "温柔透支值"},
}


class CumulativeEmotionEngine:
    """Cumulative threshold tracker with role-wear mechanism."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()
        self._slots: dict[int, dict[str, EmotionSlot]] = {}
        self._init_slots()

    def _init_slots(self) -> None:
        for slot_name, cfg in DEFAULT_SLOTS.items():
            pass  # Per-user init in _ensure_user

    def _ensure_user(self, user_id: int) -> dict[str, EmotionSlot]:
        if user_id not in self._slots:
            slots: dict[str, EmotionSlot] = {}
            for name, cfg in DEFAULT_SLOTS.items():
                slots[name] = EmotionSlot(
                    name=name,
                    threshold=cfg["threshold"],
                    decay_per_day=cfg["decay_per_day"],
                    threshold_history=[cfg["threshold"]],
                )
            self._slots[user_id] = slots
        return self._slots[user_id]

    def get_slot(self, user_id: int, name: str) -> EmotionSlot:
        slots = self._ensure_user(user_id)
        return slots[name]

    def get_all_slots(self, user_id: int) -> dict[str, EmotionSlot]:
        return self._ensure_user(user_id)

    def add(self, user_id: int, slot_name: str, value: float, trigger: str = "") -> dict:
        """Add value to a slot; if threshold is exceeded, trigger eruption."""
        slot = self.get_slot(user_id, slot_name)
        slot.value += float(value)
        events: list[dict] = []
        while slot.value >= slot.threshold:
            event = self._erupt(user_id, slot, trigger)
            events.append(event)
        return {
            "slot": slot_name,
            "value": slot.value,
            "threshold": slot.threshold,
            "events": events,
        }

    def _erupt(self, user_id: int, slot: EmotionSlot, trigger: str) -> dict:
        """Erupt: dispatch proactive push + permanently lower the threshold (角色磨损)."""
        old_threshold = slot.threshold
        # Threshold drop: 15% permanent decrease after eruption
        new_threshold = old_threshold * 0.85
        slot.threshold_history.append(new_threshold)
        slot.threshold = new_threshold
        # Reset value to half of old threshold
        slot.value = old_threshold * 0.5
        # Persist
        try:
            self.db.insert(
                "feedback_log",
                {
                    "user_id": user_id,
                    "feedback_type": "eruption",
                    "content": json.dumps({
                        "slot": slot.name,
                        "trigger": trigger,
                        "old_threshold": old_threshold,
                        "new_threshold": new_threshold,
                    }, ensure_ascii=False),
                },
            )
        except Exception:
            pass
        return {
            "type": "eruption",
            "slot": slot.name,
            "trigger": trigger,
            "old_threshold": old_threshold,
            "new_threshold": new_threshold,
        }

    def daily_decay(self, user_id: int) -> None:
        """Reduce all slot values by their daily decay rate."""
        slots = self._ensure_user(user_id)
        for slot in slots.values():
            slot.value = max(0.0, slot.value - slot.decay_per_day)

    def get_panel(self, user_id: int) -> str:
        """Return a text panel for the sidebar / debug view."""
        slots = self._ensure_user(user_id)
        lines = []
        for name, slot in slots.items():
            label = DEFAULT_SLOTS[name]["label"]
            filled = int(min(20, max(0, slot.value / slot.threshold * 20)))
            bar = "█" * filled + "░" * (20 - filled)
            lines.append(f"{label} {bar} {int(slot.value)}/{int(slot.threshold)}")
        return "\n".join(lines)

    def trigger_proactive(
        self,
        user_id: int,
        slot_name: str,
        value: float,
        trigger: str,
        messenger=None,
    ) -> dict:
        """Convenience: add value + auto-trigger proactive push if messenger provided."""
        result = self.add(user_id, slot_name, value, trigger)
        if result["events"] and messenger is not None:
            try:
                # Schedule async push; do not block
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        messenger.push("emotion_comfort", user_id, "……{comfort_word}。", trigger=trigger)
                    )
                else:
                    loop.run_until_complete(
                        messenger.push("emotion_comfort", user_id, "……{comfort_word}。", trigger=trigger)
                    )
            except Exception:
                pass
        return result

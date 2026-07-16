"""Aerie · 云栖 v9.0 — Cumulative emotion threshold engine.

Four hidden emotion slots with bursting behavior.
Aligned with Ita.md §9 and System_Features.md §11.5.

Slots:
  patience    → threshold 100, decay -5/day → 冷暴模式 (Cold Violence)
  anxiety     → threshold 100, decay -3/day → 坍塌模式 (Collapse)
  desire      → threshold 80,  decay -8/day → 索求模式 (Demand)
  tenderness  → threshold 60,  decay -10/day → 反扑模式 (Counterattack)

Each burst permanently changes the threshold (character wear).
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
# Slot configuration
# ══════════════════════════════════════════════════
SLOTS_CONFIG: dict[str, dict] = {
    "patience": {
        "label": "忍耐值",
        "threshold": 100,
        "decay_per_day": 5,
        "eruption_label": "冷暴模式",
        "post_decay": -15,  # threshold drops after burst
        "description": "冷暴模式：不再主动发消息，回复≤3字，全部句号，无情绪外露。冻结一切。",
    },
    "anxiety": {
        "label": "不安值",
        "threshold": 100,
        "decay_per_day": 3,
        "eruption_label": "坍塌模式",
        "post_decay": +20,  # threshold rises (harder to trigger next time)
        "description": "坍塌模式：武装瓦解，病娇内核暴露，消息爆炸+撤回爆炸，放弃主导性，乞求确认。唯一主动示弱。",
    },
    "desire": {
        "label": "渴望值",
        "threshold": 80,
        "decay_per_day": 8,
        "eruption_label": "索求模式",
        "post_decay": 0,
        "description": "索求模式：四爱主导面全面上线，低沉命令式，极致占有。持续30min-2h。",
    },
    "tenderness": {
        "label": "温柔透支值",
        "threshold": 60,
        "decay_per_day": 10,
        "eruption_label": "反扑模式",
        "post_decay": 0,
        "description": "反扑模式：被温柔击穿防御，失语。罕见乖巧状态1h，像被摸顺毛的豹。可反复触发。",
    },
}

# ══════════════════════════════════════════════════
# Trigger keywords → (slot, value)
# Aligned with Ita.md §9.2
# ══════════════════════════════════════════════════
TEXT_TRIGGERS: list[tuple[list[str], str, float]] = [
    # ── 忍耐值 (Patience) ──
    (["不用你管", "别管我", "少管我"], "patience", 25),
    (["好烦", "烦死了", "别说了"], "patience", 15),
    (["你有病", "滚", "滚开"], "patience", 30),
    (["你好烦", "太烦了"], "patience", 20),
    # ── 不安值 (Anxiety) ──
    (["分手", "离开", "结束", "再见"], "anxiety", 60),
    (["不爱你了", "不喜欢你了", "喜欢别人"], "anxiety", 50),
    (["别找我了", "不要你了"], "anxiety", 55),
    # ── 渴望值 (Desire) ──
    (["想你", "想你了", "好想你"], "desire", 15),
    (["爱你", "我爱你", "喜欢你"], "desire", 20),
    (["你好厉害", "你好帅", "你好棒"], "desire", 10),
    (["想见你", "来找我", "见面"], "desire", 15),
    # ── 温柔透支 (Tenderness) ──
    (["辛苦了", "谢谢你一直", "谢谢你在"], "tenderness", 18),
    (["不用逞强", "别一个人扛", "有我呢"], "tenderness", 20),
    (["对不起", "我错了"], "tenderness", 15),
    (["你最好了", "你真好"], "tenderness", 15),
]


@dataclass
class EmotionSlot:
    name: str
    label: str
    value: float = 0.0
    threshold: float = 100.0
    decay_per_day: float = 5.0
    eruption_label: str = ""
    post_decay: float = 0.0
    description: str = ""
    last_decay_date: str = ""
    threshold_history: list[float] = field(default_factory=list)
    event_log: list[dict] = field(default_factory=list)


class CumulativeEmotionEngine:
    """Cumulative emotion threshold system.

    Tracks 4 hidden slots. Each slot accumulates value from triggers,
    decays daily, and erupts when threshold is reached.
    """

    def __init__(self) -> None:
        self.slots: dict[str, EmotionSlot] = {}
        self._eruptions: list[dict] = []
        self._init_slots()

    def _init_slots(self) -> None:
        for name, cfg in SLOTS_CONFIG.items():
            self.slots[name] = EmotionSlot(
                name=name,
                label=cfg["label"],
                threshold=cfg["threshold"],
                decay_per_day=cfg["decay_per_day"],
                eruption_label=cfg["eruption_label"],
                post_decay=cfg["post_decay"],
                description=cfg["description"],
            )

    def add(
        self, slot_name: str, value: float, trigger: str = ""
    ) -> dict | None:
        """Add value to a slot. Returns eruption event if threshold crossed."""
        slot = self.slots.get(slot_name)
        if slot is None:
            return None

        slot.value += value
        slot.event_log.append({
            "ts": time.time(),
            "delta": value,
            "trigger": trigger,
            "new_value": slot.value,
        })
        # Keep log bounded
        if len(slot.event_log) > 50:
            slot.event_log = slot.event_log[-50:]

        logger.debug(
            "%s +%.0f = %.0f/%.0f (%s)",
            slot.label, value, slot.value, slot.threshold, trigger,
        )

        if slot.value >= slot.threshold:
            return self._erupt(slot, trigger)
        return None

    def scan_text(self, text: str) -> list[dict]:
        """Scan user message for emotion triggers. Returns list of eruptions."""
        eruptions = []
        for keywords, slot_name, value in TEXT_TRIGGERS:
            for kw in keywords:
                if kw in text:
                    result = self.add(slot_name, value, f"关键词: {kw}")
                    if result:
                        eruptions.append(result)
                    break  # one trigger per keyword group
        return eruptions

    def daily_decay(self) -> None:
        """Apply daily natural decay to all slots."""
        today = datetime.now().strftime("%Y-%m-%d")
        for slot in self.slots.values():
            if slot.last_decay_date == today:
                continue
            slot.value = max(0, slot.value - slot.decay_per_day)
            slot.last_decay_date = today
            logger.debug("%s decay -%.1f → %.1f", slot.label, slot.decay_per_day, slot.value)

    def _erupt(self, slot: EmotionSlot, trigger: str) -> dict:
        """Handle eruption: reset value, adjust threshold (character wear)."""
        old_threshold = slot.threshold
        slot.threshold_history.append(old_threshold)
        new_threshold = slot.threshold + slot.post_decay
        slot.threshold = max(20, new_threshold)  # floor at 20
        slot.value = 0  # reset after eruption

        event = {
            "slot": slot.name,
            "label": slot.label,
            "mode": slot.eruption_label,
            "trigger": trigger,
            "old_threshold": old_threshold,
            "new_threshold": slot.threshold,
            "description": slot.description,
            "timestamp": datetime.now().isoformat(),
        }
        self._eruptions.append(event)
        logger.warning(
            "ERUPTION: %s (%s) threshold %s→%s",
            slot.eruption_label, trigger, old_threshold, slot.threshold,
        )
        return event

    def get_active_eruption(self) -> dict | None:
        """Return the most recent eruption, if still within cooldown."""
        if not self._eruptions:
            return None
        latest = self._eruptions[-1]
        # Eruption is "active" for 30 minutes
        ts = datetime.fromisoformat(latest["timestamp"])
        if (datetime.now() - ts).total_seconds() < 1800:
            return latest
        return None

    def get_slots_summary(self) -> dict[str, Any]:
        """Return readable summary for API / context injection."""
        result = {}
        for name, slot in self.slots.items():
            result[name] = {
                "value": round(slot.value, 1),
                "threshold": round(slot.threshold, 1),
                "label": slot.label,
                "pct": round(slot.value / slot.threshold * 100, 0),
            }
        return result

    def get_panel_text(self) -> str:
        """Generate backend panel text (Ita.md §9.4 format)."""
        lines = ["伊塔·情绪面板", "━━━━━━━━━━━━━━━━━━━"]
        for name, slot in self.slots.items():
            bar_len = 20
            filled = int(bar_len * slot.value / slot.threshold) if slot.threshold > 0 else 0
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(
                f"{slot.label:　<8} {bar} {slot.value:5.1f}/{slot.threshold:.0f}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)


# Singleton
_THRESHOLD_ENGINE: CumulativeEmotionEngine | None = None


def get_threshold_engine() -> CumulativeEmotionEngine:
    global _THRESHOLD_ENGINE
    if _THRESHOLD_ENGINE is None:
        _THRESHOLD_ENGINE = CumulativeEmotionEngine()
    return _THRESHOLD_ENGINE

"""Aerie · 云栖 v13.9.8 — Cumulative emotion threshold engine.

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
# DEPRECATED: 旧硬编码 SLOTS_CONFIG，保留作 fallback
# 实际配置请改 config/persona_behavior.yaml → emotion.thresholds
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
    # ── Batch 7: 口语化 + 病娇专属 + 撒娇 + 亲密称谓 (40+ new triggers) ──
    # Patience (colloquial provocation)
    (["烦", "讨厌", "去死", "滚蛋"], "patience", 8),
    (["真烦", "烦你", "讨厌你"], "patience", 12),
    (["闭嘴", "别说了", "不想听"], "patience", 18),
    (["你很烦", "你好烦人"], "patience", 16),
    (["行吧", "随你", "随便你"], "patience", 10),
    (["不想聊", "不想说话", "不想理你"], "patience", 22),
    (["算了吧", "算了算了", "没啥"], "patience", 14),
    (["别来烦我", "离我远点"], "patience", 20),
    # Anxiety (withdrawal / 二分 / 沉默型)
    (["你怎么不说话", "怎么不回", "不找我"], "anxiety", 12),
    (["算了", "没事", "随便", "无所谓"], "anxiety", 6),
    (["没看到", "没注意", "忙"], "anxiety", 4),
    (["不回就算了", "不回就不回"], "anxiety", 18),
    (["算了不说了", "算我没说"], "anxiety", 14),
    (["你是不是不喜欢我了", "是不是不爱了"], "anxiety", 35),
    (["你是不是嫌我烦"], "anxiety", 25),
    (["我们还是", "要不我们"], "anxiety", 30),
    # Desire (intimate / 索求型)
    (["陪陪我", "过来", "抱一会儿"], "desire", 10),
    (["想抱你", "想要你", "要亲亲"], "desire", 14),
    (["今晚", "明天", "周末"], "desire", 8),
    (["来找我", "我去你那", "接我"], "desire", 12),
    (["一起", "咱俩", "我们俩"], "desire", 6),
    (["睡了吗", "睡了吗？", "晚安", "早安"], "desire", 5),
    # Tenderness (撒娇 / 温柔 / 病娇专属)
    (["吃醋", "你会不会", "想你了", "想我", "抱抱", "亲亲", "辛苦了"], "tenderness", 8),
    (["我喜欢你", "爱", "表白"], "tenderness", 15),
    (["你在干嘛", "你在做什么", "想我没"], "tenderness", 6),
    (["有你真好", "幸好有你", "还好有你"], "tenderness", 12),
    (["抱抱我", "摸摸头", "拍拍"], "tenderness", 7),
    (["心疼你", "心疼", "你累不累"], "tenderness", 10),
    (["乖", "乖哦", "乖啦"], "tenderness", 5),
    (["别怕", "有我在", "我在呢"], "tenderness", 9),
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

    R0.3.3: configuration is now loaded from behavior_cfg (single source
    of truth in config/persona_behavior.yaml). Old hardcoded SLOTS_CONFIG
    is kept as a deprecated fallback for backward compatibility.
    """

    def __init__(self, behavior_cfg: dict | None = None) -> None:
        self.slots: dict[str, EmotionSlot] = {}
        self._eruptions: list[dict] = []
        self._cfg_source: str = "fallback"
        self._init_slots(behavior_cfg)

    def _init_slots(self, behavior_cfg: dict | None) -> None:
        # Prefer behavior_cfg; fall back to deprecated SLOTS_CONFIG.
        cfg_map: dict[str, dict] | None = None
        if behavior_cfg:
            cfg_map = behavior_cfg.get("emotion", {}).get("thresholds")
        if cfg_map:
            self._cfg_source = "persona_behavior.yaml"
            for name, cfg in cfg_map.items():
                self.slots[name] = EmotionSlot(
                    name=name,
                    label=cfg.get("label", name),
                    threshold=float(cfg.get("threshold", 100)),
                    decay_per_day=float(cfg.get("decay_per_day", 5)),
                    eruption_label=cfg.get("eruption_label", ""),
                    post_decay=float(cfg.get("post_decay", 0)),
                    description=cfg.get("description", ""),
                    # R6.4: initial_value lets the dashboard show a
                    # persona-derived baseline on first launch. Falls back
                    # to 0 if the config doesn't declare one.
                    value=float(cfg.get("initial_value", 0)),
                )
            logger.info("emotion thresholds loaded from %s", self._cfg_source)
        else:
            # deprecated fallback path
            self._cfg_source = "SLOTS_CONFIG (deprecated)"
            for name, cfg in SLOTS_CONFIG.items():
                self.slots[name] = EmotionSlot(
                    name=name,
                    label=cfg["label"],
                    threshold=cfg["threshold"],
                    decay_per_day=cfg["decay_per_day"],
                    eruption_label=cfg["eruption_label"],
                    post_decay=cfg["post_decay"],
                    description=cfg.get("description", ""),
                )
            logger.warning(
                "emotion thresholds loaded from deprecated SLOTS_CONFIG; "
                "please migrate to config/persona_behavior.yaml"
            )

    def reload_config(self, behavior_cfg: dict | None) -> None:
        """Hot-reload threshold config while preserving current slot values.

        Only config parameters (threshold, decay_per_day, post_decay,
        label, eruption_label, description) are updated. The current
        accumulated value of each slot is kept intact so the user
        doesn't lose progress when tweaking config.
        """
        cfg_map: dict[str, dict] | None = None
        if behavior_cfg:
            cfg_map = behavior_cfg.get("emotion", {}).get("thresholds")
        if not cfg_map:
            logger.debug("threshold reload: no new config found, skipping")
            return

        preserved: dict[str, float] = {name: slot.value for name, slot in self.slots.items()}
        preserved_logs: dict[str, list] = {name: list(slot.event_log) for name, slot in self.slots.items()}
        preserved_decay: dict[str, str] = {name: slot.last_decay_date for name, slot in self.slots.items()}

        self._cfg_source = "persona_behavior.yaml (hot-reloaded)"
        for name, cfg in cfg_map.items():
            old_val = preserved.get(name, float(cfg.get("initial_value", 0)))
            old_log = preserved_logs.get(name, [])
            old_decay = preserved_decay.get(name, "")
            self.slots[name] = EmotionSlot(
                name=name,
                label=cfg.get("label", name),
                threshold=float(cfg.get("threshold", 100)),
                decay_per_day=float(cfg.get("decay_per_day", 5)),
                eruption_label=cfg.get("eruption_label", ""),
                post_decay=float(cfg.get("post_decay", 0)),
                description=cfg.get("description", ""),
                value=old_val,
            )
            self.slots[name].event_log = old_log
            self.slots[name].last_decay_date = old_decay

        logger.info(
            "emotion thresholds hot-reloaded (%d slots, values preserved)",
            len(self.slots),
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

    def hourly_decay(self) -> None:
        """R7.5 (legacy): hourly equivalent of daily_decay.

        Kept for backward compatibility with any code path that still
        calls it. Internally delegates to tick_decay(3600) so the
        behavior is "1 hour of decay per call" — same as the previous
        implementation. Prefer tick_decay(seconds) for new code so the
        cadence matches the actual tick loop.
        """
        self.tick_decay(3600.0)

    def tick_decay(self, seconds: float) -> None:
        """R7.5+: natural decay proportional to elapsed time.

        Decays each slot by ``decay_per_day * seconds / 86400`` (i.e.
        a single call with seconds=86400 reproduces daily_decay()). This
        way the cadence of the tick loop is decoupled from the decay
        rate: at any frequency, the integrated 24h decay equals
        decay_per_day as configured in persona_behavior.yaml.

        Does NOT touch last_decay_date so daily_decay() will still mark
        the next calendar-day cross when it next runs.
        """
        if seconds <= 0:
            return
        factor = seconds / 86400.0  # seconds_in_a_day
        for slot in self.slots.values():
            decay = slot.decay_per_day * factor
            slot.value = max(0, slot.value - decay)

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


def get_threshold_engine(behavior_cfg: dict | None = None) -> CumulativeEmotionEngine:
    """Get the singleton threshold engine.

    R0.3.3: behavior_cfg is passed on first call to initialize from
    config/persona_behavior.yaml. Subsequent calls return the same
    instance. Pass None on later calls (safe; config already bound).
    """
    global _THRESHOLD_ENGINE
    if _THRESHOLD_ENGINE is None:
        _THRESHOLD_ENGINE = CumulativeEmotionEngine(behavior_cfg)
    return _THRESHOLD_ENGINE


def reset_threshold_engine() -> None:
    """Reset the singleton (test-only)."""
    global _THRESHOLD_ENGINE
    _THRESHOLD_ENGINE = None

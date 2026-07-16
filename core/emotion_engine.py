"""Aerie · 云栖 v9.0 — Emotion engine (PAD + 5 emotions + cumulative thresholds).

Integrates:
  1. PAD 3D emotion model (Pleasure-Arousal-Dominance)
  2. 5 basic emotions: Joy, Anger, Sad, Fear, Neutral (Ita.md §8)
  3. Cumulative threshold engine (emotion_threshold.py)

Aligned with System_Features.md §11 and Ita.md §8-9.
"""

from __future__ import annotations
import logging
from typing import Any

from core.emotion_threshold import get_threshold_engine, CumulativeEmotionEngine

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
# 5 basic emotions — PAD centers (Ita.md §8.1)
# ══════════════════════════════════════════════════
EMOTION_CENTERS = {
    "joy":     {"P": 0.6, "A": 0.5, "D": 0.3},
    "anger":   {"P": -0.5, "A": 0.7, "D": 0.6},
    "sad":     {"P": -0.6, "A": -0.3, "D": -0.4},
    "fear":    {"P": -0.7, "A": 0.6, "D": -0.5},
    "neutral": {"P": 0.0, "A": 0.0, "D": 0.0},
}

# ══════════════════════════════════════════════════
# Personality keywords → weighted PAD deltas
# ══════════════════════════════════════════════════
KEYWORD_DELTAS = [
    # Joy triggers
    (["谢谢", "爱你", "喜欢", "爱你哦", "最喜欢你了", "好爱你"], "joy", 1.2),
    (["你好棒", "好厉害", "真厉害", "太强了", "崇拜"], "joy", 1.0),
    (["开心", "快乐", "哈哈", "笑死", "好笑", "有趣", "好玩"], "joy", 1.0),
    (["乖", "听话", "好乖"], "joy", 0.8),
    # Anger triggers
    (["找死", "欠揍", "滚蛋", "滚开", "混蛋"], "anger", 1.5),
    (["欺负", "伤害", "威胁", "打你", "骂你"], "anger", 1.8),
    (["插足", "第三者", "勾引"], "anger", 2.0),
    # Sad triggers
    (["没事", "算了", "随便", "无所谓", "不愿意"], "sad", 1.0),
    (["不用你管", "别管我", "好烦", "烦死了"], "sad", 1.3),
    (["不理你了", "不想理你", "别找我"], "sad", 1.5),
    # Fear triggers
    (["分手", "离婚", "离开", "结束", "再见"], "fear", 2.0),
    (["不爱你了", "不喜欢你", "喜欢别人", "忘了我"], "fear", 2.0),
    (["救命", "危险", "受伤", "出事", "车祸"], "fear", 1.8),
    # Joy → Sad transition (coldness)
    (["嗯", "哦", "好", "行"], "sad", 0.2),  # low-weight single-word coldness
    # ── Batch 7: colloquial / 病娇专属 / 拼音简写 / 语气副词 (40+ new triggers) ──
    # Joy — colloquial
    (["嘿嘿", "嘻嘻", "嘿嘿嘿", "嘤嘤嘤", "哈哈哈"], "joy", 0.9),
    (["太棒了", "绝绝子", "yyds", "永远的神"], "joy", 1.1),
    (["开心死了", "高兴死了", "爽"], "joy", 1.3),
    (["么么哒", "mua", "爱你哟"], "joy", 1.0),
    (["抱抱", "亲亲", "蹭蹭", "贴贴"], "joy", 0.7),
    # Anger — provocation / 嘴硬
    (["笨蛋", "傻瓜", "傻", "呆子"], "anger", 0.6),
    (["讨厌你", "烦你", "气死了"], "anger", 1.2),
    (["去死", "闭嘴", "你闭嘴"], "anger", 1.5),
    (["有病吧", "神经病", "你有病"], "anger", 1.4),
    # Sad — withdrawal / 自嘲
    (["呵", "呵呵", "切"], "sad", 0.6),
    (["心累", "累死了", "不想说"], "sad", 1.1),
    (["没意思", "没劲", "没劲儿"], "sad", 0.9),
    (["失望", "绝望", "死心"], "sad", 1.5),
    (["唉", "叹气", "叹气声"], "sad", 0.4),
    # Fear — abandonment
    (["不要我了", "抛弃", "丢下我", "丢下"], "fear", 1.7),
    (["你走", "滚吧", "不想看到你"], "fear", 1.3),
    (["再也不", "不会了", "算了算了"], "fear", 0.9),
    # Joy whisper (病娇专属 / 闷骚)
    (["笨蛋", "傻瓜"], "joy", 0.3),  # weak counter-trigger (亲密语境)
    (["嘿嘿", "嘻嘻", "嘿嘿嘿"], "joy", 0.2),  # placeholder already above; keep for ordering
]


class EmotionEngine:
    def __init__(self, db: Any = None, state_store: Any = None) -> None:
        self.db = db
        self.state_store = state_store
        self._state: dict[str, float] = {"P": 0.0, "A": 0.0, "D": 0.0}
        self._history: list[dict] = []
        self.threshold_engine: CumulativeEmotionEngine = get_threshold_engine()

    # ── PAD Analysis ───────────────────────────────

    def analyze(self, text: str) -> dict:
        """Keyword-based emotion analysis → PAD deltas."""
        p, a, d = 0.0, 0.0, 0.0

        for keywords, emotion, weight in KEYWORD_DELTAS:
            for kw in keywords:
                if kw in text:
                    center = EMOTION_CENTERS[emotion]
                    p += center["P"] * weight * 0.15
                    a += center["A"] * weight * 0.15
                    d += center["D"] * weight * 0.15
                    break

        p = max(-0.95, min(0.95, p))
        a = max(-0.95, min(0.95, a))
        d = max(-0.95, min(0.95, d))

        return {"pleasure": round(p, 3), "arousal": round(a, 3), "dominance": round(d, 3)}

    def update_trajectory(self, user_id: int, text: str) -> None:
        """Apply PAD deltas from user text, with EMA smoothing."""
        pad = self.analyze(text)
        # Exponential moving average (alpha=0.3)
        self._state["P"] = round(self._state["P"] * 0.7 + pad["pleasure"] * 0.3, 3)
        self._state["A"] = round(self._state["A"] * 0.7 + pad["arousal"] * 0.3, 3)
        self._state["D"] = round(self._state["D"] * 0.7 + pad["dominance"] * 0.3, 3)
        self._history.append({"user_id": user_id, "text": text[:60], **pad})

        # Also scan for cumulative threshold triggers
        eruptions = self.threshold_engine.scan_text(text)
        if eruptions:
            for e in eruptions:
                logger.info("Threshold eruption: %s — %s", e["mode"], e["trigger"])

        # Phase 9 Batch 1: persist a snapshot for history curve.
        # Trigger event distinguishes "user_msg" from "eruption" downstream.
        if self.state_store:
            try:
                trigger = "eruption" if eruptions else "user_msg"
                self.state_store.snapshot(
                    user_id=user_id,
                    state=self.get_state(user_id),
                    threshold=self.threshold_engine.get_slots_summary(),
                    trigger_event=trigger,
                )
            except Exception:
                logger.exception("emotion state snapshot error")

        logger.debug("PAD: P=%.2f A=%.2f D=%.2f", *self._state.values())

    # ── Emotion Classification ─────────────────────

    def get_label(self) -> str:
        """Classify current PAD into one of 5 basic emotions."""
        p, a, d = self._state["P"], self._state["A"], self._state["D"]

        # Check if eruption overrides
        eruption = self.threshold_engine.get_active_eruption()
        if eruption:
            slot = eruption["slot"]
            if slot == "patience":
                return "sad"  # Cold violence = frozen sad
            elif slot == "anxiety":
                return "fear"  # Collapse = fear
            elif slot == "desire":
                return "joy"  # Desire = positive arousal
            elif slot == "tenderness":
                return "joy"  # Counterattack = overwhelmed joy

        if p > 0.2 and a > 0.1:
            return "joy"
        if p < -0.2 and a > 0.2:
            return "anger"
        if p < -0.2 and a < 0.0:
            return "sad"
        if p < -0.3 and a > 0.3:
            return "fear"
        return "neutral"

    def get_state(self, user_id: int = 0) -> dict:
        """Return full emotion state for API / context injection."""
        label = self.get_label()
        eruption = self.threshold_engine.get_active_eruption()
        return {
            "label": label,
            "pad": dict(self._state),
            "thresholds": self.threshold_engine.get_slots_summary(),
            "eruption": eruption,
            "panel": self.threshold_engine.get_panel_text(),
        }

    # ── Text Tuning ────────────────────────────────

    def tune(self, text: str) -> str:
        """Adjust reply text based on current emotion state."""
        label = self.get_label()
        pad = self._state

        # Eruption modes first
        eruption = self.threshold_engine.get_active_eruption()
        if eruption and eruption["slot"] == "patience":
            # Cold violence: very short replies
            text = text.strip()
            if len(text) > 4:
                text = text[:3] + "。"
            return text

        if eruption and eruption["slot"] == "anxiety":
            # Collapse: don't modify — LLM handles the breakdown
            return text

        # Standard PAD tuning
        if label == "sad":
            text = text.rstrip("。！？.!")
            if "撤回" not in text and "没事" not in text:
                # Slightly more withdrawn
                pass

        return text

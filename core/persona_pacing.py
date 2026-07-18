"""Aerie · 云栖 v0.1.0-beta.1 — Persona-aware message pacing (Phase 9 Batch 2).

User clarification (2026-07-16):
    "第一条消息是及时的，是没有延迟的。第一条消息之后的消息是经过
     他的情感思维大脑模型推断，在尽可能快的时候时间内进行做出推论，
     然后才发出来的。我的意思是尽可能把后面这段时间缩到1.5秒之内，
     然后有任何的其他的情绪迟疑啊，或者说是其他的一些他觉得不好意
     思的一些情感表达。这个1.5秒是他表达情感的方式，并不是刻意的必
     须要维持在1.5秒之内，而是说我觉得1.5秒是一个比较好的一个时间，
     它也可以停顿3秒，也可以停顿一分钟。主要是他这个思维模型必须
     要自主化情感化，像一个真正的人一样。"

Design
------
1. The first segment is sent IMMEDIATELY (interval = 0).
2. Subsequent segments choose one of 11 persona-driven pacing styles
   from a decision tree that reads emotion label, threshold slots,
   eruption state, and the segment content itself.
3. 1.5s is the **baseline** (the "balanced" range), NOT a hard ceiling.
   Yandere hesitations may stretch to 5s; contemplative pauses to 4s.
4. Probabilistic events (yandere erase-hesitate 5%, contemplative 3%,
   shy hesitation 10% inside neutral) keep the rhythm feeling alive.
5. All output is `(interval_seconds, style_label)`. The style label
   is persisted into the cognition trace so the brain-center UI can
   explain "why this gap".

The decision tree is intentionally human-readable — this module is
where Ita's emotional cadence is encoded, and that's worth
documenting in-line.
"""

from __future__ import annotations

import random
from typing import Optional

# ── 11 persona pacing styles ───────────────────────────
# Tuple: (min_seconds, max_seconds). Picked uniformly within range.
# R8.1 (Persona 9/10): 热情度 9/10 → 打字后等不及，eager_warm 和 balanced
# 区间都压低；其余模式（eruption / contemplative）保持人类自然节奏，
# 防止 9/10 行为反而拖累非情绪关键场景。
STYLES: dict[str, tuple[float, float]] = {
    "immediate":              (0.0,  0.0),  # 1st segment — no delay
    "eager_warm":             (0.30, 0.55),  # R8.1: 9/10 → (0.40,0.70)→(0.30,0.55) — 更急
    "eager_eruption":         (0.40, 0.70),  # 维持 — eruption 仍需辨识
    "anxious_fast":           (0.50, 1.00),  # 维持
    "balanced":               (0.50, 0.85),  # R8.1: 9/10 → (0.60,1.00)→(0.50,0.85) — 更短
    "shy_hesitation":         (1.40, 1.90),  # 维持
    "shy_tenderness_pause":   (1.20, 1.70),  # 维持
    "yandere_collapse_pause": (1.00, 1.80),  # 维持
    "cold_slow":              (0.90, 1.60),  # 维持
    "contemplative":          (2.50, 4.00),  # 维持
    "yandere_erase_hesitate": (2.00, 5.00),  # 维持
}

# Probabilistic triggers inside the decision tree
PROB_SHY_HESITATION = 0.10          # 10% in balanced mode
PROB_CONTEMPLATIVE = 0.03           # 3% overall
PROB_YANDERE_ERASE = 0.05           # 5% — yandere-style "want to take it back"

# Words/phrases that suggest contemplation, longer pause
_CONTEMPLATION_CUES = (
    "为什么", "怎么", "真的", "对不起", "其实", "心里",
    "想说", "秘密", "以前", "以后", "永远", "一直",
)
# Words/phrases that suggest a recall/erase impulse
_ERASE_CUES = (
    "撤回", "刚才", "算我没说", "不要听", "忘掉",
    "当我没说", "忘掉吧",
)


def _pick_interval(style: str, rng: random.Random) -> float:
    lo, hi = STYLES.get(style, STYLES["balanced"])
    if lo >= hi:
        return lo
    return rng.uniform(lo, hi)


def compute_persona_interval(
    segment_index: int,
    emotion_label: Optional[str] = None,
    threshold: Optional[dict] = None,
    is_eruption: bool = False,
    segment_content: str = "",
    rng: Optional[random.Random] = None,
) -> tuple[float, str]:
    """Compute the next segment's pacing interval in seconds.

    Args:
        segment_index: 0-based index of the segment about to be sent.
            Index 0 is always immediate (no delay).
        emotion_label: Current emotion label (joy / sad / anger / fear / neutral / etc.)
        threshold: 4-slot summary dict (patience / anxiety / desire / tenderness).
            Each slot has {"value": float, "threshold": float, "pct": float}.
        is_eruption: True when a threshold slot just erupted.
        segment_content: The actual text of the segment (used to detect
            contemplation/erase cues).
        rng: Optional Random instance for deterministic testing.

    Returns:
        (interval_seconds, style_label) tuple. The interval is clamped
        to the style's [min, max] range.
    """
    rng = rng or random.Random()

    # ── Rule 1: first segment is always immediate ──
    if segment_index == 0:
        return (0.0, "immediate")

    label = (emotion_label or "neutral").strip().lower() or "neutral"
    threshold = threshold or {}
    text = (segment_content or "").strip()

    # ── Rule 2: eruption overrides everything ──
    if is_eruption:
        # Pull the active eruption mode from threshold summary
        active_mode = None
        for slot_name in ("patience", "anxiety", "desire", "tenderness"):
            slot = threshold.get(slot_name) or {}
            if slot.get("active"):
                active_mode = slot_name
                break
        if active_mode == "anxiety":
            # 坍塌模式 — 武装瓦解，消息爆炸+欲言又止
            return (_pick_interval("yandere_collapse_pause", rng), "yandere_collapse_pause")
        if active_mode == "tenderness":
            # 反扑模式 — 被温柔击中失语
            return (_pick_interval("shy_tenderness_pause", rng), "shy_tenderness_pause")
        if active_mode == "patience":
            # 冷暴模式 — 故意慢回，句号增多
            return (_pick_interval("cold_slow", rng), "cold_slow")
        if active_mode == "desire":
            # 索求模式 — 命令式，极致占有
            return (_pick_interval("eager_eruption", rng), "eager_eruption")
        # Unknown eruption style — eager
        return (_pick_interval("eager_eruption", rng), "eager_eruption")

    # ── Rule 3: emotion-label driven tempo ──
    if label in ("joy", "affection", "missing", "love"):
        # Warm, eager — couldn't wait
        return (_pick_interval("eager_warm", rng), "eager_warm")
    if label == "fear":
        # Anxious to hold you — fast but slightly slower than eager_warm
        return (_pick_interval("anxious_fast", rng), "anxious_fast")
    if label in ("sad", "anger"):
        # Cold violence / withdrawal — slow, deliberate
        # But if segment is short and aggressive ("知道了。"), go even slower
        return (_pick_interval("cold_slow", rng), "cold_slow")

    # ── Rule 4: neutral baseline with probabilistic overlays ──
    # 4a: 3% contemplative — long meaningful pause (independent of cues)
    if rng.random() < PROB_CONTEMPLATIVE:
        return (_pick_interval("contemplative", rng), "contemplative")

    # 4b: yandere erase-hesitate — content has recall cues
    lower = text.lower()
    for cue in _ERASE_CUES:
        if cue in text or cue in lower:
            if rng.random() < PROB_YANDERE_ERASE * 4:  # 20% when cue present
                return (
                    _pick_interval("yandere_erase_hesitate", rng),
                    "yandere_erase_hesitate",
                )
            break

    # 4c: contemplation cues (但人话多，不到 contemplative 阈值)
    for cue in _CONTEMPLATION_CUES:
        if cue in text:
            # Pick a slightly longer balanced — but not contemplative
            return (_pick_interval("shy_hesitation", rng), "shy_hesitation")

    # 4d: 10% shy hesitation (random)
    if rng.random() < PROB_SHY_HESITATION:
        return (_pick_interval("shy_hesitation", rng), "shy_hesitation")

    # 4e: standard balanced
    return (_pick_interval("balanced", rng), "balanced")


# ── Convenience: stable hashing for analysis ────────────
def pacing_style_label(interval: float) -> str:
    """Reverse-lookup the closest style for a given interval (for logging)."""
    best = "balanced"
    best_diff = float("inf")
    for style, (lo, hi) in STYLES.items():
        mid = (lo + hi) / 2
        diff = abs(mid - interval)
        if diff < best_diff:
            best_diff = diff
            best = style
    return best

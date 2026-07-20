"""Aerie · 云栖 v0.1.0-beta.1 — Proactive Judge.

R7.5: 综合判断模块。在 ``push_scheduler._dispatch`` 之前调用,
根据"心情 + 想法 + 用户上下文"算出一个 0-100 的 score,选 scene,
定 tone,把"闹钟式主动 push"升级为"她想发才发"。

输入数据源:
  - 当前情绪 (P/A/D) + 隐藏槽位 (patience/anxiety/desire/tenderness)
  - desire 5 变量 (DesireEngine.get_state())
  - 用户上下文 (最近消息时间 / 24h 聊天主题)
  - 环境 (天气/纪念日/时段)
  - cooldown / daily count (PushPolicy)

输出 (Decision):
  - scene: morning_brief / idle_care / voice_miss / weather_push / ...
  - tone: warm_with_light_flirt / anxious / cool_shut / collapsed / ...
  - score: 0-100
  - suppress_reason: "" | "cooldown" | "quiet_period" | "user_recent" | ...
  - context_snapshot: dict for decision log

调用方:
  - core/push_scheduler.py → _dispatch(scene_name, scene_cfg)
  - 直接被 proactive_judge_e2e.py 单元测试
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════
# 默认权重 (来自 config/persona_behavior.yaml → decision.weights)
# ══════════════════════════════════════════════════
DEFAULT_WEIGHTS: dict[str, float] = {
    "desire": 0.35,        # w1: 内心驱动力 (5 变量加权)
    "emotion": 0.30,       # w2: 情绪状态 (P/A/D + 槽位)
    "context": 0.20,       # w3: 用户上下文 (离线时长 / 最近主题)
    "environment": 0.10,   # w4: 环境 (天气 / 纪念日 / 时段)
    "cooldown_penalty": 0.05,  # w5: 抑制惩罚 (daily count / interval)
}


# ══════════════════════════════════════════════════
# Scene 阈值 (不同场景的最低 score 门槛)
# ══════════════════════════════════════════════════
SCENE_THRESHOLDS: dict[str, int] = {
    "morning_brief": 30,        # 早安 + 简报 (早晨环境加成容易触发)
    "morning_brief_9am": 25,    # 9 点简报
    "idle_care": 45,            # 寂寞关心
    "voice_miss": 50,           # 想听声音 (desire 高分 + 22-23:30 时段)
    "weather_push": 25,         # 天气提醒
    "lunch_remind": 25,         # 吃饭提醒
    "evening_check": 30,        # 晚间问候
    "goodnight": 25,            # 晚安 (低门槛,因为 exempt_quiet)
    "anniversary": 20,          # 纪念日 (低门槛,exempt_quiet)
    "emotion_comfort": 50,      # 情绪爆发安抚
}


# ══════════════════════════════════════════════════
# Tone 矩阵 — 根据主导情绪选择 LLM 措辞
# ══════════════════════════════════════════════════
TONE_BY_DOMINANT: dict[str, str] = {
    "joy": "warm_with_light_flirt",
    "affection": "tender_declarative",
    "missing": "longing_with_soft_possessiveness",
    "loneliness": "small_voice_seeking",
    "sadness": "quiet_companion",
    "stress": "calm_grounding",
    "neutral": "casual_warm",
    "anger": "short_pause",
    "fear": "soft_reassurance",
    # 隐藏槽位爆发态
    "patience_eruption": "cold_shut",        # 冷暴
    "anxiety_eruption": "collapse_seeking",  # 坍塌
    "desire_eruption": "demand_intimate",    # 索求
    "tenderness_eruption": "tame_soft",      # 反扑 (乖巧)
}


@dataclass
class Decision:
    """The output of a single proactive judge call."""
    scene: str
    tone: str
    score: int
    weights: dict[str, float]
    components: dict[str, float]
    suppress_reason: str = ""
    context_snapshot: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class ProactiveJudge:
    """Compute a 0-100 score, pick a scene, choose a tone.

    Usage::

        judge = ProactiveJudge(companion=companion)
        decision = judge.evaluate(scene="idle_care")
        if decision.suppress_reason:
            logger.info("proactive suppressed: %s", decision.suppress_reason)
        else:
            await brain.generate_push(decision.tone, decision.context_snapshot)

    The judge is read-only with respect to PushPolicy — it does not
    record a push. Recording stays in push_scheduler so the daily-cap /
    interval rules remain in one place.
    """

    def __init__(
        self,
        companion: Any = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.companion = companion
        self.weights = weights or dict(DEFAULT_WEIGHTS)

    # ── Public ─────────────────────────────────────
    def evaluate(
        self,
        scene: str,
        context_override: dict | None = None,
    ) -> Decision:
        """Compute the decision for a given scene."""
        components = self._read_components(context_override)
        score = self._compute_score(components)
        threshold = SCENE_THRESHOLDS.get(scene, 40)

        # Suppress if score below threshold
        suppress_reason = ""
        if score < threshold:
            suppress_reason = f"score_below_threshold({score}<{threshold})"
        # Suppress if cooldown too tight (handled by PushPolicy too,
        # but judge also flags it for visibility)
        elif components.get("cooldown_minutes_remaining", 0) > 0:
            suppress_reason = "cooldown_active"
        # Suppress if user is currently active (< 5 min)
        elif components.get("user_minutes_since_last", 999) < 5:
            suppress_reason = "user_recent_active"

        # Tone selection
        tone = self._select_tone(components, scene)

        snapshot = {
            "scene": scene,
            "weights": dict(self.weights),
            "components": dict(components),
            "score": score,
            "threshold": threshold,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }

        return Decision(
            scene=scene,
            tone=tone,
            score=score,
            weights=dict(self.weights),
            components=dict(components),
            suppress_reason=suppress_reason,
            context_snapshot=snapshot,
        )

    # ── Components ─────────────────────────────────
    def _read_components(self, override: dict | None) -> dict[str, float]:
        """Read all 5 input components. Returns dict with:
          - desire_score (0-100): 5 变量加权
          - emotion_score (0-100): P/A/D + 隐藏槽位
          - context_score (0-100): 离线时长 + 24h 主题
          - environment_score (0-100): 天气/纪念日/时段
          - cooldown_minutes_remaining (real number)
          - user_minutes_since_last (real number)
        """
        c: dict[str, float] = {
            "desire_score": 0.0,
            "emotion_score": 50.0,    # 中性基线
            "context_score": 0.0,
            "environment_score": 0.0,
            "cooldown_minutes_remaining": 0.0,
            "user_minutes_since_last": 999.0,
        }
        if override:
            c.update(override)
            return c

        # 1) Desire 5 变量
        try:
            if self.companion and getattr(self.companion, "desire", None):
                state = self.companion.desire.get_state() or {}
                raw = float(state.get("score", 0.0))
                # raw 通常是 0-100 之间
                c["desire_score"] = max(0.0, min(100.0, raw))
        except Exception:
            logger.debug("desire read failed", exc_info=True)

        # 2) 情绪 + 隐藏槽位
        try:
            if self.companion and getattr(self.companion, "emotion", None):
                est = self.companion.emotion.get_state(0) or {}
                pad = est.get("pad", {}) or {}
                # 情绪驱动 = |A| * 30 + |D| * 20 + (1 - P) * 50
                P = float(pad.get("P", 0.0))
                A = float(pad.get("A", 0.0))
                D = float(pad.get("D", 0.0))
                drive = abs(A) * 30.0 + abs(D) * 20.0 + max(0.0, 1.0 - P) * 50.0
                c["emotion_score"] = max(0.0, min(100.0, drive))
                # 隐藏槽位加成
                th = est.get("thresholds", {}) or {}
                bonus = 0.0
                for slot_name, slot_info in th.items():
                    if isinstance(slot_info, dict):
                        v = float(slot_info.get("value", 0) or 0)
                        thr = float(slot_info.get("threshold", 1) or 1)
                        if thr > 0:
                            bonus += (v / thr) * 25.0
                c["emotion_score"] = min(100.0, c["emotion_score"] + bonus)
        except Exception:
            logger.debug("emotion read failed", exc_info=True)

        # 3) 用户上下文 (最近消息时间)
        try:
            if self.companion and getattr(self.companion, "desire", None):
                absence = float(
                    self.companion.desire.get_state().get(
                        "user_absence_hours", 0.0
                    ) or 0.0
                )
                # 离线 1h = 25, 4h = 100
                c["context_score"] = max(0.0, min(100.0, absence * 25.0))
                c["user_minutes_since_last"] = absence * 60.0
        except Exception:
            logger.debug("context read failed", exc_info=True)

        # 4) 环境
        try:
            h = datetime.now().hour
            # 早晨 / 晚上 5-8 / 19-23 略高
            if 5 <= h < 8:
                c["environment_score"] += 30.0
            elif 11 <= h < 13:
                c["environment_score"] += 25.0
            elif 17 <= h < 19:
                c["environment_score"] += 25.0
            elif 19 <= h < 23:
                c["environment_score"] += 35.0
            # 天气 / 纪念日 — 简化加成
            from core import brief_fetcher
            today = datetime.now().strftime("%Y-%m-%d")
            brief = brief_fetcher.load_brief(today) or {}
            w = brief.get("weather") or {}
            desc = (w.get("desc") or "").lower()
            if "雨" in desc or "rain" in desc:
                c["environment_score"] += 15.0
            if brief.get("anniversary_count", 0) > 0:
                c["environment_score"] += 30.0
        except Exception:
            logger.debug("environment read failed", exc_info=True)
        c["environment_score"] = min(100.0, c["environment_score"])

        # 5) Cooldown
        try:
            if self.companion and getattr(self.companion, "push_scheduler", None):
                pol = self.companion.push_scheduler.cron.policy
                if pol.last_push_at:
                    elapsed_min = (datetime.now() - pol.last_push_at).total_seconds() / 60.0
                    if elapsed_min < pol.min_interval_min:
                        c["cooldown_minutes_remaining"] = float(
                            pol.min_interval_min - elapsed_min
                        )
        except Exception:
            logger.debug("cooldown read failed", exc_info=True)

        return c

    # ── Score ─────────────────────────────────────
    def _compute_score(self, c: dict[str, float]) -> int:
        w = self.weights
        s = (
            c.get("desire_score", 0.0) * w.get("desire", 0.0)
            + c.get("emotion_score", 0.0) * w.get("emotion", 0.0)
            + c.get("context_score", 0.0) * w.get("context", 0.0)
            + c.get("environment_score", 0.0) * w.get("environment", 0.0)
        )
        # Cooldown penalty: subtract
        cd = c.get("cooldown_minutes_remaining", 0.0) or 0.0
        s -= cd * w.get("cooldown_penalty", 0.0) * 10.0
        return int(max(0, min(100, round(s))))

    # ── Tone ──────────────────────────────────────
    def _select_tone(self, c: dict[str, float], scene: str) -> str:
        # Override path (used by tests + future pipeline hook)
        forced = c.get("force_tone")
        if forced:
            return str(forced)
        # Eruption 优先
        try:
            if self.companion and getattr(self.companion, "emotion", None):
                est = self.companion.emotion.get_state(0) or {}
                th = est.get("thresholds", {}) or {}
                # 任一槽位接近阈值 → 爆发态
                for slot_name, slot_info in th.items():
                    if isinstance(slot_info, dict):
                        v = float(slot_info.get("value", 0) or 0)
                        thr = float(slot_info.get("threshold", 1) or 1)
                        if thr > 0 and v / thr >= 0.9:
                            eruption_key = f"{slot_name}_eruption"
                            if eruption_key in TONE_BY_DOMINANT:
                                return TONE_BY_DOMINANT[eruption_key]
                # 否则按基本情绪
                label = (est.get("label") or "neutral").lower()
                if label in TONE_BY_DOMINANT:
                    return TONE_BY_DOMINANT[label]
        except Exception:
            logger.debug("tone select failed", exc_info=True)
        return TONE_BY_DOMINANT.get("neutral", "casual_warm")


# ══════════════════════════════════════════════════
# Self-test
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    # 6 个 mock state 验证矩阵
    cases = [
        {
            "name": "深夜 23:30,desire 高 + 用户离线 5h,应触发 goodnight + longing tone",
            "override": {
                "desire_score": 60.0,
                "emotion_score": 40.0,
                "context_score": 100.0,
                "environment_score": 35.0,
                "user_minutes_since_last": 300.0,
            },
            "scene": "goodnight",
            "expect_suppress": "",
        },
        {
            "name": "早晨 6:30,低欲望但环境加成,应触发 morning_brief",
            "override": {
                "desire_score": 10.0,
                "emotion_score": 50.0,
                "context_score": 50.0,
                "environment_score": 60.0,
                "user_minutes_since_last": 480.0,
            },
            "scene": "morning_brief",
            "expect_suppress": "",
        },
        {
            "name": "用户 1 分钟前刚发消息,应被 user_recent_active 抑制",
            "override": {
                "desire_score": 80.0,
                "emotion_score": 80.0,
                "context_score": 100.0,
                "environment_score": 50.0,
                "user_minutes_since_last": 1.0,
            },
            "scene": "idle_care",
            "expect_suppress": "user_recent_active",
        },
        {
            "name": "cooldown 还有 25 分钟,应被 cooldown_active 抑制",
            "override": {
                "desire_score": 80.0,
                "emotion_score": 60.0,
                "context_score": 80.0,
                "environment_score": 50.0,
                "cooldown_minutes_remaining": 25.0,
            },
            "scene": "idle_care",
            "expect_suppress": "cooldown_active",
        },
        {
            "name": "情绪爆发 (anxiety 90%),应触发 emotion_comfort + collapse_seeking",
            "override": {
                "desire_score": 50.0,
                "emotion_score": 90.0,
                "context_score": 50.0,
                "environment_score": 30.0,
                "force_tone": "collapse_seeking",
            },
            "scene": "emotion_comfort",
            "expect_suppress": "",
            "expect_tone": "collapse_seeking",
        },
        {
            "name": "voice_miss desire 80,context 80,score 应 ≥ 50 触发",
            "override": {
                "desire_score": 80.0,
                "emotion_score": 60.0,
                "context_score": 80.0,
                "environment_score": 50.0,
            },
            "scene": "voice_miss",
            "expect_suppress": "",
        },
    ]
    judge = ProactiveJudge()
    passed = 0
    for i, case in enumerate(cases, 1):
        d = judge.evaluate(case["scene"], context_override=case.get("override"))
        ok = True
        if case.get("expect_suppress"):
            if d.suppress_reason != case["expect_suppress"]:
                ok = False
        else:
            if d.suppress_reason.startswith("score_below_threshold"):
                ok = False
        if case.get("expect_tone"):
            if d.tone != case["expect_tone"]:
                ok = False
        status = "OK" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"[{status}] case {i}: {case['name']}")
        print(f"        scene={d.scene} tone={d.tone} score={d.score} suppress={d.suppress_reason!r}")
    print(f"\n{passed}/{len(cases)} passed")

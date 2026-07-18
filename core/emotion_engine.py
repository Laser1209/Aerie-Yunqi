"""Aerie · 云栖 v0.1.0-beta.1 — Emotion engine (PAD + 5 emotions + cumulative thresholds).

Integrates:
  1. PAD 3D emotion model (Pleasure-Arousal-Dominance)
  2. 5 basic emotions: Joy, Anger, Sad, Fear, Neutral (Ita.md §8)
  3. Cumulative threshold engine (emotion_threshold.py)

Aligned with System_Features.md §11 and Ita.md §8-9.
"""

from __future__ import annotations
import json
import logging
import random
import time
from typing import Any

import httpx

from core.emotion_threshold import get_threshold_engine, CumulativeEmotionEngine

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
# 5 basic emotions — PAD centers (Ita.md §8.1)
# DEPRECATED: 旧硬编码 EMOTION_CENTERS，保留作 fallback
# 实际配置请改 config/persona_behavior.yaml → emotion.tree.states
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
# R8.1 (Persona 9/10 · screen-aware): 热情度 9/10 → Etta 对"爱你/想你"
# 等表达反应更强烈。所有 joy 关键词权重 +0.2（例 1.2→1.4、1.0→1.2、
# 0.8→1.0），让仪表盘 emotion 标签更易显示 joy。其它情绪
# （anger / sad / fear）权重**不动** —— 9/10 基线不等于攻击性提升。
# ══════════════════════════════════════════════════
KEYWORD_DELTAS = [
    # Joy triggers
    (["谢谢", "爱你", "喜欢", "爱你哦", "最喜欢你了", "好爱你"], "joy", 1.4),  # R8.1: 1.2→1.4
    (["你好棒", "好厉害", "真厉害", "太强了", "崇拜"], "joy", 1.2),  # R8.1: 1.0→1.2
    (["开心", "快乐", "哈哈", "笑死", "好笑", "有趣", "好玩"], "joy", 1.2),  # R8.1: 1.0→1.2
    (["乖", "听话", "好乖"], "joy", 1.0),  # R8.1: 0.8→1.0
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
    (["嘿嘿", "嘻嘻", "嘿嘿嘿", "嘤嘤嘤", "哈哈哈"], "joy", 1.1),  # R8.1: 0.9→1.1
    (["太棒了", "绝绝子", "yyds", "永远的神"], "joy", 1.3),  # R8.1: 1.1→1.3
    (["开心死了", "高兴死了", "爽"], "joy", 1.5),  # R8.1: 1.3→1.5
    (["么么哒", "mua", "爱你哟"], "joy", 1.2),  # R8.1: 1.0→1.2
    (["抱抱", "亲亲", "蹭蹭", "贴贴"], "joy", 0.9),  # R8.1: 0.7→0.9
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
    (["笨蛋", "傻瓜"], "joy", 0.5),  # R8.1: 0.3→0.5 — 弱反触发
    (["嘿嘿", "嘻嘻", "嘿嘿嘿"], "joy", 0.4),  # R8.1: 0.2→0.4
]


class EmotionEngine:
    def __init__(self, db: Any = None, state_store: Any = None, behavior_cfg: dict | None = None, brain: Any = None) -> None:
        self.db = db
        self.state_store = state_store
        self.behavior_cfg = behavior_cfg or {}
        # R7.0: optional brain reference for LLM-driven emotion inference.
        # When set, update_trajectory_async() will also call the LLM to
        # produce a more nuanced PAD than the keyword-only path.
        self.brain = brain
        # R0.3.4: PAD centers now loaded from behavior_cfg; fallback to deprecated EMOTION_CENTERS.
        states_cfg = self.behavior_cfg.get("emotion", {}).get("tree", {}).get("states")
        if states_cfg:
            self._emotion_centers: dict[str, dict] = {
                name: {"P": float(v.get("P", 0)), "A": float(v.get("A", 0)), "D": float(v.get("D", 0))}
                for name, v in states_cfg.items()
            }
            self._cfg_source = "persona_behavior.yaml"
        else:
            self._emotion_centers = EMOTION_CENTERS
            self._cfg_source = "EMOTION_CENTERS (deprecated)"

        # R0.3.4: baseline PAD from config (default neutral).
        baseline_cfg = self.behavior_cfg.get("emotion", {}).get("baseline", {})
        self._baseline: dict[str, float] = {
            "P": float(baseline_cfg.get("pleasure", 0.0)),
            "A": float(baseline_cfg.get("arousal", 0.0)),
            "D": float(baseline_cfg.get("dominance", 0.0)),
        }
        self._state: dict[str, float] = dict(self._baseline)
        self._history: list[dict] = []
        # Pass behavior_cfg through to threshold engine so the same source
        # is used for both emotion and threshold configuration.
        self.threshold_engine: CumulativeEmotionEngine = get_threshold_engine(behavior_cfg)

    def update_behavior_config(self, behavior_cfg: dict) -> None:
        """Hot-reload behavior config without restarting.

        Updates emotion centers, baseline PAD, and propagates new config
        down to the threshold engine. Current PAD state is preserved.
        """
        import logging
        log = logging.getLogger(__name__)
        self.behavior_cfg = behavior_cfg or {}

        states_cfg = self.behavior_cfg.get("emotion", {}).get("tree", {}).get("states")
        if states_cfg:
            self._emotion_centers = {
                name: {"P": float(v.get("P", 0)), "A": float(v.get("A", 0)), "D": float(v.get("D", 0))}
                for name, v in states_cfg.items()
            }
            self._cfg_source = "persona_behavior.yaml"
            log.info("emotion centers reloaded from config (%d states)", len(self._emotion_centers))

        baseline_cfg = self.behavior_cfg.get("emotion", {}).get("baseline", {})
        self._baseline = {
            "P": float(baseline_cfg.get("pleasure", 0.0)),
            "A": float(baseline_cfg.get("arousal", 0.0)),
            "D": float(baseline_cfg.get("dominance", 0.0)),
        }
        log.info("emotion baseline reloaded: P=%.2f A=%.2f D=%.2f", *self._baseline.values())

        if hasattr(self, "threshold_engine") and self.threshold_engine:
            try:
                self.threshold_engine.reload_config(behavior_cfg)
            except Exception as e:
                log.warning("threshold engine reload failed: %s", e)

    # ── PAD Analysis ───────────────────────────────

    def analyze(self, text: str) -> dict:
        """Keyword-based emotion analysis → PAD deltas."""
        p, a, d = 0.0, 0.0, 0.0

        for keywords, emotion, weight in KEYWORD_DELTAS:
            for kw in keywords:
                if kw in text:
                    center = self._emotion_centers.get(emotion, {"P": 0, "A": 0, "D": 0})
                    p += center["P"] * weight * 0.15
                    a += center["A"] * weight * 0.15
                    d += center["D"] * weight * 0.15
                    break

        p = max(-0.95, min(0.95, p))
        a = max(-0.95, min(0.95, a))
        d = max(-0.95, min(0.95, d))

        return {"pleasure": round(p, 3), "arousal": round(a, 3), "dominance": round(d, 3)}

    def update_trajectory(self, user_id: int, text: str) -> None:
        """Apply PAD deltas from user text, with EMA smoothing.

        Synchronous keyword-only path. Kept for backward compatibility
        and for callers that don't have a brain / don't want the LLM
        latency. New code should call update_trajectory_async().
        """
        pad = self.analyze(text)
        self._apply_pad_and_persist(user_id, text, pad, source="keyword")

    async def update_trajectory_async(self, user_id: int, text: str) -> None:
        """R7.0: LLM-driven emotion trajectory update.

        Sequence:
          1. Run keyword analysis (sync, ~0ms) for a fast first pass.
          2. If a brain is wired up, additionally call the LLM to get a
             richer PAD reading (async, ~1-3s).
          3. Blend the two with a weighted average; if LLM fails or
             times out, the keyword result stands.
          4. Persist the blended state to state_store with
             trigger_event="llm_emotion" so the dashboard can
             distinguish "the LLM actually ran" from "fallback".
        """
        kw_pad = self.analyze(text)
        llm_pad = await self.infer_llm_pad(text) if self.brain else None
        if llm_pad is not None:
            # Weighted blend: 60% LLM, 40% keyword. LLM is the primary
            # signal because it captures nuance the keyword list misses,
            # but the keyword path keeps the LLM from drifting too far
            # on messages that contain obvious triggers.
            blended = {
                "pleasure":  round(0.6 * llm_pad["pleasure"]  + 0.4 * kw_pad["pleasure"],  3),
                "arousal":   round(0.6 * llm_pad["arousal"]   + 0.4 * kw_pad["arousal"],   3),
                "dominance": round(0.6 * llm_pad["dominance"] + 0.4 * kw_pad["dominance"], 3),
            }
            self._apply_pad_and_persist(user_id, text, blended, source="llm")
        else:
            # Fallback to keyword-only (no brain wired, or LLM call failed).
            self._apply_pad_and_persist(user_id, text, kw_pad, source="keyword")

    async def infer_llm_pad(self, text: str) -> dict | None:
        """Call the LLM to extract a PAD triple from the user text.

        Returns ``{pleasure, arousal, dominance}`` in [-1, 1] or
        ``None`` if the LLM call fails / times out. The prompt is short
        (one-shot JSON) to keep latency low.
        """
        if not self.brain or not getattr(self.brain, "_providers", None):
            return None
        prompt = (
            "你是一个情感分析专家。请阅读用户消息，"
            "按 PAD 情感模型给出 3 个 -1 到 1 之间的实数:\n"
            "  pleasure  (愉悦度: -1=极度痛苦, 0=中性, 1=极度愉悦)\n"
            "  arousal   (唤醒度: -1=极度平静, 0=中性, 1=极度激动)\n"
            "  dominance (主导度: -1=极度被动, 0=中性, 1=极度主动)\n"
            "只输出一个 JSON, 例: {\"pleasure\":0.3,\"arousal\":0.5,\"dominance\":0.2}\n"
            f"用户消息: {text[:400]}"
        )
        messages = [
            {"role": "system", "content": "你只输出 JSON，不要任何解释。"},
            {"role": "user", "content": prompt},
        ]
        # R7.0: try each provider in the brain's list, in order. This
        # mirrors brain.generate() but with a tiny max_tokens budget so
        # we don't spend 2s waiting for a 4096-token response.
        last_error = ""
        for idx, provider in enumerate(self.brain._providers):
            try:
                body = {
                    "model": provider["model"],
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 60,
                }
                headers = {
                    "Authorization": f"Bearer {provider['key']}",
                    "Content-Type": "application/json",
                }
                t0 = time.monotonic()
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        f"{provider['url']}/chat/completions",
                        json=body,
                        headers=headers,
                    )
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}"
                    continue
                data = resp.json()
                content = (
                    (data.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    or ""
                )
                parsed = self._parse_pad_json(content)
                if parsed is not None:
                    dur_ms = int((time.monotonic() - t0) * 1000)
                    logger.info(
                        "emotion LLM: provider=%s dur=%dms pad=%s",
                        provider["name"], dur_ms, parsed,
                    )
                    return parsed
                last_error = "bad_json"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "emotion LLM provider %s failed: %s",
                    provider.get("name", "?"), last_error[:80],
                )
        logger.warning("emotion LLM: all providers failed, last_error=%s", last_error[:80])
        return None

    @staticmethod
    def _parse_pad_json(content: str) -> dict | None:
        """Best-effort parse of an LLM PAD response. Strips ```json fences."""
        if not content:
            return None
        s = content.strip()
        # Strip code fences
        if s.startswith("```"):
            s = s.strip("`")
            if s.lower().startswith("json"):
                s = s[4:]
            s = s.strip()
        # Sometimes the model wraps JSON in extra prose; find first { ... }
        if "{" in s:
            s = s[s.index("{"):]
            if "}" in s:
                s = s[: s.rindex("}") + 1]
        try:
            d = json.loads(s)
        except Exception:
            return None
        try:
            p = float(d.get("pleasure", 0.0))
            a = float(d.get("arousal", 0.0))
            dom = float(d.get("dominance", 0.0))
        except Exception:
            return None
        # Clamp to [-1, 1]
        p = max(-1.0, min(1.0, p))
        a = max(-1.0, min(1.0, a))
        dom = max(-1.0, min(1.0, dom))
        return {"pleasure": round(p, 3), "arousal": round(a, 3), "dominance": round(dom, 3)}

    def _apply_pad_and_persist(self, user_id: int, text: str, pad: dict, source: str = "keyword") -> None:
        """Apply PAD with EMA smoothing and persist a snapshot.

        R7.0: extracted from update_trajectory so the sync and async
        paths share the same state-mutation + persistence logic. The
        ``source`` is recorded in state_store so the dashboard can
        distinguish LLM-driven updates from keyword-only fallbacks.
        """
        self._state["P"] = round(self._state["P"] * 0.7 + pad["pleasure"]  * 0.3, 3)
        self._state["A"] = round(self._state["A"] * 0.7 + pad["arousal"]   * 0.3, 3)
        self._state["D"] = round(self._state["D"] * 0.7 + pad["dominance"] * 0.3, 3)
        self._history.append({"user_id": user_id, "text": text[:60], "source": source, **pad})

        # Scan for cumulative threshold triggers
        eruptions = self.threshold_engine.scan_text(text)
        if eruptions:
            for e in eruptions:
                logger.info("Threshold eruption: %s — %s", e["mode"], e["trigger"])

        # Persist a snapshot. ``trigger_event`` now includes the source
        # so the dashboard can show "LLM 触发的情绪变化" vs "fallback".
        if self.state_store:
            try:
                trigger = f"{source}_msg" if not eruptions else f"{source}_eruption"
                self.state_store.snapshot(
                    user_id=user_id,
                    state=self.get_state(user_id),
                    threshold=self.threshold_engine.get_slots_summary(),
                    trigger_event=trigger,
                )
            except Exception:
                logger.exception("emotion state snapshot error")

        logger.debug(
            "PAD(%s): P=%.2f A=%.2f D=%.2f",
            source, *self._state.values(),
        )

    # ── Emotion Classification ─────────────────────

    def get_label(self) -> str:
        """Classify current PAD into one of 5 basic emotions."""
        p, a, _ = self._state["P"], self._state["A"], self._state["D"]

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

    def idle_tick(self) -> dict:
        """R7.5: periodic background tick for dashboard liveness.

        - EMA: 0.98 * current + 0.02 * baseline (gentle pull toward
          neutral so PAD eventually settles without strong signals).
        - plus tiny Gaussian noise (sigma=0.01) so the dashboard never
          looks frozen.
        - No LLM call, no DB write here (caller decides when to snapshot
          via state_store.snapshot(trigger_event="idle_tick")).
        Returns the new state for inspection.
        """
        for k in ("P", "A", "D"):
            cur = float(self._state.get(k, 0.0))
            base = float(self._baseline.get(k, 0.0))
            ema = 0.98 * cur + 0.02 * base
            noise = random.gauss(0.0, 0.01)
            self._state[k] = max(-0.95, min(0.95, ema + noise))
        return dict(self._state)

    # ── Text Tuning ────────────────────────────────

    def tune(self, text: str) -> str:
        """Adjust reply text based on current emotion state."""
        label = self.get_label()

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

"""阶段 5 · 存量违规改造测试（ProactiveJudge / DesireEngine）.

覆盖：
- ProactiveJudge：score 硬阈值 → 调制 p + 采样（低分仍非零、高分仍非必然）；
- ProactiveJudge 硬闸门保留：user_recent_active(<5min) / cooldown_active；
- ProactiveJudge 采样固定 seed 可复现；
- DesireEngine：阈值阶梯 → 调制 + 采样；高分发射率 > 低分、低分仍 >0、高分仍有未发射；
- DesireEngine 固定 seed 回放「改前基线 vs 改后」；
- legacy 落库缺口：proactive_delivery_v2 关闭时也落库（chat_log + normalized 双写）。
"""

from __future__ import annotations

import random
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core import behavior_sampler as bs
from core.proactive_judge import DEFAULT_SAMPLING, ProactiveJudge, SCENE_THRESHOLDS

# ── ProactiveJudge：调制 + 采样 ────────────────────────

_OVERRIDE = {
    "desire_score": 20.0,
    "emotion_score": 50.0,
    "context_score": 50.0,
    "environment_score": 30.0,
    "user_minutes_since_last": 300.0,  # 无硬闸门
}


def test_judge_reference_is_probability_inflection_not_hard_gate():
    ref = SCENE_THRESHOLDS["idle_care"]
    kw = dict(reference=ref, tau=DEFAULT_SAMPLING["tau"],
              floor=DEFAULT_SAMPLING["p_floor"], ceiling=DEFAULT_SAMPLING["p_ceiling"])
    p_below = bs.emit_probability(ref - 30, **kw)
    p_at = bs.emit_probability(ref, **kw)
    p_above = bs.emit_probability(ref + 30, **kw)
    assert 0.0 < p_below < p_at < p_above < 1.0   # 不再是「低于阈值即抑制」
    assert p_below >= DEFAULT_SAMPLING["p_floor"]  # 低分仍有非零概率


def test_judge_below_reference_can_still_emit_no_suppress_reason():
    # 采样恒命中（rng 返回 0）→ 即便 score < 参考分也应放行（无 score_below_threshold）。
    judge = ProactiveJudge(rng=lambda: 0.0)
    decision = judge.evaluate("idle_care", context_override=_OVERRIDE)
    assert decision.score < SCENE_THRESHOLDS["idle_care"]
    assert decision.suppress_reason == ""
    assert decision.sampled is True


def test_judge_above_reference_can_sample_out():
    # 采样永不命中（rng 返回 ~1）→ 高分也保留未发射样本。
    judge = ProactiveJudge(rng=lambda: 0.999999)
    decision = judge.evaluate("idle_care", context_override=_OVERRIDE)
    assert decision.suppress_reason == "sampled_out"


def test_judge_sampling_reproducible_with_seed():
    def outcomes(seed: int) -> list[bool]:
        judge = ProactiveJudge(rng=random.Random(seed).random)
        return [
            judge.evaluate("idle_care", context_override=_OVERRIDE).suppress_reason == ""
            for _ in range(40)
        ]

    assert outcomes(2026) == outcomes(2026)


def test_judge_hard_gate_user_recent_active():
    desire = MagicMock()
    desire.get_state.return_value = {"score": 0.0, "user_absence_hours": 1.0 / 60.0}
    companion = SimpleNamespace(desire=desire, emotion=None, push_scheduler=None)
    judge = ProactiveJudge(companion=companion, rng=lambda: 0.0)

    assert judge.hard_gate_reason() == "user_recent_active"
    assert judge.evaluate("idle_care").suppress_reason == "user_recent_active"


def test_judge_hard_gate_cooldown_active():
    desire = MagicMock()
    desire.get_state.return_value = {"score": 0.0, "user_absence_hours": 5.0}
    policy = SimpleNamespace(last_push_at=datetime.now(), min_interval_min=30)
    companion = SimpleNamespace(
        desire=desire,
        emotion=None,
        push_scheduler=SimpleNamespace(cron=SimpleNamespace(policy=policy)),
    )
    judge = ProactiveJudge(companion=companion, rng=lambda: 0.0)

    assert judge.hard_gate_reason() == "cooldown_active"
    assert judge.evaluate("idle_care").suppress_reason == "cooldown_active"


def test_judge_reuses_desire_emit_grant_without_resampling():
    # 欲望引擎已采样放行 → judge 复用、不再采样（即使 rng 必定失败）。
    desire = MagicMock()
    desire.get_state.return_value = {"score": 50.0, "user_absence_hours": 5.0}
    desire._emit_grant = ("idle_care", __import__("time").time())
    companion = SimpleNamespace(desire=desire, emotion=None, push_scheduler=None)
    judge = ProactiveJudge(companion=companion, rng=lambda: 0.999999)

    decision = judge.evaluate("idle_care")
    assert decision.suppress_reason == ""
    assert decision.sampled is False  # 未二次采样


# ── DesireEngine：阈值阶梯 → 调制 + 采样 ────────────────

def _engine(tmp_path, seed: int):
    from core.desire_engine import DesireEngine

    return DesireEngine(
        SimpleNamespace(),
        {"desire": {"triggers": {"care": 50, "voice": 80, "cooldown_hours": 12}, "variables": {}}},
        state_path=tmp_path / f"desire_{seed}.json",
        rng=random.Random(seed).random,
    )


def _fire_counts(tmp_path, seed: int, score: float, ticks: int = 400) -> int:
    engine = _engine(tmp_path, seed)
    fires = 0
    for i in range(ticks):
        if engine._decide_trigger(score, i * 3600.0):  # 间隔 1h > 30min 防抖窗口
            fires += 1
    return fires


def test_desire_high_score_fires_more_low_still_nonzero(tmp_path):
    high = _fire_counts(tmp_path, 11, score=75)
    low = _fire_counts(tmp_path, 11, score=20)
    assert high > low           # 高分发射频率更高
    assert low > 0              # 低分仍有非零概率（不再「低于阈值即不发」）
    assert high < 400           # 高分仍存在未发射样本


def test_desire_sampling_reproducible_with_seed(tmp_path):
    assert _fire_counts(tmp_path, 7, score=65) == _fire_counts(tmp_path, 7, score=65)


def test_desire_replay_baseline_vs_modulated(tmp_path):
    """固定 seed 回放：改前硬阈值阶梯（纯函数快照） vs 改后「调制 + 采样」。

    改前代码已被本次改造替换，故用参数化的旧阈值逻辑纯函数产生基线数，
    再用同一 seed 回放新逻辑对比触发次数，偏差须在 ±30% 以内。
    """
    care, voice, tick, spacing = 50.0, 80.0, 300.0, 1800.0
    replay_days = 7
    ticks = replay_days * 24 * 12  # 5min tick
    seed = 20260927
    data_rng = random.Random(seed)
    scores = [data_rng.uniform(40.0, 70.0) for _ in range(ticks)]  # <80 → 不触语音

    # 改前基线：score >= care 即触发（含 30min 防抖）——参数化复现。
    def legacy_fires(values: list[float]) -> int:
        fires = 0
        last = -1e18
        t = 0.0
        for value in values:
            if value >= care and (t - last) > spacing:
                last = t
                fires += 1
            t += tick
        return fires

    baseline = legacy_fires(scores)

    # 改后：调制 p + 采样（固定 seed）。
    engine = _engine(tmp_path, seed)
    modulated = 0
    t = 0.0
    for value in scores:
        if engine._decide_trigger(value, t):
            modulated += 1
        t += tick

    deviation = abs(modulated - baseline) / max(1, baseline)
    print(
        f"\n[replay] days={replay_days} ticks={ticks} seed={seed} "
        f"baseline={baseline} modulated={modulated} deviation={deviation:.1%}"
    )
    assert baseline > 0
    assert deviation <= 0.30


# ── legacy 落库缺口修复 ────────────────────────────────

@pytest.mark.asyncio
async def test_legacy_flag_off_persists_chat_log_and_normalized():
    """proactive_delivery_v2 关闭时也落库（chat_log + persist_proactive_message）。"""
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.settings = {"qq": {"self_qq": 7}, "proactive": {}}
    companion.feature_flags = SimpleNamespace(is_enabled=MagicMock(return_value=False))
    companion.get_primary_user_selection = MagicMock(
        return_value=SimpleNamespace(user_id=7)
    )
    companion._active_persona_id = MagicMock(return_value="aerie_default")
    companion._proactive_channel_identity = MagicMock(
        return_value=("actor-1", "desktop", "local")
    )
    companion.qq = SimpleNamespace(
        is_logged_in=True, self_id=7, send_message=AsyncMock(return_value=True)
    )
    companion.emotion = SimpleNamespace(
        get_state=MagicMock(return_value={"label": "neutral"})
    )
    companion.brain = SimpleNamespace(
        generate_push=AsyncMock(return_value="想起你之前说的事。")
    )
    companion.db = SimpleNamespace(insert=MagicMock(return_value=42))
    persist = MagicMock(return_value="conv-1")
    companion.conversation_repository = SimpleNamespace(
        persist_proactive_message=persist
    )

    ok = await companion._dispatch_push(
        "topic_resurface",
        {"template": "想起你之前说的事。", "self_initiated": True},
    )

    assert ok is True
    # 修复点 1：legacy 路径写 chat_log，且 self_initiated 与既有标记共存。
    companion.db.insert.assert_called_once()
    fields = companion.db.insert.call_args.args[1]
    assert fields["msg_type"] == "proactive"
    assert fields["route_mode"] == "PROACTIVE"
    assert fields["scene"] == "topic_resurface"
    assert fields["self_initiated"] == 1
    # 修复点 2：normalized messages 双写（persist_proactive_message 被调用）。
    persist.assert_called_once()
    assert persist.call_args.kwargs["legacy_chat_log_id"] == 42
    assert persist.call_args.kwargs["content"] == "想起你之前说的事。"

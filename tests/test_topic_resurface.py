"""阶段 5 · 话题复现触发源测试.

覆盖：候选召回（仅 dormant + 相关度粗筛）、m 归一化与单调、概率上下限、
唯一采样点、固定 seed 的高/低 m 发射频率、低 m 子额度独立性、
分派分支注册与记账、硬闸门（user_recent_active / cooldown）、日上限。
"""

from __future__ import annotations

import random
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core import behavior_sampler as bs
from core.push_scheduler import CronScheduler
from core.topic_lifecycle import TopicLifecycle
from core.topic_resurface import TopicResurface, resolve_params
from core.topic_tracker import Topic, TopicTracker

HOUR = 3600.0
DAY = 86400.0
T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def _isolate_resurface_state(tmp_path, monkeypatch):
    """额度记账落盘隔离：额度状态绝不写进仓库的 data/。"""
    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path / "data"))


def _lifecycle(tmp_path, *, enabled: bool = True) -> TopicLifecycle:
    tracker = TopicTracker(state_path=tmp_path / "topic_state.json", clock=lambda: T0)
    return TopicLifecycle(
        tracker=tracker, clock=lambda: T0, enabled_check=lambda: enabled
    )


def _add_topic(
    lifecycle: TopicLifecycle,
    subject: str,
    *,
    interest: float = 0.8,
    dormancy_hours: float = 48.0,
    lifecycle_state: str = "dormant",
) -> Topic:
    """直接构造话题（控制兴趣评分 / 沉寂时长，保证测试确定性）。"""
    topic = Topic(
        id=f"t{len(lifecycle.tracker.topics)}",
        subject=subject,
        state="closed",
        started_at=T0 - 3 * DAY,
        last_active_at=T0 - dormancy_hours * HOUR,
        lifecycle=lifecycle_state,
        interest_score=interest,
        dormancy_since=T0 - dormancy_hours * HOUR,
        last_context=subject,
    )
    lifecycle.tracker.topics.append(topic)
    lifecycle.tracker.save()
    return topic


def _resurface(lifecycle: TopicLifecycle, rng=random.random) -> TopicResurface:
    return TopicResurface(lifecycle_provider=lambda: lifecycle, rng=rng, clock=lambda: T0)


# ── 阶段一：候选召回 ───────────────────────────────────

def test_recall_returns_only_dormant(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    dormant = _add_topic(lifecycle, "书的事", interest=0.8)
    _add_topic(lifecycle, "电影的事", interest=0.8, lifecycle_state="dead")

    candidates = _resurface(lifecycle).recall(resolve_params({}))

    assert [c.topic_id for c in candidates] == [dormant.id]


def test_recall_filters_by_context_relevance(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    # 先造一个 active 话题作为当前上下文参考。
    lifecycle.observe({"text": "那本书的结局真好看", "now": T0, "user_id": 1})
    related = _add_topic(lifecycle, "那本书的结局", interest=0.9)
    _add_topic(lifecycle, "明天开会安排", interest=0.9)

    candidates = _resurface(lifecycle).recall(
        resolve_params({"context_candidate_floor": 0.5})
    )
    ids = {c.topic_id for c in candidates}

    assert related.id in ids          # 相关 → 通过粗筛
    assert len(candidates) == 1       # 不相关 → 被上下文相关度粗筛掉


def test_recall_empty_when_lifecycle_disabled(tmp_path):
    lifecycle = _lifecycle(tmp_path, enabled=False)
    _add_topic(lifecycle, "书的事")
    assert _resurface(lifecycle).recall(resolve_params({})) == []


# ── 调制信号 m（归一化 + 单调）─────────────────────────

def test_modulation_normalized_and_monotonic():
    params = resolve_params({})
    low = TopicResurface._modulation(0.2, 0.2, 0.2, params)
    high = TopicResurface._modulation(0.9, 0.9, 0.9, params)
    assert 0.0 < low < high <= 1.0
    # 单因子单调：仅提高兴趣评分，m 上升。
    assert (
        TopicResurface._modulation(0.9, 0.2, 0.2, params)
        > TopicResurface._modulation(0.2, 0.2, 0.2, params)
    )


def test_recall_normalizes_dormancy_and_interest(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    _add_topic(lifecycle, "很久以前的事", interest=1.0, dormancy_hours=7 * 24)
    proposal = _resurface(lifecycle).propose(resolve_params({}))
    assert proposal is not None
    assert 0.0 <= proposal.interest <= 1.0
    assert 0.0 <= proposal.relevance <= 1.0
    assert proposal.dormancy == pytest.approx(1.0)  # 达上限即封顶 1.0
    assert 0.0 < proposal.m <= 1.0


# ── 阶段二：概率发射（唯一采样点）───────────────────────

def test_emit_probability_floor_and_ceiling():
    params = resolve_params({})
    kw = dict(reference=params["m_midpoint"], tau=params["tau"],
              floor=params["p_floor"], ceiling=params["p_ceiling"])
    p_low = bs.emit_probability(0.05, **kw)
    p_mid = bs.emit_probability(0.5, **kw)
    p_high = bs.emit_probability(0.98, **kw)
    assert 0.0 < p_low < p_mid < p_high < 1.0   # 严格落在 (floor, ceiling)
    assert p_low >= params["p_floor"]           # 低 m 仍有非零概率
    assert p_high <= params["p_ceiling"]        # 高 m 仍非必然


def test_high_m_emits_more_than_low_m_fixed_seed():
    params = resolve_params({})
    kw = dict(reference=params["m_midpoint"], tau=params["tau"],
              floor=params["p_floor"], ceiling=params["p_ceiling"])
    p_high = bs.emit_probability(0.95, **kw)
    p_low = bs.emit_probability(0.05, **kw)

    rng = random.Random(20260927)
    draws = [rng.random() for _ in range(3000)]
    high = sum(1 for d in draws if bs.sample_once(p_high, lambda v=d: v))
    low = sum(1 for d in draws if bs.sample_once(p_low, lambda v=d: v))

    assert high > 2 * low          # 高 m 发射频率显著高于低 m
    assert low > 0                 # 低 m 仍有非零发射率
    assert high < len(draws)       # 高 m 仍存在未发射样本


def test_decide_uses_exactly_one_sample(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    _add_topic(lifecycle, "书的事", interest=0.9, dormancy_hours=120)

    class _CountingRng:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> float:
            self.calls += 1
            return 0.0  # 必发射

    rng = _CountingRng()
    proposal = _resurface(lifecycle, rng=rng).decide(resolve_params({}))

    assert proposal is not None and proposal.emitted is True
    assert rng.calls == 1  # 同一决策链只有一个采样点


# ── 低 m 子额度 ────────────────────────────────────────

def test_low_m_sub_budget_does_not_eat_main(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    params = resolve_params({"main_budget": 4, "low_m_budget": 1})
    resurface = _resurface(lifecycle)

    # 低 m 用光子额度后：低 m 被拒，主额度不受影响。
    resurface.consume(True, params)
    assert resurface.budget_allows(True, params) is False
    assert resurface.budget_allows(False, params) is True


def test_main_budget_exhausted_low_m_still_available(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    params = resolve_params({"main_budget": 4, "low_m_budget": 1})
    resurface = _resurface(lifecycle)

    for _ in range(4):
        resurface.consume(False, params)
    assert resurface.budget_allows(False, params) is False   # 主额度耗尽
    assert resurface.budget_allows(True, params) is True      # 低 m 子额度仍可用
    # 子额度也吃满后不再放行（不超日额度）。
    resurface.consume(True, params)
    assert resurface.budget_allows(True, params) is False


def test_budget_survives_restart(tmp_path):
    """额度按日落盘：重启后当日已用额度不清零。"""
    lifecycle = _lifecycle(tmp_path)
    params = resolve_params({"main_budget": 4, "low_m_budget": 1})
    first = _resurface(lifecycle)
    for _ in range(4):
        first.consume(False, params)
    assert first.budget_allows(False, params) is False

    # 模拟进程重启：新实例从同一个落盘文件恢复。
    second = _resurface(lifecycle)
    assert second.budget_allows(False, params) is False
    assert second.budget_allows(True, params) is True


def test_budget_resets_on_next_day(tmp_path):
    """跨日后额度清零（重启 + 跨日组合场景）。"""
    lifecycle = _lifecycle(tmp_path)
    params = resolve_params({"main_budget": 4})
    first = _resurface(lifecycle)
    for _ in range(4):
        first.consume(False, params)
    assert first.budget_allows(False, params) is False

    tomorrow = T0 + DAY
    second = TopicResurface(
        lifecycle_provider=lambda: lifecycle, clock=lambda: tomorrow
    )
    assert second.budget_allows(False, params) is True


# ── 分派分支注册 + 记账 + 状态复位 ──────────────────────

def _scheduler() -> CronScheduler:
    return CronScheduler(
        {
            "proactive": {
                "enabled": True,
                "quiet_start": "23:30",
                "quiet_end": "07:00",
                # 豁免静默/间隔，令分支契约测试与真实时钟无关。
                "exempt_scenes": ["topic_resurface"],
            },
            "scenes": {},
        }
    )


@pytest.mark.asyncio
async def test_dispatch_branch_emits_records_and_reactivates(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    topic = _add_topic(lifecycle, "书的事", interest=0.9, dormancy_hours=120)
    resurface = _resurface(lifecycle, rng=lambda: 0.0)  # 必发射

    scheduler = _scheduler()
    scheduler.topic_resurface = resurface
    scheduler.policy.today = date.today()
    sent = AsyncMock(return_value=True)
    scheduler.set_dispatcher(sent)

    ok = await scheduler._dispatch(
        "topic_resurface",
        {
            "custom_dispatcher": "topic_resurface",
            "defer_sampling": True,
            "self_initiated": True,
            "template": "想起你之前说的事。",
        },
    )

    assert ok is True
    sent.assert_awaited_once()
    scene_arg, cfg_arg = sent.await_args.args
    assert scene_arg == "topic_resurface"
    assert cfg_arg["resurface_topic"]["topic_id"] == topic.id
    assert cfg_arg["resurface_topic"]["context"]
    assert scheduler.policy.daily_count == 1          # 复用 policy 记账
    assert topic.lifecycle == "active"                # 复现后状态复位


@pytest.mark.asyncio
async def test_sampled_out_does_not_dispatch(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    _add_topic(lifecycle, "书的事", interest=0.6)
    resurface = _resurface(lifecycle, rng=lambda: 0.999999)  # 必定采样失败

    scheduler = _scheduler()
    scheduler.topic_resurface = resurface
    sent = AsyncMock(return_value=True)
    scheduler.set_dispatcher(sent)

    ok = await scheduler._dispatch(
        "topic_resurface", {"custom_dispatcher": "topic_resurface", "defer_sampling": True}
    )

    assert ok is False
    sent.assert_not_awaited()
    assert scheduler.policy.daily_count == 0


# ── 硬闸门（防撞车 / 冷却，不采样化）───────────────────

def _judge_with(absence_hours: float, last_push_at=None):
    from core.proactive_judge import ProactiveJudge

    desire = MagicMock()
    desire.get_state.return_value = {
        "score": 0.0,
        "user_absence_hours": absence_hours,
    }
    policy = SimpleNamespace(
        last_push_at=last_push_at,
        min_interval_min=30,
    )
    companion = SimpleNamespace(
        desire=desire,
        emotion=None,
        push_scheduler=SimpleNamespace(cron=SimpleNamespace(policy=policy)),
    )
    return ProactiveJudge(companion=companion)


@pytest.mark.asyncio
async def test_user_recent_active_blocks_resurface(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    _add_topic(lifecycle, "书的事", interest=0.9, dormancy_hours=120)

    scheduler = _scheduler()
    scheduler.topic_resurface = _resurface(lifecycle, rng=lambda: 0.0)
    scheduler.judge = _judge_with(absence_hours=1.0 / 60.0)  # 1 分钟前活跃
    sent = AsyncMock(return_value=True)
    scheduler.set_dispatcher(sent)

    ok = await scheduler._dispatch(
        "topic_resurface", {"custom_dispatcher": "topic_resurface", "defer_sampling": True}
    )

    assert ok is False                 # 硬闸门生效
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_cooldown_blocks_resurface(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    _add_topic(lifecycle, "书的事", interest=0.9, dormancy_hours=120)

    scheduler = _scheduler()
    scheduler.topic_resurface = _resurface(lifecycle, rng=lambda: 0.0)
    scheduler.judge = _judge_with(absence_hours=5.0, last_push_at=datetime.now())
    sent = AsyncMock(return_value=True)
    scheduler.set_dispatcher(sent)

    ok = await scheduler._dispatch(
        "topic_resurface", {"custom_dispatcher": "topic_resurface", "defer_sampling": True}
    )

    assert ok is False                 # cooldown 硬闸门生效
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_hard_cap_blocks_resurface(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    _add_topic(lifecycle, "书的事", interest=0.9, dormancy_hours=120)

    scheduler = _scheduler()
    scheduler.topic_resurface = _resurface(lifecycle, rng=lambda: 0.0)
    scheduler.policy.today = date.today()
    scheduler.policy.daily_count = scheduler.policy.hard_cap  # 已达日上限
    sent = AsyncMock(return_value=True)
    scheduler.set_dispatcher(sent)

    ok = await scheduler._dispatch(
        "topic_resurface", {"custom_dispatcher": "topic_resurface", "defer_sampling": True}
    )

    assert ok is False                 # 不超过日上限
    sent.assert_not_awaited()

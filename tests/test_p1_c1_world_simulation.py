"""TDD tests for Task P1-C.1: WorldSimulation tick 与 WorldSnapshot.

覆盖:
  - WorldSnapshot 包含 phase/location/activity/energy/social/nearby_objects/
                  available_visual_topics/instance_id/timestamp 字段
  - tick() 返回 WorldSnapshot 实例, instance_id 唯一
  - 同一 tick 周期(秒级)幂等返回缓存快照
  - phase 基于小时映射 morning/noon/afternoon/evening/night
  - energy 随时间衰减/恢复
  - nearby_objects 包含当前环境物件
  - available_visual_topics 基于 activity 和 nearby_objects 生成
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# 世界模拟统一使用本地时区（北京时间 UTC+08:00）。
LOCAL = timezone(timedelta(hours=8))


# ── WorldSnapshot 字段齐全 ──────────────────────────
def test_world_snapshot_has_all_fields():
    from core.world_simulation import WorldSimulation, WorldSnapshot

    sim = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=LOCAL))
    snap = sim.tick()
    assert isinstance(snap, WorldSnapshot)
    for attr in (
        "phase",
        "location",
        "activity",
        "energy",
        "social",
        "nearby_objects",
        "available_visual_topics",
        "instance_id",
        "timestamp",
    ):
        assert hasattr(snap, attr), f"missing field: {attr}"
    assert isinstance(snap.nearby_objects, list)
    assert isinstance(snap.available_visual_topics, list)
    assert snap.instance_id


# ── instance_id 唯一 ───────────────────────────────
def test_tick_generates_unique_instance_ids_across_seconds():
    from core.world_simulation import WorldSimulation

    t = datetime(2026, 7, 28, 9, 0, 0, tzinfo=LOCAL)
    sim = WorldSimulation(clock=lambda: t)
    s1 = sim.tick()

    # 推进到下一秒
    t2 = t + timedelta(seconds=1)
    sim.clock = lambda: t2  # type: ignore[assignment]
    s2 = sim.tick()
    assert s1.instance_id != s2.instance_id


# ── 同秒幂等 ────────────────────────────────────────
def test_tick_idempotent_within_same_second():
    from core.world_simulation import WorldSimulation

    fixed = datetime(2026, 7, 28, 9, 0, 0, tzinfo=LOCAL)
    sim = WorldSimulation(clock=lambda: fixed)
    s1 = sim.tick()
    s2 = sim.tick()
    assert s1.instance_id == s2.instance_id
    assert s1.phase == s2.phase


# ── phase 小时映射（7 档，world_phase 单一真源）────────────
@pytest.mark.parametrize(
    "hour,expected",
    [
        (6, "dawn"),
        (7, "morning"),
        (11, "morning"),
        (12, "noon"),
        (13, "noon"),
        (15, "afternoon"),
        (18, "evening"),
        (19, "evening"),
        (22, "late_evening"),
        (23, "late_evening"),
        (0, "night"),
        (2, "night"),
        (5, "dawn"),
    ],
)
def test_phase_mapping_by_hour(hour, expected):
    from core.world_simulation import WorldSimulation

    sim = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, hour, 0, tzinfo=LOCAL)
    )
    snap = sim.tick()
    assert snap.phase == expected, f"hour={hour} -> {snap.phase}, want {expected}"


# ── energy 随时间衰减/恢复 ──────────────────────────
def test_energy_decays_and_recovers():
    """Night(morning 前) 应处于低能量恢复期, 上午高能量, 下午开始衰减."""
    from core.world_simulation import WorldSimulation

    def sim_at(hour: int):
        s = WorldSimulation(
            clock=lambda h=hour: datetime(2026, 7, 28, h, 0, tzinfo=LOCAL)
        )
        return s.tick()

    night = sim_at(3)       # 夜间睡眠 -> 低能量但正在恢复
    morning = sim_at(9)     # 上午 -> 高能量
    afternoon = sim_at(15)  # 下午 -> 中等
    evening = sim_at(21)    # 晚间 -> 偏低

    assert night.energy < 0.5
    assert morning.energy >= 0.6
    assert afternoon.energy < morning.energy  # 衰减
    assert evening.energy <= afternoon.energy


# ── nearby_objects 包含环境物件 ─────────────────────
def test_nearby_objects_reflects_environment():
    from core.world_simulation import WorldSimulation

    # 上午在家 planning -> 家里物件
    home = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=LOCAL)
    ).tick()
    assert home.location == "home"
    assert len(home.nearby_objects) > 0
    assert any(isinstance(o, str) for o in home.nearby_objects)

    # 下午在 study working -> 书房物件
    study = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 15, 0, tzinfo=LOCAL)
    ).tick()
    assert study.location == "study"
    assert len(study.nearby_objects) > 0
    # 两个地点物件集合应不同
    assert set(home.nearby_objects) != set(study.nearby_objects)


# ── available_visual_topics 基于 activity + objects ─
def test_visual_topics_derive_from_activity_and_objects():
    from core.world_simulation import WorldSimulation

    snap = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=LOCAL)
    ).tick()
    # planning 活动应产生可发送的视觉话题
    assert isinstance(snap.available_visual_topics, list)
    assert len(snap.available_visual_topics) >= 1
    for topic in snap.available_visual_topics:
        assert isinstance(topic, str)
        assert topic  # 非空


def test_visual_topics_differ_by_activity():
    from core.world_simulation import WorldSimulation

    morning = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=LOCAL)
    ).tick()
    evening = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 21, 0, tzinfo=LOCAL)
    ).tick()
    # planning vs relaxing 话题应有差异
    assert set(morning.available_visual_topics) != set(evening.available_visual_topics)


# ── 根因审计回归测试 ────────────────────────────────
def test_16_48_local_should_be_afternoon():
    """本地 16:48 应判 afternoon(14-19)，绝不能是 morning。"""
    from core.world_simulation import WorldSimulation

    sim = WorldSimulation(clock=lambda: datetime(2026, 8, 11, 16, 48, tzinfo=LOCAL))
    assert sim.tick().phase == "afternoon"


def test_get_snapshot_refreshes_when_stale():
    """缓存超过 max_age_sec 未更新时, get_snapshot 强制随真实时钟重算时段。"""
    from datetime import datetime, timedelta, timezone
    from core.world_simulation import WorldSimulation

    LOCAL = timezone(timedelta(hours=8))

    def later_clock():
        return datetime(2026, 7, 28, 15, 0, tzinfo=LOCAL)

    sim = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=LOCAL))
    sim.tick()  # 本地 9 点 → morning 缓存
    cached = sim.get_snapshot()
    assert cached.phase == "morning"

    sim.clock = later_clock  # 推进到本地 15 点，但缓存未刷新
    assert sim.get_snapshot().phase == "morning"          # 默认 None 仍返回旧缓存
    assert sim.get_snapshot(max_age_sec=300).phase == "afternoon"  # 过期 → 强制刷新


# ── 白天出门（最小版）──────────────────────────────
def test_go_out_turns_snapshot_outdoor():
    from core.world_simulation import WorldSimulation

    t = datetime(2026, 7, 28, 14, 0, tzinfo=LOCAL)  # 白天 14:00
    sim = WorldSimulation(config={"outdoor_probability": 0.0}, clock=lambda: t)
    result = sim.go_out("商圈步行街", duration_min=30)
    assert result["accepted"] is True
    snap = sim.tick()
    assert snap.outdoor is True
    assert snap.outdoor_place == "商圈步行街"
    assert snap.location.startswith("out_")
    assert "商圈步行街" in snap.nearby_objects  # 室外素材用地点而非家具
    assert "室外" in snap.position_desc


def test_go_out_auto_returns_home_after_duration():
    from core.world_simulation import WorldSimulation

    t = datetime(2026, 7, 28, 14, 0, tzinfo=LOCAL)
    sim = WorldSimulation(config={"outdoor_probability": 0.0}, clock=lambda: t)
    sim.go_out("江边步道", duration_min=1)
    assert sim.tick().outdoor is True
    # 超过时长 → 自动回房
    sim.clock = lambda: t + timedelta(minutes=2)  # type: ignore[assignment]
    snap = sim.tick()
    assert snap.outdoor is False
    assert not snap.location.startswith("out_")


def test_auto_outdoor_fires_when_high_probability_daytime():
    from core.world_simulation import WorldSimulation

    t = datetime(2026, 7, 28, 12, 0, tzinfo=LOCAL)
    sim = WorldSimulation(config={"outdoor_probability": 1.0}, clock=lambda: t)
    snap = sim.tick()
    assert snap.outdoor is True  # 白天概率 1.0 必出门
    assert snap.outdoor_place


def test_auto_outdoor_skipped_at_night():
    from core.world_simulation import WorldSimulation

    night = datetime(2026, 7, 28, 23, 0, tzinfo=LOCAL)
    sim = WorldSimulation(config={"outdoor_probability": 1.0}, clock=lambda: night)
    assert sim.tick().outdoor is False  # 夜里不出门


# ── 人设驱动出门 + 特殊事件加权（下雪/节假日）────────────
def test_effective_probability_combines_personality_weather_holiday():
    """有效概率 = base × 大五人格 × 天气 × 节日，且 clamp 到 [0,1]。"""
    from core.world_simulation import WorldSimulation

    def day(y, m, d):
        return datetime(y, m, d, 10, 0, tzinfo=LOCAL)

    # 高外向人设 + 雪天 + 元旦 → 顶格 1.0（必出门）
    sim = WorldSimulation(
        config={"outdoor_probability": 0.5, "outdoor_personality_factor": 1.496}
    )
    sim.set_reality({"weather": {"desc": "小雪"}})
    eff, factors = sim._effective_outdoor_probability(day(2026, 1, 1))
    assert factors["personality"] == 1.496
    assert factors["weather"] == 1.8
    assert factors["holiday"] == 1.6
    assert eff >= 1.0  # 0.5*1.496*1.8*1.6 被 clamp 到 1.0
    # 元旦出门地点应有雪景/节日偏好
    assert sim.go_out("", 0, "auto")["accepted"] is True

    # 大雨平日 → 概率被显著压低
    sim2 = WorldSimulation(
        config={"outdoor_probability": 0.5, "outdoor_personality_factor": 1.496}
    )
    sim2.set_reality({"weather": {"desc": "大暴雨"}})
    eff2, f2 = sim2._effective_outdoor_probability(day(2026, 7, 20))  # 周一
    assert f2["weather"] == 0.4
    assert f2["holiday"] == 1.0
    assert 0.0 <= eff2 < 0.5  # 0.5*1.496*0.4 约为 0.299

    # 周末 → 1.2 加成
    sim3 = WorldSimulation(
        config={"outdoor_probability": 0.5, "outdoor_personality_factor": 1.496}
    )
    sim3.set_reality({"weather": {"desc": ""}})
    eff3, f3 = sim3._effective_outdoor_probability(day(2026, 7, 18))  # 周六
    assert f3["holiday"] == 1.2


def test_event_bonus_place_used_when_snowing():
    """下雪天自动出门地点优先来自雪景池。"""
    from core.world_simulation import WorldSimulation

    t = datetime(2026, 1, 5, 12, 0, tzinfo=LOCAL)
    sim = WorldSimulation(
        config={"outdoor_probability": 1.0, "outdoor_personality_factor": 1.496},
        clock=lambda: t,
    )
    sim.set_reality({"weather": {"desc": "小雪"}})
    # bonus roll 70% 落到雪景池；跑多次确认大概率雪景描述
    snow_hits = sum(
        "雪" in sim._pick_outdoor_place(t + timedelta(days=i))
        for i in range(30)
    )
    assert snow_hits >= 15  # 至少一半以上命中雪景


def test_holiday_module_flags():
    """内置公历节假日判定：节日/周末/平日区分与再见日场景。"""
    from datetime import date
    from core.holidays import holiday_name, is_holiday, is_weekend, event_factor

    assert holiday_name(date(2026, 1, 1)) == "元旦"
    assert is_holiday(date(2026, 5, 1))
    assert holiday_name(date(2026, 10, 1)) == "国庆"
    assert is_holiday(date(2026, 2, 14))  # 情人节
    assert is_weekend(date(2026, 7, 18))  # 周六
    assert not is_holiday(date(2026, 7, 20))  # 周一平日
    assert event_factor(date(2026, 10, 1)) == 1.6
    assert event_factor(date(2026, 7, 18)) == 1.2
    assert event_factor(date(2026, 7, 20)) == 1.0


# ── 出门/回家指令（companion 层）────────────────────────
def test_companion_outdoor_command_goes_out_and_home():
    from core.companion import Companion

    class _WorldWorld:
        def go_out(self, place="", duration_min=0, source="manual"):
            return {"accepted": True, "place": place or "公园", "duration_min": 30}

        def go_home(self, reason="manual"):
            return {"accepted": True}

    class _WorldPort:
        world = _WorldWorld()

        def tick(self):  # noqa: D401
            return None

    comp = Companion.__new__(Companion)
    comp.world_port = _WorldPort()
    comp._world_snapshot_for_context = lambda: {"outdoor": False}  # type: ignore[method-assign]

    out = comp._apply_outdoor_command("走，出门逛逛")
    assert out is not None and out["moved"] is True and out["outdoor"] is True

    comp._world_snapshot_for_context = lambda: {"outdoor": True}  # type: ignore[method-assign]
    home = comp._apply_outdoor_command("回家")
    assert home is not None and home["outdoor"] is False

    # 无关指令 → None
    comp._world_snapshot_for_context = lambda: {"outdoor": False}  # type: ignore[method-assign]
    assert comp._apply_outdoor_command("今天天气不错") is None

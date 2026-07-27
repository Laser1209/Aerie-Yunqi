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


# ── WorldSnapshot 字段齐全 ──────────────────────────
def test_world_snapshot_has_all_fields():
    from core.world_simulation import WorldSimulation, WorldSnapshot

    sim = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc))
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

    t = datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc)
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

    fixed = datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc)
    sim = WorldSimulation(clock=lambda: fixed)
    s1 = sim.tick()
    s2 = sim.tick()
    assert s1.instance_id == s2.instance_id
    assert s1.phase == s2.phase


# ── phase 小时映射 ──────────────────────────────────
@pytest.mark.parametrize(
    "hour,expected",
    [
        (7, "morning"),
        (11, "morning"),
        (12, "noon"),
        (13, "noon"),
        (15, "afternoon"),
        (18, "afternoon"),
        (19, "evening"),
        (22, "evening"),
        (23, "night"),
        (2, "night"),
        (5, "night"),
        (6, "morning"),
    ],
)
def test_phase_mapping_by_hour(hour, expected):
    from core.world_simulation import WorldSimulation

    sim = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, hour, 0, tzinfo=timezone.utc)
    )
    snap = sim.tick()
    assert snap.phase == expected, f"hour={hour} -> {snap.phase}, want {expected}"


# ── energy 随时间衰减/恢复 ──────────────────────────
def test_energy_decays_and_recovers():
    """Night(morning 前) 应处于低能量恢复期, 上午高能量, 下午开始衰减."""
    from core.world_simulation import WorldSimulation

    def sim_at(hour: int):
        s = WorldSimulation(
            clock=lambda h=hour: datetime(2026, 7, 28, h, 0, tzinfo=timezone.utc)
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
        clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    ).tick()
    assert home.location == "home"
    assert len(home.nearby_objects) > 0
    assert any(isinstance(o, str) for o in home.nearby_objects)

    # 下午在 study working -> 书房物件
    study = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)
    ).tick()
    assert study.location == "study"
    assert len(study.nearby_objects) > 0
    # 两个地点物件集合应不同
    assert set(home.nearby_objects) != set(study.nearby_objects)


# ── available_visual_topics 基于 activity + objects ─
def test_visual_topics_derive_from_activity_and_objects():
    from core.world_simulation import WorldSimulation

    snap = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
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
        clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    ).tick()
    evening = WorldSimulation(
        clock=lambda: datetime(2026, 7, 28, 21, 0, tzinfo=timezone.utc)
    ).tick()
    # planning vs relaxing 话题应有差异
    assert set(morning.available_visual_topics) != set(evening.available_visual_topics)

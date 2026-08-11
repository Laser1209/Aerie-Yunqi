"""Integration tests for 房间空间定位（WorldSimulation zone 字段 + companion 生图上下文）.

覆盖:
  - WorldSnapshot 新增 floor/zone/position_desc 字段
  - tick() 按时段映射 zone（morning->living / noon->dining / afternoon->studio / night->master_bedroom）
  - nearby_objects 使用 zone 对应 OBJ-xxx 物件
  - to_dict / restore 序列化往返保留 zone
  - companion._HER_HOME_OBJECTS_ZH 合并新房间 OBJ-xxx 翻译
  - companion._image_world_context 包含 floor/zone/position_desc
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# 世界模拟统一使用本地时区（北京时间 UTC+08:00）。
LOCAL = timezone(timedelta(hours=8))


def _sim_at(hour: int, minute: int = 0):
    from core.world_simulation import WorldSimulation

    return WorldSimulation(
        clock=lambda: datetime(2026, 8, 12, hour, minute, tzinfo=LOCAL)
    ).tick()


# ── WorldSnapshot 新增定位字段 ────────────────────────
def test_world_snapshot_has_floor_zone_fields():
    from core.world_simulation import WorldSimulation

    sim = WorldSimulation(
        clock=lambda: datetime(2026, 8, 12, 9, 0, tzinfo=LOCAL)
    )
    snap = sim.tick()
    assert hasattr(snap, "floor")
    assert hasattr(snap, "zone")
    assert hasattr(snap, "position_desc")


# ── tick() 时段 -> zone 映射 ──────────────────────────
def test_morning_zone_is_living():
    snap = _sim_at(9)
    assert snap.zone == "living"
    assert snap.floor == 1
    assert snap.position_desc == "一层·客厅"


def test_afternoon_zone_is_studio():
    snap = _sim_at(15)
    assert snap.zone == "studio"
    assert snap.floor == 2
    assert snap.position_desc == "二层·工作室"


def test_night_zone_is_master_bedroom():
    snap = _sim_at(23, 30)
    assert snap.zone == "master_bedroom"
    assert snap.floor == 2


def test_noon_zone_is_dining():
    snap = _sim_at(12, 30)
    assert snap.zone == "dining"


def test_nearby_objects_use_zone_objects():
    snap = _sim_at(9)  # morning -> living
    assert "OBJ-040" in snap.nearby_objects  # 灰色模块沙发
    assert "OBJ-042" in snap.nearby_objects  # 钓鱼落地灯


# ── 序列化 / 恢复 ─────────────────────────────────────
def test_floor_zone_serialize_in_to_dict():
    snap = _sim_at(9)
    data = snap.to_dict()
    assert data["floor"] == 1
    assert data["zone"] == "living"


def test_restore_roundtrip_preserves_zone():
    from core.world_simulation import WorldSimulation

    snap = _sim_at(9)
    restored = WorldSimulation().restore(snap.to_dict())
    assert restored["zone"] == "living"
    assert restored["floor"] == 1
    assert restored["position_desc"] == "一层·客厅"


# ── companion 生图上下文接入 ───────────────────────────
def test_companion_object_zh_merged():
    from core.companion import _HER_HOME_OBJECTS_ZH

    assert "OBJ-045" in _HER_HOME_OBJECTS_ZH
    assert _HER_HOME_OBJECTS_ZH["OBJ-045"] == "你送的挂件"
    assert "king_bed" in _HER_HOME_OBJECTS_ZH  # 旧英文 id 兼容


def test_image_world_context_has_position_keys():
    from core.companion import Companion

    # 裸实例：跳过 __init__ 的重活，仅测 _image_world_context 同步方法。
    companion = Companion.__new__(Companion)
    companion._world_snapshot_for_context = lambda: {
        "phase": "afternoon",
        "floor": 2,
        "zone": "studio",
        "position_desc": "二层·工作室",
        "nearby_objects": ["OBJ-053"],
        "iso_time": "2026-08-12T15:00:00+08:00",
    }
    ctx = companion._image_world_context({})
    assert isinstance(ctx, dict)
    assert ctx.get("floor") == 2
    assert ctx.get("zone") == "studio"
    assert ctx.get("position_desc") == "二层·工作室"

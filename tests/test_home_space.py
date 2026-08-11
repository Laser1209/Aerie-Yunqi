"""TDD tests for 伊塔 132㎡ 江景复式空间数据模型 (core/home_space.py).

覆盖:
  - find_zone 楼层坐标 -> zone 判定（命中 / 未命中 / 非法输入安全兜底）
  - position_desc 中文位置描述（"二层·工作室"）
  - PHASE_ZONE / zone_for_phase 时段 -> zone 映射
  - objects_for_zone / object_zh / describe_objects 物件查询
  - ZONES / OBJECT_ZH / LEGACY_OBJECT_ZH 数据完整性
"""

from __future__ import annotations

# ── 位置判定 ──────────────────────────────────────────
def test_find_zone_kitchen():
    from core.home_space import find_zone

    # kitchen bounds x:[2.4,6.8] y:[0,2.2]
    assert find_zone(1, 4, 1) == "kitchen"


def test_find_zone_living():
    from core.home_space import find_zone

    # living bounds x:[1.2,10.0] y:[4.4,9.0]
    assert find_zone(1, 5, 6) == "living"


def test_find_zone_studio():
    from core.home_space import find_zone

    # studio bounds x:[1.2,7.2] y:[0,5.2]
    assert find_zone(2, 3, 2) == "studio"


def test_find_zone_master_bedroom():
    from core.home_space import find_zone

    # master_bedroom bounds x:[7.2,11.2] y:[6.8,9.0]
    assert find_zone(2, 9, 8) == "master_bedroom"


def test_find_zone_unknown_when_outside():
    from core.home_space import find_zone

    # 楼层 9 不存在
    assert find_zone(9, 9, 9) == "unknown"


def test_find_zone_invalid_input():
    from core.home_space import find_zone

    # 非法坐标安全返回 unknown，不抛异常
    assert find_zone(None, "abc", None) == "unknown"


# ── 位置描述 ──────────────────────────────────────────
def test_position_desc_level2_studio():
    from core.home_space import position_desc

    assert position_desc(2, "studio") == "二层·工作室"


def test_position_desc_level1_living():
    from core.home_space import position_desc

    assert position_desc(1, "living") == "一层·客厅"


def test_position_desc_unknown_zone():
    from core.home_space import position_desc

    # zone 未知时不崩，楼层仍正常输出
    assert "一层" in position_desc(1, "nope")


# ── phase -> zone 映射 ────────────────────────────────
def test_zone_for_phase_mapping():
    from core.home_space import zone_for_phase

    assert zone_for_phase("night") == "master_bedroom"
    assert zone_for_phase("morning") == "living"
    assert zone_for_phase("noon") == "dining"
    assert zone_for_phase("afternoon") == "studio"
    assert zone_for_phase("evening") == "living"


def test_zone_for_phase_unknown():
    from core.home_space import zone_for_phase

    assert zone_for_phase("") == "unknown"


# ── 物件查询 ──────────────────────────────────────────
def test_objects_for_zone_limit():
    from core.home_space import objects_for_zone

    # 默认 limit=6，living 有 8 个物件 -> 默认截断到 6
    assert len(objects_for_zone("living")) == 6
    # 明确传 limit=10 -> 返回全部 8 个，且都是 OBJ- 前缀
    objs = objects_for_zone("living", limit=10)
    assert len(objs) == 8
    assert all(o.startswith("OBJ-") for o in objs)
    # 未知 zone 返回空列表
    assert objects_for_zone("nope") == []


def test_object_zh_known_and_unknown():
    from core.home_space import object_zh

    assert object_zh("OBJ-045") == "你送的挂件"
    # 未知 id 原样返回
    assert object_zh("not_exist") == "not_exist"


def test_describe_objects():
    from core.home_space import describe_objects

    assert describe_objects(["OBJ-040", "OBJ-042"]) == "灰色模块沙发、钓鱼落地灯"


# ── 数据完整性 ────────────────────────────────────────
def test_all_zones_have_level_and_objects():
    from core.home_space import ZONES

    assert len(ZONES) == 13
    for zone_id, zone in ZONES.items():
        assert zone["level"] in (1, 2), f"{zone_id}: level 非法"
        assert zone["name"], f"{zone_id}: name 为空"
        assert zone["objects"], f"{zone_id}: objects 为空"


def test_object_zh_has_75_entries():
    from core.home_space import OBJECT_ZH

    assert len(OBJECT_ZH) >= 75


def test_legacy_english_ids_translated():
    from core.home_space import LEGACY_OBJECT_ZH

    assert "king_bed" in LEGACY_OBJECT_ZH

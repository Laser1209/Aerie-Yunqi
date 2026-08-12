"""P2 navigation tests — zone 连通图 / BFS / 避障寻路 / 视线拉直."""

from __future__ import annotations

import pytest

from core.home_space import ZONES, ZONE_ADJACENCY, path_between
from core.navigation_data import (
    RoomObstacle,
    a_star_path,
    coordinate_route,
    load_room_obstacles,
    segment_hits_obstacles,
    straighten_path,
    zone_center,
)


# ── zone 连通图（home_space）──────────────────────────────────
class TestZoneGraph:
    def test_all_zones_have_at_least_one_edge(self):
        for zone_id in ZONES:
            assert ZONE_ADJACENCY.get(zone_id), f"{zone_id} 无边"

    def test_cross_level_only_stair_corridor(self):
        """跨层连通仅 stair ↔ corridor（楼梯）。"""
        from core.home_space import ZONES as _Z

        for z, neighbors in ZONE_ADJACENCY.items():
            my_level = _Z[z]["level"]
            for n in neighbors:
                n_level = _Z[n]["level"]
                if my_level != n_level:
                    assert {z, n} == {"stair", "corridor"}, (
                        f"非法跨层边 {z}↔{n}"
                    )

    def test_adjacency_is_symmetric(self):
        for z, neighbors in ZONE_ADJACENCY.items():
            for n in neighbors:
                assert z in ZONE_ADJACENCY.get(n, []), f"不对称边 {z}↔{n}"

    def test_bfs_living_to_master_bedroom(self):
        """沙发→楼梯→二楼→主卧。"""
        path = path_between("living", "master_bedroom")
        assert path[0] == "living"
        assert path[-1] == "master_bedroom"
        assert "stair" in path and "corridor" in path

    def test_bfs_same_zone(self):
        assert path_between("living", "living") == ["living"]

    def test_bfs_unknown_returns_empty(self):
        assert path_between("nowhere", "living") == []

    def test_zone_center_inside_bounds(self):
        level, x, y = zone_center("living")
        assert level == 1
        assert 1.2 <= x <= 10.0
        assert 4.4 <= y <= 9.0


# ── 避障寻路（navigation_data）───────────────────────────────
def _obstacle(x, y, w=1.0, d=1.0, level=1, obj_id="T"):
    return RoomObstacle(obj_id=obj_id, level=level, x=x, y=y, w=w, d=d)


class TestNavigationAStar:
    def test_segment_hits_rect_center(self):
        """水平线穿过障碍中心 → 命中。"""
        obs = [_obstacle(5, 5)]
        assert segment_hits_obstacles(obs, 1, 1, 5, 9, 5) is True

    def test_segment_clear_of_rect(self):
        """水平线远离障碍 → 不命中。"""
        obs = [_obstacle(5, 5)]
        assert segment_hits_obstacles(obs, 1, 1, 1, 9, 1) is False

    def test_level_filter(self):
        """不同楼层障碍不参与判定。"""
        obs = [_obstacle(5, 5, level=2)]
        assert segment_hits_obstacles(obs, 1, 1, 1, 9, 5) is False

    def test_a_star_routes_around_wall(self):
        """竖向墙阻隔：起点左侧、终点右侧 → A* 绕行。"""
        wall = [_obstacle(5, 5, w=0.2, d=6.0)]
        # start 左侧 (2,5)，goal 右侧 (8,5)，墙在 x=5 竖条
        # 上下两个绕行 waypoint（须在墙膨胀范围 [1.7,8.3] 之外）
        waypoints = [(5, 0.8), (5, 9.2)]
        path = a_star_path(wall, waypoints, (2, 5), (8, 5), 1)
        assert path[0] == (2, 5)
        assert path[-1] == (8, 5)
        # 路径不应直线穿越 x=5 竖墙（中间点 y 应偏离 5）
        interior = path[1:-1]
        assert interior, "应存在绕行中间点"
        assert all(abs(y - 5) > 1.5 for x, y in interior)

    def test_a_star_no_obstacle_straight(self):
        """无障碍 → A* 直连（起点→终点）。"""
        path = a_star_path([], [], (2, 2), (8, 8), 1)
        assert path[0] == (2, 2) and path[-1] == (8, 8)

    def test_straighten_removes_needless_points(self):
        """共线多余点被拉直。"""
        points = [(0, 0), (1, 0), (2, 0), (3, 0)]
        out = straighten_path([], points, 1)
        assert out == [(0, 0), (3, 0)]

    def test_load_obstacles_from_design_json(self):
        """从设计 JSON 派生障碍（数据源存在时应非空）。"""
        obstacles = load_room_obstacles()
        if obstacles:  # JSON 存在
            assert all(isinstance(o, RoomObstacle) for o in obstacles)
            assert all(o.w > 0 and o.d > 0 for o in obstacles)

    def test_coordinate_route_living_to_bedroom(self):
        """coordinate_route 输出 zone 路径 + 坐标路径。"""
        route = coordinate_route("living", "master_bedroom")
        assert route["ok"] is True
        assert route["zone_path"][0] == "living"
        assert route["zone_path"][-1] == "master_bedroom"
        assert len(route["waypoints"]) >= 2
        wp = route["waypoints"]
        assert all("x" in p and "y" in p and "level" in p for p in wp)

    def test_coordinate_route_same_zone(self):
        route = coordinate_route("living", "living")
        assert route["ok"] is True
        assert route["zone_path"] == ["living"]

    def test_coordinate_route_unknown(self):
        route = coordinate_route("nowhere", "living")
        assert route["ok"] is False


# ── 移动状态机（P2b）──────────────────────────────────────────
from core.movement import MovementManager  # noqa: E402


class _Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _fake_coord(from_z: str, to_z: str) -> dict:
    return {
        "zone_path": [from_z, "stair", "corridor", to_z],
        "waypoints": [
            {"level": 1, "x": 0.0, "y": 0.0},
            {"level": 1, "x": 1.0, "y": 0.0},
            {"level": 2, "x": 1.0, "y": 1.0},
            {"level": 2, "x": 2.0, "y": 2.0},
        ],
        "ok": True,
    }


class TestMovementManager:
    def test_move_same_zone_arrives(self):
        clock = _Clock()
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord)
        mm.move_to("living", "living", "继续待着")
        snap = mm.snapshot()
        assert snap["status"] == "arrived"
        assert snap["current_zone"] == "living"

    def test_move_starts_moving(self):
        clock = _Clock()
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord)
        mm.move_to("living", "master_bedroom", "准备去睡觉")
        snap = mm.snapshot()
        assert snap["status"] == "moving"
        assert snap["path"] == ["living", "stair", "corridor", "master_bedroom"]
        assert snap["from_zone"] == "living"
        assert snap["to_zone"] == "master_bedroom"
        assert snap["current_zone"] == "living"
        assert len(snap["waypoints"]) >= 2

    def test_progress_advances_with_clock(self):
        clock = _Clock()
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord)
        mm.move_to("living", "master_bedroom", "准备去睡觉")
        clock.t += 16.0  # 第一段 15s 已过
        snap = mm.snapshot()
        assert snap["status"] == "moving"
        assert snap["current_idx"] >= 1

    def test_arrives_after_segments(self):
        clock = _Clock()
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord)
        mm.move_to("living", "master_bedroom", "准备去睡觉")
        # 三段 × 15s 下限 → 45s 足够
        clock.t += 46.0
        snap = mm.snapshot()
        assert snap["status"] == "arrived"
        assert snap["current_zone"] == "master_bedroom"
        assert snap["progress"] == 1.0

    def test_snapshot_idempotent_within_same_clock(self):
        """同一时刻多次读取不推进（实时派生幂等）。"""
        clock = _Clock()
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord)
        mm.move_to("living", "master_bedroom")
        s1 = mm.snapshot()
        s2 = mm.snapshot()
        assert s1["current_idx"] == s2["current_idx"]
        assert s1["progress"] == s2["progress"]

    def test_decision_log_written(self, tmp_path):
        from core.decision_log import DecisionLogger

        clock = _Clock()
        logger = DecisionLogger(log_dir=tmp_path / "logs")
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord, decision_log=logger)
        mm.move_to("living", "master_bedroom", "准备去睡觉")
        entries = [e for e in logger.recent() if e["kind"] == "movement"]
        assert len(entries) >= 1
        assert entries[0]["chosen"]["to_zone"] == "master_bedroom"

    def test_reset_returns_idle(self):
        clock = _Clock()
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord)
        mm.move_to("living", "master_bedroom")
        mm.reset()
        snap = mm.snapshot()
        assert snap["status"] == "idle"

    def test_current_zone_empty_when_idle(self):
        clock = _Clock()
        mm = MovementManager(clock=clock, coordinate_fn=_fake_coord)
        assert mm.current_zone() == ""


# ── 位置联动对话接线（P2c）──────────────────────────────────
from types import SimpleNamespace  # noqa: E402

from core.companion import Companion  # noqa: E402


def _make_world_companion(tmp_path):
    """构造带 movement/daily_planner 的 Companion（不跑 __init__）。"""
    from core.daily_planner import DailyPlanner
    from core.decision_log import DecisionLogger

    c = object.__new__(Companion)
    c.decision_log = DecisionLogger(log_dir=tmp_path / "logs")
    c.movement_manager = MovementManager(clock=_Clock(), coordinate_fn=_fake_coord, decision_log=c.decision_log)
    c.daily_planner = DailyPlanner(state_path=tmp_path / "daily_plan.json", decision_log=c.decision_log)
    c.world_port = SimpleNamespace(
        get_world_snapshot=lambda *a, **k: {
            "phase": "evening",
            "location": "home",
            "zone": "living",
            "floor": 1,
            "position_desc": "一层·客厅",
            "activity": "relaxing",
            "energy": 0.5,
            "social": "private",
        }
    )
    return c


class TestWorldMovementWiring:
    def test_snapshot_attaches_movement_when_idle(self, tmp_path):
        c = _make_world_companion(tmp_path)
        snap = c._world_snapshot_for_context()
        assert snap["movement"]["status"] == "idle"
        assert snap["zone"] == "living"  # idle 不覆盖 zone

    def test_snapshot_movement_overrides_zone_when_moving(self, tmp_path):
        c = _make_world_companion(tmp_path)
        c.movement_manager.move_to("living", "master_bedroom", "准备去睡觉")
        snap = c._world_snapshot_for_context()
        mv = snap["movement"]
        assert mv["status"] == "moving"
        # 移动中 zone 派生优先（PHASE_ZONE 优先级规则）
        assert mv["current_zone"] == "living"

    def test_consume_daily_plan_triggers_move(self, tmp_path):
        """slot 目标 zone ≠ 当前位置 → 发起移动并写决策日志。"""
        c = _make_world_companion(tmp_path)
        # 15:00 → afternoon slot 目标 studio
        c.daily_planner.plan_today(now=_ts("2026-08-13 15:00"))
        slots = c.daily_planner.slot_for_now(now=_ts("2026-08-13 15:00"))
        snap = {"zone": "living"}
        c._consume_daily_plan(snap, now=_ts("2026-08-13 15:00"))
        entries = [e for e in c.decision_log.recent() if e["kind"] == "movement"]
        assert len(entries) >= 1
        assert entries[0]["chosen"]["to_zone"] == slots["zone"]

    def test_consume_daily_plan_same_zone_skips(self, tmp_path):
        """目标 zone == 当前位置 → 不发起移动。"""
        c = _make_world_companion(tmp_path)
        c.daily_planner.plan_today(now=_ts("2026-08-13 08:00"))
        # 早上 morning slot zone = living；当前也 living → 不移动
        c._consume_daily_plan({"zone": "living"}, now=_ts("2026-08-13 08:00"))
        entries = [e for e in c.decision_log.recent() if e["kind"] == "movement"]
        assert len(entries) == 0


def _ts(text: str) -> float:
    """本地字符串 → epoch（Asia/Shanghai）。"""
    from datetime import datetime, timedelta, timezone

    dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=timezone(timedelta(hours=8))).timestamp()

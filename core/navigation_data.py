"""Aerie · navigation_data — 坐标级避障寻路（P2 寻路感知）.

从设计 JSON（ita_river_loft_room_data.json）派生大件障碍（AABB，膨胀
0.3m 人宽），配合 zone 中心点 + 门洞点构成 waypoint 图，A* 求绕障路径，
再做视线拉直（string pulling）平滑。全程纯函数、无随机。

- 障碍数据唯一真源 = JSON 米制坐标；SVG 仅呈现层，禁止反向。
- 数据缺失/非法时安全降级为空集（move 回退 zone 中心直连，不阻断）。
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.home_space import ZONES

# 默认设计 JSON（与 home_space 同一数据源）。
_DEFAULT_JSON = (
    Path(__file__).resolve().parent.parent
    / "ita-river-loft-room.design-project"
    / "assets"
    / "ita_river_loft_room_data.json"
)

# 障碍膨胀（人半宽，米）
EXPAND_M = 0.3

# 只把"可构成阻挡"的大件计入障碍（贴墙小件/悬挂件/灯具忽略）。
_OBSTACLE_CATEGORIES: frozenset[str] = frozenset(
    {
        "sofa", "table", "dining_table", "coffee_table", "kitchen_island",
        "bed", "closet", "cabinet", "bookshelf", "desk", "vanity",
        "bathtub", "storage", "island", "couch", "wardrobe", "sideboard",
    }
)


@dataclass(frozen=True)
class RoomObstacle:
    obj_id: str
    level: int
    x: float
    y: float
    w: float
    d: float

    @property
    def rect(self) -> tuple[float, float, float, float]:
        """膨胀后的 AABB（x0, y0, x1, y1）。"""
        return (
            self.x - self.w / 2 - EXPAND_M,
            self.y - self.d / 2 - EXPAND_M,
            self.x + self.w / 2 + EXPAND_M,
            self.y + self.d / 2 + EXPAND_M,
        )


# ── 障碍表派生 ───────────────────────────────────────────────
def load_room_obstacles(json_path: Optional[Path] = None, max_count: int = 24) -> list[RoomObstacle]:
    """从设计 JSON 派生大件障碍（含 category 过滤，<= max_count）。

    数据缺失/解析失败返回空列表（安全降级）。
    """
    path = Path(json_path) if json_path else _DEFAULT_JSON
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    objects = data.get("objects") or []
    obstacles: list[RoomObstacle] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        category = str(obj.get("category") or "")
        if category not in _OBSTACLE_CATEGORIES:
            continue
        try:
            obstacles.append(
                RoomObstacle(
                    obj_id=str(obj.get("id") or ""),
                    level=int(obj.get("level") or 0),
                    x=float(obj.get("x") or 0.0),
                    y=float(obj.get("y") or 0.0),
                    w=float(obj.get("w") or 0.0),
                    d=float(obj.get("d") or 0.0),
                )
            )
        except (TypeError, ValueError):
            continue
        if len(obstacles) >= max_count:
            break
    return obstacles


def load_doorways(json_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """从设计 JSON 派生门洞中心点（供 waypoint 连接）。"""
    path = Path(json_path) if json_path else _DEFAULT_JSON
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    doors: list[dict[str, Any]] = []
    for d in data.get("openings") or []:
        if not isinstance(d, dict):
            continue
        pos = d.get("position") or {}
        doors.append(
            {
                "id": str(d.get("id") or ""),
                "level": int(d.get("level") or 0),
                "x": float(pos.get("x") or 0.0),
                "y": float(pos.get("y") or 0.0),
            }
        )
    return doors


# ── 几何工具（纯函数）────────────────────────────────────────
def _rect_hits_segment(
    rect: tuple[float, float, float, float],
    x1: float, y1: float, x2: float, y2: float,
) -> bool:
    """Liang-Barsky：线段与 AABB 是否相交。"""
    rx0, ry0, rx1, ry1 = rect
    dx = x2 - x1
    dy = y2 - y1
    p = [-dx, dx, -dy, dy]
    q = [x1 - rx0, rx1 - x1, y1 - ry0, ry1 - y1]
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-9:
            if qi < 0:
                return False  # 平行于该轴且位于窗外 → 完全不相交
        else:
            r = qi / pi
            if pi < 0:
                if r > u2:
                    return False
                if r > u1:
                    u1 = r
            else:
                if r < u1:
                    return False
                if r < u2:
                    u2 = r
    return True


def segment_hits_obstacles(obstacles: list[RoomObstacle], level: int, x1: float, y1: float, x2: float, y2: float) -> bool:
    """线段是否穿过指定楼层的任一障碍矩形。"""
    for ob in obstacles:
        if ob.level != level:
            continue
        if _rect_hits_segment(ob.rect, x1, y1, x2, y2):
            return True
    return False


# ── zone 中心 waypoint ───────────────────────────────────────
def zone_center(zone_id: str) -> tuple[int, float, float]:
    """zone 中心点：(level, x, y)。未知返回 (0, 0, 0)。"""
    zone = ZONES.get(str(zone_id or ""))
    if not zone:
        return (0, 0.0, 0.0)
    try:
        bx = zone.get("bounds", {}).get("x", [0, 0])
        by = zone.get("bounds", {}).get("y", [0, 0])
        cx = (float(bx[0]) + float(bx[1])) / 2.0
        cy = (float(by[0]) + float(by[1])) / 2.0
        return (int(zone.get("level") or 0), cx, cy)
    except (TypeError, ValueError, IndexError):
        return (0, 0.0, 0.0)


# ── A* 寻路（waypoint 图）───────────────────────────────────
def a_star_path(
    obstacles: list[RoomObstacle],
    waypoints: list[tuple[float, float]],
    start: tuple[float, float],
    goal: tuple[float, float],
    level: int,
) -> list[tuple[float, float]]:
    """在 waypoint 图上 A*：起点 → 终点（互可见建边 + 欧氏启发）。

    返回坐标点序列（含起终点）；无路时返回 [start, goal]（直连兜底）。
    """
    nodes = [start, goal] + waypoints
    n = len(nodes)

    def dist(i: int, j: int) -> float:
        return math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1])

    def visible(i: int, j: int) -> bool:
        x1, y1 = nodes[i]
        x2, y2 = nodes[j]
        return not segment_hits_obstacles(obstacles, level, x1, y1, x2, y2)

    # 启发
    def h(i: int) -> float:
        return dist(i, 1)  # goal 是 nodes[1]

    open_heap: list[tuple[float, int]] = [(0.0, 0)]
    came: dict[int, int] = {}
    g_score: dict[int, float] = {0: 0.0}
    closed: set[int] = set()
    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        if cur == 1:
            # 回溯
            path = [nodes[1]]
            node = 1
            while node != 0:
                node = came[node]
                path.append(nodes[node])
            path.reverse()
            return path
        closed.add(cur)
        for j in range(n):
            if j == cur or j in closed:
                continue
            if not visible(cur, j):
                continue
            tentative = g_score[cur] + dist(cur, j)
            if tentative < g_score.get(j, float("inf")):
                came[j] = cur
                g_score[j] = tentative
                heapq.heappush(open_heap, (tentative + h(j), j))
    return [start, goal]


def straighten_path(
    obstacles: list[RoomObstacle],
    points: list[tuple[float, float]],
    level: int,
) -> list[tuple[float, float]]:
    """视线拉直（string pulling）：跳过被障碍阻挡的中间点。"""
    if len(points) <= 2:
        return points
    result = [points[0]]
    i = 0
    while i < len(points) - 1:
        j = len(points) - 1
        while j > i:
            x1, y1 = result[-1]
            x2, y2 = points[j]
            if not segment_hits_obstacles(obstacles, level, x1, y1, x2, y2):
                break
            j -= 1
        result.append(points[j])
        i = j
    return result


# ── 高层：zone 间坐标路线 ───────────────────────────────────
def coordinate_route(from_zone: str, to_zone: str) -> dict[str, Any]:
    """zone 间完整路线（叙事层 zone 路径 + 呈现层坐标路径）。

    返回 {"zone_path": [...], "waypoints": [{level,x,y}, ...], "ok": bool}。
    坐标路径 = zone 中心点序列 + 拉直（绕大件）；无 A* 数据时直连中心。
    """
    from core.home_space import path_between

    zone_path = path_between(from_zone, to_zone)
    if not zone_path:
        return {"zone_path": [], "waypoints": [], "ok": False}
    obstacles = load_room_obstacles()
    # zone 中心点序列（跨层时按 zone 的 level 标注）
    centers: list[tuple[int, float, float]] = [zone_center(z) for z in zone_path]
    level = centers[0][0] if centers else 1
    points: list[tuple[float, float]] = [(x, y) for _, x, y in centers]
    raw = a_star_path(obstacles, points[1:-1], points[0], points[-1], level)
    refined = straighten_path(obstacles, raw, level)
    waypoints = [{"level": level, "x": float(x), "y": float(y)} for x, y in refined]
    return {"zone_path": zone_path, "waypoints": waypoints, "ok": True}

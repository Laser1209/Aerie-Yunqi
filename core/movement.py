"""Aerie · movement — 移动状态机（P2 寻路感知）.

位置沿路径逐点行进（非瞬移）：zone BFS 定序（叙事层）+ 坐标级
waypoint（呈现层，含避障）。移动是**依赖 moved_at 的时序状态**，
每次读取时按注入 clock() 实时派生 progress —— 不进确定性快照缓存，
避免破坏 tick 幂等与 restore 白名单。

- 移动触发：move_to(from, to, reason)，发起时一次性算好 path+waypoints；
- 段时长 = clamp(段距/1.5m/s, 15s, 120s)（可观测性优先，1.5 为叙事速度）；
- 决策埋点 3：移动目标候选 + 选择写入决策日志；
- 全程注入 clock()，禁止 datetime.now()；重启即复位（restore 不补时序）。
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from core.navigation_data import coordinate_route

logger = logging.getLogger(__name__)

# 段时长参数（秒）
_SEGMENT_SPEED_MPS = 1.5
_SEGMENT_MIN_SEC = 15.0
_SEGMENT_MAX_SEC = 120.0


@dataclass
class Movement:
    """移动时序状态（restore 时重置为 idle，重启即复位）。"""

    status: str = "idle"  # idle | moving | arrived
    from_zone: str = ""
    to_zone: str = ""
    path: list[str] = field(default_factory=list)  # zone 序列（叙事层）
    waypoints: list[dict] = field(default_factory=list)  # [{level,x,y}]（呈现层）
    current_idx: int = 0
    progress: float = 0.0
    moved_at: float = 0.0
    reason: str = ""


class MovementManager:
    """移动状态机（读取时实时派生；注入 clock 保证可测确定性）。"""

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], float]] = None,
        decision_log: Any = None,
        coordinate_fn: Optional[Callable[[str, str], dict]] = None,
    ) -> None:
        self._clock = clock or _time_now
        self._decision_log = decision_log
        self._coordinate_fn = coordinate_fn or coordinate_route
        self._movement: Optional[Movement] = None

    # ── 触发 ───────────────────────────────────────────────

    def move_to(self, from_zone: str, to_zone: str, reason: str = "") -> Movement:
        """发起一次移动（同 zone 直接 arrived）。"""
        from_zone = str(from_zone or "")
        to_zone = str(to_zone or "")
        now = self._clock()
        if not from_zone or not to_zone or from_zone == to_zone:
            self._movement = Movement(
                status="arrived",
                from_zone=from_zone,
                to_zone=to_zone or from_zone,
                path=[to_zone or from_zone],
                current_idx=0,
                progress=1.0,
                moved_at=now,
                reason=reason,
            )
            return self._movement

        route: dict[str, Any] = {}
        try:
            route = self._coordinate_fn(from_zone, to_zone)
        except Exception:
            logger.debug("movement coordinate route failed", exc_info=True)
        path = [str(x) for x in (route.get("zone_path") or [])]
        waypoints = route.get("waypoints") or []
        if not path:
            path = [from_zone, to_zone]
        if not waypoints:
            waypoints = [{"level": 1, "x": 0.0, "y": 0.0}]
        self._movement = Movement(
            status="moving",
            from_zone=from_zone,
            to_zone=to_zone,
            path=path,
            waypoints=waypoints,
            current_idx=0,
            progress=0.0,
            moved_at=now,
            reason=str(reason or ""),
        )
        # 决策埋点 3：移动目标候选 + 选择。
        if self._decision_log is not None:
            try:
                self._decision_log.append(
                    kind="movement",
                    candidates=[
                        {"id": z, "topic": z, "score": 0.0} for z in path
                    ],
                    chosen={"to_zone": to_zone, "reason": self._movement.reason},
                    reason=f"from={from_zone}",
                )
            except Exception:
                logger.debug("movement decision log append failed", exc_info=True)
        return self._movement

    def arrive(self) -> None:
        """手动标记已到达（set_activity 覆盖场景）。"""
        if self._movement is not None:
            self._movement.status = "arrived"
            self._movement.progress = 1.0

    # ── 读取（实时派生）────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """当前位置派生快照（读取时推进，不进确定性缓存）。"""
        m = self._movement
        if m is None:
            return self._idle_snapshot()
        now = self._clock()
        if m.status == "moving":
            self._advance(m, now)
        if m.status == "arrived":
            current = m.to_zone if m.path else ""
            return {
                "status": "arrived",
                "from_zone": m.from_zone,
                "to_zone": m.to_zone,
                "path": list(m.path),
                "waypoints": m.waypoints,
                "current_zone": current or (m.path[-1] if m.path else ""),
                "current_idx": m.current_idx,
                "progress": 1.0,
                "reason": m.reason,
            }
        current_zone = m.path[m.current_idx] if m.path else m.to_zone
        return {
            "status": "moving",
            "from_zone": m.from_zone,
            "to_zone": m.to_zone,
            "path": list(m.path),
            "waypoints": m.waypoints,
            "current_zone": current_zone,
            "current_idx": m.current_idx,
            "progress": round(m.progress, 4),
            "reason": m.reason,
        }

    def current_zone(self) -> str:
        """当前所在 zone（供 PHASE_ZONE 优先级与 nearby_objects 派生）。"""
        if self._movement is None:
            return ""
        snap = self.snapshot()
        return str(snap.get("current_zone") or "")

    def reset(self) -> None:
        """重启即复位。"""
        self._movement = None

    # ── 内部 ───────────────────────────────────────────────

    def _advance(self, m: Movement, now: float) -> None:
        """按注入时钟推进进度；段完成后进入下一路径点，走到最后即 arrived。"""
        while m.current_idx < len(m.path) - 1:
            seg_sec = self._segment_duration(m)
            elapsed = now - m.moved_at
            if elapsed < seg_sec:
                m.progress = elapsed / seg_sec if seg_sec else 1.0
                return
            # 本段走完 → 下一路径点
            elapsed -= seg_sec
            m.current_idx += 1
            m.moved_at = now - elapsed
            m.progress = 0.0
        # current_idx == len(path) - 1 → 已到达终点
        m.progress = 1.0
        m.status = "arrived"

    def _segment_duration(self, m: Movement) -> float:
        """当前段时长 = clamp(段距/1.5, 15, 120)；waypoint 坐标不足时默认 20s。"""
        if len(m.waypoints) >= 2:
            idx = min(m.current_idx, len(m.waypoints) - 2)
            try:
                a = m.waypoints[idx]
                b = m.waypoints[idx + 1]
                dist = math.hypot(
                    float(a.get("x", 0)) - float(b.get("x", 0)),
                    float(a.get("y", 0)) - float(b.get("y", 0)),
                )
                return max(_SEGMENT_MIN_SEC, min(dist / _SEGMENT_SPEED_MPS, _SEGMENT_MAX_SEC))
            except (TypeError, ValueError):
                return _SEGMENT_MIN_SEC
        return _SEGMENT_MIN_SEC

    def _idle_snapshot(self) -> dict[str, Any]:
        return {
            "status": "idle",
            "from_zone": "",
            "to_zone": "",
            "path": [],
            "waypoints": [],
            "current_zone": "",
            "current_idx": 0,
            "progress": 0.0,
            "reason": "",
        }


def _time_now() -> float:
    import time

    return time.time()

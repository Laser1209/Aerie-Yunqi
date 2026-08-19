"""PulsePlanner — hourly rolling plan for proactive pushes.

Design (Proactive Push v2, §6.1–6.2):

- Runs once on each hour boundary; reads a state snapshot and computes how
  much the *next hour* should carry (0..N pushes), then writes the plan into
  PushPolicy.pending_plans. The next re-plan replaces the whole window, so
  the schedule stays rolling and adaptive.
- max_per_day becomes a SOFT budget (advisory); HARD_CAP in PushPolicy is
  the unconditional fuse.

Pure & deterministic: given the same snapshot, the same plan is produced
(the ``jitter`` knob is off by default for testability).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

# 决策权重（设计方案 §6.2）：所有 factor ∈ [0,1]
WEIGHTS: dict[str, float] = {
    "user_active": 0.30,   # 近 30 分钟在线/刚发过消息
    "window": 0.20,        # 当前在作息活跃窗口内
    "last_interaction": 0.15,  # 距最近一次交互越久（>6h）越高
    "mood_need": 0.20,     # PAD 需要度（P 低 / A 高 / 想念焦虑）
    "desire": 0.15,        # desire_engine 场景分（0~1）
}

DEFAULT_HOURLY_BASE = 0.75  # 基准：每小时约 0.75 条的计划基数


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


@dataclass
class PlannedPulse:
    """One planned push inside the next hour window."""

    at: datetime
    shape: str = "state_based"     # "anchor" | "state_based"
    scene: str | None = None       # anchor 场景名；state_based 为空/默认场景
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "shape": self.shape,
            "scene": self.scene,
            "payload": dict(self.payload),
        }


def compute_hour_coefficient(state: dict[str, Any]) -> dict[str, Any]:
    """Map a state snapshot onto an hour coefficient in [0, 1].

    State keys (all optional, missing factors default to 0/neutral):
        user_active: bool         近 30 分钟在线/刚发消息
        in_active_window: bool    当前时刻在作息活跃窗口内
        hours_since_last_interaction: float   距最近一次交互的小时数
        mood_need: float           PAD 派生需要度（0~1）
        desire: float              desire engine 场景分（0~1）

    Returns:
        {"coefficient": float, "factors": {...}, "weights": WEIGHTS}
    """
    factors: dict[str, float] = {}
    factors["user_active"] = 1.0 if state.get("user_active") else 0.0
    factors["window"] = 1.0 if state.get("in_active_window") else 0.0
    hours = float(state.get("hours_since_last_interaction") or 0.0)
    factors["last_interaction"] = _clamp01(hours / 12.0)
    factors["mood_need"] = _clamp01(float(state.get("mood_need") or 0.0))
    factors["desire"] = _clamp01(float(state.get("desire") or 0.0))
    coefficient = sum(WEIGHTS[k] * factors[k] for k in WEIGHTS)
    return {"coefficient": coefficient, "factors": factors, "weights": WEIGHTS}


def plan_count_for_hour(
    coefficient: float,
    hourly_base: float = DEFAULT_HOURLY_BASE,
) -> int:
    """下一个小时的计划条数（含缓冲）。"""
    return int(round(hourly_base * coefficient))


class PulsePlanner:
    """整点滚动自检：为下一小时生成 PlannedPulse 列表。"""

    def __init__(
        self,
        *,
        hourly_base: float = DEFAULT_HOURLY_BASE,
        now_provider: Callable[[], datetime] | None = None,
        default_scene: str = "idle_care",
    ) -> None:
        self.hourly_base = hourly_base
        self.now_provider = now_provider or datetime.now
        self.default_scene = default_scene

    def plan_next_hour(self, state: dict[str, Any]) -> list[PlannedPulse]:
        """Compute the next-hour plan (0..N pulses, sampling evenly).

        Args:
            state: snapshot from companion's state providers:
                - budget_remaining_today: int   hard / soft accounting
                - in_active_window: bool
                - user_active: bool
                - hours_since_last_interaction: float
                - mood_need: float
                - desire: float
                - is_quiet_now: bool           (bool; 静默时段 skip)

        Returns:
            Sorted plans; empty list when the hour should stay silent.
        """
        if state.get("is_quiet_now"):
            return []
        result = compute_hour_coefficient(state)
        count = plan_count_for_hour(result["coefficient"], self.hourly_base)
        budget = int(state.get("soft_remaining_today", count) or 0)
        count = max(0, min(count, max(budget, 0)))
        if count <= 0:
            return []
        plans: list[PlannedPulse] = []
        now = self.now_provider()
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        # 在下一小时内均匀分散 trigger（留 5 分钟头距，避免压点）
        slot_min = 60.0 / count
        for i in range(count):
            offset_min = int(5 + slot_min * (i + 0.5))
            pulse = now + timedelta(minutes=offset_min)
            plans.append(
                PlannedPulse(
                    at=pulse,
                    shape="state_based",
                    scene=self.default_scene,
                    payload={"trigger_shape": "state_based", "planned": True},
                )
            )
        plans.sort(key=lambda p: p.at)
        return plans
"""Aerie · daily_planner — 每日行为规划（P1 时序行为调度）.

跨天一次性生成当天全部行为 slot，供世界推进循环按当前时间消费；
行为多样性引擎 = 确定性规则（时段/zone/能量约束）+ 加权随机
（最近做过降权，同日不重复），并写入决策日志（伪主观性证据层）。

- 动机句按需生成：不为每个 slot 预生成（365×10 次/天 大多无人消费），
  主动消息 / 被问"你在干什么"时才由上层按需补动机句。
- 局部重规划：slot_for_now 在计划过期/缺失时惰性重选单点 slot，
  不改变已固化计划。
- 持久化：data/daily_plan.json，跨天覆盖写，原子写（tmp+replace）。
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from core.behavior_library import Behavior, behavior_pool
from core.paths import data_dir
from core.world_phase import DEFAULT_WORLD_PHASES, PHASE_ZONE

logger = logging.getLogger(__name__)

_LOCAL_TZ: timezone = timezone(timedelta(hours=8))


@dataclass
class DailyPlanner:
    """每日行为规划生成器（纯同步核心 + 决策日志可选注入）。"""

    state_path: Optional[Path] = None
    seed: int = 0
    decision_log: Any = None  # DecisionLogger 或 None

    _slots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _cached_date: str = ""

    def __post_init__(self) -> None:
        self._state_path = Path(self.state_path) if self.state_path else data_dir() / "daily_plan.json"

    # ── 对外入口 ───────────────────────────────────────

    def plan_today(self, now: Optional[float] = None) -> list[dict[str, Any]]:
        """跨天一次性生成当天计划；当天已有则直接返回（幂等）。"""
        now = float(now) if now is not None else _now()
        date_str = _local_date(now)
        if self._slots and self._cached_date == date_str:
            return self._slots
        self._slots = self._generate(now)
        self._cached_date = date_str
        self._save()
        return self._slots

    def slot_for_now(self, now: Optional[float] = None, zone_hint: Optional[str] = None) -> Optional[dict[str, Any]]:
        """返回覆盖当前时刻的 slot；计划缺失/过期时局部重规划单点。"""
        now = float(now) if now is not None else _now()
        date_str = _local_date(now)
        if self._cached_date != date_str or not self._slots:
            self.plan_today(now)
        for slot in self._slots:
            if slot["start"] <= now < slot["end"]:
                return slot
        # 无覆盖（计划空洞/极端情况）→ 惰性重选一个单点 slot
        return self._replan_one(now, zone_hint)

    def load_today(self) -> Optional[dict[str, Any]]:
        """读取持久化的当天计划（未生成返回 None）。"""
        if not self._state_path.exists():
            return None
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("daily plan could not be loaded", exc_info=True)
            return None

    # ── 生成 ───────────────────────────────────────────

    def _generate(self, now: float) -> list[dict[str, Any]]:
        rng = random.Random(f"{self.seed}:{_local_date(now)}")
        used: set[str] = set()
        slots: list[dict[str, Any]] = []
        for phase, pdata in DEFAULT_WORLD_PHASES.items():
            zone = PHASE_ZONE.get(phase, "living")
            start = _phase_ts(now, pdata.get("start", "00:00"))
            end = _phase_ts(now, pdata.get("end", "23:59"))
            if end <= start:  # 跨午夜 slot（如 night 23:30 → 次日 05:00）
                end += 86400.0
            pool = behavior_pool(zone)
            # 同日不重复：过滤已用行为，空了才放宽
            fresh = [b for b in pool if b.behavior_desc not in used] or list(pool)
            candidates = _sample_candidates(fresh, k=3, rng=rng)
            chosen = candidates[0]
            used.add(chosen.behavior_desc)
            slot = {
                "date": _local_date(now),
                "start": start,
                "end": end,
                "phase": phase,
                "zone": zone,
                "obj_id": chosen.obj_id,
                "behavior_desc": chosen.behavior_desc,
                "duration_min": chosen.duration_min,
                "visual_topic": chosen.visual_topic,
                "source": "planner",
            }
            slots.append(slot)
            self._log_decision(phase, candidates, chosen)
        return slots

    def _replan_one(self, now: float, zone_hint: Optional[str]) -> Optional[dict[str, Any]]:
        """局部重规划：惰性生成一个覆盖当前时刻的单点 slot。"""
        rng = random.Random(f"replan:{_local_date(now)}:{int(now)}")
        zone = zone_hint or "living"
        pool = behavior_pool(zone)
        candidates = _sample_candidates(pool, k=3, rng=rng)
        chosen = candidates[0]
        slot = {
            "date": _local_date(now),
            "start": now,
            "end": now + float(chosen.duration_min) * 60,
            "phase": "unknown",
            "zone": zone,
            "obj_id": chosen.obj_id,
            "behavior_desc": chosen.behavior_desc,
            "duration_min": chosen.duration_min,
            "visual_topic": chosen.visual_topic,
            "source": "replan",
        }
        self._log_decision("replan", candidates, chosen)
        return slot

    def _log_decision(self, phase: str, candidates: list[Behavior], chosen: Behavior) -> None:
        if self.decision_log is None:
            return
        try:
            self.decision_log.append(
                kind="behavior",
                candidates=[
                    {"id": b.obj_id, "topic": b.behavior_desc, "score": 0.0}
                    for b in candidates
                ],
                chosen={"id": chosen.obj_id, "topic": chosen.behavior_desc},
                reason=f"phase={phase}",
            )
        except Exception:
            logger.debug("behavior decision log append failed", exc_info=True)

    # ── 持久化 ─────────────────────────────────────────

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "date": self._cached_date,
                "slots": self._slots,
            }
            tmp = self._state_path.with_name(self._state_path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._state_path)
        except Exception:
            logger.warning("daily plan could not be saved", exc_info=True)


# ── 工具 ───────────────────────────────────────────────────────
def _now() -> float:
    return datetime.now(_LOCAL_TZ).timestamp()


def _local_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, _LOCAL_TZ).strftime("%Y-%m-%d")


def _phase_ts(day_ts: float, hhmm: str) -> float:
    """把"HH:MM"解析为与 day_ts 同一天的 epoch（跨午夜由调用方 +86400 处理）。"""
    day = datetime.fromtimestamp(day_ts, _LOCAL_TZ)
    try:
        h, m = (int(x) for x in str(hhmm).split(":"))
    except (TypeError, ValueError):
        h, m = 0, 0
    return day.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()


def _sample_candidates(pool: list[Behavior], k: int, rng: random.Random) -> list[Behavior]:
    """按权重（最近做过降权已在 used 过滤）随机取 k 个候选，首个为选中。"""
    if not pool:
        return []
    items = list(pool)
    rng.shuffle(items)
    return items[:k]

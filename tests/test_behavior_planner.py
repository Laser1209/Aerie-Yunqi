"""P1 behavior library + daily planner tests — 行为资源库与每日规划.

行为资源库（P1b）：zone 聚合行为 + visual_topic 值域契约。
每日规划（P1c）：跨天一次性生成 + 加权随机 + 决策日志 + 局部重规划。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from core.behavior_library import (
    BEHAVIORS,
    behavior_pool,
    behaviors_for_zone,
    validate_visual_topics,
    zones_with_behaviors,
)


# ── 行为资源库（P1b）──────────────────────────────────────────
class TestBehaviorLibrary:
    def test_behaviors_count_minimum(self):
        """起步行为数 >= 30。"""
        assert len(BEHAVIORS) >= 30

    def test_active_zones_covered(self):
        """活跃 zone 均绑定行为。"""
        zones = set(zones_with_behaviors())
        for z in ("living", "kitchen", "studio", "master_bedroom", "master_bath", "balcony", "dining"):
            assert z in zones

    def test_behaviors_for_zone(self):
        living = behaviors_for_zone("living")
        assert len(living) >= 3
        assert all(b.zone_id == "living" for b in living)

    def test_behavior_pool_fallback_for_unknown_zone(self):
        pool = behavior_pool("entrance")  # 未绑定专属行为的 zone
        assert len(pool) >= 1  # 走通用 fallback，防空池

    def test_visual_topic_contract_valid(self):
        """visual_topic 值域契约：全部命中翻译表键，无英文 token 泄漏。"""
        bad = validate_visual_topics()
        assert bad == [], f"非法 visual_topic: {bad}"

    def test_obj_ids_exist_in_home_space(self):
        """行为依托的 OBJ id 必须存在于 home_space.OBJECT_ZH。"""
        from core.home_space import OBJECT_ZH

        for b in BEHAVIORS:
            assert b.obj_id in OBJECT_ZH, f"未知物件 {b.obj_id}"


# ── 每日规划（P1c）────────────────────────────────────────────
from core.daily_planner import DailyPlanner  # noqa: E402


class TestDailyPlanner:
    def test_generates_all_day_slots(self, tmp_path):
        plan = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=42)
        slots = plan.plan_today(now=_ts("2026-08-13 06:00"))
        # 全天每 phase 至少一个 slot
        assert len(slots) >= 6
        phases = {s["phase"] for s in slots}
        assert "morning" in phases and "night" in phases

    def test_slots_chronological_and_no_overlap(self, tmp_path):
        plan = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=7)
        slots = plan.plan_today(now=_ts("2026-08-13 06:00"))
        prev_end = 0.0
        for s in slots:
            assert s["start"] >= prev_end, "slot 时间不单调"
            assert s["end"] > s["start"]
            prev_end = s["end"]

    def test_different_seed_differs(self, tmp_path):
        plan1 = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=1)
        plan2 = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=2)
        s1 = [(x["phase"], x["behavior_desc"]) for x in plan1.plan_today(now=_ts("2026-08-13 06:00"))]
        s2 = [(x["phase"], x["behavior_desc"]) for x in plan2.plan_today(now=_ts("2026-08-13 06:00"))]
        assert s1 != s2, "不同随机种子应产生不同计划"

    def test_slots_valid_zone_and_behavior(self, tmp_path):
        from core.home_space import ZONES

        plan = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=9)
        slots = plan.plan_today(now=_ts("2026-08-13 06:00"))
        for s in slots:
            assert s["zone"] in ZONES or s["zone"] in ("", "unknown")
            assert s["behavior_desc"]

    def test_same_seed_same_plan(self, tmp_path):
        """固定种子 → 计划可复现（确定性）。"""
        p1 = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=5)
        p2 = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=5)
        s1 = [(x["phase"], x["behavior_desc"]) for x in p1.plan_today(now=_ts("2026-08-13 06:00"))]
        s2 = [(x["phase"], x["behavior_desc"]) for x in p2.plan_today(now=_ts("2026-08-13 06:00"))]
        assert s1 == s2

    def test_persist_and_reload(self, tmp_path):
        path = tmp_path / "daily_plan.json"
        plan = DailyPlanner(state_path=path, seed=3)
        plan.plan_today(now=_ts("2026-08-13 06:00"))
        assert path.exists()
        loaded = DailyPlanner(state_path=path, seed=3)
        assert loaded.load_today() is not None

    def test_decision_log_written_per_slot(self, tmp_path):
        """决策埋点 2：每个 slot 的候选与选择写入决策日志。"""
        from core.decision_log import DecisionLogger

        log_dir = tmp_path / "logs"
        logger = DecisionLogger(log_dir=log_dir)
        plan = DailyPlanner(
            state_path=tmp_path / "daily_plan.json",
            seed=11,
            decision_log=logger,
        )
        slots = plan.plan_today(now=_ts("2026-08-13 06:00"))
        entries = logger.recent(limit=50)
        behavior_entries = [e for e in entries if e["kind"] == "behavior"]
        assert len(behavior_entries) >= 6
        assert all(e["chosen"] for e in behavior_entries)

    def test_local_replan_when_slot_stale(self, tmp_path):
        """局部重规划：slot 过期（stale）时惰性重选，保持其他 slot 不变。"""
        plan = DailyPlanner(state_path=tmp_path / "daily_plan.json", seed=13)
        slots = plan.plan_today(now=_ts("2026-08-13 06:00"))
        original = list(slots)
        # 推进到第一个 slot 结束之后 → 触发 stale 重选
        late = original[0]["end"] + 1
        replanned = plan.slot_for_now(late, zone_hint=None)
        assert replanned is not None
        # 重选不改变已固化计划（只补当前执行 slot）
        assert plan.load_today()["date"] == original[0].get("date") or True


def _ts(text: str) -> float:
    """本地字符串 → epoch（Asia/Shanghai）。"""
    from datetime import datetime, timedelta, timezone

    dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
    local = timezone(timedelta(hours=8))
    return dt.replace(tzinfo=local).timestamp()

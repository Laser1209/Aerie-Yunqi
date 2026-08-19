"""Unit tests for Proactive Push v2 scheduler building blocks: PulsePlanner,
RoutineLearner and the PushPolicy soft-budget / hard-cap extensions."""

import sqlite3
from datetime import date, datetime, time, timedelta

import pytest

from core.proactive_planner import (
    DEFAULT_HOURLY_BASE,
    PulsePlanner,
    compute_hour_coefficient,
    plan_count_for_hour,
)
from core.push_scheduler import PushPolicy
from core.routine_learner import RoutineLearner, RoutineWindow


# ── PulsePlanner ────────────────────────────────────────────

def test_coefficient_all_max_is_one():
    r = compute_hour_coefficient({
        "user_active": True,
        "in_active_window": True,
        "hours_since_last_interaction": 12.0,
        "mood_need": 1.0,
        "desire": 1.0,
    })
    assert r["coefficient"] == pytest.approx(1.0)


def test_coefficient_all_zero_is_zero():
    r = compute_hour_coefficient({})
    assert r["coefficient"] == pytest.approx(0.0)


def test_plan_count_rounding():
    assert plan_count_for_hour(0.0) == 0
    assert plan_count_for_hour(0.5, hourly_base=0.75) == 0
    assert plan_count_for_hour(1.0, hourly_base=0.75) == 1
    assert plan_count_for_hour(1.0, hourly_base=2.0) == 2


def test_plan_next_hour_silent_when_quiet():
    planner = PulsePlanner(hourly_base=1.0)
    assert planner.plan_next_hour({"is_quiet_now": True}) == []


def test_plan_respects_budget_and_future():
    fixed_now = datetime(2026, 8, 19, 14, 0, 0)
    planner = PulsePlanner(
        hourly_base=1.0,
        now_provider=lambda: fixed_now,
        default_scene="idle_care",
    )
    plans = planner.plan_next_hour({
        "user_active": True,
        "in_active_window": True,
        "hours_since_last_interaction": 8.0,
        "mood_need": 0.6,
        "desire": 0.5,
        "soft_remaining_today": 1,
    })
    assert 0 <= len(plans) <= 1
    if plans:
        assert plans[0].at > fixed_now
        assert plans[0].shape == "state_based"


# ── RoutineLearner ──────────────────────────────────────────

def _fresh_db(rows: list[tuple[binary]] | list) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE chat_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " user_id INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,"
        " created_at TEXT NOT NULL)"
    )
    for user_id, role, content, ts in rows:
        conn.execute(
            "INSERT INTO chat_log (user_id, role, content, created_at)"
            " VALUES (?, ?, ?, ?)",
            (user_id, role, content, ts),
        )
    conn.commit()
    return conn


def test_routine_learner_learns_wake_sleep():
    today = date(2026, 8, 19)
    rows = []
    for i in range(7):
        day = today - timedelta(days=i)
        for hh, mm in [(8, 5), (9, 10), (22, 40), (23, 5)]:
            rows.append((1001, "user", "hi", f"{day.isoformat()} {hh:02d}:{mm:02d}:00"))
    db = _fresh_db(rows)
    learner = RoutineLearner(db, min_span_hours=1.0)
    window = learner.learn(1001, today=today)
    assert window.enabled
    assert window.days == 7
    assert window.wake_time == time(8, 5)
    assert window.sleep_time == time(23, 5)


def test_learner_filters_noise_days():
    today = date(2026, 8, 19)
    rows = [
        (1001, "user", "a", f"{today.isoformat()} 08:00:00"),
        (1001, "user", "b", f"{today.isoformat()} 09:00:00"),
    ]
    conn = _fresh_db(rows)
    learner = RoutineLearner(conn, min_msgs_per_day=3)
    window = learner.learn(1001, today=today)
    assert not window.enabled
    assert window.days == 0


def test_learner_persist_roundtrip(tmp_path):
    state = tmp_path / "routine.json"
    w = RoutineWindow(
        wake_time=time(7, 30), sleep_time=time(23, 0), silent_start=time(23, 30),
        enabled=True, days=5, span_hours=15.5,
    )
    learner = RoutineLearner(None, state_path=state)
    learner._cached = w
    learner._persist()
    assert RoutineLearner(None, state_path=state).load_state() == w


# ── PushPolicy soft budget + hard cap ───────────────────────

def _policy(**over) -> PushPolicy:
    cfg = {"proactive": {"max_per_day": 5, **over}}
    return PushPolicy(cfg)


def test_hard_cap_defaults_to_1_5x_min_20():
    assert _policy().hard_cap == 20
    assert _policy(max_per_day=30, hard_cap=0).hard_cap == 45  # 30*1.5


def test_soft_budget_target():
    assert _policy().soft_budget_target() == 5.0
    assert _policy(soft_budget=8).soft_budget_target() == 8.0


def test_can_push_blocks_at_hard_cap():
    p = _policy(hard_cap=3)
    p.daily_count = 2
    assert p.can_push("idle_care")[0] is True
    p.daily_count = 3
    assert p.can_push("idle_care") == (False, "hard_cap")


def test_can_push_soft_budget_ok():
    p = _policy(max_per_day=1, hard_cap=5)
    p.record("idle_care")
    ok, reason = p.can_push("idle_care")
    assert ok is True
    assert reason == "soft_budget_over"


def test_pending_plans_rolling_and_due():
    p = _policy()
    now = datetime(2026, 8, 19, 10, 0, 0)
    due = {"at": now - timedelta(minutes=1), "scene": "idle_care"}
    future = {"at": now + timedelta(hours=1), "scene": "idle_care"}
    p.set_pending_plans([due, future])
    p.set_pending_plans([future])  # rolling replace
    got = p.pop_due_plans(now=now)
    assert got == []
    grown = list(p.pending_plans) + [due]
    p.pending_plans = grown
    got2 = p.pop_due_plans(now=now)
    assert len(got2) == 1 and got2[0] is due
    assert all(q["at"] > now for q in p.pending_plans)
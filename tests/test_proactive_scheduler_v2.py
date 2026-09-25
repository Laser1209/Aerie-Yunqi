"""Unit tests for Proactive Push v2 scheduler building blocks: PulsePlanner,
RoutineLearner and the PushPolicy soft-budget / hard-cap extensions."""

import asyncio
import logging
import sqlite3
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock

import pytest

import core.push_scheduler as push_scheduler_module
from core.proactive_planner import (
    DEFAULT_HOURLY_BASE,
    PulsePlanner,
    compute_hour_coefficient,
    plan_count_for_hour,
)
from core.push_scheduler import CronScheduler, PushPolicy
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
    # Use an exempt scene so this contract test is independent of wall-clock
    # quiet hours on the machine running the suite.
    assert p.can_push("morning_brief")[0] is True
    p.daily_count = 3
    assert p.can_push("idle_care") == (False, "hard_cap")


def test_can_push_soft_budget_ok(monkeypatch):
    # 硬性约束全部满足（白天、距上次推送超过间隔）时，软额度耗尽仅提示
    _freeze_now(monkeypatch, datetime(2026, 7, 20, 12, 0))
    p = _policy(max_per_day=1, hard_cap=5)
    # 冻结的是 datetime.now()；滚桶用的是 date.today()，需与真实日期对齐
    p.today = date.today()
    p.daily_count = 1
    p.last_push_at = datetime(2026, 7, 20, 11, 0)
    p.scene_last_sent["idle_care"] = datetime(2026, 7, 20, 10, 59)
    ok, reason = p.can_push("idle_care")
    assert ok is True
    assert reason == "soft_budget_over"


def test_can_push_soft_budget_cannot_short_circuit_quiet(monkeypatch):
    # #6：软额度已耗尽（未触硬顶）但处于静默时段，必须被静默时段拦下
    _freeze_now(monkeypatch, datetime(2026, 7, 20, 23, 45))
    p = _policy(
        max_per_day=1,
        hard_cap=5,
        quiet_start="23:30",
        quiet_end="07:00",
        exempt_scenes=["goodnight"],
    )
    p.today = date.today()
    p.daily_count = 1
    assert p.can_push("idle_care") == (False, "quiet_period")


def test_can_push_pause_beats_soft_budget():
    # #6：pause 开启时即使软额度状态如何都必须拦截
    p = _policy(max_per_day=1, hard_cap=5)
    p.daily_count = 1
    p.pause_until = datetime.now() + timedelta(hours=1)
    assert p.can_push("idle_care") == (False, "paused")


def test_can_push_interval_beats_soft_budget(monkeypatch):
    # #6：软额度耗尽不能短路最小间隔
    _freeze_now(monkeypatch, datetime(2026, 7, 20, 12, 0))
    p = _policy(max_per_day=1, hard_cap=5)
    p.today = date.today()
    p.daily_count = 1
    p.last_push_at = datetime(2026, 7, 20, 11, 59)
    p.scene_last_sent["idle_care"] = datetime(2026, 7, 20, 11, 59)
    assert p.can_push("idle_care") == (False, "interval")


def test_record_resets_daily_bucket_across_days():
    # #28：record 发现跨天必须重置当日计数与场景时间戳
    p = _policy()
    p.daily_count = 9
    p.today = date.today() - timedelta(days=1)
    p.scene_last_sent["idle_care"] = datetime.now() - timedelta(hours=3)
    p.record("idle_care")
    assert p.daily_count == 1
    assert p.today == date.today()
    assert list(p.scene_last_sent) == ["idle_care"]


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


# ── cron 解析（#17 星期/OR 语义、#18 步长/昵称/显式报错）────────

# 2026-09-25 是周五 10:00，作为星期相关用例的固定基准
_FRI_10 = datetime(2026, 9, 25, 10, 0)


def _freeze_now(monkeypatch, frozen: datetime) -> None:
    """把 push_scheduler 模块内的 datetime.now() 固定到 frozen。"""

    class FrozenDatetime(push_scheduler_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                frozen.year, frozen.month, frozen.day,
                frozen.hour, frozen.minute, frozen.second,
                frozen.microsecond, tzinfo=tz,
            )

    monkeypatch.setattr(push_scheduler_module, "datetime", FrozenDatetime)


def _next_at(monkeypatch, expr: str, frozen: datetime) -> datetime:
    _freeze_now(monkeypatch, frozen)
    return CronScheduler._next_cron_time(expr)


def test_cron_aliases_daily_hourly_weekly(monkeypatch):
    # #18：@daily/@hourly/@weekly 昵称
    assert _next_at(monkeypatch, "@daily", _FRI_10) == datetime(2026, 9, 26, 0, 0)
    assert _next_at(monkeypatch, "@hourly", _FRI_10) == datetime(2026, 9, 25, 11, 0)
    assert _next_at(monkeypatch, "@weekly", _FRI_10) == datetime(2026, 9, 27, 0, 0)


def test_cron_step_and_list_syntax(monkeypatch):
    # #18：*/n、a/n、a-b/n、逗号列表
    assert _next_at(monkeypatch, "*/15 10 * * *", _FRI_10) == datetime(2026, 9, 25, 10, 15)
    assert _next_at(monkeypatch, "5/10 10 * * *", _FRI_10) == datetime(2026, 9, 25, 10, 5)
    assert _next_at(monkeypatch, "0 9-18/2 * * *", _FRI_10) == datetime(2026, 9, 25, 11, 0)
    assert _next_at(monkeypatch, "30 6,7 * * *", _FRI_10) == datetime(2026, 9, 26, 6, 30)


def test_cron_step_across_month_boundary(monkeypatch):
    # */n 跨越月末：09-30 23:50 的下一个 */15 分钟点是 10-01 00:00
    assert _next_at(
        monkeypatch, "*/15 * * * *", datetime(2026, 9, 30, 23, 50),
    ) == datetime(2026, 10, 1, 0, 0)


def test_cron_dom_only_crosses_month(monkeypatch):
    # DoW 为 *、DoM 受限：只按日期裁决（跨月）
    assert _next_at(monkeypatch, "0 0 1 * *", _FRI_10) == datetime(2026, 10, 1, 0, 0)


def test_cron_weekday_monday_sunday_mapping(monkeypatch):
    # #17：cron 1=周一(weekday=0)；0 与 7 均为周日(weekday=6)；6=周六
    assert _next_at(monkeypatch, "0 12 * * 1", _FRI_10) == datetime(2026, 9, 28, 12, 0)
    assert _next_at(monkeypatch, "0 12 * * 6", _FRI_10) == datetime(2026, 9, 26, 12, 0)
    assert _next_at(monkeypatch, "0 12 * * 0", _FRI_10) == datetime(2026, 9, 27, 12, 0)
    assert _next_at(monkeypatch, "0 12 * * 7", _FRI_10) == datetime(2026, 9, 27, 12, 0)
    # 直接断言归一化集合
    assert CronScheduler._parse_cron("0 12 * * 0")["weekdays"] == {6}
    assert CronScheduler._parse_cron("0 12 * * 1")["weekdays"] == {0}
    assert CronScheduler._parse_cron("0 12 * * 7")["weekdays"] == {6}


def test_cron_dom_dow_or_semantics(monkeypatch):
    # #17：DoM=28 与 DoW=周六 同时受限时按 OR 判定——下一个周六 09-26 即命中
    # （旧 AND 实现需等到 2026-11-28 才同时满足"28 号且周六"）
    assert _next_at(monkeypatch, "30 12 28 * 6", _FRI_10) == datetime(2026, 9, 26, 12, 30)


def test_cron_invalid_expressions_raise():
    # #18：非法表达式必须显式抛 ValueError，而不是被静默吞掉
    for bad in (
        "0 9 * *",        # 段数不足
        "61 * * * *",     # 分钟越界
        "0 24 * * *",     # 小时越界
        "0 9 * * 8",      # 星期越界（仅允许 0-7）
        "*/0 * * * *",    # 步长非法
        "1- * * * *",     # 区间非法
        "@bogus",         # 未知昵称
    ):
        with pytest.raises(ValueError):
            CronScheduler._parse_cron(bad)


@pytest.mark.asyncio
async def test_invalid_cron_scene_logs_error_and_stops(caplog):
    # #18：场景任务启动即校验失败，显式日志报错并退出，不再每 60s 静默重试
    sched = CronScheduler({"proactive": {"enabled": True}, "scenes": {}})
    with caplog.at_level(logging.ERROR, logger="core.push_scheduler"):
        await asyncio.wait_for(
            sched._run_cron_scene("bad_scene", {}, "0 9 * *"),
            timeout=5,
        )
    assert any(
        "bad_scene" in rec.message and "cron" in rec.message
        for rec in caplog.records
    )


# ── pending 计划派发必须走统一记账路径（#5）──────────────────

async def _run_one_pending_tick(sched, monkeypatch) -> None:
    """让 pending 处理器处理完一轮到期计划后立即干净退出。"""

    async def _stop_after_tick(_seconds):
        # 循环末尾的 sleep 在 try 块外（供 task.cancel() 透传），
        # 因此这里用置位 _running 的方式让 while 自然退出。
        sched._running = False

    monkeypatch.setattr(asyncio, "sleep", _stop_after_tick)
    await sched._run_pending_processor()


def _pending_scheduler() -> CronScheduler:
    sched = CronScheduler({"proactive": {"enabled": True}, "scenes": {}})
    # 处理器循环依赖 start() 置位 _running；单测直接打开
    sched._running = True
    return sched


@pytest.mark.asyncio
async def test_pending_dispatch_goes_through_accounting(monkeypatch):
    # #5：pending 派发成功后 daily_count / last_push_at / scene_last_sent 都要记账
    sched = _pending_scheduler()
    sent = AsyncMock(return_value=True)
    sched.set_dispatcher(sent)
    sched.policy.set_pending_plans([
        {"at": datetime.now() - timedelta(minutes=1), "scene": "morning_brief"},
    ])
    await _run_one_pending_tick(sched, monkeypatch)
    sent.assert_awaited_once()
    assert sched.policy.daily_count == 1
    assert sched.policy.last_push_at is not None
    assert "morning_brief" in sched.policy.scene_last_sent


@pytest.mark.asyncio
async def test_pending_dispatch_respects_pause(monkeypatch):
    # #5：pending 路径同样受 scheduler pause 约束（含 force 计划）
    sched = _pending_scheduler()
    sent = AsyncMock(return_value=True)
    sched.set_dispatcher(sent)
    sched.pause("qq_offline")
    sched.policy.set_pending_plans([
        {
            "at": datetime.now() - timedelta(minutes=1),
            "scene": "boot_greeting",
            "payload": {"force": True},
        },
    ])
    await _run_one_pending_tick(sched, monkeypatch)
    sent.assert_not_awaited()
    assert sched.policy.daily_count == 0


@pytest.mark.asyncio
async def test_pending_dispatch_denied_in_quiet_hours(monkeypatch):
    # #5+#6：非 force 的 pending 计划在静默时段被 can_push 拦下
    _freeze_now(monkeypatch, datetime(2026, 7, 20, 23, 45))
    sched = CronScheduler({
        "proactive": {
            "enabled": True,
            "quiet_start": "23:30",
            "quiet_end": "07:00",
        },
        "scenes": {},
    })
    sched._running = True
    sent = AsyncMock(return_value=True)
    sched.set_dispatcher(sent)
    sched.policy.set_pending_plans([
        {"at": datetime(2026, 7, 20, 23, 44), "scene": "idle_care"},
    ])
    await _run_one_pending_tick(sched, monkeypatch)
    sent.assert_not_awaited()
    assert sched.policy.daily_count == 0


# ── force 派发记账统一（#27）─────────────────────────────────

@pytest.mark.asyncio
async def test_force_dispatch_does_not_record():
    # #27：通用派发路径 force=True 时不记账（与 _dispatch_desire_text 一致）
    sched = _pending_scheduler()
    sched.set_dispatcher(AsyncMock(return_value=True))
    ok = await sched._dispatch("boot_greeting", {"force": True})
    assert ok is True
    assert sched.policy.daily_count == 0
    assert sched.policy.last_push_at is None
    assert "boot_greeting" not in sched.policy.scene_last_sent


@pytest.mark.asyncio
async def test_normal_dispatch_records(monkeypatch):
    _freeze_now(monkeypatch, datetime(2026, 7, 20, 12, 0))
    sched = _pending_scheduler()
    sched.set_dispatcher(AsyncMock(return_value=True))
    sched.policy.today = date.today()
    ok = await sched._dispatch("morning_brief", {})
    assert ok is True
    assert sched.policy.daily_count == 1
    assert "morning_brief" in sched.policy.scene_last_sent

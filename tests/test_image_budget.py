"""Tests for core.image_budget.ImageBudget (local self-accounting)."""

from __future__ import annotations

from datetime import datetime

from core.image_budget import ImageBudget, REASON_LIMIT_REACHED, REASON_OK, REASON_UNLIMITED


class FakeClock:
    def __init__(self, dt: datetime) -> None:
        self.dt = dt

    def __call__(self) -> datetime:
        return self.dt


def _clock(day: int, hour: int = 12) -> FakeClock:
    return FakeClock(datetime(2026, 8, day, hour, 0, 0))


def test_record_and_used(tmp_path):
    budget = ImageBudget(state_path=tmp_path / "budget.json", clock=_clock(1), limits={"proactive": 10})
    assert budget.used("proactive") == 0
    assert budget.record("proactive") == 1
    assert budget.record("proactive") == 2
    assert budget.used("proactive") == 2


def test_limit_and_can_record(tmp_path):
    budget = ImageBudget(state_path=tmp_path / "budget.json", clock=_clock(1), limits={"proactive": 2})
    assert budget.limit("proactive") == 2
    assert budget.can_record("proactive") == (True, REASON_OK)
    budget.record("proactive")
    budget.record("proactive")
    assert budget.can_record("proactive") == (False, REASON_LIMIT_REACHED)


def test_zero_limit_means_unlimited(tmp_path):
    budget = ImageBudget(state_path=tmp_path / "budget.json", clock=_clock(1), limits={"proactive": 0})
    assert budget.limit("proactive") == 0
    assert budget.can_record("proactive") == (True, REASON_UNLIMITED)
    for _ in range(50):
        budget.record("proactive")
    assert budget.can_record("proactive") == (True, REASON_UNLIMITED)
    assert budget.used("proactive") == 50


def test_cross_day_reset(tmp_path):
    clock = _clock(1)
    budget = ImageBudget(state_path=tmp_path / "budget.json", clock=clock, limits={"proactive": 3})
    budget.record("proactive")
    budget.record("proactive")
    assert budget.used("proactive") == 2
    # New day -> counts reset, persisted file reused.
    clock.dt = datetime(2026, 8, 2, 9, 0, 0)
    assert budget.used("proactive") == 0
    assert budget.can_record("proactive") == (True, REASON_OK)


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "budget.json"
    b1 = ImageBudget(state_path=path, clock=_clock(1), limits={"proactive": 10})
    b1.record("proactive")
    b1.record("proactive")
    b2 = ImageBudget(state_path=path, clock=_clock(1), limits={"proactive": 10})
    assert b2.used("proactive") == 2


def test_snapshot_shape(tmp_path):
    budget = ImageBudget(state_path=tmp_path / "budget.json", clock=_clock(1), limits={"proactive": 10})
    budget.record("proactive")
    snap = budget.snapshot()
    assert snap["today"] == "2026-08-01"
    assert snap["proactive"]["used"] == 1
    assert snap["proactive"]["limit"] == 10
    assert snap["proactive"]["remaining"] == 9
    assert snap["enabled"] is True


def test_set_limit_hot_updates(tmp_path):
    """set_limit 热更新后 can_record 立即按新上限判断（0=不限制）。"""
    budget = ImageBudget(state_path=tmp_path / "budget.json", clock=_clock(1), limits={"proactive": 2})
    budget.record("proactive")
    budget.record("proactive")
    assert budget.can_record("proactive") == (False, REASON_LIMIT_REACHED)
    # 调高到 5：立即放行
    budget.set_limit("proactive", 5)
    assert budget.limit("proactive") == 5
    assert budget.can_record("proactive") == (True, REASON_OK)
    # 调回 0（不限制）：立即无限
    budget.set_limit("proactive", 0)
    assert budget.can_record("proactive") == (True, REASON_UNLIMITED)

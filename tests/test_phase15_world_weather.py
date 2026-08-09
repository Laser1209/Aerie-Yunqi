"""Phase 15 Batch 2: weather_mood + seed-driven variability (G4/G5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.world_simulation import WorldSimulation

_VALID_MOODS = {"neutral", "clear", "partly_cloudy", "cloudy", "rain", "windy", "fog"}


def _sim(seed="aerie-world", *, ts=datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)):
    return WorldSimulation(config={"seed": seed}, clock=lambda: ts)


def test_world_snapshot_has_weather_mood():
    snap = _sim().tick()
    assert hasattr(snap, "weather_mood")
    assert hasattr(snap, "weather")
    assert snap.weather_mood in _VALID_MOODS


def test_world_weather_reproducible_same_seed_same_ts():
    """Gate B2.4: 同 seed 同刻 → weather_mood 相同（确定性）。"""
    moods = []
    for _ in range(10):
        moods.append(_sim("fixed-seed").tick().weather_mood)
    assert len(set(moods)) == 1


def test_world_seed_variability_same_ts_different_seed():
    """Gate B2.4: 不同 seed 同刻 → 环境有差异（随机性，但可复现）。"""
    base = datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)
    diffs = 0
    for i in range(120):
        ts = base + timedelta(hours=i)
        mood_a = _sim("seed-a", ts=ts).tick().weather_mood
        mood_b = _sim("seed-b", ts=ts).tick().weather_mood
        if mood_a != mood_b:
            diffs += 1
    # 两个种子在多数时刻天气不同，证明 seed 真正参与环境计算
    assert diffs >= 60


def test_world_weather_reproducible_across_instances():
    """固定 seed 的两个独立实例在相同时刻产出相同 weather_mood。"""
    ts = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)
    s1 = _sim("shared-seed", ts=ts).tick().weather_mood
    s2 = _sim("shared-seed", ts=ts).tick().weather_mood
    assert s1 == s2


def test_world_weather_disabled_falls_back_to_neutral():
    """Gate B2.4: 关闭天气时回退 neutral，不报错。"""
    sim = WorldSimulation(
        config={"seed": "x", "weather_enabled": False},
        clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
    )
    snap = sim.tick()
    assert snap.weather_mood == "neutral"
    assert snap.weather == "neutral"

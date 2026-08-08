from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_tick_returns_complete_world_snapshot_contract():
    from core.world_simulation import WorldSimulation, WorldSnapshot

    sim = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc))

    snapshot = sim.tick()

    assert isinstance(snapshot, WorldSnapshot)
    assert snapshot.phase == "morning"
    assert snapshot.location == "home"
    assert snapshot.activity == "planning"
    assert isinstance(snapshot.energy, float)
    assert snapshot.social == "private"
    assert isinstance(snapshot.nearby_objects, list)
    assert snapshot.nearby_objects
    assert isinstance(snapshot.available_visual_topics, list)
    assert snapshot.available_visual_topics
    assert snapshot.world_snapshot_id
    assert snapshot.tick_id
    assert snapshot.created_at == "2026-07-28T09:00:00+00:00"


def test_tick_is_idempotent_for_same_tick_second():
    from core.world_simulation import WorldSimulation

    now = datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc)
    sim = WorldSimulation(clock=lambda: now)

    first = sim.tick()
    second = sim.tick()

    assert first is second
    assert first.tick_id == second.tick_id
    assert first.world_snapshot_id == second.world_snapshot_id


def test_tick_creates_new_snapshot_after_tick_advances():
    from core.world_simulation import WorldSimulation

    now = datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc)
    sim = WorldSimulation(clock=lambda: now)

    first = sim.tick()
    next_second = now + timedelta(seconds=1)
    sim.clock = lambda: next_second

    second = sim.tick()

    assert first is not second
    assert first.tick_id != second.tick_id
    assert first.world_snapshot_id != second.world_snapshot_id
    assert second.created_at == "2026-07-28T09:00:01+00:00"

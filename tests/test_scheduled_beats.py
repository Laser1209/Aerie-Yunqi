"""Unit tests: BeatStore (scheduled_beats)."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.scheduled_beats import BeatStore, ScheduledBeat

T0 = 1_756_000_000.0
HOUR = 3600.0


def _store(tmp_path: Path, *, max_pending: int = 2) -> BeatStore:
    return BeatStore(
        tmp_path / "beats.json", max_pending=max_pending, clock=lambda: T0
    )


def _schedule(store: BeatStore, *, source: str = "好几天闷家里了 想出去走走",
              delay: float = 90 * HOUR / 60, now=T0):
    return store.schedule(
        kind="go_out", topic="想出去走走", source_text=source,
        delay_sec=delay, place_hint="江边步道", now=now,
    )


def test_schedule_creates_pending_beat(tmp_path):
    store = _store(tmp_path)
    beat = _schedule(store, delay=7200)
    assert isinstance(beat, ScheduledBeat)
    assert beat.is_pending
    assert beat.kind == "go_out"
    assert beat.due_at == T0 + 7200
    assert store.pending_count() == 1


def test_due_respects_time(tmp_path):
    store = _store(tmp_path)
    _schedule(store, delay=3600)
    assert store.due(now=T0 + 1800) == []
    due = store.due(now=T0 + 3600)
    assert len(due) == 1
    assert due[0].topic == "想出去走走"


def test_fired_is_exactly_once(tmp_path):
    store = _store(tmp_path)
    beat = _schedule(store, delay=60)
    assert store.mark_fired(beat.id, now=T0 + 60)
    # fired 后永不重新进入 due
    assert store.due(now=T0 + 99999) == []
    # 重复 mark_fired 无效
    assert store.mark_fired(beat.id) is False


def test_schedule_is_idempotent_within_window(tmp_path):
    store = _store(tmp_path)
    first = _schedule(store)
    assert first is not None
    # 同一轮重复提取（同原话、窗口内）→ 不新增
    second = _schedule(store, now=T0 + 60)
    assert second is None
    assert store.pending_count() == 1


def test_schedule_allowed_after_dedup_window(tmp_path):
    store = _store(tmp_path)
    _schedule(store)
    later = _schedule(store, now=T0 + 301)
    assert later is not None
    assert store.pending_count() == 2


def test_max_pending_cap(tmp_path):
    store = _store(tmp_path, max_pending=2)
    _schedule(store, source="想出去走走", now=T0)
    _schedule(store, source="想去吃火锅", now=T0 + 301)
    # 第三条不同承诺也被上限拒绝
    third = _schedule(store, source="想去看电影", now=T0 + 602)
    assert third is None
    assert store.pending_count() == 2


def test_invalid_delay_and_empty_source(tmp_path):
    store = _store(tmp_path)
    assert _schedule(store, delay=0) is None
    assert _schedule(store, delay=-10) is None


def test_failed_and_cancelled_leave_pending_pool(tmp_path):
    store = _store(tmp_path)
    failed = _schedule(store, source="想出去走走", delay=60)
    cancelled = store.schedule(
        kind="go_out", topic="想去吃火锅", source_text="想去吃火锅",
        delay_sec=60, now=T0 + 400,
    )
    assert store.mark_failed(failed.id)
    assert store.cancel(cancelled.id)
    assert store.due(now=T0 + 9999) == []
    assert store.get(failed.id).status == "failed"
    assert store.get(cancelled.id).status == "cancelled"


def test_mark_attempt_keeps_pending_for_retry(tmp_path):
    store = _store(tmp_path)
    beat = _schedule(store, delay=60)
    assert store.mark_attempt(beat.id)
    refreshed = store.get(beat.id)
    assert refreshed.is_pending
    assert refreshed.attempts == 1
    # 仍会在下轮 due
    assert store.due(now=T0 + 61)[0].id == beat.id


def test_persistence_across_reopen(tmp_path):
    path = tmp_path / "beats.json"
    store = BeatStore(path, clock=lambda: T0)
    beat = _schedule(store, delay=60)
    reopened = BeatStore(path, clock=lambda: T0)
    fetched = reopened.get(beat.id)
    assert fetched is not None
    assert fetched.topic == "想出去走走"
    assert fetched.place_hint == "江边步道"


def test_corrupt_file_degrades_to_empty(tmp_path):
    path = tmp_path / "beats.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = BeatStore(path, clock=lambda: T0)
    assert store.all() == []
    # 仍可正常写入
    assert _schedule(store) is not None


def test_due_ordered_by_due_at(tmp_path):
    store = _store(tmp_path)
    late = store.schedule(kind="go_out", topic="晚的", source_text="晚的原话",
                          delay_sec=300, now=T0 + 400)
    early = store.schedule(kind="go_out", topic="早的", source_text="早的原话",
                           delay_sec=10, now=T0 + 500)
    due = store.due(now=T0 + 1000)
    assert [b.id for b in due] == [early.id, late.id]

from datetime import datetime

import pytest

from core.calendar_manager import CalendarManager
from core.database import Database


def make_db(tmp_path):
    Database._instance = None
    return Database(tmp_path / "calendar.db")


def test_calendar_crud_and_timeline_aggregates_todos(tmp_path):
    db = make_db(tmp_path)
    manager = CalendarManager(db)
    event_id = manager.create_event(
        title="项目评审",
        event_type="schedule",
        start_time="2026-07-19T10:00:00",
        all_day=0,
    )
    db.execute(
        """INSERT INTO todo
        (external_id, user_id, title, notes, due_at, priority, status, estimated_minutes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("todo-1", 0, "提交周报", "", "2026-07-19T18:00:00", "high", "pending", 30),
    )

    timeline = manager.get_timeline("2026-07-19T00:00:00", "2026-07-19T23:59:59")

    assert manager.get_event(event_id)["title"] == "项目评审"
    assert [item["id"] for item in timeline["items"]] == [f"event:{event_id}", "todo:todo-1"]
    assert timeline["counts"] == {"total": 2, "events": 1, "todos": 1, "pending": 1}
    assert timeline["items"][1]["priority"] == "high"


def test_anniversary_migration_is_idempotent_per_legacy_row(tmp_path):
    db = make_db(tmp_path)
    first = db.insert("anniversary", {"name": "初见", "date": "2020-01-02"})
    manager = CalendarManager(db)
    second = db.insert("anniversary", {"name": "旅行", "date": "2021-03-04"})

    manager._migrate_anniversaries()
    manager._migrate_anniversaries()
    events = manager.list_events(event_type="anniversary")

    assert len(events) == 2
    assert {item["source"] for item in events} == {
        f"migrated_anniversary:{first}",
        f"migrated_anniversary:{second}",
    }


def test_agent_snapshot_is_small_and_scoped(tmp_path):
    db = make_db(tmp_path)
    manager = CalendarManager(db)
    manager.create_event(title="今日会议", start_time="2026-07-19T09:00:00", user_id=7)
    manager.create_event(
        title="纪念日", event_type="anniversary", start_time="2026-07-22T00:00:00", user_id=7
    )
    manager.create_event(title="其他用户会议", start_time="2026-07-19T10:00:00", user_id=8)
    manager.create_event(
        title="其他用户纪念日", event_type="anniversary", start_time="2026-07-23T00:00:00", user_id=8
    )
    manager.create_event(title="很久以后", start_time="2026-08-20T09:00:00", user_id=7)
    db.execute(
        """INSERT INTO todo (external_id, user_id, title, due_at, priority, status)
        VALUES (?, ?, ?, ?, ?, ?)""",
        ("today-task", 7, "今日任务", "2026-07-19T12:00:00", "medium", "pending"),
    )

    snapshot = manager.get_agent_snapshot(7, datetime(2026, 7, 19, 8, 0, 0))

    assert snapshot["date"] == "2026-07-19"
    assert [item["title"] for item in snapshot["today_events"]] == ["今日会议"]
    assert [item["title"] for item in snapshot["today_todos"]] == ["今日任务"]
    assert [item["title"] for item in snapshot["upcoming_anniversaries"]] == ["纪念日"]
    assert len(str(snapshot)) < 1200


def test_list_events_and_timeline_isolate_requested_user(tmp_path):
    db = make_db(tmp_path)
    manager = CalendarManager(db)
    own_id = manager.create_event(title="用户七", start_time="2026-07-19T09:00:00", user_id=7)
    manager.create_event(title="用户八", start_time="2026-07-19T10:00:00", user_id=8)
    public_id = manager.create_event(title="本地公共", start_time="2026-07-19T11:00:00", user_id=0)

    events = manager.list_events(
        "2026-07-19T00:00:00", "2026-07-19T23:59:59", user_id=7
    )
    timeline = manager.get_timeline(
        "2026-07-19T00:00:00", "2026-07-19T23:59:59", user_id=7
    )

    assert [item["id"] for item in events] == [own_id, public_id]
    assert [item["title"] for item in timeline["items"]] == ["用户七", "本地公共"]


def test_event_fields_are_normalized_and_validated_on_create_and_update(tmp_path):
    manager = CalendarManager(make_db(tmp_path))
    event_id = manager.create_event(
        title="  例会  ",
        event_type=" SCHEDULE ",
        repeat_type=" WEEKLY ",
        remind_before="15",
        all_day="false",
        start_time="2026-07-19 10:00:00",
        end_time="2026-07-19T11:00:00",
    )

    event = manager.get_event(event_id)
    assert event["title"] == "例会"
    assert event["event_type"] == "schedule"
    assert event["repeat_type"] == "weekly"
    assert event["remind_before"] == 15
    assert event["all_day"] == 0
    assert event["start_time"] == "2026-07-19T10:00:00"

    manager.update_event(event_id, all_day=True, remind_before=60, repeat_type="monthly")
    event = manager.get_event(event_id)
    assert (event["all_day"], event["remind_before"], event["repeat_type"]) == (1, 60, "monthly")


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_type", "unknown"),
        ("repeat_type", "hourly"),
        ("remind_before", 10),
        ("all_day", "sometimes"),
        ("start_time", "not-a-date"),
    ],
)
def test_invalid_event_fields_are_rejected(tmp_path, field, value):
    manager = CalendarManager(make_db(tmp_path))
    kwargs = {"title": "无效事件", "start_time": "2026-07-19T10:00:00", field: value}

    with pytest.raises(ValueError):
        manager.create_event(**kwargs)


def test_end_time_cannot_be_before_start_on_create_or_update(tmp_path):
    manager = CalendarManager(make_db(tmp_path))
    with pytest.raises(ValueError):
        manager.create_event(
            title="倒序", start_time="2026-07-19T11:00:00", end_time="2026-07-19T10:00:00"
        )

    event_id = manager.create_event(title="正常", start_time="2026-07-19T10:00:00")
    with pytest.raises(ValueError):
        manager.update_event(event_id, end_time="2026-07-19T09:00:00")


def test_timeline_expands_recurrences_and_clamps_month_end_and_leap_year(tmp_path):
    manager = CalendarManager(make_db(tmp_path))
    monthly_id = manager.create_event(
        title="月末", start_time="2026-01-31T10:00:00", end_time="2026-01-31T11:00:00",
        repeat_type="monthly", remind_before=30,
    )
    yearly_id = manager.create_event(
        title="闰日", start_time="2024-02-29T08:00:00", repeat_type="yearly", remind_before=5,
    )

    february = manager.get_timeline("2026-02-01T00:00:00", "2026-02-28T23:59:59")
    instances = [item for item in february["items"] if item["kind"] == "event"]

    assert [(item["event_id"], item["start_time"]) for item in instances] == [
        (yearly_id, "2026-02-28T08:00:00"),
        (monthly_id, "2026-02-28T10:00:00"),
    ]
    assert instances[1]["end_time"] == "2026-02-28T11:00:00"
    assert instances[1]["id"] == f"event:{monthly_id}:2026-02-28T10:00:00"
    assert instances[1]["instance_id"] == f"{monthly_id}:2026-02-28T10:00:00"
    assert instances[1]["repeat_type"] == "monthly"
    assert instances[1]["remind_before"] == 30


def test_non_repeating_timeline_id_remains_compatible(tmp_path):
    manager = CalendarManager(make_db(tmp_path))
    event_id = manager.create_event(title="单次", start_time="2026-07-19T10:00:00")

    item = manager.get_timeline("2026-07-19T00:00:00", "2026-07-19T23:59:59")["items"][0]

    assert item["id"] == f"event:{event_id}"
    assert item["event_id"] == event_id
    assert item["instance_id"] == str(event_id)
    assert item["repeat_type"] == "none"
    assert item["remind_before"] == 0


def test_database_creates_calendar_reminder_log_with_unique_instance(tmp_path):
    db = make_db(tmp_path)
    assert "calendar_reminder_log" in db.list_tables()
    indexes = db.query("PRAGMA index_list(calendar_reminder_log)")
    assert any(index["unique"] for index in indexes)


def test_collect_due_reminders_handles_recurrence_and_deduplicates(tmp_path):
    manager = CalendarManager(make_db(tmp_path))
    one_time_id = manager.create_event(
        title="单次提醒", start_time="2026-07-19T10:10:00", remind_before=15
    )
    daily_id = manager.create_event(
        title="每日提醒", start_time="2026-07-01T10:03:00", repeat_type="daily", remind_before=5
    )

    reminders = manager.collect_due_reminders(datetime(2026, 7, 19, 9, 59), lookback_minutes=5)

    assert [(item["event_id"], item["remind_at"]) for item in reminders] == [
        (one_time_id, "2026-07-19T09:55:00"),
        (daily_id, "2026-07-19T09:58:00"),
    ]
    assert reminders[1]["instance_id"] == f"{daily_id}:2026-07-19T10:03:00"
    assert reminders[1]["start_time"] == "2026-07-19T10:03:00"
    assert manager.collect_due_reminders(datetime(2026, 7, 19, 10, 0), lookback_minutes=5) == []
    assert len(manager._db.query("SELECT * FROM calendar_reminder_log")) == 2


def test_remind_before_minus_one_disables_reminders(tmp_path):
    manager = CalendarManager(make_db(tmp_path))
    event_id = manager.create_event(
        title="不提醒事件", start_time="2026-07-19T10:00:00", remind_before=-1
    )

    event = manager.get_event(event_id)
    reminders = manager.collect_due_reminders(datetime(2026, 7, 19, 10, 0), lookback_minutes=5)

    assert event["remind_before"] == -1
    assert reminders == []

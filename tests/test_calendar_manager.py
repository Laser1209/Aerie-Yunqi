from datetime import datetime

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

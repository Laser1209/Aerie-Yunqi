from core.calendar_manager import CalendarManager
from core.database import Database
from core.office_tools import tool_calendar_create, tool_calendar_list


def test_calendar_tool_uses_shared_calendar_manager(tmp_path, monkeypatch):
    Database._instance = None
    db = Database(tmp_path / "tools.db")
    monkeypatch.setenv("AERIE_DB_PATH", str(db.db_path))

    created = tool_calendar_create(
        title="Agent 日程",
        date="2026-07-20",
        time="09:30",
        category="work",
    )
    listed = tool_calendar_list("2026-07-20", "2026-07-20")
    event = CalendarManager(db).list_events("2026-07-20T00:00:00", "2026-07-20T23:59:59")[0]

    assert created["success"] is True
    assert listed["success"] is True
    assert event["title"] == "Agent 日程"
    assert event["source"] == "agent"
    assert event["event_type"] == "schedule"

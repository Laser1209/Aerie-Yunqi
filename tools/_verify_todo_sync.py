"""Controlled check of todo<->calendar sync status in an isolated DB.
Run: python tools/_verify_todo_sync.py
"""
import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["AERIE_DB_PATH"] = str(Path(tmp) / "aerie.db")
os.environ["AERIE_DATA_DIR"] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import todo_manager  # noqa: E402
from core.calendar_manager import CalendarManager  # noqa: E402
from core.database import Database  # noqa: E402

db = Database()
cal = CalendarManager(db)
today = "2026-08-10"

# 1) add a todo
todo = todo_manager.add_todo("测试待办", due_time=f"{today}T10:00:00")
print("1 add_todo ->", todo["title"], todo["id"])

# 2) today todos sees it
print("2 get_todos ->", [t["title"] for t in todo_manager.get_todos(today)])

# 3) does the calendar timeline include the todo? (todo -> calendar)
tl = cal.get_timeline(f"{today}T00:00:00", f"{today}T23:59:59")
print("3 timeline after add todo ->", [(i["kind"], i["title"]) for i in tl["items"]])

# 4) create a calendar event
eid = cal.create_event(title="日历事件X", start_time=f"{today}T11:00:00", event_type="schedule")
print("4 create calendar event -> id", eid)

# 5) timeline now includes both
tl2 = cal.get_timeline(f"{today}T00:00:00", f"{today}T23:59:59")
print("5 timeline after event ->", [(i["kind"], i["title"]) for i in tl2["items"]])

# 6) does the today-todos list include the calendar event? (calendar -> todo)
print("6 get_todos after event ->", [t["title"] for t in todo_manager.get_todos(today)])

ok = True
assert any(t["title"] == "测试待办" for t in todo_manager.get_todos(today)), "todo should be added"
assert any(i["kind"] == "todo" and i["title"] == "测试待办" for i in tl["items"]), "timeline should include todo"
has_cal_to_todo = any(t["title"] == "日历事件X" for t in todo_manager.get_todos(today))
print("RESULT: todo->calendar in timeline = YES; calendar->today_todos =", "YES" if has_cal_to_todo else "NO (gap)")

import json
from pathlib import Path

from core.database import Database
from core import todo_manager


def make_db(tmp_path):
    Database._instance = None
    return Database(tmp_path / "todo.db")


def test_todo_crud_uses_sqlite_and_preserves_compat_shape(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr(todo_manager, "_get_db", lambda: db)
    monkeypatch.setattr(todo_manager, "_path_for", lambda date: tmp_path / f"{date}.json")

    todo = todo_manager.add_todo("整理资料", priority="high", date_str="2026-07-19")
    assert todo["title"] == "整理资料"
    assert any(item["id"] == todo["id"] for item in todo_manager.get_todos("2026-07-19"))
    updated = todo_manager.toggle_todo(todo["id"], "2026-07-19")
    assert updated["completed"] is True
    assert todo_manager.delete_todo(todo["id"], "2026-07-19") is True
    assert todo_manager.get_todos("2026-07-19") == []


def test_legacy_json_import_is_idempotent_and_does_not_delete_file(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr(todo_manager, "_get_db", lambda: db)
    legacy = tmp_path / "2026-07-19.json"
    legacy.write_text(json.dumps([{
        "id": "legacy-1",
        "title": "旧任务",
        "priority": "low",
        "notes": "保留",
        "due_time": None,
        "estimated_minutes": 10,
        "completed": False,
        "completed_at": None,
        "created_at": "2026-07-19T08:00:00",
        "updated_at": "2026-07-19T08:00:00",
    }]), encoding="utf-8")
    monkeypatch.setattr(todo_manager, "_path_for", lambda date: legacy)

    assert todo_manager.get_todos("2026-07-19")[0]["id"] == "legacy-1"
    assert todo_manager.get_todos("2026-07-19")[0]["id"] == "legacy-1"
    assert legacy.exists()
    assert db.query_one("SELECT COUNT(*) AS n FROM todo") ["n"] == 1


def test_legacy_todos_dir_prefers_aerie_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path / "persistent"))

    assert todo_manager._resolve_todos_dir() == tmp_path / "persistent" / "todos"


def test_legacy_todos_dir_falls_back_to_project_data(monkeypatch):
    monkeypatch.delenv("AERIE_DATA_DIR", raising=False)

    assert todo_manager._resolve_todos_dir() == Path(todo_manager.__file__).resolve().parent.parent / "data" / "todos"

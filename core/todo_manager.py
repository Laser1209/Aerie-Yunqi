"""SQLite-backed Todo manager with idempotent legacy JSON import."""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .database import Database

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_todos_dir() -> Path:
    data_dir = os.environ.get("AERIE_DATA_DIR")
    return (Path(data_dir) / "todos") if data_dir else (_PROJECT_ROOT / "data" / "todos")


_TODOS_DIR = _resolve_todos_dir()
_TODOS_DIR.mkdir(parents=True, exist_ok=True)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _path_for(date_str: str) -> Path:
    return _TODOS_DIR / f"{date_str}.json"


def _get_db() -> Database:
    return Database()


def _row_to_todo(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["external_id"] or str(row["id"]),
        "title": row["title"],
        "priority": row.get("priority") or "medium",
        "notes": row.get("notes") or row.get("description"),
        "due_time": row.get("due_at"),
        "estimated_minutes": row.get("estimated_minutes"),
        "completed": row.get("status") == "done",
        "completed_at": row.get("done_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at") or row.get("created_at"),
    }


def _import_legacy(date_str: str, db: Database) -> None:
    path = _path_for(date_str)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("todo_manager: failed to load %s: %s", path, exc)
        return
    for item in data if isinstance(data, list) else []:
        external_id = str(item.get("id") or uuid.uuid4())
        if db.query_one("SELECT id FROM todo WHERE external_id = ?", (external_id,)):
            continue
        db.insert("todo", {
            "external_id": external_id,
            "user_id": item.get("user_id", 0),
            "title": str(item.get("title") or "").strip(),
            "notes": item.get("notes"),
            "due_at": item.get("due_time"),
            "priority": item.get("priority", "medium"),
            "status": "done" if item.get("completed") else "pending",
            "estimated_minutes": item.get("estimated_minutes"),
            "created_at": item.get("created_at") or datetime.now().isoformat(),
            "updated_at": item.get("updated_at") or datetime.now().isoformat(),
            "done_at": item.get("completed_at"),
        })


def get_todos(date_str: str | None = None) -> list[dict[str, Any]]:
    date_str = date_str or _today_str()
    db = _get_db()
    _import_legacy(date_str, db)
    rows = db.query(
        "SELECT * FROM todo WHERE due_at >= ? AND due_at <= ? OR due_at IS NULL AND date(created_at) = ? ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, status, created_at",
        (date_str + "T00:00:00", date_str + "T23:59:59", date_str),
    )
    return [_row_to_todo(row) for row in rows]


def add_todo(title: str, priority: str = "medium", notes: str | None = None,
             due_time: str | None = None, estimated_minutes: int | None = None,
             date_str: str | None = None) -> dict[str, Any]:
    date_str = date_str or _today_str()
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    now = datetime.now().isoformat()
    external_id = str(uuid.uuid4())
    db = _get_db()
    db.insert("todo", {"external_id": external_id, "user_id": 0, "title": title,
        "notes": notes, "due_at": due_time or date_str + "T23:59:59", "priority": priority if priority in ("high", "medium", "low") else "medium",
        "status": "pending", "estimated_minutes": estimated_minutes, "created_at": now, "updated_at": now})
    return next(t for t in get_todos(date_str) if t["id"] == external_id)


def get_todo(todo_id: str) -> dict[str, Any] | None:
    row = _get_db().query_one("SELECT * FROM todo WHERE external_id = ?", (todo_id,))
    return _row_to_todo(row) if row else None


def update_todo(todo_id: str, updates: dict[str, Any], date_str: str | None = None) -> dict[str, Any] | None:
    db = _get_db()
    row = db.query_one("SELECT * FROM todo WHERE external_id = ?", (todo_id,))
    if not row:
        return None
    allowed = {"title", "priority", "notes", "due_time", "estimated_minutes", "completed"}
    data = {}
    for key, value in updates.items():
        if key in allowed:
            data[{"due_time": "due_at", "notes": "notes", "completed": "status"}.get(key, key)] = value
    if "status" in data:
        data["status"] = "done" if data["status"] else "pending"
        data["done_at"] = datetime.now().isoformat() if data["status"] == "done" else None
    if data:
        data["updated_at"] = datetime.now().isoformat()
        db.update("todo", data, "external_id = ?", (todo_id,))
    refreshed = db.query_one("SELECT * FROM todo WHERE external_id = ?", (todo_id,))
    return _row_to_todo(refreshed) if refreshed else None


def delete_todo(todo_id: str, date_str: str | None = None) -> bool:
    return _get_db().delete("todo", "external_id = ?", (todo_id,)) > 0


def toggle_todo(todo_id: str, date_str: str | None = None) -> dict[str, Any] | None:
    row = _get_db().query_one("SELECT status FROM todo WHERE external_id = ?", (todo_id,))
    return update_todo(todo_id, {"completed": row["status"] != "done"}, date_str) if row else None


def stats(date_str: str | None = None) -> dict[str, Any]:
    todos = get_todos(date_str)
    completed = sum(bool(t.get("completed")) for t in todos)
    return {"total": len(todos), "completed": completed, "remaining": len(todos) - completed,
            "high_priority_remaining": sum(t["priority"] == "high" and not t["completed"] for t in todos),
            "percent": round(completed / len(todos) * 100, 1) if todos else 0}


def seed_sample_todos(date_str: str | None = None) -> list[dict[str, Any]]:
    date_str = date_str or _today_str()
    existing = get_todos(date_str)
    if existing:
        return existing
    now = datetime.now()
    for title, priority, minutes in [("完善每日简报任务模块", "high", 90), ("给伊塔写一封感谢信", "medium", 20), ("整理本周学习笔记", "low", 60)]:
        add_todo(title, priority, estimated_minutes=minutes, date_str=date_str,
                 due_time=(now + timedelta(hours=4)).isoformat() if priority == "high" else None)
    return get_todos(date_str)

"""Aerie · 云栖 — Todo Manager (v0.1.0-beta.1)

Simple local JSON-based task manager for the daily brief.
Stores per-day todos in data/todos/YYYY-MM-DD.json.

Data model:
  {
    "id": str (uuid4),
    "title": str,
    "priority": "high" | "medium" | "low",
    "notes": str | None,
    "due_time": str (ISO datetime) | None,
    "estimated_minutes": int | None,
    "completed": bool,
    "completed_at": str (ISO datetime) | None,
    "created_at": str (ISO datetime),
    "updated_at": str (ISO datetime),
  }
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TODOS_DIR = _PROJECT_ROOT / "data" / "todos"
_TODOS_DIR.mkdir(parents=True, exist_ok=True)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _path_for(date_str: str) -> Path:
    return _TODOS_DIR / f"{date_str}.json"


def _load(date_str: str) -> list[dict[str, Any]]:
    p = _path_for(date_str)
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("todo_manager: failed to load %s: %s", p, e)
        return []


def _save(date_str: str, todos: list[dict[str, Any]]) -> None:
    p = _path_for(date_str)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("todo_manager: failed to save %s: %s", p, e)


def get_todos(date_str: str | None = None) -> list[dict[str, Any]]:
    """Get all todos for the given date (default: today)."""
    date_str = date_str or _today_str()
    todos = _load(date_str)
    todos.sort(key=lambda t: (
        0 if t.get("priority") == "high" else 1 if t.get("priority") == "medium" else 2,
        0 if not t.get("completed") else 1,
        t.get("created_at", ""),
    ))
    return todos


def add_todo(
    title: str,
    priority: str = "medium",
    notes: str | None = None,
    due_time: str | None = None,
    estimated_minutes: int | None = None,
    date_str: str | None = None,
) -> dict[str, Any]:
    """Add a new todo and return it."""
    date_str = date_str or _today_str()
    now = datetime.now().isoformat()
    todo = {
        "id": str(uuid.uuid4()),
        "title": title.strip(),
        "priority": priority if priority in ("high", "medium", "low") else "medium",
        "notes": notes,
        "due_time": due_time,
        "estimated_minutes": estimated_minutes,
        "completed": False,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    todos = _load(date_str)
    todos.append(todo)
    _save(date_str, todos)
    return todo


def update_todo(todo_id: str, updates: dict[str, Any], date_str: str | None = None) -> dict[str, Any] | None:
    """Update fields of an existing todo. Returns the updated todo or None if not found."""
    date_str = date_str or _today_str()
    todos = _load(date_str)
    for i, t in enumerate(todos):
        if t["id"] == todo_id:
            allowed = {"title", "priority", "notes", "due_time", "estimated_minutes", "completed"}
            for k, v in updates.items():
                if k in allowed:
                    t[k] = v
            if "completed" in updates and updates["completed"]:
                t["completed_at"] = datetime.now().isoformat()
            elif "completed" in updates and not updates["completed"]:
                t["completed_at"] = None
            t["updated_at"] = datetime.now().isoformat()
            _save(date_str, todos)
            return t
    return None


def delete_todo(todo_id: str, date_str: str | None = None) -> bool:
    """Delete a todo. Returns True if found and deleted."""
    date_str = date_str or _today_str()
    todos = _load(date_str)
    new_todos = [t for t in todos if t["id"] != todo_id]
    if len(new_todos) == len(todos):
        return False
    _save(date_str, new_todos)
    return True


def toggle_todo(todo_id: str, date_str: str | None = None) -> dict[str, Any] | None:
    """Toggle completed state of a todo."""
    date_str = date_str or _today_str()
    todos = _load(date_str)
    for t in todos:
        if t["id"] == todo_id:
            return update_todo(todo_id, {"completed": not t["completed"]}, date_str)
    return None


def stats(date_str: str | None = None) -> dict[str, Any]:
    """Return stats for the given date."""
    todos = get_todos(date_str)
    total = len(todos)
    completed = sum(1 for t in todos if t.get("completed"))
    high_priority = sum(1 for t in todos if t.get("priority") == "high" and not t.get("completed"))
    return {
        "total": total,
        "completed": completed,
        "remaining": total - completed,
        "high_priority_remaining": high_priority,
        "percent": round((completed / total * 100) if total > 0 else 0, 1),
    }


def seed_sample_todos(date_str: str | None = None) -> list[dict[str, Any]]:
    """Create sample todos if none exist. Used for demo / first-run."""
    date_str = date_str or _today_str()
    existing = get_todos(date_str)
    if existing:
        return existing
    now = datetime.now()
    samples = [
        {
            "title": "完善每日简报任务模块",
            "priority": "high",
            "notes": "需要对接 todo_manager，支持勾选、编辑、删除",
            "due_time": (now + timedelta(hours=4)).isoformat(),
            "estimated_minutes": 90,
        },
        {
            "title": "给伊塔写一封感谢信",
            "priority": "medium",
            "notes": "她今天又陪了我一整天，说点暖心的话",
            "due_time": None,
            "estimated_minutes": 20,
        },
        {
            "title": "整理本周学习笔记",
            "priority": "low",
            "notes": "把这周看的论文和教程整理成思维导图",
            "due_time": None,
            "estimated_minutes": 60,
        },
    ]
    for s in samples:
        add_todo(date_str=date_str, **s)
    return get_todos(date_str)

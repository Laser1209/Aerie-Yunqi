"""Aerie · 云栖 v9.0 — Proactive push log.

Tracks all proactive push attempts (success / skipped / failed) for
auditability and policy enforcement (daily count, last push time).
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from core.database import Database


class PushLog:
    """CRUD wrapper around the push_log table."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()

    def write(
        self,
        scene: str,
        user_id: int,
        content: str,
        status: str,
        reason: str = "",
    ) -> None:
        """Record a push attempt result."""
        self.db.insert(
            "push_log",
            {
                "scene": scene,
                "user_id": user_id,
                "content": content,
                "status": status,
                "reason": reason,
            },
        )

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Return most recent push log entries."""
        return self.db.query(
            "SELECT scene, user_id, content, status, reason, created_at "
            "FROM push_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def get_today_count(self, user_id: int) -> int:
        """Count successful pushes for a user today."""
        today = date.today().isoformat()
        rows = self.db.query(
            "SELECT COUNT(*) AS cnt FROM push_log "
            "WHERE user_id = ? AND status = 'success' AND date(created_at) = ?",
            (user_id, today),
        )
        return rows[0]["cnt"] if rows else 0

    def get_last_push_time(self, user_id: int) -> Optional[datetime]:
        """Return timestamp of the most recent push to a user."""
        rows = self.db.query(
            "SELECT created_at FROM push_log "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        if not rows:
            return None
        raw = rows[0]["created_at"]
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            return datetime.fromisoformat(raw)
        return None

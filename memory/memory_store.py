"""Aerie · 云栖 v0.1.0-beta.1 — Long-term memory store."""

from __future__ import annotations
from typing import Any


class LongTermMemory:
    def __init__(self, db: Any = None) -> None:
        self.db = db

    def store(
        self,
        user_id: int,
        memory_type: str,
        content: str,
        importance: int = 5,
        *,
        actor_id: str | None = None,
    ) -> int:
        if not self.db:
            return 0
        return self.db.insert("long_term_memory", {
            "user_id": user_id,
            "actor_id": actor_id,
            "memory_type": memory_type,
            "content": content,
            "importance": importance,
        })

    def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        *,
        actor_id: str | None = None,
    ) -> list[dict]:
        if not self.db:
            return []
        if actor_id:
            sql = (
                "SELECT * FROM long_term_memory WHERE actor_id = ? "
                "ORDER BY importance DESC, created_at DESC LIMIT ?"
            )
            params = (actor_id, limit)
        else:
            sql = (
                "SELECT * FROM long_term_memory WHERE user_id = ? "
                "ORDER BY importance DESC, created_at DESC LIMIT ?"
            )
            params = (user_id, limit)
        try:
            rows = self.db.query(sql, params)
            if query:
                keywords = query.strip().split()
                rows = [r for r in rows if any(kw in r.get("content", "") for kw in keywords)]
            return rows[:limit]
        except Exception:
            return []

    def decay(self) -> None:
        """Reduce importance of old memories."""
        if not self.db:
            return
        try:
            self.db.execute(
                "UPDATE long_term_memory SET importance = MAX(0, importance - 1) "
                "WHERE importance > 1 AND accessed_at < datetime('now', '-14 days')"
            )
        except Exception:
            pass

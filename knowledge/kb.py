"""Aerie · 云栖 v9.0 — Knowledge base (lightweight SQLite-backed)."""

from __future__ import annotations
from typing import Any


class KnowledgeBase:
    def __init__(self, db: Any = None) -> None:
        self.db = db

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Simple keyword search over knowledge_base table."""
        if not self.db:
            return []
        keywords = query.strip().split()
        if not keywords:
            return []

        conditions = " OR ".join(["content LIKE ?" for _ in keywords])
        params = tuple(f"%{kw}%" for kw in keywords)
        sql = f"SELECT * FROM knowledge_base WHERE {conditions} LIMIT ?"
        params = params + (limit,)
        try:
            return self.db.query(sql, params)
        except Exception:
            return []

    def add(self, category: str, title: str, content: str, tags: str = "") -> int:
        if not self.db:
            return 0
        return self.db.insert("knowledge_base", {
            "category": category,
            "title": title,
            "content": content,
            "tags": tags,
        })

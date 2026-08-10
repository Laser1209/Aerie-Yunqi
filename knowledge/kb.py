"""Aerie · 云栖 v0.1.0-beta.1 — Knowledge base (lightweight SQLite-backed)."""

from __future__ import annotations
from datetime import datetime
from typing import Any


class KnowledgeBase:
    def __init__(self, db: Any = None) -> None:
        self.db = db

    def search(
        self, query: str, limit: int = 5, category: str | None = None
    ) -> list[dict]:
        """Simple keyword search over knowledge_base table.

        Args:
            query: space-separated keywords; matched against content and tags.
            limit: max rows.
            category: optional exact category filter; when provided only rows
                of this category are returned (category match takes priority).
        """
        if not self.db:
            return []
        keywords = query.strip().split()
        if not keywords:
            return []

        # 每个关键词独立匹配 title/content/tags（任一命中即算），
        # 避免"整句拼接"导致逗号分隔的 tags 永远匹配不到。
        per_kw = " OR ".join(
            ["(title LIKE ? OR content LIKE ? OR tags LIKE ?)" for _ in keywords]
        )
        params: list[Any] = []
        for kw in keywords:
            params.extend([f"%{kw}%"] * 3)
        if category:
            conditions = f"(category = ? AND ({per_kw}))"
            params = [category] + params
        else:
            conditions = f"({per_kw})"
        sql = f"SELECT * FROM knowledge_base WHERE {conditions} LIMIT ?"
        params.append(limit)
        try:
            return self.db.query(sql, params)
        except Exception:
            return []

    def get(self, item_id: int) -> dict | None:
        if not self.db:
            return None
        return self.db.query_one("SELECT * FROM knowledge_base WHERE id = ?", (item_id,))

    def list(
        self,
        page: int = 1,
        limit: int = 20,
        category: str = "",
        search: str = "",
    ) -> tuple[list[dict], int]:
        if not self.db:
            return [], 0
        conditions = []
        params: list[Any] = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if search:
            conditions.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern])
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        total_row = self.db.query_one(
            f"SELECT COUNT(*) AS cnt FROM knowledge_base{where}", tuple(params)
        )
        rows = self.db.query(
            f"SELECT * FROM knowledge_base{where} "
            "ORDER BY COALESCE(updated_at, created_at) DESC, id DESC LIMIT ? OFFSET ?",
            tuple(params) + (limit, (page - 1) * limit),
        )
        return rows, int(total_row["cnt"] if total_row else 0)

    def add(self, category: str, title: str, content: str, tags: str = "") -> int:
        if not self.db:
            return 0
        now = datetime.now().isoformat(timespec="microseconds")
        return self.db.insert("knowledge_base", {
            "category": category,
            "title": title,
            "content": content,
            "tags": tags,
            "updated_at": now,
        })

    def update(
        self,
        item_id: int,
        category: str,
        title: str,
        content: str,
        tags: str = "",
    ) -> bool:
        if not self.db:
            return False
        return bool(self.db.update("knowledge_base", {
            "category": category,
            "title": title,
            "content": content,
            "tags": tags,
            "updated_at": datetime.now().isoformat(timespec="microseconds"),
        }, "id = ?", (item_id,)))

    def delete(self, item_id: int) -> bool:
        if not self.db:
            return False
        return bool(self.db.delete("knowledge_base", "id = ?", (item_id,)))

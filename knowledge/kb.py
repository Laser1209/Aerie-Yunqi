"""Aerie · 云栖 v9.0 — Knowledge base.

Categories: persona / user / world / task. Provides add / search / stats.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from core.database import Database


VALID_CATEGORIES = {"persona", "user", "world", "task"}


def _tokenize(text: str) -> set[str]:
    text = re.sub(r"[\s,。.!！？?、,.;:()\[\]\"'`~@#\$%\^&\*\+=/\\|<>{}-]", " ", text or "")
    return {t for t in text.split() if len(t) >= 2}


class KnowledgeBase:
    """Keyword-based knowledge base (4 categories)."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()

    def add(self, category: str, title: str, content: str, tags: str = "") -> int:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"invalid category: {category}")
        return self.db.insert(
            "knowledge_base",
            {
                "category": category,
                "title": title,
                "content": content,
                "tags": tags,
            },
        )

    def search(self, query: str, top_k: int = 3, category: Optional[str] = None) -> list[dict]:
        sql = "SELECT id, category, title, content, tags, created_at FROM knowledge_base"
        params: tuple = ()
        if category:
            sql += " WHERE category = ?"
            params = (category,)
        rows = self.db.query(sql, params)
        q_tokens = _tokenize(query)
        if not q_tokens:
            return rows[:top_k]
        scored: list[tuple[float, dict]] = []
        for r in rows:
            content = r.get("content", "")
            title = r.get("title", "")
            tokens = _tokenize(content + " " + title)
            overlap = len(q_tokens & tokens)
            if overlap == 0:
                if any(t in content for t in q_tokens):
                    overlap = 0.5
                else:
                    continue
            scored.append((overlap, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def stats(self) -> dict:
        rows = self.db.query(
            "SELECT category, COUNT(*) AS n FROM knowledge_base GROUP BY category"
        )
        total = sum(r["n"] for r in rows)
        return {
            "entries": total,
            "categories": len(rows),
            "by_category": {r["category"]: r["n"] for r in rows},
        }

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM knowledge_base")
        return row["n"] if row else 0

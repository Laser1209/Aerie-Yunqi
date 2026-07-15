"""Aerie · 云栖 v9.0 — Long-term memory.

Persistent storage in SQLite. Provides add / search (keyword) /
get_recent with importance sorting.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from core.database import Database


def _tokenize(text: str) -> set[str]:
    text = re.sub(r"[\s,。.!！？?、,.;:()\[\]\"'`~@#\$%\^&\*\+=/\\|<>{}-]", " ", text or "")
    return {t for t in text.split() if len(t) >= 2}


class LongTermMemory:
    """Keyword-based long-term memory (BM25-light)."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()

    def add(
        self,
        user_id: int,
        memory_type: str,
        content: str,
        importance: int = 5,
    ) -> int:
        return self.db.insert(
            "long_term_memory",
            {
                "user_id": user_id,
                "memory_type": memory_type,
                "content": content,
                "importance": max(0, min(10, int(importance))),
            },
        )

    def search(self, user_id: int, query: str, top_k: int = 5) -> list[dict]:
        """Return top-k memories matching query, sorted by relevance * importance."""
        rows = self.db.query(
            "SELECT id, memory_type, content, importance, created_at "
            "FROM long_term_memory WHERE user_id = ?",
            (user_id,),
        )
        q_tokens = _tokenize(query)
        if not q_tokens:
            return sorted(rows, key=lambda r: r.get("importance", 0), reverse=True)[:top_k]
        scored: list[tuple[float, dict]] = []
        for r in rows:
            content = r.get("content", "")
            tokens = _tokenize(content)
            if not tokens:
                continue
            overlap = len(q_tokens & tokens)
            if overlap == 0:
                # Try substring fallback
                if any(t in content for t in q_tokens):
                    overlap = 0.5
                else:
                    continue
            score = overlap * (1 + r.get("importance", 0) / 10.0)
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def get_recent(self, user_id: int, limit: int = 10) -> list[dict]:
        return self.db.query(
            "SELECT id, memory_type, content, importance, created_at "
            "FROM long_term_memory WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    def count(self, user_id: int) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM long_term_memory WHERE user_id = ?",
            (user_id,),
        )
        return row["n"] if row else 0

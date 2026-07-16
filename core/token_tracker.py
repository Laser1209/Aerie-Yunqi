"""Aerie · 云栖 v9.0 — Token usage tracker.

Records LLM token consumption per call, supports daily/weekly/monthly aggregation.
Integrated with brain.py and pipeline.py for automatic recording.
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class TokenTracker:
    """Track and aggregate LLM token usage."""

    def __init__(self, db: Any = None) -> None:
        self._db = db
        self._ensure_table()

    def set_db(self, db: Any) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        if not self._db:
            return
        try:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_user
                ON token_usage(user_id, created_at)
            """)
        except Exception as e:
            logger.warning("Failed to create token_usage table: %s", e)

    def record(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        user_id: int = 0,
    ) -> None:
        """Record one LLM call's token usage."""
        if not self._db:
            return
        total = prompt_tokens + completion_tokens
        try:
            self._db.insert("token_usage", {
                "user_id": user_id,
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
            })
            logger.debug("Token record: %s %s → %d tokens", provider, model, total)
        except Exception as e:
            logger.warning("Failed to record token usage: %s", e)

    def get_today(self, user_id: int = 0) -> dict:
        """Get today's token usage summary."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self._aggregate(
            "WHERE user_id = ? AND date(created_at) = ?",
            (user_id, today),
        )

    def get_week(self, user_id: int = 0) -> dict:
        """Get this week's token usage summary."""
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        return self._aggregate(
            "WHERE user_id = ? AND date(created_at) >= ?",
            (user_id, week_ago),
        )

    def get_month(self, user_id: int = 0) -> dict:
        """Get this month's token usage summary."""
        month_start = datetime.now().strftime("%Y-%m-01")
        return self._aggregate(
            "WHERE user_id = ? AND date(created_at) >= ?",
            (user_id, month_start),
        )

    def get_by_provider(self, user_id: int = 0) -> dict:
        """Get token usage broken down by provider."""
        if not self._db:
            return {}
        try:
            rows = self._db.query(
                """SELECT provider,
                   SUM(prompt_tokens) as prompt,
                   SUM(completion_tokens) as completion,
                   SUM(total_tokens) as total,
                   COUNT(*) as calls
                FROM token_usage
                WHERE user_id = ?
                GROUP BY provider""",
                (user_id,),
            )
            return {row["provider"]: dict(row) for row in rows}
        except Exception as e:
            logger.warning("Failed to query by provider: %s", e)
            return {}

    def _aggregate(self, where_clause: str, params: tuple) -> dict:
        if not self._db:
            return {"prompt": 0, "completion": 0, "total": 0, "calls": 0}
        try:
            row = self._db.query_one(
                f"""SELECT
                    COALESCE(SUM(prompt_tokens), 0) as prompt,
                    COALESCE(SUM(completion_tokens), 0) as completion,
                    COALESCE(SUM(total_tokens), 0) as total,
                    COUNT(*) as calls
                FROM token_usage {where_clause}""",
                params,
            )
            if row:
                return {k: (row[k] if row[k] is not None else 0) for k in row}
        except Exception as e:
            logger.warning("Failed to aggregate token stats: %s", e)
        return {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


# Singleton
_TOKEN_TRACKER: TokenTracker | None = None


def get_token_tracker(db: Any = None) -> TokenTracker:
    global _TOKEN_TRACKER
    if _TOKEN_TRACKER is None:
        _TOKEN_TRACKER = TokenTracker(db)
    elif db is not None and _TOKEN_TRACKER._db is None:
        _TOKEN_TRACKER.set_db(db)
    return _TOKEN_TRACKER

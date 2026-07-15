"""Aerie · 云栖 v9.0 — Token usage tracker.

Records every LLM call into the token_usage table and provides
aggregation queries.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Optional

from core.database import Database


class TokenTracker:
    """Records and aggregates LLM token usage per user / model / provider."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()

    def record(
        self,
        user_id: int,
        provider: str,
        model: str,
        scene: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        total = prompt_tokens + completion_tokens
        return self.db.insert(
            "token_usage",
            {
                "user_id": user_id,
                "provider": provider,
                "model": model,
                "scene": scene,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
                "duration_ms": duration_ms,
                "success": 1 if success else 0,
                "error_message": error_message,
            },
        )

    def get_today_stats(self, user_id: int) -> dict:
        """Return today's totals for a user."""
        today = datetime.now().strftime("%Y-%m-%d")
        rows = self.db.query(
            "SELECT provider, model, SUM(total_tokens) AS tokens, "
            "COUNT(*) AS calls, SUM(duration_ms) AS total_ms, "
            "SUM(success) AS successes "
            "FROM token_usage WHERE user_id = ? AND created_at LIKE ? "
            "GROUP BY provider, model",
            (user_id, f"{today}%"),
        )
        total_tokens = sum(r["tokens"] or 0 for r in rows)
        total_calls = sum(r["calls"] or 0 for r in rows)
        total_success = sum(r["successes"] or 0 for r in rows)
        return {
            "date": today,
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "success_rate": (total_success / total_calls) if total_calls else 0.0,
            "by_model": rows,
        }

    def get_by_model(self, user_id: int, days: int = 7) -> list[dict]:
        """Return per-model usage over the last N days."""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return self.db.query(
            "SELECT provider, model, SUM(total_tokens) AS tokens, "
            "COUNT(*) AS calls, AVG(duration_ms) AS avg_ms, "
            "SUM(success) AS successes "
            "FROM token_usage WHERE user_id = ? AND created_at >= ? "
            "GROUP BY provider, model",
            (user_id, since),
        )

    def get_recent_calls(self, user_id: int, limit: int = 20) -> list[dict]:
        return self.db.query(
            "SELECT provider, model, scene, total_tokens, duration_ms, "
            "success, error_message, created_at "
            "FROM token_usage WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    def get_model_health(self) -> list[dict]:
        """Return per-provider health summary over the last hour."""
        since = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        return self.db.query(
            "SELECT provider, COUNT(*) AS calls, "
            "AVG(duration_ms) AS avg_ms, "
            "SUM(success) AS successes, "
            "AVG(CASE WHEN success=1 THEN 1.0 ELSE 0.0 END) AS success_rate "
            "FROM token_usage WHERE created_at >= ? GROUP BY provider",
            (since,),
        )

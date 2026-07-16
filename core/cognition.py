"""Aerie · 云栖 v9.0 — Cognition engine (Phase 9: brain center trace).

Provides a structured 9-stage trace for every incoming message:
  1. route
  2. emotion
  3. threshold
  4. context
  5. brain
  6. tools
  7. split
  8. postprocess
  9. output

Plus two extra trace blobs:
  - decision_trace  (multi-layer decision scores from §10.2)
  - react_trace     (LLM thought / action / observation)

Persistence target: cognition_log table.
Realtime target:    stderr [CHAT_EVENT] lines, picked up by SSE.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from core.chat_events import emit as stderr_emit

logger = logging.getLogger(__name__)

# Stages — keep as a list so the brain panel can show them in order
STAGES: list[str] = [
    "route",          # 1
    "emotion",        # 2
    "threshold",      # 3
    "context",        # 4
    "brain",          # 5
    "tools",          # 6
    "split",          # 7
    "postprocess",    # 8
    "output",         # 9
]


class CognitionEngine:
    """Records the per-message 9-stage trace + decision/react sub-traces."""

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Lifecycle ──────────────────────────────────────
    def begin(
        self,
        user_id: int,
        source: str,
        user_message: str,
    ) -> dict:
        """Start a new trace. Returns an in-memory trace dict."""
        return {
            "id": None,
            "ts": int(time.time() * 1000),
            "user_id": user_id,
            "source": source,
            "user_message": user_message,
            "stages": {},
            "decision_trace": None,
            "react_trace": None,
            "is_command": 0,
            "duration_ms": 0,
        }

    def record(self, trace: dict, stage: str, payload: Any) -> None:
        """Record a single stage payload; also push to SSE as a stage event."""
        if stage not in STAGES:
            logger.warning("unknown stage %s — accepted anyway", stage)
        trace["stages"][stage] = payload
        # Realtime push: don't block on failure
        try:
            stderr_emit(
                "cognition_stage",
                stage=stage,
                user_id=trace["user_id"],
                payload=payload,
            )
        except Exception:
            pass

    def record_decision(self, trace: dict, decision: Any) -> None:
        trace["decision_trace"] = decision
        try:
            stderr_emit(
                "decision_made",
                user_id=trace["user_id"],
                chosen=(decision or {}).get("chosen"),
            )
        except Exception:
            pass

    def record_react(self, trace: dict, react: Any) -> None:
        trace["react_trace"] = react

    def mark_command(self, trace: dict) -> None:
        """Mark this trace as originating from an IRC/QQ command."""
        trace["is_command"] = 1

    def commit(self, trace: dict, route_mode: str) -> int:
        """Persist the trace into cognition_log. Returns row id, or 0 on failure."""
        try:
            row_id = self._db.insert(
                "cognition_log",
                {
                    "ts": trace["ts"],
                    "source": trace["source"],
                    "user_id": trace["user_id"],
                    "user_message": trace["user_message"],
                    "route_mode": route_mode,
                    "stage_route": json.dumps(
                        trace["stages"].get("route"), ensure_ascii=False
                    ),
                    "stage_emotion": json.dumps(
                        trace["stages"].get("emotion"), ensure_ascii=False
                    ),
                    "stage_threshold": json.dumps(
                        trace["stages"].get("threshold"), ensure_ascii=False
                    ),
                    "stage_context": json.dumps(
                        trace["stages"].get("context"), ensure_ascii=False
                    ),
                    "stage_brain": json.dumps(
                        trace["stages"].get("brain"), ensure_ascii=False
                    ),
                    "stage_tools": json.dumps(
                        trace["stages"].get("tools"), ensure_ascii=False
                    ),
                    "stage_split": json.dumps(
                        trace["stages"].get("split"), ensure_ascii=False
                    ),
                    "stage_postprocess": json.dumps(
                        trace["stages"].get("postprocess"), ensure_ascii=False
                    ),
                    "stage_output": json.dumps(
                        trace["stages"].get("output"), ensure_ascii=False
                    ),
                    "decision_trace": json.dumps(
                        trace["decision_trace"], ensure_ascii=False
                    ),
                    "react_trace": json.dumps(
                        trace["react_trace"], ensure_ascii=False
                    ),
                    "is_command": trace["is_command"],
                    "duration_ms": int(time.time() * 1000) - trace["ts"],
                },
            )
            trace["id"] = row_id
            try:
                stderr_emit(
                    "cognition_committed",
                    id=row_id,
                    user_id=trace["user_id"],
                    duration_ms=trace["duration_ms"],
                )
            except Exception:
                pass
            return row_id
        except Exception:
            logger.exception("cognition commit error")
            return 0

    # ── Read helpers (used by API) ─────────────────────
    def recent(self, user_id: Optional[int] = None, source: Optional[str] = None,
               limit: int = 20) -> list[dict]:
        sql = "SELECT id, ts, source, user_id, user_message, route_mode, " \
              "is_command, duration_ms, created_at FROM cognition_log"
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self._db.query(sql, tuple(params))

    def get(self, row_id: int) -> Optional[dict]:
        return self._db.query_one(
            "SELECT * FROM cognition_log WHERE id = ?", (row_id,)
        )

    def stats(self) -> dict:
        total = self._db.query_one(
            "SELECT COUNT(*) AS n FROM cognition_log"
        ) or {"n": 0}
        today = self._db.query_one(
            "SELECT COUNT(*) AS n FROM cognition_log "
            "WHERE date(created_at, 'localtime') = date('now', 'localtime')"
        ) or {"n": 0}
        avg = self._db.query_one(
            "SELECT COALESCE(AVG(duration_ms), 0) AS a FROM cognition_log"
        ) or {"a": 0}
        return {
            "total": total["n"],
            "today": today["n"],
            "avg_duration_ms": round(avg["a"], 1),
        }

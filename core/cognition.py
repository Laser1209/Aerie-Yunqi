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

    def patch_stage_output(self, trace_id: int, output_payload: dict) -> bool:
        """Re-write the ``stage_output`` column on an already-committed row.

        The pacing decisions for the assistant segments are computed
        AFTER commit (because they depend on segment_content and need
        the next-style tree). Rather than refactor the entire pipeline
        to commit twice, we expose this small patch so the pipeline /
        send_queue can attach pacing_decisions without losing them.

        Idempotent: re-writing the same payload is a no-op.

        Returns True on success, False on any failure (logged).
        """
        if not trace_id:
            return False
        try:
            self._db.update(
                "cognition_log",
                {
                    "stage_output": json.dumps(
                        output_payload, ensure_ascii=False
                    ),
                },
                "id = ?",
                (int(trace_id),),
            )
            return True
        except Exception:
            logger.exception("cognition patch_stage_output error id=%s", trace_id)
            return False

    def patch_decision(self, trace_id: int, decision_payload: dict) -> bool:
        """Re-write the ``decision_trace`` column on an already-committed row."""
        if not trace_id:
            return False
        try:
            self._db.update(
                "cognition_log",
                {
                    "decision_trace": json.dumps(
                        decision_payload, ensure_ascii=False
                    ),
                },
                "id = ?",
                (int(trace_id),),
            )
            return True
        except Exception:
            logger.exception("cognition patch_decision error id=%s", trace_id)
            return False

    def append_pacing_decisions(
        self, trace_id: int, additional: list[dict]
    ) -> bool:
        """Append pacing decisions to stage_output.pacing_decisions.

        Phase 9 Batch 7 (B7.2): pacing for QQ messages is computed inside
        SendQueue (which runs in a separate worker task), so the values
        arrive AFTER the pipeline has already committed the trace. We
        cannot rewrite the entire stage_output blindly (the local path
        may have written first), so this method appends to the
        existing ``pacing_decisions`` list, de-duplicating by
        (seg_idx, style).

        Idempotent: re-appending the same item is a no-op.

        Returns True on success, False on any failure (logged).
        """
        if not trace_id or not additional:
            return False
        try:
            row = self._db.query_one(
                "SELECT stage_output FROM cognition_log WHERE id = ?",
                (int(trace_id),),
            )
            if not row:
                logger.warning(
                    "append_pacing_decisions: no row id=%s", trace_id
                )
                return False

            raw = row.get("stage_output")
            current: dict = {}
            if raw and isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        current = parsed
                except Exception:
                    pass
            elif isinstance(raw, dict):
                current = raw

            existing = current.get("pacing_decisions") or []
            if not isinstance(existing, list):
                existing = []

            # de-dup by (seg_idx, style) — keep the first occurrence.
            seen: set[tuple] = {
                (int(x.get("seg_idx", -1)), str(x.get("style") or x.get("next_style") or ""))
                for x in existing
            }
            for item in additional:
                if not isinstance(item, dict):
                    continue
                key = (
                    int(item.get("seg_idx", -1)),
                    str(item.get("style") or item.get("next_style") or ""),
                )
                if key in seen:
                    continue
                existing.append(item)
                seen.add(key)

            current["pacing_decisions"] = existing
            self._db.update(
                "cognition_log",
                {
                    "stage_output": json.dumps(
                        current, ensure_ascii=False
                    ),
                },
                "id = ?",
                (int(trace_id),),
            )
            return True
        except Exception:
            logger.exception(
                "cognition append_pacing_decisions error id=%s", trace_id
            )
            return False

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

"""Aerie · 云栖 v0.1.0-beta.1 — Emotion state persistence store (Phase 9 Batch 1).

Persists emotion state + threshold values into ``emotion_state_snapshot``
so the dashboard can show 24h / 7d / 30d curves and we survive restarts.

Schema (already created in core/database.py):
    ts INTEGER NOT NULL                  -- unix ms
    user_id INTEGER NOT NULL
    pleasure REAL
    arousal REAL
    dominance REAL
    label TEXT
    patience_value REAL
    anxiety_value REAL
    desire_value REAL
    tenderness_value REAL
    active_eruption TEXT
    trigger_event TEXT                   -- 'user_msg' | 'eruption' | 'daily_decay' | 'startup'
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))

The store is intentionally read-heavy (dashboard) and write-light
(one row per inbound message). All operations are best-effort —
any DB error returns an empty result rather than raising, so the
emotion engine never crashes the main pipeline.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class EmotionStateStore:
    """Persist + query emotion state snapshots."""

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Write ─────────────────────────────────────────
    def snapshot(
        self,
        user_id: int,
        state: dict,
        threshold: dict,
        trigger_event: str = "user_msg",
    ) -> int:
        """Insert one snapshot row. Returns row id (0 on failure)."""
        try:
            pad = (state or {}).get("pad") or {}
            thresholds = threshold or {}
            eruption = thresholds.get("active_eruption") if isinstance(thresholds, dict) else None
            if not isinstance(eruption, dict):
                eruption = None

            row = {
                "ts": int(time.time() * 1000),
                "user_id": int(user_id or 0),
                "pleasure": float(pad.get("P", pad.get("pleasure", 0.0)) or 0.0),
                "arousal": float(pad.get("A", pad.get("arousal", 0.0)) or 0.0),
                "dominance": float(pad.get("D", pad.get("dominance", 0.0)) or 0.0),
                "label": (state or {}).get("label", "neutral") or "neutral",
                "patience_value": float((thresholds.get("patience") or {}).get("value", 0.0) or 0.0),
                "anxiety_value": float((thresholds.get("anxiety") or {}).get("value", 0.0) or 0.0),
                "desire_value": float((thresholds.get("desire") or {}).get("value", 0.0) or 0.0),
                "tenderness_value": float((thresholds.get("tenderness") or {}).get("value", 0.0) or 0.0),
                "active_eruption": (eruption or {}).get("mode") if eruption else None,
                "trigger_event": trigger_event,
            }
            return self._db.insert("emotion_state_snapshot", row)
        except Exception:
            logger.exception("emotion_state_store.snapshot error")
            return 0

    # ── Read ──────────────────────────────────────────
    def history(
        self,
        user_id: int,
        since_ts: int,
        limit: int = 2000,
    ) -> list[dict]:
        """Return snapshots newer than since_ts, ascending by ts."""
        try:
            return self._db.query(
                "SELECT * FROM emotion_state_snapshot "
                "WHERE user_id = ? AND ts >= ? "
                "ORDER BY ts ASC LIMIT ?",
                (int(user_id or 0), int(since_ts), int(limit)),
            )
        except Exception:
            logger.exception("emotion_state_store.history error")
            return []

    def latest(self, user_id: int) -> Optional[dict]:
        try:
            return self._db.query_one(
                "SELECT * FROM emotion_state_snapshot "
                "WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (int(user_id or 0),),
            )
        except Exception:
            logger.exception("emotion_state_store.latest error")
            return None

    def aggregate(
        self,
        user_id: int,
        since_ts: int,
        bucket_ms: int = 60_000,
        limit: int = 2000,
    ) -> list[dict]:
        """Bucket-aggregated history. Each bucket averages PAD + 4 slots.

        Useful for the 7d/30d line chart so 5k+ points collapse to ~hundreds.
        """
        try:
            rows = self.history(user_id, since_ts, limit=limit)
            if not rows:
                return []
            buckets: dict[int, dict] = {}
            for r in rows:
                ts = int(r.get("ts") or 0)
                bidx = ts // bucket_ms
                b = buckets.setdefault(bidx, {
                    "ts": bidx * bucket_ms,
                    "pleasure": 0.0, "arousal": 0.0, "dominance": 0.0,
                    "patience_value": 0.0, "anxiety_value": 0.0,
                    "desire_value": 0.0, "tenderness_value": 0.0,
                    "n": 0, "labels": {},
                    "active_eruption": None,
                })
                b["pleasure"] += float(r.get("pleasure") or 0.0)
                b["arousal"] += float(r.get("arousal") or 0.0)
                b["dominance"] += float(r.get("dominance") or 0.0)
                b["patience_value"] += float(r.get("patience_value") or 0.0)
                b["anxiety_value"] += float(r.get("anxiety_value") or 0.0)
                b["desire_value"] += float(r.get("desire_value") or 0.0)
                b["tenderness_value"] += float(r.get("tenderness_value") or 0.0)
                b["n"] += 1
                label = r.get("label")
                if label:
                    b["labels"][label] = b["labels"].get(label, 0) + 1
                if r.get("active_eruption"):
                    b["active_eruption"] = r["active_eruption"]
            out: list[dict] = []
            for bidx in sorted(buckets.keys()):
                b = buckets[bidx]
                n = max(1, b["n"])
                labels = b["labels"] or {}
                out.append({
                    "ts": b["ts"],
                    "pleasure": round(b["pleasure"] / n, 3),
                    "arousal": round(b["arousal"] / n, 3),
                    "dominance": round(b["dominance"] / n, 3),
                    "patience_value": round(b["patience_value"] / n, 1),
                    "anxiety_value": round(b["anxiety_value"] / n, 1),
                    "desire_value": round(b["desire_value"] / n, 1),
                    "tenderness_value": round(b["tenderness_value"] / n, 1),
                    "n": b["n"],
                    "label": max(labels.items(), key=lambda kv: kv[1])[0] if labels else "neutral",
                    "active_eruption": b["active_eruption"],
                })
            return out
        except Exception:
            logger.exception("emotion_state_store.aggregate error")
            return []

    def count(self, user_id: Optional[int] = None) -> int:
        try:
            if user_id is None:
                row = self._db.query_one("SELECT COUNT(*) AS n FROM emotion_state_snapshot")
            else:
                row = self._db.query_one(
                    "SELECT COUNT(*) AS n FROM emotion_state_snapshot WHERE user_id = ?",
                    (int(user_id),),
                )
            return int((row or {}).get("n", 0))
        except Exception:
            return 0

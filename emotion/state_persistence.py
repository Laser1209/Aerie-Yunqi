"""Aerie · 云栖 v9.0 — Emotion state persistence.

Saves and restores PAD state snapshots to the emotion_log table,
enabling continuity across restarts.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from core.database import Database
from core.emotion_engine import PADState


class StatePersistence:
    """Persist emotional state to SQLite for cross-session continuity."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()

    def save_state(self, user_id: int, pad: PADState, event_type: str = "snapshot") -> None:
        """Write current PAD state to emotion_log."""
        self.db.insert(
            "emotion_log",
            {
                "user_id": user_id,
                "event_type": event_type,
                "pleasure": round(pad.pleasure, 4),
                "arousal": round(pad.arousal, 4),
                "dominance": round(pad.dominance, 4),
                "label": pad.label,
                "timestamp": datetime.now().isoformat(),
            },
        )

    def load_state(self, user_id: int) -> Optional[PADState]:
        """Restore the most recent PAD state from emotion_log."""
        rows = self.db.query(
            "SELECT pleasure, arousal, dominance, label FROM emotion_log "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return PADState(
            pleasure=float(r["pleasure"]),
            arousal=float(r["arousal"]),
            dominance=float(r["dominance"]),
            label=r["label"],
        )

    def export_history(self, user_id: int, limit: int = 50) -> list[dict]:
        """Return recent emotion log entries as dicts."""
        return self.db.query(
            "SELECT event_type, pleasure, arousal, dominance, label, timestamp "
            "FROM emotion_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

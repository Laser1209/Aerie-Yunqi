"""Image generation budget — local self-accounting.

Counts image generations per day by kind (``proactive`` / ``manual``) and
persists to a JSON state file so the daily quota survives restarts. It is
decoupled from the image provider so it works regardless of whether the
provider exposes a balance endpoint (the current third-party relay does not
guarantee one).

Kinds:
  - ``proactive``: AI / auto-initiated image sends (bounded by the daily quota).
  - ``manual``:    user-triggered generations (recorded but not counted toward
                   the proactive quota; reserved for future use).

A ``limit`` of ``0`` means unlimited for that kind.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_LIMITS: dict[str, int] = {"proactive": 0, "manual": 0}

# Human-readable reasons returned by :meth:`can_record`.
REASON_UNLIMITED = "unlimited"
REASON_OK = "ok"
REASON_LIMIT_REACHED = "daily_image_limit"


class ImageBudget:
    """Thread-safe, JSON-persisted daily image generation counter."""

    def __init__(
        self,
        *,
        state_path: str | Path,
        clock: Callable[[], datetime] | None = None,
        enabled: bool = True,
        limits: dict[str, int] | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.enabled = bool(enabled)
        self.limits: dict[str, int] = {**DEFAULT_LIMITS, **(limits or {})}
        self._lock = threading.RLock()
        self._clock = clock or datetime.now
        self._today = ""
        self._counts: dict[str, int] = {}
        self._load()

    # ── Public API ──────────────────────────────────────────────

    def limit(self, kind: str) -> int:
        """Return the configured daily limit for ``kind`` (0 == unlimited)."""
        return int(self.limits.get(kind, 0) or 0)

    def set_limit(self, kind: str, limit: int) -> None:
        """Hot-update the daily limit for ``kind`` (0 == unlimited).

        Callers may invoke this when the user edits the proactive image limit
        in settings, so the running budget picks it up without a restart.
        """
        with self._lock:
            self.limits[kind] = int(limit) if int(limit) > 0 else 0

    def used(self, kind: str) -> int:
        """Return how many generations of ``kind`` happened today."""
        self._ensure_today()
        with self._lock:
            return int(self._counts.get(kind, 0))

    def can_record(self, kind: str) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` for recording one generation of ``kind``."""
        if not self.enabled:
            return True, REASON_UNLIMITED
        limit = self.limit(kind)
        if limit <= 0:
            return True, REASON_UNLIMITED
        with self._lock:
            self._ensure_today()
            if int(self._counts.get(kind, 0)) >= limit:
                return False, REASON_LIMIT_REACHED
            return True, REASON_OK

    def record(self, kind: str) -> int:
        """Increment today's counter for ``kind`` and return the new total.

        Recording is not blocked when the quota is reached; callers should use
        :meth:`can_record` before generating.
        """
        with self._lock:
            self._ensure_today()
            current = int(self._counts.get(kind, 0)) + 1
            self._counts[kind] = current
            self._persist()
            return current

    def snapshot(self) -> dict[str, Any]:
        """Return a public, read-only summary for UI display."""
        self._ensure_today()
        with self._lock:
            return {
                "today": self._today,
                "proactive": {
                    "used": int(self._counts.get("proactive", 0)),
                    "limit": self.limit("proactive"),
                    "remaining": max(0, self.limit("proactive") - int(self._counts.get("proactive", 0))),
                },
                "enabled": self.enabled,
            }

    # ── Internal state ──────────────────────────────────────────

    def _ensure_today(self) -> None:
        today = self._clock().date().isoformat()
        with self._lock:
            if today != self._today:
                self._today = today
                self._counts = {}
                self._persist()

    def _load(self) -> None:
        with self._lock:
            try:
                if not self.state_path.exists():
                    self._today = self._clock().date().isoformat()
                    self._counts = {}
                    return
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("image budget state corrupt: %s", self.state_path, exc_info=True)
                self._today = self._clock().date().isoformat()
                self._counts = {}
                return
            stored_today = str(data.get("today") or "")
            counts = data.get("counts")
            if not isinstance(counts, dict):
                counts = {}
            today = self._clock().date().isoformat()
            if stored_today == today:
                self._today = today
                self._counts = {k: int(v) for k, v in counts.items() if isinstance(v, (int, float))}
            else:
                # Cross-day boundary: reset counts but keep the same state file.
                self._today = today
                self._counts = {}
                self._persist()

    def _persist(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "today": self._today,
                        "counts": self._counts,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            tmp.replace(self.state_path)
        except Exception:
            logger.warning("image budget persist failed: %s", self.state_path, exc_info=True)

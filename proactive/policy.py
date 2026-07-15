"""Aerie · 云栖 v9.0 — Push policy.

Five-gate check before any proactive push:
1. Global enabled
2. Pause-until window
3. Daily cap
4. Quiet period (with exempt scenes)
5. Minimum interval since last push
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from typing import Optional

from config.persona_loader import load_proactive


def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _in_quiet_window(now: dtime, start: dtime, end: dtime) -> bool:
    """Return True if `now` is in [start, end), handling cross-midnight."""
    if start <= end:
        return start <= now < end
    # Cross-midnight: e.g. 23:30 - 07:00
    return now >= start or now < end


class PushPolicy:
    """Authoritative gatekeeper for proactive pushes."""

    def __init__(self, config: Optional[dict] = None) -> None:
        cfg = config or load_proactive()
        p = cfg.get("proactive", {})
        self.enabled: bool = p.get("enabled", True)
        self.max_per_day: int = p.get("max_per_day", 5)
        self.min_interval_min: int = p.get("min_interval_min", 30)
        self.quiet_start: dtime = _parse_hhmm(p.get("quiet_start", "23:30"))
        self.quiet_end: dtime = _parse_hhmm(p.get("quiet_end", "07:00"))
        self.exempt_scenes: set[str] = set(p.get("exempt_scenes", []))
        self.timezone = p.get("timezone", "Asia/Shanghai")

        # Runtime state
        self.pause_until: Optional[datetime] = None
        self.last_push_at: Optional[datetime] = None
        self.daily_count: int = 0
        self.daily_count_date: str = datetime.now().strftime("%Y-%m-%d")

    def _maybe_reset_daily(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        if today != self.daily_count_date:
            self.daily_count = 0
            self.daily_count_date = today

    def can_push(self, scene: str, now: Optional[datetime] = None) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        if not self.enabled:
            return False, "global_disabled"
        now = now or datetime.now()
        self._maybe_reset_daily(now)
        if self.pause_until and now < self.pause_until:
            return False, "paused"
        if self.daily_count >= self.max_per_day:
            return False, "daily_cap"
        in_quiet = _in_quiet_window(now.time(), self.quiet_start, self.quiet_end)
        if in_quiet and scene not in self.exempt_scenes:
            return False, "quiet_period"
        if self.last_push_at:
            elapsed = (now - self.last_push_at).total_seconds() / 60.0
            if elapsed < self.min_interval_min:
                return False, "min_interval"
        return True, "ok"

    def record(self, scene: str, now: Optional[datetime] = None) -> None:
        """Mark a successful push."""
        now = now or datetime.now()
        self._maybe_reset_daily(now)
        self.last_push_at = now
        self.daily_count += 1

    def pause(self, minutes: int = 60) -> None:
        self.pause_until = datetime.now() + timedelta(minutes=minutes)

    def pause_until(self, when: datetime) -> None:
        self.pause_until = when

    def resume(self) -> None:
        self.pause_until = None

    def get_state(self) -> dict:
        return {
            "enabled": self.enabled,
            "max_per_day": self.max_per_day,
            "min_interval_min": self.min_interval_min,
            "quiet_start": self.quiet_start.strftime("%H:%M"),
            "quiet_end": self.quiet_end.strftime("%H:%M"),
            "exempt_scenes": sorted(self.exempt_scenes),
            "pause_until": self.pause_until.isoformat() if self.pause_until else None,
            "last_push_at": self.last_push_at.isoformat() if self.last_push_at else None,
            "daily_count": self.daily_count,
            "daily_count_date": self.daily_count_date,
        }

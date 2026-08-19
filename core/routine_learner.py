"""RoutineLearner — 近 7 天滚动作息学习（起床/入睡窗口）。

Design (Proactive Push v2, §6.3): learns the user's typical first/last
message times from ``chat_log`` (role='user', local timezone), filters
noise days, and exposes a RoutineWindow used by PulsePlanner/scheduler to
shift cron anchors and skip silent hours. Persists a JSON snapshot so a
restarted backend continues from the learned window.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WINDOW_DAILY = """
    SELECT MIN(created_at), MAX(created_at), COUNT(*)
    FROM chat_log
    WHERE user_id = ? AND role = 'user' AND date(created_at) = ?
"""


@dataclass
class RoutineProfile:
    day: date
    first: time | None = None
    last: time | None = None
    count: int = 0

    @property
    def span_hours(self) -> float:
        if not (self.first and self.last):
            return 0.0
        first_s = self.first.hour * 3600 + self.first.minute * 60 + self.first.second
        last_s = self.last.hour * 3600 + self.last.minute * 60 + self.last.second
        return (last_s - first_s) / 3600.0


@dataclass
class RoutineWindow:
    wake_time: time | None = None       # 平均起床（首条消息）时刻
    sleep_time: time | None = None      # 平均入睡（末条消息）时刻
    silent_start: time | None = None    # 静默开始 = sleep_time ≈ +30min
    enabled: bool = False
    days: int = 0                        # 参与统计的有效天数
    span_hours: float = 0.0              # 平均活跃跨度

    def as_dict(self) -> dict[str, Any]:
        def _t(v: time | None) -> str | None:
            return v.isoformat() if v else None

        return {
            "wake_time": _t(self.wake_time),
            "sleep_time": _t(self.sleep_time),
            "silent_start": _t(self.silent_start),
            "enabled": self.enabled,
            "days": self.days,
            "span_hours": self.span_hours,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "RoutineWindow":
        def _t(v: Any) -> time | None:
            if not v:
                return None
            if isinstance(v, time):
                return v
            try:
                return time.fromisoformat(str(v))
            except (TypeError, ValueError):
                return None

        return RoutineWindow(
            wake_time=_t(d.get("wake_time")),
            sleep_time=_t(d.get("sleep_time")),
            silent_start=_t(d.get("silent_start")),
            enabled=bool(d.get("enabled")) and _t(d.get("wake_time")) is not None,
            days=int(d.get("days") or 0),
            span_hours=float(d.get("span_hours") or 0.0),
        )


class RoutineLearner:
    """Learn wake/sleep times from the 7-day message history."""

    def __init__(
        self,
        db: Any,
        *,
        window_days: int = 7,
        min_msgs_per_day: int = 3,
        min_span_hours: float = 8.0,
        state_path: str | os.PathLike | None = None,
    ) -> None:
        self.db = db
        self.window_days = window_days
        self.min_msgs_per_day = min_msgs_per_day
        self.min_span_hours = min_span_hours
        self.state_path = Path(state_path) if state_path else None
        self._cached: RoutineWindow | None = None

    # ── query ─────────────────────────────────────────────
    def _daily(self, user_id: int, day: date) -> RoutineProfile:
        try:
            row = self.db.execute(
                _WINDOW_DAILY,
                (int(user_id), day.isoformat()),
            ).fetchone()
        except Exception:
            logger.debug("[RoutineLearner] daily query failed: %s", day)
            return RoutineProfile(day=day)
        return self._row_to_profile(day, row)

    def _row_to_profile(self, day: date, row: Any) -> RoutineProfile:
        if not row or row[2] is None:
            return RoutineProfile(day=day)
        count = int(row[2] or 0)
        first = self._parse_ts(row[0])
        last = self._parse_ts(row[1])
        return RoutineProfile(day=day, first=first, last=last, count=count)

    @staticmethod
    def _parse_ts(value: Any) -> time | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        return dt.time()

    def learn(self, user_id: int, today: date | None = None) -> RoutineWindow:
        """Re-derive the routine window from the last N days."""
        today = today or date.today()
        profiles: list[RoutineProfile] = []
        for i in range(self.window_days):
            day = today - timedelta(days=i)
            profile = self._daily(user_id, day)
            if profile.count >= self.min_msgs_per_day \
               and profile.span_hours >= self.min_span_hours:
                profiles.append(profile)
        if not profiles:
            window = RoutineWindow()
        else:
            def _secs(t: time | None) -> float:
                return (t.hour * 3600 + t.minute * 60 + t.second) if t else 0.0

            avg_first = sum(_secs(p.first) for p in profiles) / len(profiles)
            avg_last = sum(_secs(p.last) for p in profiles) / len(profiles)

            def _to_time(secs: float) -> time:
                secs = int(secs) % 86400
                return time(secs // 3600, (secs // 60) % 60, secs % 60)

            wake = _to_time(avg_first)
            sleep = _to_time(avg_last)
            silent = _to_time(avg_last + 60 * 60) if avg_last >= 0 else None
            window = RoutineWindow(
                wake_time=wake,
                sleep_time=sleep,
                silent_start=silent,
                enabled=True,
                days=len(profiles),
                span_hours=sum(p.span_hours for p in profiles) / len(profiles),
            )
        self._cached = window
        if self.state_path is not None:
            self._persist()
        logger.info(
            "[RoutineLearner] wake=%s sleep=%s days=%d",
            window.wake_time, window.sleep_time, window.days,
        )
        return window

    def window(self, user_id: int | None = None, *, refresh: bool = False) -> RoutineWindow:
        """Cached window; refreshes when the learner has no cache yet."""
        if refresh or self._cached is None:
            if user_id is not None and self.db is not None:
                self._cached = self.learn(user_id)
            elif self._cached is None:
                self._cached = RoutineWindow()
        return self._cached

    # ------------------------------------------------------------------ persistence
    def _persist(self) -> None:
        if not self.state_path:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(self._cached.as_dict() if self._cached else {}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.debug("[RoutineLearner] persist failed", exc_info=True)

    def load_state(self) -> RoutineWindow:
        """Load a previously persisted window (no re-learn)."""
        if not self.state_path or not self.state_path.exists():
            return RoutineWindow()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._cached = RoutineWindow.from_dict(data) if isinstance(data, dict) else RoutineWindow()
        except Exception:
            self._cached = RoutineWindow()
        return self._cached
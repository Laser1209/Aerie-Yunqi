"""Aerie v0.1.0-beta.1 · 日历管理器

支持：日程、纪念日、倒计时、日志
与对话联动：Agent 可以通过工具调用创建事件
"""

from __future__ import annotations
import time
import logging
from calendar import monthrange
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

EVENT_TYPES = {
    "schedule": "日程",
    "anniversary": "纪念日",
    "countdown": "倒计时",
    "journal": "日志",
    "reminder": "提醒",
}

EVENT_COLORS = {
    "schedule": "#ff9a9e",
    "anniversary": "#a18cd1",
    "countdown": "#fad0c4",
    "journal": "#84fab0",
    "reminder": "#fccb90",
}

REPEAT_TYPES = {"none", "daily", "weekly", "monthly", "yearly"}
REMIND_BEFORE_VALUES = {-1, 0, 5, 15, 30, 60, 1440}


def _normalize_choice(value: Any, allowed: set[str], field: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ValueError(f"invalid {field}")
    return normalized


def _normalize_datetime(value: Any, field: str, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    return parsed.isoformat(timespec="seconds")


def _normalize_all_day(value: Any) -> int:
    if isinstance(value, bool) or value in (0, 1):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return 1
        if normalized in {"false", "0"}:
            return 0
    raise ValueError("invalid all_day")


def _normalize_remind_before(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid remind_before") from exc
    if normalized not in REMIND_BEFORE_VALUES or isinstance(value, float) and value != normalized:
        raise ValueError("invalid remind_before")
    return normalized


def _shift_month(origin: datetime, months: int) -> datetime:
    month_index = origin.year * 12 + origin.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return origin.replace(year=year, month=month, day=min(origin.day, monthrange(year, month)[1]))


def _shift_year(origin: datetime, years: int) -> datetime:
    year = origin.year + years
    return origin.replace(year=year, day=min(origin.day, monthrange(year, origin.month)[1]))


class CalendarManager:
    """日历事件管理器"""

    def __init__(self, db):
        self._db = db
        self._migrate_anniversaries()

    def _migrate_anniversaries(self):
        """从旧的 anniversary 表迁移数据到 calendar_events"""
        try:
            rows = self._db.query(
                "SELECT * FROM anniversary WHERE 1=1"
            ) or []
            if not rows:
                return
            for row in rows:
                legacy_source = f"migrated_anniversary:{row['id']}"
                exists = self._db.query_one(
                    "SELECT id FROM calendar_events WHERE source = ?", (legacy_source,)
                )
                if exists:
                    continue
                self.create_event(
                    title=row["name"],
                    description=row.get("description", ""),
                    event_type="anniversary",
                    start_time=row["date"] + "T00:00:00",
                    all_day=1,
                    color=EVENT_COLORS["anniversary"],
                    remind_before=row.get("remind_before_days", 0),
                    source=legacy_source,
                )
            logger.info("calendar: migrated %d anniversaries", len(rows))
        except Exception as e:
            logger.exception("calendar migrate error: %s", e)

    def create_event(self, **kwargs) -> int:
        """创建日历事件，返回事件 ID"""
        title = kwargs.get("title", "").strip()
        if not title:
            raise ValueError("title is required")
        event_type = _normalize_choice(kwargs.get("event_type", "schedule"), set(EVENT_TYPES), "event_type")
        start_time = _normalize_datetime(
            kwargs.get("start_time", datetime.now()), "start_time", required=True
        )
        end_time = _normalize_datetime(kwargs.get("end_time"), "end_time")
        if end_time and end_time < start_time:
            raise ValueError("end_time cannot be before start_time")
        all_day = _normalize_all_day(kwargs.get("all_day", 1))
        color = kwargs.get("color") or EVENT_COLORS.get(event_type, "#ff9a9e")
        description = kwargs.get("description", "")
        repeat_type = _normalize_choice(kwargs.get("repeat_type", "none"), REPEAT_TYPES, "repeat_type")
        remind_before = _normalize_remind_before(kwargs.get("remind_before", 0))
        source = kwargs.get("source", "manual")
        user_id = kwargs.get("user_id")

        result = self._db.execute(
            """
            INSERT INTO calendar_events
                (title, description, event_type, start_time, end_time, all_day,
                 color, repeat_type, remind_before, source, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, description, event_type, start_time, end_time, all_day,
             color, repeat_type, remind_before, source, user_id),
        )
        return result.lastrowid

    def update_event(self, event_id: int, **kwargs) -> bool:
        """更新日历事件"""
        existing = self.get_event(event_id)
        if not existing:
            return False
        normalized = dict(kwargs)
        if "title" in normalized:
            normalized["title"] = str(normalized["title"]).strip()
            if not normalized["title"]:
                raise ValueError("title is required")
        if "event_type" in normalized:
            normalized["event_type"] = _normalize_choice(normalized["event_type"], set(EVENT_TYPES), "event_type")
        if "repeat_type" in normalized:
            normalized["repeat_type"] = _normalize_choice(normalized["repeat_type"], REPEAT_TYPES, "repeat_type")
        if "remind_before" in normalized:
            normalized["remind_before"] = _normalize_remind_before(normalized["remind_before"])
        if "all_day" in normalized:
            normalized["all_day"] = _normalize_all_day(normalized["all_day"])
        for field in ("start_time", "end_time"):
            if field in normalized:
                normalized[field] = _normalize_datetime(
                    normalized[field], field, required=field == "start_time"
                )
        start_time = normalized.get("start_time", existing["start_time"])
        end_time = normalized.get("end_time", existing["end_time"])
        if end_time and end_time < start_time:
            raise ValueError("end_time cannot be before start_time")
        fields = []
        values = []
        allowed = [
            "title", "description", "event_type", "start_time", "end_time",
            "all_day", "color", "repeat_type", "remind_before",
        ]
        for key in allowed:
            if key in normalized:
                fields.append(f"{key} = ?")
                values.append(normalized[key])
        if not fields:
            return False
        fields.append("updated_at = datetime('now', 'localtime')")
        values.append(event_id)
        self._db.execute(
            f"UPDATE calendar_events SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        return True

    def delete_event(self, event_id: int) -> bool:
        """删除日历事件"""
        return self._db.delete("calendar_events", "id = ?", (event_id,)) > 0

    def get_event(self, event_id: int) -> Optional[dict]:
        """获取单个事件详情"""
        row = self._db.query_one(
            "SELECT * FROM calendar_events WHERE id = ?",
            (event_id,),
        )
        return dict(row) if row else None

    def list_events(self, start_date: str = None, end_date: str = None,
                    event_type: str = None, limit: int = 200,
                    user_id: int | None = None) -> list[dict]:
        """列出指定时间范围内的事件"""
        sql = "SELECT * FROM calendar_events WHERE 1=1"
        params = []
        if start_date:
            sql += " AND (end_time IS NULL OR end_time >= ?)"
            params.append(start_date)
        if end_date:
            sql += " AND start_time <= ?"
            params.append(end_date)
        if event_type and event_type in EVENT_TYPES:
            sql += " AND event_type = ?"
            params.append(event_type)
        if user_id is not None:
            sql += " AND (user_id = ? OR user_id = 0 OR user_id IS NULL)"
            params.append(user_id)
        sql += " ORDER BY start_time ASC LIMIT ?"
        params.append(limit)
        rows = self._db.query(sql, tuple(params)) or []
        return [dict(r) for r in rows]

    def _event_instances(self, event: dict, range_start: datetime, range_end: datetime) -> list[dict]:
        origin = datetime.fromisoformat(event["start_time"])
        duration = None
        if event.get("end_time"):
            duration = datetime.fromisoformat(event["end_time"]) - origin
        repeat_type = event.get("repeat_type") or "none"
        starts = []
        if repeat_type == "none":
            event_end = origin + duration if duration is not None else origin
            if origin <= range_end and event_end >= range_start:
                starts.append(origin)
        else:
            if repeat_type == "daily":
                step = max(0, (range_start.date() - origin.date()).days - 1)
                occurrence = origin + timedelta(days=step)
                advance = lambda current, index: current + timedelta(days=1)
            elif repeat_type == "weekly":
                step = max(0, (range_start.date() - origin.date()).days // 7 - 1)
                occurrence = origin + timedelta(weeks=step)
                advance = lambda current, index: current + timedelta(weeks=1)
            elif repeat_type == "monthly":
                step = max(0, (range_start.year - origin.year) * 12 + range_start.month - origin.month - 1)
                occurrence = _shift_month(origin, step)
                advance = lambda current, index: _shift_month(origin, index)
            else:
                step = max(0, range_start.year - origin.year - 1)
                occurrence = _shift_year(origin, step)
                advance = lambda current, index: _shift_year(origin, index)
            index = step
            while occurrence <= range_end:
                occurrence_end = occurrence + duration if duration is not None else occurrence
                if occurrence >= origin and occurrence_end >= range_start:
                    starts.append(occurrence)
                index += 1
                occurrence = advance(occurrence, index)

        instances = []
        for occurrence in starts:
            start_time = occurrence.isoformat(timespec="seconds")
            repeated = repeat_type != "none"
            instance_id = f"{event['id']}:{start_time}" if repeated else str(event["id"])
            instance = dict(event)
            instance.update(
                start_time=start_time,
                end_time=(occurrence + duration).isoformat(timespec="seconds") if duration is not None else None,
                event_id=event["id"],
                instance_id=instance_id,
                repeat_type=repeat_type,
                remind_before=int(event.get("remind_before") or 0),
            )
            instances.append(instance)
        return instances

    def _events_in_range(
        self, start_date: str, end_date: str, user_id: int | None = None
    ) -> list[dict]:
        range_start = datetime.fromisoformat(start_date)
        range_end = datetime.fromisoformat(end_date)
        sql = "SELECT * FROM calendar_events WHERE start_time <= ?"
        params: list[Any] = [end_date]
        if user_id is not None:
            sql += " AND (user_id = ? OR user_id = 0 OR user_id IS NULL)"
            params.append(user_id)
        rows = self._db.query(sql + " ORDER BY start_time ASC", tuple(params)) or []
        instances = []
        for event in rows:
            instances.extend(self._event_instances(event, range_start, range_end))
        return sorted(instances, key=lambda item: item["start_time"])

    def get_timeline(self, start_date: str, end_date: str, user_id: int | None = None) -> dict:
        events = self._events_in_range(start_date, end_date, user_id)
        params = [start_date, end_date]
        sql = "SELECT * FROM todo WHERE due_at >= ? AND due_at <= ?"
        if user_id is not None:
            sql += " AND (user_id = ? OR user_id = 0)"
            params.append(user_id)
        todos = self._db.query(sql + " ORDER BY due_at ASC", tuple(params)) or []
        items = []
        for event in events:
            repeated = event["repeat_type"] != "none"
            item_id = f"event:{event['instance_id']}" if repeated else f"event:{event['id']}"
            items.append({"id": item_id, "kind": "event", "type": event["event_type"],
                          "event_id": event["event_id"], "instance_id": event["instance_id"],
                          "repeat_type": event["repeat_type"], "remind_before": event["remind_before"],
                          "title": event["title"], "description": event.get("description", ""),
                          "start_time": event["start_time"], "end_time": event.get("end_time"),
                          "all_day": bool(event.get("all_day")), "color": event.get("color"),
                          "completed": None, "priority": None, "editable": True, "source": event.get("source", "manual")})
        for todo in todos:
            items.append({"id": f"todo:{todo['external_id']}", "kind": "todo", "type": "todo",
                          "title": todo["title"], "description": todo.get("notes") or "",
                          "start_time": todo.get("due_at"), "end_time": None, "all_day": False,
                          "color": None, "completed": todo.get("status") == "done",
                          "priority": todo.get("priority"), "editable": True, "source": "todo"})
        items.sort(key=lambda item: item.get("start_time") or "")
        return {"items": items, "counts": {"total": len(items), "events": len(events), "todos": len(todos),
                "pending": sum(item["completed"] is False for item in items)}}

    def collect_due_reminders(
        self, now: datetime | None = None, lookback_minutes: int = 5
    ) -> list[dict]:
        now = now or datetime.now()
        if lookback_minutes < 0:
            raise ValueError("lookback_minutes cannot be negative")
        window_start = now - timedelta(minutes=lookback_minutes)
        max_remind_before = max(REMIND_BEFORE_VALUES)
        event_range_start = window_start
        event_range_end = now + timedelta(minutes=max_remind_before)
        events = self._events_in_range(
            event_range_start.isoformat(timespec="seconds"),
            event_range_end.isoformat(timespec="seconds"),
        )
        due = []
        for event in events:
            if event["remind_before"] < 0:
                continue
            remind_at = datetime.fromisoformat(event["start_time"]) - timedelta(
                minutes=event["remind_before"]
            )
            if not window_start <= remind_at <= now:
                continue
            record = dict(event)
            record["remind_at"] = remind_at.isoformat(timespec="seconds")
            due.append(record)

        collected = []
        for reminder in sorted(due, key=lambda item: item["remind_at"]):
            cursor = self._db.execute(
                """INSERT OR IGNORE INTO calendar_reminder_log
                   (event_id, instance_id, remind_at) VALUES (?, ?, ?)""",
                (reminder["event_id"], reminder["instance_id"], reminder["remind_at"]),
            )
            if cursor.rowcount:
                collected.append(reminder)
        return collected

    def get_agent_snapshot(self, user_id: int, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        date = now.strftime("%Y-%m-%d")
        end = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
        today = self.get_timeline(date + "T00:00:00", date + "T23:59:59", user_id)
        upcoming = self.list_events(date + "T00:00:00", end, "anniversary", 20, user_id)
        return {"date": date, "today_events": [i for i in today["items"] if i["kind"] == "event"],
                "today_todos": [i for i in today["items"] if i["kind"] == "todo" and not i["completed"]],
                "upcoming_anniversaries": [{"title": i["title"], "start_time": i["start_time"]} for i in upcoming[:10]]}

    def get_stats(self) -> dict:
        """获取日历统计信息"""
        try:
            total = self._db.query_one(
                "SELECT COUNT(*) AS n FROM calendar_events"
            ) or {"n": 0}
            by_type = {}
            for t in EVENT_TYPES:
                row = self._db.query_one(
                    "SELECT COUNT(*) AS n FROM calendar_events WHERE event_type = ?",
                    (t,),
                )
                by_type[t] = row["n"] if row else 0
            upcoming = self.list_events(
                start_date=datetime.now().strftime("%Y-%m-%dT00:00:00"),
                end_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59"),
                limit=10,
            )
            return {
                "total": total["n"],
                "by_type": by_type,
                "upcoming": upcoming,
            }
        except Exception as e:
            logger.exception("calendar stats error: %s", e)
            return {"total": 0, "by_type": {}, "upcoming": []}

    def get_day_events(self, date_str: str) -> list[dict]:
        """获取某天的所有事件"""
        start = date_str + "T00:00:00"
        end = date_str + "T23:59:59"
        return self.list_events(start_date=start, end_date=end)

    def get_companion_stats(self, first_start_ts: int = None) -> dict:
        """获取陪伴统计：相识天数、消息数等"""
        try:
            now = datetime.now()
            if first_start_ts:
                first_date = datetime.fromtimestamp(first_start_ts)
            else:
                row = self._db.query_one(
                    "SELECT MIN(created_at) AS first FROM chat_log"
                )
                if row and row["first"]:
                    try:
                        first_date = datetime.fromisoformat(row["first"])
                    except Exception:
                        first_date = now
                else:
                    first_date = now
            days_together = max(1, (now - first_date).days + 1)

            user_msg_row = self._db.query_one(
                "SELECT COUNT(*) AS n FROM chat_log WHERE role = 'user'"
            )
            companion_msg_row = self._db.query_one(
                "SELECT COUNT(*) AS n FROM chat_log WHERE role = 'assistant'"
            )
            user_msgs = user_msg_row["n"] if user_msg_row else 0
            companion_msgs = companion_msg_row["n"] if companion_msg_row else 0

            return {
                "days_together": days_together,
                "first_date": first_date.strftime("%Y-%m-%d"),
                "user_messages": user_msgs,
                "companion_messages": companion_msgs,
            }
        except Exception as e:
            logger.exception("companion stats error: %s", e)
            return {
                "days_together": 1,
                "first_date": datetime.now().strftime("%Y-%m-%d"),
                "user_messages": 0,
                "companion_messages": 0,
            }

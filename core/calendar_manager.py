"""Aerie v12.0.1 · 日历管理器

支持：日程、纪念日、倒计时、日志
与对话联动：Agent 可以通过工具调用创建事件
"""

from __future__ import annotations
import time
import logging
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


class CalendarManager:
    """日历事件管理器"""

    def __init__(self, db):
        self._db = db
        self._migrate_anniversaries()

    def _migrate_anniversaries(self):
        """从旧的 anniversary 表迁移数据到 calendar_events"""
        try:
            rows = self._db.query_all(
                "SELECT * FROM anniversary WHERE 1=1"
            ) or []
            if not rows:
                return
            existing = self._db.query_all(
                "SELECT id FROM calendar_events WHERE source = 'migrated_anniversary'"
            ) or []
            if existing:
                return
            for row in rows:
                self.create_event(
                    title=row["name"],
                    description=row.get("description", ""),
                    event_type="anniversary",
                    start_time=row["date"] + "T00:00:00",
                    all_day=1,
                    color=EVENT_COLORS["anniversary"],
                    remind_before=row.get("remind_before_days", 0),
                    source="migrated_anniversary",
                )
            logger.info("calendar: migrated %d anniversaries", len(rows))
        except Exception as e:
            logger.exception("calendar migrate error: %s", e)

    def create_event(self, **kwargs) -> int:
        """创建日历事件，返回事件 ID"""
        title = kwargs.get("title", "").strip()
        if not title:
            raise ValueError("title is required")
        event_type = kwargs.get("event_type", "schedule")
        if event_type not in EVENT_TYPES:
            event_type = "schedule"
        start_time = kwargs.get("start_time")
        if not start_time:
            start_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        end_time = kwargs.get("end_time")
        all_day = kwargs.get("all_day", 1)
        color = kwargs.get("color") or EVENT_COLORS.get(event_type, "#ff9a9e")
        description = kwargs.get("description", "")
        repeat_type = kwargs.get("repeat_type", "none")
        remind_before = kwargs.get("remind_before", 0)
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
        fields = []
        values = []
        allowed = [
            "title", "description", "event_type", "start_time", "end_time",
            "all_day", "color", "repeat_type", "remind_before",
        ]
        for key in allowed:
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
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
        self._db.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
        return True

    def get_event(self, event_id: int) -> Optional[dict]:
        """获取单个事件详情"""
        row = self._db.query_one(
            "SELECT * FROM calendar_events WHERE id = ?",
            (event_id,),
        )
        return dict(row) if row else None

    def list_events(self, start_date: str = None, end_date: str = None,
                    event_type: str = None, limit: int = 200) -> list[dict]:
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
        sql += " ORDER BY start_time ASC LIMIT ?"
        params.append(limit)
        rows = self._db.query_all(sql, tuple(params)) or []
        return [dict(r) for r in rows]

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

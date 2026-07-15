"""聊天日志存储

Phase 2：SQLite 单表存储，异步接口
Phase 3+：可扩展加密（SQLCipher）

表结构：
  chat_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id      INTEGER,           -- QQ 消息 ID
    user_id     INTEGER NOT NULL,  -- 发送者 QQ 号
    self_id     INTEGER,           -- 接收者 QQ 号（伊塔）
    role        TEXT NOT NULL,     -- 'user' | 'assistant' | 'system'
    content     TEXT NOT NULL,     -- 消息内容
    intent      TEXT,              -- 意图分类结果 (Phase 2+)
    msg_type    TEXT,              -- private | group | temp
    timestamp   REAL NOT NULL,     -- Unix timestamp
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
  )

索引：
  - idx_chat_log_user_id ON chat_log(user_id)
  - idx_chat_log_timestamp ON chat_log(timestamp)
"""

from __future__ import annotations

import sqlite3
import asyncio
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from communication.message import IncomingMessage, OutgoingReply, MessageType


# ===== 表创建 DDL =====
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chat_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id      INTEGER,
    user_id     INTEGER NOT NULL,
    self_id     INTEGER,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    intent      TEXT,
    msg_type    TEXT,
    timestamp   REAL NOT NULL,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
)
"""

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_chat_log_user_id ON chat_log(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_chat_log_timestamp ON chat_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_chat_log_role ON chat_log(role)",
]


class ChatLogger:
    """异步 SQLite 聊天日志存储"""

    def __init__(self, db_path: str = "data/chat_log.db"):
        """
        Args:
            db_path: SQLite 数据库文件路径（相对于项目根目录或绝对路径）
        """
        if not os.path.isabs(db_path):
            # 相对于 main.py 所在目录
            self._db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", db_path)
        else:
            self._db_path = db_path

        # 确保目录存在
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        # 线程本地连接池（SQLite 要求同线程使用）
        self._local = threading.local()
        self._lock = asyncio.Lock()
        self._initialized = False

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    async def initialize(self) -> None:
        """初始化数据库表和索引（幂等）"""
        async with self._lock:
            conn = self._get_conn()
            conn.execute(CREATE_TABLE_SQL)
            for idx_sql in CREATE_INDEXES_SQL:
                conn.execute(idx_sql)
            conn.commit()
            self._initialized = True
            logger.info(f"聊天日志已初始化: {self._db_path}")

    def _run_sync(self, func, *args, **kwargs):
        """在默认线程池中运行同步 SQLite 操作"""
        conn = self._get_conn()
        result = func(conn, *args, **kwargs)
        conn.commit()
        return result

    async def log_incoming(self, msg: IncomingMessage, intent: Optional[str] = None) -> int:
        """
        记录收到的消息。

        Args:
            msg: 收到的消息
            intent: 意图分类结果

        Returns:
            插入的行 ID
        """
        def _insert(conn, msg, intent):
            return conn.execute(
                """INSERT INTO chat_log (msg_id, user_id, self_id, role, content, intent, msg_type, timestamp)
                   VALUES (?, ?, ?, 'user', ?, ?, ?, ?)""",
                (
                    msg.msg_id,
                    msg.user_id,
                    msg.self_id,
                    msg.content,
                    intent,
                    msg.msg_type.value,
                    msg.timestamp.timestamp(),
                ),
            ).lastrowid

        return await asyncio.get_event_loop().run_in_executor(
            None, self._run_sync, _insert, msg, intent
        )

    async def log_outgoing(self, reply: OutgoingReply, in_reply_to_msg_id: Optional[int] = None) -> int:
        """
        记录发出的回复。

        Args:
            reply: 发出的回复
            in_reply_to_msg_id: 回复的消息 ID

        Returns:
            插入的行 ID
        """
        def _insert(conn, reply, in_reply_to_msg_id):
            return conn.execute(
                """INSERT INTO chat_log (msg_id, user_id, self_id, role, content, msg_type, timestamp)
                   VALUES (?, ?, ?, 'assistant', ?, ?, ?)""",
                (
                    in_reply_to_msg_id or 0,
                    reply.user_id,
                    0,  # self_id 在实际场景中由环境变量提供
                    reply.content,
                    reply.msg_type.value,
                    datetime.now().timestamp(),
                ),
            ).lastrowid

        return await asyncio.get_event_loop().run_in_executor(
            None, self._run_sync, _insert, reply, in_reply_to_msg_id
        )

    async def get_recent(
        self,
        user_id: int,
        limit: int = 20,
        role: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取指定用户的最近聊天记录。

        Args:
            user_id: 用户 QQ 号
            limit: 返回条数
            role: 过滤角色 ('user' | 'assistant' | None=不限制)

        Returns:
            [{"role": "user", "content": "...", "timestamp": ..., ...}, ...]
        """
        def _query(conn, user_id, limit, role):
            if role:
                rows = conn.execute(
                    """SELECT role, content, timestamp, intent, msg_type
                       FROM chat_log
                       WHERE user_id = ? AND role = ?
                       ORDER BY timestamp DESC
                       LIMIT ?""",
                    (user_id, role, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT role, content, timestamp, intent, msg_type
                       FROM chat_log
                       WHERE user_id = ?
                       ORDER BY timestamp DESC
                       LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            # 反转时间序（最早在前）
            return [dict(row) for row in reversed(rows)]

        return await asyncio.get_event_loop().run_in_executor(
            None, self._run_sync, _query, user_id, limit, role
        )

    async def get_stats(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        获取聊天统计。

        Args:
            user_id: 指定用户，None 则全局统计

        Returns:
            {"total_user_msgs": N, "total_assistant_msgs": N, "unique_users": N, ...}
        """
        def _query(conn, user_id):
            if user_id:
                row = conn.execute(
                    """SELECT
                         COUNT(CASE WHEN role='user' THEN 1 END) as user_msgs,
                         COUNT(CASE WHEN role='assistant' THEN 1 END) as assistant_msgs,
                         MAX(timestamp) as last_msg_time
                       FROM chat_log WHERE user_id = ?""",
                    (user_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT
                         COUNT(CASE WHEN role='user' THEN 1 END) as user_msgs,
                         COUNT(CASE WHEN role='assistant' THEN 1 END) as assistant_msgs,
                         COUNT(DISTINCT user_id) as unique_users,
                         MAX(timestamp) as last_msg_time
                       FROM chat_log""",
                ).fetchone()
            return dict(row) if row else {}

        return await asyncio.get_event_loop().run_in_executor(
            None, self._run_sync, _query, user_id
        )

    async def close(self) -> None:
        """关闭数据库连接"""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
            logger.debug("聊天日志连接已关闭")

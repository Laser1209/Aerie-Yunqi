"""待办管理工具

使用独立 SQLite 数据库 data/todo.db

支持操作：
- todo_create — 创建待办
- todo_list — 列出待办
- todo_complete — 完成待办
- todo_delete — 删除待办
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from tools.base import Tool


# ===== 数据库路径 =====
_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_DB_PATH = os.path.join(_DB_DIR, "todo.db")

CREATE_TODO_TABLE = """
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    completed   INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
    completed_at TEXT
)
"""


class _TodoDB:
    """线程安全的 SQLite 连接管理"""

    def __init__(self):
        os.makedirs(_DB_DIR, exist_ok=True)
        self._local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(_DB_PATH)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute(CREATE_TODO_TABLE)
            self._local.conn.commit()
        return self._local.conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._get_conn()
        c = conn.execute(sql, params)
        conn.commit()
        return c

    def fetchall(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.execute(sql, params).fetchall()]


_db = _TodoDB()


class TodoCreateTool(Tool):
    name = "todo_create"
    description = "创建一条新的待办事项"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "待办事项内容",
                },
            },
            "required": ["content"],
        }

    async def execute(self, content: str = "", **kwargs) -> Tuple[bool, str]:
        if not content:
            return False, "错误：待办内容不能为空"

        try:
            _db.execute(
                "INSERT INTO todos (user_id, content) VALUES (?, ?)",
                (0, content),  # user_id=0 表示本地用户
            )
            logger.debug(f"todo_create: {content}")
            return True, f"✅ 已创建待办: {content}"
        except Exception as e:
            return False, f"创建待办失败: {e}"


class TodoListTool(Tool):
    name = "todo_list"
    description = "列出所有待办事项。可选择性筛选未完成/已完成的。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["all", "active", "completed"],
                    "description": "筛选状态：all=全部, active=未完成, completed=已完成",
                },
            },
            "required": [],
        }

    async def execute(self, status: str = "active", **kwargs) -> Tuple[bool, str]:
        try:
            if status == "completed":
                rows = _db.fetchall(
                    "SELECT * FROM todos WHERE completed=1 ORDER BY completed_at DESC"
                )
            elif status == "active":
                rows = _db.fetchall(
                    "SELECT * FROM todos WHERE completed=0 ORDER BY created_at DESC"
                )
            else:
                rows = _db.fetchall(
                    "SELECT * FROM todos ORDER BY completed ASC, created_at DESC"
                )

            if not rows:
                return True, "📋 暂无待办事项"

            lines = ["📋 待办列表:"]
            for r in rows:
                mark = "☑" if r["completed"] else "☐"
                created = r["created_at"][:16] if r["created_at"] else ""
                line = f"  {mark} [{r['id']}] {r['content']}"
                if r["completed"]:
                    line += f" ✅ ({r.get('completed_at', '')[:16]})"
                else:
                    line += f" 📅 {created}"
                lines.append(line)

            logger.debug(f"todo_list: {status} → {len(rows)} 项")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"列出待办失败: {e}"


class TodoCompleteTool(Tool):
    name = "todo_complete"
    description = "将指定 ID 的待办事项标记为已完成"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "integer",
                    "description": "待办事项的 ID（从 todo_list 获取）",
                },
            },
            "required": ["todo_id"],
        }

    async def execute(self, todo_id: int = 0, **kwargs) -> Tuple[bool, str]:
        if not todo_id:
            return False, "错误：请提供待办 ID"

        try:
            row = _db.fetchall("SELECT * FROM todos WHERE id=? AND completed=0", (todo_id,))
            if not row:
                return False, f"未找到 ID={todo_id} 的未完成待办"

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _db.execute(
                "UPDATE todos SET completed=1, completed_at=? WHERE id=?",
                (now, todo_id),
            )
            logger.debug(f"todo_complete: {todo_id}")
            return True, f"✅ 已完成: {row[0]['content']}"
        except Exception as e:
            return False, f"完成待办失败: {e}"


class TodoDeleteTool(Tool):
    name = "todo_delete"
    description = "删除指定 ID 的待办事项"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "integer",
                    "description": "待办事项的 ID（从 todo_list 获取）",
                },
            },
            "required": ["todo_id"],
        }

    async def execute(self, todo_id: int = 0, **kwargs) -> Tuple[bool, str]:
        if not todo_id:
            return False, "错误：请提供待办 ID"

        try:
            row = _db.fetchall("SELECT * FROM todos WHERE id=?", (todo_id,))
            if not row:
                return False, f"未找到 ID={todo_id} 的待办"

            _db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
            logger.debug(f"todo_delete: {todo_id}")
            return True, f"🗑 已删除: {row[0]['content']}"
        except Exception as e:
            return False, f"删除待办失败: {e}"

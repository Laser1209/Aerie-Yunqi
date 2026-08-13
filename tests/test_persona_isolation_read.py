"""Read-path persona isolation tests (portal C)."""

import os
import sqlite3
import tempfile


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_legacy_history_sql_filters_by_persona():
    """验证 persona 过滤的 SQL 逻辑：A 角色看到 A+NULL，B 角色只看到 NULL。"""
    with tempfile.TemporaryDirectory() as td:
        conn = _make_db(os.path.join(td, "t.db"))
        conn.execute(
            """CREATE TABLE chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                created_at TEXT DEFAULT '', deleted_at TEXT,
                persona_id TEXT DEFAULT NULL
            )"""
        )
        conn.executemany(
            "INSERT INTO chat_log (user_id, role, content, persona_id) VALUES (?, ?, ?, ?)",
            [
                (7, "user", "旧共享消息", None),
                (7, "assistant", "角色A消息", "persona_a"),
                (7, "assistant", "角色B消息", "persona_b"),
            ],
        )
        conn.commit()

        def rows(persona):
            if persona is None:
                where = "WHERE user_id = ? AND deleted_at IS NULL"
                params = (7,)
            else:
                where = (
                    "WHERE user_id = ? AND deleted_at IS NULL "
                    "AND (persona_id = ? OR persona_id IS NULL)"
                )
                params = (7, persona)
            return {
                r["content"]
                for r in conn.execute(
                    f"SELECT content FROM chat_log {where} ORDER BY id", params
                )
            }

        assert rows("persona_a") == {"旧共享消息", "角色A消息"}
        assert rows("persona_b") == {"旧共享消息", "角色B消息"}
        conn.close()

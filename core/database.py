"""Aerie · 云栖 v9.0 — Database singleton.

Provides sqlite3-based Database with context-manager support and
8 tables required by the v9.0 spec.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional


# All 8 table schemas. Code-level comments are in English.
SCHEMA_SQL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS chat_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,                 -- 'user' | 'assistant' | 'system'
        content TEXT NOT NULL,
        msg_type TEXT,                      -- private | group | proactive
        route_mode TEXT,                    -- FULL | AUTO | BASIC
        scene TEXT,                         -- daily | emotional | proactive | etc.
        parse_error INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS long_term_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        memory_type TEXT NOT NULL,          -- preference | event | fact | etc.
        content TEXT NOT NULL,
        importance INTEGER DEFAULT 5,       -- 0-10
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        accessed_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_base (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,             -- persona | user | world | task
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        tags TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS todo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        due_at TEXT,
        reminder_at TEXT,
        priority INTEGER DEFAULT 5,         -- 0-10
        status TEXT DEFAULT 'pending',      -- pending | done | cancelled
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        done_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS emotion_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,           -- user_praise | user_cold | user_attack | ...
        intensity REAL DEFAULT 1.0,
        pleasure REAL,
        arousal REAL,
        dominance REAL,
        label TEXT,                         -- joy | sad | anger | fear | neutral
        context TEXT,                       -- JSON snapshot
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS push_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scene TEXT NOT NULL,                -- morning_brief | weather_push | ...
        user_id INTEGER NOT NULL,
        content TEXT,
        status TEXT NOT NULL,               -- success | failed | skipped_daily | skipped_quiet | skipped_pause | skipped_interval
        reason TEXT,
        skip_reason TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        chat_log_id INTEGER,
        feedback_type TEXT NOT NULL,         -- positive | negative | correction | recall
        content TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS token_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        provider TEXT NOT NULL,             -- qwen | deepseek | gemini
        model TEXT NOT NULL,
        scene TEXT,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        success INTEGER DEFAULT 1,
        error_message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_name TEXT NOT NULL,
        user_id INTEGER,
        arguments TEXT,
        result TEXT,
        success INTEGER DEFAULT 1,
        duration_ms INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
]


class Database:
    """SQLite singleton with context-manager support and thread safety."""

    _instance: Optional["Database"] = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "Database":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: str | Path = "data/aerie.db") -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn_lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Open a new connection (caller closes)."""
        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,            # autocommit
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    @contextmanager
    def connection(self) -> Iterable[sqlite3.Connection]:
        """Thread-safe connection context manager."""
        with self._conn_lock:
            conn = self._connect()
            try:
                yield conn
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            for stmt in SCHEMA_SQL:
                conn.execute(stmt)

    # ===== CRUD helpers =====
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self.connection() as conn:
            return conn.execute(sql, params)

    def executemany(self, sql: str, params_list: Iterable[tuple | dict]) -> sqlite3.Cursor:
        with self.connection() as conn:
            return conn.executemany(sql, params_list)

    def insert(self, table: str, data: dict) -> int:
        keys = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({keys}) VALUES ({placeholders})"
        with self.connection() as conn:
            cur = conn.execute(sql, tuple(data.values()))
            return cur.lastrowid or 0

    def update(self, table: str, data: dict, where: str, where_params: tuple = ()) -> int:
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        with self.connection() as conn:
            cur = conn.execute(sql, tuple(data.values()) + tuple(where_params))
            return cur.rowcount

    def delete(self, table: str, where: str, where_params: tuple = ()) -> int:
        sql = f"DELETE FROM {table} WHERE {where}"
        with self.connection() as conn:
            cur = conn.execute(sql, where_params)
            return cur.rowcount

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def list_tables(self) -> list[str]:
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [r["name"] for r in rows]

    def reset(self) -> None:
        """Drop and recreate all tables. For tests only."""
        tables = self.list_tables()
        with self.connection() as conn:
            for t in tables:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
        self._init_schema()


if __name__ == "__main__":
    db = Database("data/aerie.db")
    print("Tables:", db.list_tables())

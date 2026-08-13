"""Tests for migration 013_persona_scoped_dialogue_memory (role isolation)."""

import os
import sqlite3
import tempfile

from core.migrations import (
    MigrationRunner,
    persona_scoped_dialogue_memory_migrations,
)


def _fresh_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_migration_adds_persona_columns():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "t.db")
        conn = _fresh_db(db_path)
        # 先建依赖表（simulate phase3；列需含 013 索引引用的真实列）
        conn.executescript(
            """
            CREATE TABLE conversations (
                conversation_id TEXT PRIMARY KEY,
                actor_id TEXT DEFAULT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE turns (turn_id TEXT PRIMARY KEY);
            CREATE TABLE messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE requests (
                request_id TEXT PRIMARY KEY,
                actor_id TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE long_term_memory (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                importance INTEGER DEFAULT 5
            );
            CREATE TABLE conversation_summary_buckets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_index INTEGER NOT NULL
            );
            """
        )
        runner = MigrationRunner(conn)
        pending = runner.run(persona_scoped_dialogue_memory_migrations())
        assert pending == ["013_persona_scoped_dialogue_memory"]
        for table in (
            "chat_log", "conversations", "turns", "messages",
            "requests", "long_term_memory", "conversation_summary_buckets",
        ):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert "persona_id" in cols, f"{table} 缺 persona_id"
        conn.close()


def test_migration_idempotent():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "t.db")
        conn = _fresh_db(db_path)
        conn.executescript(
            """
            CREATE TABLE conversations (
                conversation_id TEXT PRIMARY KEY,
                actor_id TEXT DEFAULT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE turns (turn_id TEXT PRIMARY KEY);
            CREATE TABLE messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE requests (
                request_id TEXT PRIMARY KEY,
                actor_id TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE long_term_memory (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                importance INTEGER DEFAULT 5
            );
            CREATE TABLE conversation_summary_buckets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_index INTEGER NOT NULL
            );
            """
        )
        runner = MigrationRunner(conn)
        runner.run(persona_scoped_dialogue_memory_migrations())
        second = runner.run(persona_scoped_dialogue_memory_migrations())
        assert second == [], "重复执行不应再返回 pending"
        conn.close()

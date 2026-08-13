"""Memory-chain persona isolation tests (portal D).

验证角色级记忆隔离：
  - MemoryItem DTO 带 persona_id 字段（默认 None）
  - LongTermMemoryLayer 写入时 persona_id 落 SQLite 行
  - SQLite fallback 过滤子句：角色 A 看到 A + NULL 共享，B 只看到 B + NULL
  - 核心断言：角色 A 检索不到角色 B 的记忆

测试仅使用临时目录 / 内存 SQLite，不触碰真实 data/。
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

import pytest

from memory.layers.base import MemoryItem


class SQLiteDB:
    """最小 SQLite 包装，模拟 core.database.Database 的 CRUD 接口."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple = ()) -> Any:
        try:
            return self._conn.execute(sql, params or ())
        except sqlite3.ProgrammingError:
            return self._conn.executescript(sql)

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, params or ()).fetchall()]

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, table: str, data: dict) -> int:
        cols = ", ".join(data.keys())
        ph = ", ".join(["?"] * len(data))
        cur = self._conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({ph})", list(data.values())
        )
        return cur.lastrowid or 0

    def update(self, table: str, data: dict, where: str, where_params: tuple = ()) -> int:
        set_clause = ", ".join(f"{k} = ?" for k in data.keys())
        cur = self._conn.execute(
            f"UPDATE {table} SET {set_clause} WHERE {where}",
            list(data.values()) + list(where_params),
        )
        return cur.rowcount


def _make_layer(tmp_path) -> tuple[SQLiteDB, Any]:
    """构造 LongTermMemoryLayer（临时 chroma 目录、不传 embedding_fn → 走 SQLite 路径）."""
    from memory.layers.long_permanent import LongTermMemoryLayer

    db = SQLiteDB()
    layer = LongTermMemoryLayer(
        db=db,
        chroma_persist_dir=str(tmp_path / "chroma"),
    )
    return db, layer


def test_memory_item_has_persona_id_field():
    """DTO：persona_id 字段存在且默认 None（向后兼容）."""
    item = MemoryItem(content="x")
    assert item.persona_id is None
    item2 = MemoryItem(content="y", persona_id="persona_a")
    assert item2.persona_id == "persona_a"


def test_store_writes_persona_id_to_sqlite(tmp_path):
    """写入：store 时 persona_id 落 SQLite 行（NULL 角色共享记忆保持 NULL）."""
    db, layer = _make_layer(tmp_path)

    async def seed():
        await layer.store(MemoryItem(content="A 专属记忆", importance=8.0, user_id=1), persona_id="persona_a")
        await layer.store(MemoryItem(content="共享记忆", importance=8.0, user_id=1))

    asyncio.run(seed())

    row_a = db.query_one("SELECT persona_id FROM long_term_memory WHERE content = 'A 专属记忆'")
    assert row_a and row_a["persona_id"] == "persona_a"
    row_shared = db.query_one("SELECT persona_id FROM long_term_memory WHERE content = '共享记忆'")
    assert row_shared and row_shared["persona_id"] is None


def test_persona_filter_clause_generation(tmp_path):
    """SQLite fallback 过滤子句：A 角色看到 A+NULL，B 角色只看到 NULL 共享."""
    db = SQLiteDB()
    db.execute("""
        CREATE TABLE long_term_memory (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            memory_type TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            importance REAL DEFAULT 5.0,
            access_count INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0,
            updated_at REAL DEFAULT 0,
            accessed_at REAL DEFAULT 0,
            source TEXT DEFAULT '',
            has_embedding INTEGER DEFAULT 0,
            source_message_id TEXT,
            confidence REAL DEFAULT 0.5,
            user_confirmed INTEGER DEFAULT 0,
            expires_at REAL,
            deleted_at REAL,
            persona_id TEXT
        )
    """)
    db.insert("long_term_memory", {"id": "m1", "user_id": 1, "memory_type": "fact", "content": "A 的偏好", "importance": 8.0, "persona_id": "persona_a"})
    db.insert("long_term_memory", {"id": "m2", "user_id": 1, "memory_type": "fact", "content": "B 的偏好", "importance": 8.0, "persona_id": "persona_b"})
    db.insert("long_term_memory", {"id": "m3", "user_id": 1, "memory_type": "fact", "content": "共享事实", "importance": 8.0, "persona_id": None})

    def filter_ids(persona_id: str | None) -> list[str]:
        sql = """
            SELECT id FROM long_term_memory
            WHERE user_id = ? AND (deleted_at IS NULL OR deleted_at = 0)
        """
        params: list[Any] = [1]
        if persona_id:
            sql += " AND (persona_id = ? OR persona_id IS NULL)"
            params.append(persona_id)
        sql += " ORDER BY id"
        return [r["id"] for r in db.query(sql, tuple(params))]

    assert filter_ids("persona_a") == ["m1", "m3"]
    assert filter_ids("persona_b") == ["m2", "m3"]
    assert filter_ids(None) == ["m1", "m2", "m3"]


def test_retrieve_persona_isolation(tmp_path):
    """核心断言：角色 A 检索不到角色 B 的记忆（A 可见 A + NULL 共享）."""
    _, layer = _make_layer(tmp_path)

    async def seed():
        await layer.store(MemoryItem(content="A 的记忆", importance=8.0, user_id=1), persona_id="persona_a")
        await layer.store(MemoryItem(content="B 的记忆", importance=8.0, user_id=1), persona_id="persona_b")
        await layer.store(MemoryItem(content="共享记忆", importance=8.0, user_id=1))

    asyncio.run(seed())

    async def go():
        hits_a = await layer.retrieve(1, query="记忆", limit=10, persona_id="persona_a")
        hits_b = await layer.retrieve(1, query="记忆", limit=10, persona_id="persona_b")
        hits_none = await layer.retrieve(1, query="记忆", limit=10)
        return hits_a, hits_b, hits_none

    a, b, n = asyncio.run(go())
    contents_a = {r.item.content for r in a}
    contents_b = {r.item.content for r in b}
    contents_n = {r.item.content for r in n}

    assert "B 的记忆" not in contents_a, "角色 A 不得检索到角色 B 的记忆"
    assert "A 的记忆" not in contents_b, "角色 B 不得检索到角色 A 的记忆"
    assert "A 的记忆" in contents_a and "共享记忆" in contents_a
    assert "B 的记忆" in contents_b and "共享记忆" in contents_b
    assert contents_n == {"A 的记忆", "B 的记忆", "共享记忆"}, "无 persona 时保持全量可见"

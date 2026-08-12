"""P1-D.5.3 TDD: LayeredMemory 同步适配器接入生产接口.

验证 sync adapter 在旧 LongTermMemory 接口之上暴露 LayeredMemory：
  - store / retrieve / decay 语义正确
  - 在运行中的 asyncio 事件循环内同步调用不抛 "already running" / 不死锁
    （模拟 context_builder.build 在异步 pipeline 内调用的真实场景）
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from typing import Any

import pytest

from core.knowledge_indexer import _hash_embedding
from memory.layers import LayeredMemory
from memory.layers.sync_adapter import LayeredMemorySyncAdapter


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


def _make_adapter(tmp_path) -> LayeredMemorySyncAdapter:
    db = SQLiteDB()
    layered = LayeredMemory(
        db=db,
        chroma_persist_dir=str(tmp_path / "chroma"),
        permanent_dir=str(tmp_path / "permanent"),
        embedding_fn=_hash_embedding,
    )
    return LayeredMemorySyncAdapter(layered)


def test_adapter_store_retrieve_roundtrip(tmp_path):
    adapter = _make_adapter(tmp_path)

    mid = adapter.store(1, "preference", "用户喜欢猫", importance=8)
    assert mid == 0 or mid > 0  # long_term 落库成功或内存 id

    rows = adapter.retrieve(1, "用户喜欢什么", limit=5)
    assert isinstance(rows, list)
    assert rows, "应能检索到已存记忆"
    row = rows[0]
    assert "content" in row
    assert "importance" in row
    assert "memory_type" in row


def test_adapter_retrieve_from_running_loop_no_deadlock(tmp_path):
    """关键场景：在运行中的事件循环内同步调用 retrieve，不应抛错/死锁."""
    adapter = _make_adapter(tmp_path)
    adapter.store(1, "fact", "主动陪伴是核心情绪价值", importance=8)

    async def inside_loop() -> list[dict]:
        # 模拟 context_builder.build 在 async pipeline 内调用同步 retrieve
        return adapter.retrieve(1, "陪伴", limit=5)

    rows = asyncio.run(inside_loop())
    assert isinstance(rows, list)


def test_adapter_decay_no_crash(tmp_path):
    adapter = _make_adapter(tmp_path)
    adapter.store(1, "fact", "一些临时记忆", importance=5)
    adapter.decay()  # 不应抛异常


def test_adapter_store_channel_then_retrieve_tags_source(tmp_path):
    """store 带 channel 后 retrieve 透出 channel；缺失时默认 unknown（§4 #11 用例⑥）。"""
    adapter = _make_adapter(tmp_path)

    adapter.store(1, "preference", "用户说过喜欢吃火锅", importance=8, channel="qq")
    rows = adapter.retrieve(1, "火锅", limit=5)
    assert rows
    row = rows[0]
    assert "channel" in row
    assert row["channel"] == "qq"

    # 不带 channel 的记忆：channel=unknown
    adapter.store(1, "fact", "无来源的记忆", importance=8)
    rows = adapter.retrieve(1, "无来源", limit=5)
    assert rows
    assert all(r.get("channel") in ("unknown", "qq") for r in rows)


def test_adapter_retrieve_empty_when_no_memory(tmp_path):
    adapter = _make_adapter(tmp_path)
    rows = adapter.retrieve(999, "不存在", limit=5)
    assert rows == []

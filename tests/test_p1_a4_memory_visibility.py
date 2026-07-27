"""P1-A.4 — 记忆可见性与用户控制.

测试长期记忆条目的可见性字段和用户控制接口：
  - source_message_id / confidence / user_confirmed / expires_at / deleted_at
  - list_active_memories：排除已删除和已过期
  - delete_memory：软删除（设置 deleted_at）
  - update_user_confirmed：更新用户确认标记
  - 按 confidence 降序排列 + 分页
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from memory.layers.base import MemoryItem, MemoryType
from memory.layers.long_permanent import LongTermMemoryLayer


# ── 测试用 SQLite DB（不预建 long_term_memory 表，交给 LongTermMemoryLayer 建表）──

class _SQLiteTestDB:
    """轻量 SQLite wrapper，匹配 LongTermMemoryLayer 所需的 DB 接口."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def insert(self, table: str, data: dict) -> int:
        keys = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({keys}) VALUES ({placeholders})"
        with self._lock:
            cur = self._conn.execute(sql, tuple(data.values()))
            self._conn.commit()
            return cur.lastrowid or 0

    def update(self, table: str, data: dict, where: str, where_params: tuple = ()) -> int:
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        with self._lock:
            cur = self._conn.execute(sql, tuple(data.values()) + tuple(where_params))
            self._conn.commit()
            return cur.rowcount

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None


@pytest.fixture
def mem_layer(tmp_path) -> LongTermMemoryLayer:
    """构造一个纯 SQLite 模式的 LongTermMemoryLayer."""
    db = _SQLiteTestDB()
    return LongTermMemoryLayer(db=db, chroma_persist_dir=str(tmp_path / "chroma"))


# ─────────────────────────────────────────────────────
# 1. MemoryItem 可见性字段
# ─────────────────────────────────────────────────────

def test_memory_item_has_visibility_fields():
    """MemoryItem 应包含 source_message_id/confidence/user_confirmed/expires_at/deleted_at."""
    item = MemoryItem(content="test")
    assert hasattr(item, "source_message_id")
    assert hasattr(item, "confidence")
    assert hasattr(item, "user_confirmed")
    assert hasattr(item, "expires_at")
    assert hasattr(item, "deleted_at")


def test_memory_item_visibility_field_defaults():
    """新增字段的默认值应合理."""
    item = MemoryItem(content="test")
    assert item.source_message_id is None or item.source_message_id == ""
    assert item.confidence == 0.5
    assert item.user_confirmed is False
    assert item.expires_at is None
    assert item.deleted_at is None


# ─────────────────────────────────────────────────────
# 2. list_active_memories — 排除已删除和已过期
# ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_active_memories_excludes_deleted(mem_layer):
    """deleted_at 不为空的记忆不出现在活跃列表中."""
    mid = await mem_layer.store(MemoryItem(
        user_id=1, content="活跃记忆", importance=8.0, confidence=0.9,
    ))
    await mem_layer.delete_memory(mid)

    active = await mem_layer.list_active_memories(user_id=1)
    ids = [m.id for m in active]
    assert mid not in ids


@pytest.mark.asyncio
async def test_list_active_memories_excludes_expired(mem_layer):
    """expires_at 已过期的记忆不出现在活跃列表中."""
    past = time.time() - 3600  # 1 小时前
    await mem_layer.store(MemoryItem(
        user_id=1, content="过期记忆", importance=8.0,
        confidence=0.8, expires_at=past,
    ))
    await mem_layer.store(MemoryItem(
        user_id=1, content="有效记忆", importance=8.0,
        confidence=0.8, expires_at=None,
    ))

    active = await mem_layer.list_active_memories(user_id=1)
    contents = [m.content for m in active]
    assert "有效记忆" in contents
    assert "过期记忆" not in contents


@pytest.mark.asyncio
async def test_list_active_memories_includes_unexpired(mem_layer):
    """expires_at 在未来的记忆仍出现在活跃列表中."""
    future = time.time() + 3600  # 1 小时后
    await mem_layer.store(MemoryItem(
        user_id=1, content="未来过期记忆", importance=8.0,
        confidence=0.8, expires_at=future,
    ))

    active = await mem_layer.list_active_memories(user_id=1)
    contents = [m.content for m in active]
    assert "未来过期记忆" in contents


# ─────────────────────────────────────────────────────
# 3. delete_memory — 软删除
# ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_memory_sets_deleted_at(mem_layer):
    """delete_memory 后 deleted_at 被设置为非 None."""
    mid = await mem_layer.store(MemoryItem(
        user_id=1, content="待删除记忆", importance=7.0, confidence=0.7,
    ))
    assert mid is not None

    ok = await mem_layer.delete_memory(mid)
    assert ok is True

    item = await mem_layer.get(mid)
    assert item is not None  # 软删除：记录仍在
    assert item.deleted_at is not None


@pytest.mark.asyncio
async def test_deleted_memory_not_in_active_list(mem_layer):
    """删除后的记忆不出现在活跃列表中，但 get 仍可获取."""
    mid = await mem_layer.store(MemoryItem(
        user_id=1, content="会被删除", importance=7.0, confidence=0.7,
    ))
    await mem_layer.delete_memory(mid)

    active = await mem_layer.list_active_memories(user_id=1)
    assert mid not in [m.id for m in active]

    # get 仍能获取（软删除不擦除数据）
    item = await mem_layer.get(mid)
    assert item is not None


# ─────────────────────────────────────────────────────
# 4. update_user_confirmed
# ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_user_confirmed(mem_layer):
    """user_confirmed 标记可更新为 True."""
    mid = await mem_layer.store(MemoryItem(
        user_id=1, content="需确认记忆", importance=7.0,
        confidence=0.6, user_confirmed=False,
    ))

    ok = await mem_layer.update_user_confirmed(mid, True)
    assert ok is True

    item = await mem_layer.get(mid)
    assert item.user_confirmed is True


@pytest.mark.asyncio
async def test_update_user_confirmed_toggle_back(mem_layer):
    """user_confirmed 可从 True 切回 False."""
    mid = await mem_layer.store(MemoryItem(
        user_id=1, content="已确认记忆", importance=7.0,
        confidence=0.9, user_confirmed=True,
    ))

    ok = await mem_layer.update_user_confirmed(mid, False)
    assert ok is True

    item = await mem_layer.get(mid)
    assert item.user_confirmed is False


# ─────────────────────────────────────────────────────
# 5. 按 confidence 降序排列
# ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_memories_sorted_by_confidence_desc(mem_layer):
    """活跃记忆列表按 confidence 降序排列."""
    items_data = [
        ("低置信度", 0.3),
        ("高置信度", 0.95),
        ("中置信度", 0.6),
    ]
    for content, conf in items_data:
        await mem_layer.store(MemoryItem(
            user_id=1, content=content, importance=8.0, confidence=conf,
        ))

    active = await mem_layer.list_active_memories(user_id=1)
    confidences = [m.confidence for m in active]
    assert confidences == sorted(confidences, reverse=True)
    assert active[0].content == "高置信度"


# ─────────────────────────────────────────────────────
# 6. 分页
# ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_memories_pagination(mem_layer):
    """list_active_memories 支持 limit + offset 分页."""
    for i in range(7):
        await mem_layer.store(MemoryItem(
            user_id=1, content=f"记忆_{i}", importance=8.0,
            confidence=0.5 + i * 0.05,
        ))

    page1 = await mem_layer.list_active_memories(user_id=1, limit=3, offset=0)
    page2 = await mem_layer.list_active_memories(user_id=1, limit=3, offset=3)
    page3 = await mem_layer.list_active_memories(user_id=1, limit=3, offset=6)

    assert len(page1) == 3
    assert len(page2) == 3
    assert len(page3) == 1  # 只剩 1 条

    # 三页合起来覆盖全部 7 条，无重叠
    all_ids = [m.id for m in page1] + [m.id for m in page2] + [m.id for m in page3]
    assert len(set(all_ids)) == 7

    # page1 的 confidence 应 >= page2 的 confidence
    assert page1[-1].confidence >= page2[0].confidence


# ─────────────────────────────────────────────────────
# 7. store 时持久化可见性字段
# ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_persists_visibility_fields(mem_layer):
    """store 时写入的可见性字段在 get 时能读回."""
    mid = await mem_layer.store(MemoryItem(
        user_id=1,
        content="带来源的记忆",
        importance=8.0,
        confidence=0.88,
        source_message_id="msg_001",
        user_confirmed=True,
        expires_at=time.time() + 7200,
    ))

    item = await mem_layer.get(mid)
    assert item is not None
    assert item.source_message_id == "msg_001"
    assert item.confidence == 0.88
    assert item.user_confirmed is True
    assert item.expires_at is not None
    assert item.deleted_at is None

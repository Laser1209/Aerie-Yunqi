"""Aerie · P4b admin_service 测试（§3.5.2 后台管理平台核心）.

覆盖：
- 迁移 011：软删列 + audit_log
- 解锁门闩（服务端标志 + token 校验）
- 聊天记录级联软删 / 恢复（messages + 摘要分桶 + long_term_memory）
- 检索侧软删过滤（history_page 排除已删消息）
- 过期 purge 物理删除
- 分层记忆 CRUD / 软删 / 恢复
- 知识库确认 + undo 快照
- 审计留痕
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pytest

from core.admin_service import AdminService


@pytest.fixture
def admin_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIE_FEATURE_MIGRATION_FRAMEWORK_V1", "true")
    from core.database import Database

    Database.reset_instance()
    db = Database(tmp_path / "admin.db")
    try:
        yield db
    finally:
        Database.reset_instance()


class _FakeRuntimeConfig:
    """runtime_config 的最小替身：snapshot/update（revision 乐观锁）。"""

    def __init__(self) -> None:
        self.values: dict = {"admin_unlocked": False}
        self.revision = 0

    def snapshot(self) -> dict:
        return {"revision": self.revision, "values": dict(self.values)}

    def update(self, changes: dict, *, expected_revision: int) -> dict:
        if int(expected_revision) != self.revision:
            raise RuntimeError("revision conflict")
        self.values.update(changes)
        self.revision += 1
        return self.snapshot()


def _make_service(tmp_path, db, runtime_config=None):
    return AdminService(
        db=db,
        data_dir=tmp_path / "admin-data",
        runtime_config=runtime_config or _FakeRuntimeConfig(),
        memory=None,
        retention_hours=24 * 7,
    )


def _seed_conversation(db, conversation_id: str, channel: str, content: str = "hello"):
    """写入一个完整会话（conversation + turn + message + 关联长期记忆）。"""
    db.insert(
        "conversations",
        {"conversation_id": conversation_id, "actor_id": None, "channel": channel},
    )
    db.insert(
        "turns",
        {
            "turn_id": f"turn-{conversation_id}",
            "conversation_id": conversation_id,
            "status": "completed",
            "created_at": "2026-08-01 10:00:00",
        },
    )
    db.insert(
        "messages",
        {
            "message_id": f"msg-{conversation_id}",
            "conversation_id": conversation_id,
            "turn_id": f"turn-{conversation_id}",
            "role": "user",
            "content": content,
            "sequence": 1,
            "channel": channel,
        },
    )
    memory_id = f"mem-{conversation_id}"
    db.insert(
        "long_term_memory",
        {
            "id": memory_id,
            "user_id": 1,
            "memory_type": "fact",
            "content": f"来自 {conversation_id} 的记忆",
            "importance": 8,
            "source_message_id": f"msg-{conversation_id}",
        },
    )
    return memory_id


# ── 迁移 011 ──────────────────────────────────────────────
def test_migration_011_creates_columns_and_audit_log(admin_db):
    with admin_db.connection() as conn:
        msg_cols = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        bucket_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(conversation_summary_buckets)")
        }
        kb_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(knowledge_base)")
        }
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "deleted_at" in msg_cols
    assert "deleted_at" in bucket_cols
    assert "deleted_at" in kb_cols
    assert "audit_log" in tables


def test_migration_011_checksum_ledger(admin_db):
    from core.migrations import MigrationRunner, admin_management_migrations

    with admin_db.connection() as conn:
        assert MigrationRunner(conn).run(admin_management_migrations()) == []


# ── 解锁门闩 ──────────────────────────────────────────────
def test_unlock_latch_flow(tmp_path, admin_db):
    service = _make_service(tmp_path, admin_db)
    assert not service.is_unlocked()

    token = service.unlock()
    assert token and service.is_unlocked()
    assert service.verify_token(token)
    assert not service.verify_token("wrong-token")
    assert service.verify_token(f" {token} ")  # 容忍空白

    service.lock()
    assert not service.is_unlocked()
    assert not service.verify_token(token)


# ── 级联软删 / 恢复 ───────────────────────────────────────
def test_conversation_cascade_trash_restore(tmp_path, admin_db):
    from core.admin_service import AdminService

    service = AdminService(db=admin_db, data_dir=tmp_path / "d", runtime_config=_FakeRuntimeConfig())
    _seed_conversation(admin_db, "conv-a", "desktop", content="今天工作顺利")
    _seed_conversation(admin_db, "conv-b", "qq", content="想你了")
    _seed_conversation(admin_db, "conv-c", "desktop", content="我发了张图")
    admin_db.insert(
        "conversation_summary_buckets",
        {
            "conversation_id": "conv-a",
            "bucket_index": 1,
            "bucket_start_rowid": 1,
            "through_rowid": 8,
            "source_message_count": 8,
            "summary": "工作讨论",
        },
    )

    result = service.trash_conversations(["conv-a", "conv-b"])
    assert result["trashed_messages"] == 2
    assert result["trashed_buckets"] == 1
    assert result["trashed_memories"] == 2

    # 软删后：消息/分桶/记忆均带 deleted_at
    assert admin_db.query_one("SELECT deleted_at FROM messages WHERE message_id='msg-conv-a'")["deleted_at"]
    assert admin_db.query_one(
        "SELECT deleted_at FROM conversation_summary_buckets WHERE conversation_id='conv-a'"
    )["deleted_at"]
    assert admin_db.query_one("SELECT deleted_at FROM long_term_memory WHERE id='mem-conv-a'")["deleted_at"]
    # 未删除的会话不受影响
    assert admin_db.query_one("SELECT deleted_at FROM messages WHERE message_id='msg-conv-c'")["deleted_at"] is None

    restore = service.restore_conversations(["conv-a"])
    assert restore["restored_messages"] == 1
    assert admin_db.query_one("SELECT deleted_at FROM messages WHERE message_id='msg-conv-a'")["deleted_at"] is None


def test_history_page_excludes_trashed(tmp_path, admin_db):
    from core.conversation_repository import ConversationRepository, resolve_conversation_id

    conv_id = resolve_conversation_id(
        actor_id=None, channel="desktop", channel_account_id=None, user_id=1
    )
    _seed_conversation(admin_db, conv_id, "desktop", content="保留消息")
    admin_db.insert(
        "turns",
        {
            "turn_id": "turn-extra",
            "conversation_id": conv_id,
            "status": "completed",
            "created_at": "2026-08-01 10:00:01",
        },
    )
    admin_db.insert(
        "messages",
        {
            "message_id": "msg-keep-2",
            "conversation_id": conv_id,
            "turn_id": "turn-extra",
            "role": "assistant",
            "content": "回复内容",
            "sequence": 2,
            "channel": "desktop",
        },
    )
    repo = ConversationRepository(admin_db, enabled=True)
    service = AdminService(db=admin_db, data_dir=tmp_path / "d", runtime_config=_FakeRuntimeConfig())

    # 软删前：两条消息都在
    page = repo.history_page(
        actor_id=None, channel="desktop", channel_account_id=None,
        user_id=1, limit=50,
    )
    assert len(page["items"]) == 2

    service.trash_conversations([conv_id])
    page = repo.history_page(
        actor_id=None, channel="desktop", channel_account_id=None,
        user_id=1, limit=50,
    )
    assert page["items"] == []

    service.restore_conversations([conv_id])
    page = repo.history_page(
        actor_id=None, channel="desktop", channel_account_id=None,
        user_id=1, limit=50,
    )
    assert len(page["items"]) == 2


# ── purge ─────────────────────────────────────────────────
def test_purge_expired_physically_deletes(tmp_path, admin_db):
    service = AdminService(
        db=admin_db, data_dir=tmp_path / "d",
        runtime_config=_FakeRuntimeConfig(), retention_hours=48,
    )
    _seed_conversation(admin_db, "conv-old", "desktop", content="过期消息")
    _seed_conversation(admin_db, "conv-fresh", "desktop", content="保留消息")
    # 手工把 conv-old 标记为 10 天前删除
    old_ts = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    admin_db.execute(
        "UPDATE messages SET deleted_at = ? WHERE message_id = 'msg-conv-old'",
        (old_ts,),
    )
    admin_db.execute(
        "UPDATE long_term_memory SET deleted_at = ? WHERE id = 'mem-conv-old'",
        (time.time() - 10 * 86400,),
    )

    result = service.purge_expired()
    assert result["messages"] == 1
    assert result["memories"] == 1
    assert admin_db.query_one("SELECT 1 AS x FROM messages WHERE message_id='msg-conv-old'") is None
    assert admin_db.query_one("SELECT 1 AS x FROM long_term_memory WHERE id='mem-conv-old'") is None
    assert admin_db.query_one("SELECT 1 AS x FROM messages WHERE message_id='msg-conv-fresh'") is not None


def test_purge_all_clears_trash(tmp_path, admin_db):
    service = AdminService(db=admin_db, data_dir=tmp_path / "d", runtime_config=_FakeRuntimeConfig())
    _seed_conversation(admin_db, "conv-a", "desktop")
    service.trash_conversations(["conv-a"])

    result = service.purge_all()
    assert result["messages"] == 1
    assert admin_db.query_one("SELECT 1 AS x FROM messages WHERE message_id='msg-conv-a'") is None


# ── 分层记忆 ──────────────────────────────────────────────
def test_memory_list_update_delete_restore(tmp_path, admin_db):
    service = AdminService(db=admin_db, data_dir=tmp_path / "d", runtime_config=_FakeRuntimeConfig())
    _seed_conversation(admin_db, "conv-a", "desktop", content="记录一条重要信息")

    listed = service.list_memory(user_id=1, layer="long_term")
    assert listed["total"] == 1
    mid = listed["items"][0]["id"]

    updated = service.update_memory(mid, {"importance": 10, "content": "改过的内容"})
    assert updated["importance"] == 10
    assert updated["content"] == "改过的内容"

    assert service.delete_memory(mid)
    row = service.get_memory(mid)
    assert row["deleted_at"] is not None
    # 默认列表包含已删行；include_trashed=False 时排除
    assert service.list_memory(user_id=1, include_trashed=True)["total"] == 1
    assert service.list_memory(user_id=1, include_trashed=False)["total"] == 0

    assert service.restore_memory(mid)
    assert service.get_memory(mid)["deleted_at"] is None


def test_memory_delete_unknown_returns_false(tmp_path, admin_db):
    service = AdminService(db=admin_db, data_dir=tmp_path / "d", runtime_config=_FakeRuntimeConfig())
    assert not service.delete_memory("missing-id")
    assert not service.restore_memory("missing-id")


# ── 知识库 undo 快照 ──────────────────────────────────────
def test_kb_delete_with_undo(tmp_path, admin_db):
    service = AdminService(db=admin_db, data_dir=tmp_path / "d", runtime_config=_FakeRuntimeConfig())
    kb_id = admin_db.insert(
        "knowledge_base",
        {"category": "world", "title": "伊塔喜欢重庆", "content": "山城夜景"},
    )

    assert service.list_kb()["total"] == 1
    snapshot = service.delete_kb_with_undo(kb_id)
    assert snapshot and snapshot["title"] == "伊塔喜欢重庆"
    # 软删后列表（deleted_at IS NULL）不可见
    assert service.list_kb()["total"] == 0

    assert service.undo_kb_delete(kb_id)
    assert service.list_kb()["total"] == 1


# ── 状态文件（只读查看） ────────────────────────────────
def test_state_files_list_and_view(tmp_path, admin_db):
    data_dir = tmp_path / "d"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "desire_state.json").write_text(
        '{"desire": {"level": 0.6}}', encoding="utf-8"
    )
    service = AdminService(db=admin_db, data_dir=data_dir, runtime_config=_FakeRuntimeConfig())

    items = service.list_state()["items"]
    by_kind = {i["kind"]: i for i in items}
    assert by_kind["desire"]["exists"] is True
    assert by_kind["desire"]["size"] > 0
    assert by_kind["topic"]["exists"] is False

    got = service.get_state("desire")
    assert got is not None and got["exists"] is True
    assert got["content"]["desire"]["level"] == 0.6
    assert service.get_state("unknown") is None


# ── 审计 ──────────────────────────────────────────────────
def test_audit_entries_written(tmp_path, admin_db):
    service = AdminService(db=admin_db, data_dir=tmp_path / "d", runtime_config=_FakeRuntimeConfig())
    _seed_conversation(admin_db, "conv-a", "desktop")
    service.trash_conversations(["conv-a"])

    entries = service.recent_audit(limit=10)
    assert entries, "回收站操作必须留审计"
    assert entries[0]["action"] == "trash"
    assert entries[0]["target_id"] == "conv-a"
    assert entries[0]["actor"] == "local_user"
    assert entries[0]["timestamp"]
    assert entries[0]["reason_code"] == "manual"

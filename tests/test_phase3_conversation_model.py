import json
import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }


def _conversation_fixture() -> sqlite3.Connection:
    from core.migrations import (
        MigrationRunner,
        phase3_backfill_migrations,
        phase3_conversation_migrations,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE actors (
            actor_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            attachments TEXT,
            actor_id TEXT,
            channel TEXT,
            channel_account_id TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00'
        )"""
    )
    runner = MigrationRunner(conn)
    runner.run(phase3_conversation_migrations())
    runner.run(phase3_backfill_migrations())
    return conn


def test_phase3_migration_keeps_published_phase004_checksum_stable():
    from core.migrations import phase3_conversation_migrations

    migration = phase3_conversation_migrations()[0]

    assert migration.checksum == (
        "7b808212291a457ff3ca1cc2a54e60a58192f80356f59ebefbb3de8349417702"
    )


def test_phase3_migration_creates_normalized_conversation_tables():
    from core.migrations import (
        MigrationRunner,
        phase3_conversation_migrations,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE actors (
            actor_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )"""
    )
    runner = MigrationRunner(conn)

    pending = runner.run(phase3_conversation_migrations())

    assert pending == ["004_conversation_model"]
    assert _columns(conn, "conversations") >= {
        "conversation_id",
        "actor_id",
        "channel",
        "channel_account_id",
        "status",
        "created_at",
        "updated_at",
    }
    assert _columns(conn, "turns") >= {
        "turn_id",
        "conversation_id",
        "status",
        "created_at",
        "completed_at",
    }
    assert _columns(conn, "messages") >= {
        "message_id",
        "conversation_id",
        "turn_id",
        "role",
        "content",
        "attachments",
        "response_group_id",
        "sequence",
        "channel",
        "actor_id",
        "legacy_chat_log_id",
        "created_at",
    }
    assert _columns(conn, "requests") >= {
        "request_id",
        "conversation_id",
        "turn_id",
        "status",
        "created_at",
        "updated_at",
        "completed_at",
        "error",
    }
    assert conn.execute(
        "SELECT status FROM migration_ledger WHERE version = ?",
        ("004_conversation_model",),
    ).fetchone()["status"] == "completed"


def test_phase3_backfill_preserves_order_attachments_and_groups_assistant_segments():
    from core.conversation_backfill import backfill_chat_log

    conn = _conversation_fixture()
    conn.executemany(
        """INSERT INTO chat_log
           (user_id, role, content, attachments, actor_id, channel,
            channel_account_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (7, "user", "第一问", json.dumps([{"path": "a.png"}]), None, "qq", "7"),
            (7, "assistant", "第一段", None, None, "qq", "7"),
            (7, "assistant", "第二段", None, None, "qq", "7"),
            (7, "user", "第二问", None, None, "qq", "7"),
        ],
    )

    result = backfill_chat_log(conn)

    assert result["processed"] == 4
    rows = conn.execute(
        """SELECT role, content, attachments, sequence,
                  response_group_id, legacy_chat_log_id
           FROM messages ORDER BY legacy_chat_log_id"""
    ).fetchall()
    assert [row["content"] for row in rows] == [
        "第一问", "第一段", "第二段", "第二问"
    ]
    assert [row["sequence"] for row in rows] == [0, 1, 2, 0]
    assert rows[0]["attachments"] == json.dumps([{"path": "a.png"}])
    assert rows[1]["response_group_id"] == rows[2]["response_group_id"]
    assert rows[1]["response_group_id"] is not None
    assert rows[0]["legacy_chat_log_id"] == 1


def test_phase3_backfill_is_idempotent_and_does_not_guess_missing_identity():
    from core.conversation_backfill import backfill_chat_log

    conn = _conversation_fixture()
    conn.executemany(
        "INSERT INTO chat_log (user_id, role, content) VALUES (?, ?, ?)",
        [(9, "user", "未知来源"), (9, "assistant", "保留原文")],
    )

    first = backfill_chat_log(conn)
    second = backfill_chat_log(conn)

    assert first["inserted"] == 2
    assert second["inserted"] == 0
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    identity_rows = conn.execute(
        "SELECT actor_id, channel, channel_account_id FROM messages"
    ).fetchall()
    assert [tuple(row) for row in identity_rows] == [
        (None, None, None),
        (None, None, None),
    ]
    assert conn.execute(
        "SELECT COUNT(*) FROM conversations"
    ).fetchone()[0] == 1


def test_phase3_backfill_isolates_short_term_conversations_by_channel():
    from core.conversation_backfill import backfill_chat_log

    conn = _conversation_fixture()
    conn.executemany(
        """INSERT INTO chat_log
           (user_id, role, content, actor_id, channel, channel_account_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (7, "user", "QQ 消息", "actor_shared", "qq", "7"),
            (7, "assistant", "QQ 回复", "actor_shared", "qq", "7"),
            (7, "user", "桌面消息", "actor_shared", "desktop", "local"),
            (7, "assistant", "桌面回复", "actor_shared", "desktop", "local"),
        ],
    )

    backfill_chat_log(conn)

    conversations = conn.execute(
        """SELECT conversation_id, actor_id, channel, channel_account_id
           FROM conversations ORDER BY channel"""
    ).fetchall()
    assert len(conversations) == 2
    assert {
        (row["actor_id"], row["channel"], row["channel_account_id"])
        for row in conversations
    } == {
        ("actor_shared", "qq", "7"),
        ("actor_shared", "desktop", "local"),
    }
    messages = conn.execute(
        """SELECT content, channel, channel_account_id
           FROM messages ORDER BY legacy_chat_log_id"""
    ).fetchall()
    assert [tuple(row) for row in messages] == [
        ("QQ 消息", "qq", "7"),
        ("QQ 回复", "qq", "7"),
        ("桌面消息", "desktop", "local"),
        ("桌面回复", "desktop", "local"),
    ]


def test_phase3_database_runs_backfill_migration_after_schema_creation(tmp_path):
    from core.database import Database

    db_path = tmp_path / "phase3-backfill.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00'
        )"""
    )
    conn.execute(
        "INSERT INTO chat_log (user_id, role, content) VALUES (7, 'user', '历史消息')"
    )
    conn.commit()
    conn.close()

    Database.reset_instance()
    try:
        Database(db_path)
        check = sqlite3.connect(db_path)
        try:
            assert check.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
            assert check.execute(
                "SELECT status FROM migration_ledger WHERE version = ?",
                ("005_conversation_backfill",),
            ).fetchone()[0] == "completed"
        finally:
            check.close()
    finally:
        Database.reset_instance()


def test_phase3_repository_persists_one_turn_with_ordered_assistant_messages():
    from core.conversation_repository import ConversationRepository

    conn = _conversation_fixture()
    repository = ConversationRepository(conn, enabled=True)

    result = repository.persist_turn(
        request_id="request_live_1",
        user_id=7,
        actor_id="actor_shared",
        channel="qq",
        channel_account_id="7",
        user_content="现在好吗",
        user_attachments=[{"path": "m.png"}],
        assistant_segments=["我在", "等你"],
    )

    assert result["conversation_id"].startswith("conv_")
    assert result["turn_id"].startswith("turn_")
    assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 1
    rows = conn.execute(
        """SELECT role, content, sequence, response_group_id, attachments
           FROM messages ORDER BY sequence"""
    ).fetchall()
    assert [tuple(row[:3]) for row in rows] == [
        ("user", "现在好吗", 0),
        ("assistant", "我在", 1),
        ("assistant", "等你", 2),
    ]
    assert rows[0]["attachments"] == json.dumps([{"path": "m.png"}])
    assert rows[1]["response_group_id"] == rows[2]["response_group_id"]


def test_phase3_repository_rolls_back_entire_turn_when_message_write_fails():
    from core.conversation_repository import ConversationRepository

    conn = _conversation_fixture()
    conn.execute(
        """CREATE TRIGGER fail_assistant_message
           BEFORE INSERT ON messages
           WHEN NEW.role = 'assistant'
           BEGIN
               SELECT RAISE(ABORT, 'assistant write failed');
           END"""
    )
    repository = ConversationRepository(conn, enabled=True)

    try:
        repository.persist_turn(
            request_id="request_atomic_1",
            user_id=7,
            actor_id="actor_shared",
            channel="qq",
            channel_account_id="7",
            user_content="原子写入",
            user_attachments=None,
            assistant_segments=["触发失败"],
        )
    except sqlite3.IntegrityError as exc:
        assert str(exc) == "assistant write failed"
    else:
        raise AssertionError("expected assistant message write to fail")

    assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_phase3_repository_supports_database_connection_provider(tmp_path):
    from core.conversation_repository import ConversationRepository
    from core.database import Database

    Database.reset_instance()
    try:
        db = Database(tmp_path / "phase3-live.db")
        repository = ConversationRepository(db, enabled=True)

        repository.persist_turn(
            request_id="request_provider_1",
            user_id=7,
            actor_id=None,
            channel="desktop",
            channel_account_id="local",
            user_content="连接提供者",
            user_attachments=None,
            assistant_segments=["已持久化"],
        )

        assert db.query_one(
            "SELECT content FROM messages WHERE role = 'user'"
        )["content"] == "连接提供者"
    finally:
        Database.reset_instance()


def test_phase3_repository_is_noop_when_feature_flag_is_disabled():
    from core.conversation_repository import ConversationRepository

    conn = _conversation_fixture()
    repository = ConversationRepository(conn, enabled=False)

    assert repository.persist_turn(
        request_id="request_legacy_1",
        user_id=7,
        actor_id="actor_shared",
        channel="desktop",
        channel_account_id="local",
        user_content="旧路径",
        user_attachments=[],
        assistant_segments=["旧回复"],
    ) is None
    assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_phase3_repository_reads_recent_complete_turns_without_splitting_segments():
    from core.conversation_repository import ConversationRepository

    conn = _conversation_fixture()
    repository = ConversationRepository(conn, enabled=True)
    for index in range(3):
        repository.persist_turn(
            request_id=f"request_history_{index}",
            user_id=7,
            actor_id="actor_shared",
            channel="qq",
            channel_account_id="7",
            user_content=f"问题 {index}",
            user_attachments=None,
            assistant_segments=[f"回复 {index}A", f"回复 {index}B"],
        )
    repository.persist_turn(
        request_id="request_other_channel",
        user_id=7,
        actor_id="actor_shared",
        channel="desktop",
        channel_account_id="local",
        user_content="桌面隔离",
        user_attachments=None,
        assistant_segments=["桌面回复"],
    )

    history = repository.recent_turn_history(
        actor_id="actor_shared",
        channel="qq",
        channel_account_id="7",
        user_id=7,
        limit=2,
    )

    assert [(row["role"], row["content"], row["sequence"]) for row in history] == [
        ("user", "问题 1", 0),
        ("assistant", "回复 1A", 1),
        ("assistant", "回复 1B", 2),
        ("user", "问题 2", 0),
        ("assistant", "回复 2A", 1),
        ("assistant", "回复 2B", 2),
    ]
    assert all(row["channel"] == "qq" for row in history)

import sqlite3

import pytest


def _connection(*, desktop=True):
    from core.migrations import (
        MigrationRunner,
        desktop_chat_continuity_migrations,
        phase3_conversation_migrations,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "CREATE TABLE actors (actor_id TEXT PRIMARY KEY, created_at TEXT)"
    )
    runner = MigrationRunner(conn)
    runner.run(phase3_conversation_migrations())
    conn.execute("ALTER TABLE messages ADD COLUMN channel_account_id TEXT")
    if desktop:
        runner.run(desktop_chat_continuity_migrations())
    return conn


def _seed_messages(conn, count=10000):
    conn.execute(
        "INSERT INTO conversations (conversation_id, channel) VALUES ('conv_test', 'desktop')"
    )
    conn.execute(
        """INSERT INTO turns
           (turn_id, conversation_id, status, completed_at)
           VALUES ('turn_test', 'conv_test', 'completed', datetime('now'))"""
    )
    conn.executemany(
        """INSERT INTO messages
           (message_id, conversation_id, turn_id, role, content, sequence)
           VALUES (?, 'conv_test', 'turn_test', ?, ?, ?)""",
        [
            (
                f"msg_{index:05d}",
                "user" if index % 2 == 0 else "assistant",
                f"message {index}",
                index,
            )
            for index in range(count)
        ],
    )


def test_desktop_chat_migration_is_additive_and_ledgered():
    from core.migrations import (
        MigrationRunner,
        desktop_chat_continuity_migrations,
    )

    conn = _connection(desktop=False)
    migration = desktop_chat_continuity_migrations()[0]
    assert migration.version == "008_desktop_chat_continuity"
    assert MigrationRunner(conn).run([migration]) == [migration.version]
    assert MigrationRunner(conn).run([migration]) == []
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "conversation_summaries",
        "desktop_attachments",
        "desktop_attachment_chunks",
    } <= tables


def test_cursor_pages_all_10000_messages_without_duplicates_or_gaps():
    from core.conversation_repository import ConversationRepository

    conn = _connection()
    _seed_messages(conn)
    repository = ConversationRepository(conn, enabled=True)
    cursor = None
    all_items = []
    while True:
        page = repository.history_page(
            actor_id=None,
            channel="desktop",
            channel_account_id="local",
            user_id=7,
            conversation_id="conv_test",
            cursor=cursor,
            limit=137,
        )
        all_items = page["items"] + all_items
        if not page["hasMore"]:
            break
        cursor = page["nextCursor"]

    assert len(all_items) == 10000
    assert len({item["id"] for item in all_items}) == 10000
    assert [item["content"] for item in all_items] == [
        f"message {index}" for index in range(10000)
    ]


def test_history_cursor_supports_older_and_newer_window_navigation():
    from core.conversation_repository import ConversationRepository

    conn = _connection()
    _seed_messages(conn, 12)
    repository = ConversationRepository(conn, enabled=True)
    latest = repository.history_page(
        actor_id=None,
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_test",
        limit=4,
    )
    older = repository.history_page(
        actor_id=None,
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_test",
        cursor=latest["olderCursor"],
        direction="older",
        limit=4,
    )
    newer = repository.history_page(
        actor_id=None,
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_test",
        cursor=older["newerCursor"],
        direction="newer",
        limit=4,
    )

    assert [item["content"] for item in latest["items"]] == [
        "message 8", "message 9", "message 10", "message 11"
    ]
    assert [item["content"] for item in older["items"]] == [
        "message 4", "message 5", "message 6", "message 7"
    ]
    assert [item["content"] for item in newer["items"]] == [
        "message 8", "message 9", "message 10", "message 11"
    ]


def test_history_cursor_rejects_malformed_values():
    from core.conversation_repository import (
        ConversationRepository,
        InvalidHistoryCursor,
    )

    conn = _connection()
    _seed_messages(conn, 1)
    repository = ConversationRepository(conn, enabled=True)
    with pytest.raises(InvalidHistoryCursor):
        repository.history_page(
            actor_id=None,
            channel="desktop",
            channel_account_id="local",
            user_id=7,
            conversation_id="conv_test",
            cursor="not-a-cursor",
        )


def test_disabled_conversation_model_uses_legacy_cursor_page():
    from core.conversation_repository import ConversationRepository

    conn = _connection()
    conn.execute(
        """CREATE TABLE chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            attachments TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.executemany(
        "INSERT INTO chat_log (user_id, role, content) VALUES (7, 'user', ?)",
        [(f"legacy {index}",) for index in range(5)],
    )
    repository = ConversationRepository(conn, enabled=False)
    page = repository.history_page(
        actor_id=None,
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        limit=2,
    )
    assert [item["content"] for item in page["items"]] == ["legacy 3", "legacy 4"]
    assert page["hasOlder"] is True


def test_summary_refresh_and_context_assembly_are_bounded():
    from core.conversation_continuity import (
        ContextAssembler,
        ConversationSummaryRepository,
        SummaryConflict,
        SummaryRefreshPlanner,
    )
    from core.conversation_repository import ConversationRepository

    conn = _connection()
    repository = ConversationRepository(conn, enabled=True)
    for index in range(20):
        repository.persist_turn(
            request_id=f"req_{index}",
            user_id=7,
            actor_id=None,
            channel="desktop",
            channel_account_id="local",
            user_content=f"question {index} " + "u" * 300,
            user_attachments=None,
            assistant_segments=[f"answer {index} " + "a" * 300],
            conversation_id="conv_summary",
        )

    summaries = ConversationSummaryRepository(conn)
    planner = SummaryRefreshPlanner(summaries, max_input_chars=5000)
    job = planner.prepare("conv_summary")
    assert job is not None
    assert sum(len(item["content"]) for item in job["messages"]) <= 5000
    saved = planner.complete(job, lambda previous, messages: "early sentinel: ALPHA")
    assert saved["revision"] == 1
    with pytest.raises(SummaryConflict):
        summaries.upsert(
            conversation_id="conv_summary",
            summary="stale update",
            through_message_rowid=saved["through_message_rowid"],
            source_message_count=saved["source_message_count"],
            expected_revision=0,
        )

    assembler = ContextAssembler(
        repository,
        summaries,
        max_total_chars=3500,
        recent_turn_limit=8,
    )
    result = assembler.assemble(
        system_prompt="system " + "s" * 5000,
        current_user_content="where is ALPHA? " + "q" * 1000,
        actor_id=None,
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_summary",
        memories=["memory " + "m" * 4000],
        attachment_snippets=["attachment " + "x" * 5000],
    )
    assert result.audit["bounded"] is True
    assert result.audit["total_chars"] <= 3500
    assert "ALPHA" in result.messages[0]["content"]
    assert result.messages[-1]["role"] == "user"

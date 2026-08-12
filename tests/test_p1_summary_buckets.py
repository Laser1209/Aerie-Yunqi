"""P1 分组摘要测试（§3.2 / §4 #10 / §5-4）。

覆盖：migration 建表、repository bucket 方法、planner 分桶生成、
assembler 分桶注入。
"""

import sqlite3


def _connection():
    from core.migrations import (
        MigrationRunner,
        desktop_chat_continuity_migrations,
        phase3_conversation_migrations,
        summary_buckets_migrations,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE actors (actor_id TEXT PRIMARY KEY, created_at TEXT)")
    runner = MigrationRunner(conn)
    runner.run(phase3_conversation_migrations())
    conn.execute("ALTER TABLE messages ADD COLUMN channel_account_id TEXT")
    runner.run(desktop_chat_continuity_migrations())
    runner.run(summary_buckets_migrations())
    return conn


def _seed_turns(conn, conversation_id="conv_bucket", n_turns=20):
    conn.execute(
        "INSERT INTO conversations (conversation_id, channel) VALUES (?, 'desktop')",
        (conversation_id,),
    )
    for t in range(1, n_turns + 1):
        turn_id = f"turn_{t}"
        conn.execute(
            "INSERT INTO turns (turn_id, conversation_id, status, completed_at) "
            "VALUES (?, ?, 'completed', datetime('now'))",
            (turn_id, conversation_id),
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, turn_id, role, content, sequence) "
            "VALUES (?, ?, ?, 'user', ?, 1)",
            (f"msg_u_{t}", conversation_id, turn_id, f"第{t}轮问题"),
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, turn_id, role, content, sequence) "
            "VALUES (?, ?, ?, 'assistant', ?, 2)",
            (f"msg_a_{t}", conversation_id, turn_id, f"第{t}轮回复"),
        )


def _echo_summarizer(previous, messages):
    return "摘要:" + ";".join(str(m.get("content") or "") for m in messages)[:200]


def test_bucket_migration_creates_table():
    from core.migrations import MigrationRunner, summary_buckets_migrations

    conn = _connection()
    assert (
        MigrationRunner(conn).run(summary_buckets_migrations()) == []
    ), "二次运行应幂等 no-op"
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_summary_buckets'"
    ).fetchone()
    assert row is not None


def test_planner_generates_first_bucket_after_8_turns():
    from core.conversation_continuity import (
        ConversationSummaryRepository,
        SummaryRefreshPlanner,
    )

    conn = _connection()
    _seed_turns(conn, n_turns=8)
    repo = ConversationSummaryRepository(conn)
    planner = SummaryRefreshPlanner(repo, turn_interval=8)

    job = planner.prepare("conv_bucket")
    assert job is not None
    assert job["bucket_index"] == 1
    assert job["through_message_rowid"] > 0
    # 每桶只含 8 轮消息
    turn_ids = {m.get("turn_id") for m in job["messages"]} - {None}
    assert len(turn_ids) <= 8

    bucket = planner.complete(job, _echo_summarizer)
    assert bucket["bucket_index"] == 1
    assert "第8轮回复" in bucket["summary"]

    # 未到下一个 8 轮前不再生成
    assert planner.prepare("conv_bucket") is None


def test_planner_generates_next_bucket_incrementally():
    from core.conversation_continuity import (
        ConversationSummaryRepository,
        SummaryRefreshPlanner,
    )

    conn = _connection()
    _seed_turns(conn, n_turns=16)
    repo = ConversationSummaryRepository(conn)
    planner = SummaryRefreshPlanner(repo, turn_interval=8)

    job1 = planner.prepare("conv_bucket")
    planner.complete(job1, _echo_summarizer)

    job2 = planner.prepare("conv_bucket")
    assert job2 is not None
    assert job2["bucket_index"] == 2
    planner.complete(job2, _echo_summarizer)

    buckets = repo.recent_buckets("conv_bucket", limit=3)
    assert [b["bucket_index"] for b in buckets] == [2, 1]
    latest = repo.latest_bucket("conv_bucket")
    assert latest["bucket_index"] == 2


def test_repository_bucket_upsert_updates_revision():
    from core.conversation_continuity import ConversationSummaryRepository

    conn = _connection()
    _seed_turns(conn, n_turns=8)
    repo = ConversationSummaryRepository(conn)

    bucket = repo.upsert_bucket(
        conversation_id="conv_bucket",
        bucket_index=1,
        bucket_start_rowid=1,
        through_rowid=100,
        source_message_count=16,
        summary="第一版摘要",
    )
    assert bucket["revision"] == 1

    bucket2 = repo.upsert_bucket(
        conversation_id="conv_bucket",
        bucket_index=1,
        bucket_start_rowid=1,
        through_rowid=100,
        source_message_count=16,
        summary="第二版摘要",
    )
    assert bucket2["revision"] == 2
    assert bucket2["summary"] == "第二版摘要"


def test_assembler_injects_buckets_from_real_repository():
    from core.conversation_continuity import (
        ContextAssembler,
        ConversationSummaryRepository,
        SummaryRefreshPlanner,
    )
    from core.conversation_repository import ConversationRepository

    conn = _connection()
    _seed_turns(conn, n_turns=16)
    repo = ConversationSummaryRepository(conn)
    planner = SummaryRefreshPlanner(repo, turn_interval=8)
    for _ in range(2):
        job = planner.prepare("conv_bucket")
        if job is None:
            break
        planner.complete(job, _echo_summarizer)

    conv_repo = ConversationRepository(database=conn, enabled=True)
    asm = ContextAssembler(conv_repo, repo, max_total_chars=24_000)
    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="acc",
        user_id=1,
        conversation_id="conv_bucket",
    )
    system = result.messages[0]["content"]
    assert "[滚动对话摘要·第 1 段]" in system
    assert "[滚动对话摘要·第 2 段]" in system
    assert system.index("第 1 段") < system.index("第 2 段")

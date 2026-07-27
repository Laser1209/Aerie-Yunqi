"""Offline acceptance stress tests for desktop conversation continuity."""

from __future__ import annotations

import json
import math
import sqlite3
import time


def _connection() -> sqlite3.Connection:
    from core.migrations import (
        MigrationRunner,
        desktop_chat_continuity_migrations,
        phase3_conversation_migrations,
    )

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "CREATE TABLE actors (actor_id TEXT PRIMARY KEY, created_at TEXT)"
    )
    runner = MigrationRunner(connection)
    runner.run(phase3_conversation_migrations())
    connection.execute("ALTER TABLE messages ADD COLUMN channel_account_id TEXT")
    runner.run(desktop_chat_continuity_migrations())
    return connection


def test_acceptance_cursor_pages_10000_without_gaps_duplicates_or_reordering():
    from core.conversation_repository import ConversationRepository

    started = time.perf_counter()
    connection = _connection()
    connection.execute(
        "INSERT INTO conversations (conversation_id, channel) "
        "VALUES ('conv_acceptance_10k', 'desktop')"
    )
    connection.execute(
        """INSERT INTO turns
           (turn_id, conversation_id, status, completed_at)
           VALUES (
               'turn_acceptance_10k', 'conv_acceptance_10k',
               'completed', datetime('now')
           )"""
    )
    total_messages = 10_000
    page_limit = 137
    connection.executemany(
        """INSERT INTO messages
           (message_id, conversation_id, turn_id, role, content, sequence)
           VALUES (?, 'conv_acceptance_10k', 'turn_acceptance_10k', ?, ?, ?)""",
        (
            (
                f"msg_acceptance_{index:05d}",
                "user" if index % 2 == 0 else "assistant",
                f"synthetic-{index:05d}",
                index,
            )
            for index in range(total_messages)
        ),
    )

    repository = ConversationRepository(connection, enabled=True)
    cursor = None
    ordered_ids: list[str] = []
    page_count = 0
    while True:
        page = repository.history_page(
            actor_id=None,
            channel="desktop",
            channel_account_id="local",
            user_id=7,
            conversation_id="conv_acceptance_10k",
            cursor=cursor,
            direction="older",
            limit=page_limit,
        )
        ordered_ids = [item["id"] for item in page["items"]] + ordered_ids
        page_count += 1
        if not page["hasMore"]:
            break
        cursor = page["nextCursor"]

    expected_ids = [
        f"msg_acceptance_{index:05d}" for index in range(total_messages)
    ]
    assert ordered_ids == expected_ids
    assert len(set(ordered_ids)) == total_messages
    assert page_count == math.ceil(total_messages / page_limit)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    print(
        "ACCEPTANCE_METRIC "
        + json.dumps(
            {
                "case": "cursor_10000",
                "messageCount": total_messages,
                "distinctMessageCount": len(set(ordered_ids)),
                "pageLimit": page_limit,
                "pageCount": page_count,
                "expectedPageCount": math.ceil(total_messages / page_limit),
                "noDuplicates": True,
                "noGaps": True,
                "ordered": True,
                "elapsedMs": elapsed_ms,
            },
            sort_keys=True,
        )
    )


def test_acceptance_200_turn_summary_retrieval_is_bounded_and_keeps_early_fact():
    from core.conversation_continuity import (
        ContextAssembler,
        ConversationSummaryRepository,
        SummaryRefreshPlanner,
    )
    from core.conversation_repository import ConversationRepository
    from core.pipeline import Pipeline

    started = time.perf_counter()
    connection = _connection()
    connection.execute(
        "INSERT INTO actors (actor_id, created_at) "
        "VALUES ('actor_acceptance', datetime('now'))"
    )
    repository = ConversationRepository(connection, enabled=True)
    summaries = ConversationSummaryRepository(connection)
    planner = SummaryRefreshPlanner(summaries, max_input_chars=24_000)

    total_turns = 200
    summary_interval = 20
    sentinel = "SYNTHETIC_EARLY_FACT_7F3A"
    conversation_id = "conv_acceptance_200"
    for index in range(total_turns):
        marker = sentinel if index == 0 else "ordinary"
        repository.persist_turn(
            request_id=f"req_acceptance_{index:03d}",
            user_id=7,
            actor_id="actor_acceptance",
            channel="desktop",
            channel_account_id="local",
            user_content=f"synthetic user turn {index:03d} {marker} " + "u" * 80,
            user_attachments=None,
            assistant_segments=[
                f"synthetic assistant turn {index:03d} " + "a" * 80
            ],
            conversation_id=conversation_id,
        )
        if (index + 1) % summary_interval == 0:
            job = planner.prepare(conversation_id)
            assert job is not None
            planner.complete(job, Pipeline._default_rolling_summary)

    summary = summaries.get(conversation_id)
    assert summary is not None
    assert summary["revision"] == total_turns // summary_interval
    assert summary["source_message_count"] == total_turns * 2
    assert sentinel in summary["summary"]

    retrieval_marker = "SYNTHETIC_RETRIEVAL_CHANNEL_PRESENT"
    attachment_marker = "SYNTHETIC_ATTACHMENT_CHANNEL_PRESENT"
    assembler = ContextAssembler(
        repository,
        summaries,
        max_total_chars=24_000,
        recent_message_limit=24,
    )
    context = assembler.assemble(
        system_prompt="synthetic system " + "s" * 5_800,
        current_user_content="retrieve early synthetic fact " + "q" * 900,
        actor_id="actor_acceptance",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id=conversation_id,
        memories=[retrieval_marker],
        attachment_snippets=[attachment_marker],
    )

    system_content = context.messages[0]["content"]
    assert sentinel in system_content
    assert retrieval_marker in system_content
    assert attachment_marker in system_content
    assert context.audit["bounded"] is True
    assert context.audit["total_chars"] <= 24_000
    assert context.audit["summary_revision"] == 10
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    print(
        "ACCEPTANCE_METRIC "
        + json.dumps(
            {
                "case": "continuity_200_turns",
                "turnCount": total_turns,
                "messageCount": total_turns * 2,
                "summaryIntervalTurns": summary_interval,
                "summaryRevision": context.audit["summary_revision"],
                "summarySourceMessageCount": summary["source_message_count"],
                "earlyFactPresentInSummary": True,
                "earlyFactAvailableInContext": True,
                "retrievalChannelPresent": True,
                "attachmentChannelPresent": True,
                "historyMessagesInContext": context.audit["history_messages"],
                "contextChars": context.audit["total_chars"],
                "contextCharLimit": context.audit["max_total_chars"],
                "bounded": context.audit["bounded"],
                "realModelCalls": 0,
                "elapsedMs": elapsed_ms,
            },
            sort_keys=True,
        )
    )

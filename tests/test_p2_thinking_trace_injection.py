"""P2 思维链决策自省测试（§3.6-2 / §4 #9 thinking_trace_injection_v1）。

覆盖：CognitionEngine.recent_react_summary 摘要构建与截断、
ContextAssembler 自省段注入、flag 默认关闭。
"""

import json
import sqlite3

from core.cognition import CognitionEngine


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE cognition_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT 0,
            source TEXT, user_id INTEGER, user_message TEXT,
            route_mode TEXT,
            stage_route TEXT, stage_emotion TEXT, stage_threshold TEXT,
            stage_context TEXT, stage_brain TEXT, stage_tools TEXT,
            stage_split TEXT, stage_postprocess TEXT, stage_output TEXT,
            decision_trace TEXT, react_trace TEXT,
            is_command INTEGER DEFAULT 0, duration_ms INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )

    class FakeDB:
        def insert(self, table, payload):
            cols = ", ".join(payload.keys())
            marks = ", ".join(["?"] * len(payload))
            cur = conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                list(payload.values()),
            )
            return cur.lastrowid

        def query(self, sql, params=()):
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

        def query_one(self, sql, params=()):
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

        def update(self, table, payload, where, params):
            sets = ", ".join(f"{k} = ?" for k in payload.keys())
            conn.execute(
                f"UPDATE {table} SET {sets} WHERE {where}",
                list(payload.values()) + list(params),
            )

    return FakeDB()


def _seed_trace(db, *, user_id=7, thought="想拍个侧面，光线刚好", action="调用生图", tool_name="generate_image", chosen="image"):
    cog = CognitionEngine(db)
    trace = cog.begin(user_id, "qq", "看看腿")
    cog.record_react(trace, {
        "react_source": "model",
        "thought": thought,
        "action": action,
        "tool_name": tool_name,
    })
    cog.record_decision(trace, {"chosen": chosen})
    cog.record(trace, "brain", {"text": "answer"})
    return cog.commit(trace, "FULL")


def test_recent_react_summary_builds_compact_snippet():
    db = _make_db()
    _seed_trace(db, user_id=7)

    cog = CognitionEngine(db)
    summary = cog.recent_react_summary(7)
    assert summary is not None
    assert "想拍个侧面" in summary
    assert "调用生图" in summary
    assert "generate_image" in summary
    assert "决策：image" in summary


def test_recent_react_summary_returns_none_when_no_trace():
    db = _make_db()
    cog = CognitionEngine(db)
    assert cog.recent_react_summary(7) is None


def test_recent_react_summary_bounds_length():
    db = _make_db()
    _seed_trace(db, user_id=7, thought="x" * 500, action="a" * 500)
    cog = CognitionEngine(db)
    summary = cog.recent_react_summary(7, max_chars=80)
    assert summary is not None
    assert len(summary) <= 80


def test_recent_react_summary_ignores_null_json():
    db = _make_db()
    cog = CognitionEngine(db)
    trace = cog.begin(7, "qq", "hi")
    cog.commit(trace, "FULL")  # react_trace / decision_trace 均为 None
    assert cog.recent_react_summary(7) is None


def _assembler():
    from core.conversation_continuity import (
        ContextAssembler,
        ConversationSummaryRepository,
    )
    from core.conversation_repository import ConversationRepository

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from core.migrations import (
        MigrationRunner,
        desktop_chat_continuity_migrations,
        phase3_conversation_migrations,
        summary_buckets_migrations,
    )

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE actors (actor_id TEXT PRIMARY KEY, created_at TEXT)")
    runner = MigrationRunner(conn)
    runner.run(phase3_conversation_migrations())
    conn.execute("ALTER TABLE messages ADD COLUMN channel_account_id TEXT")
    runner.run(desktop_chat_continuity_migrations())
    runner.run(summary_buckets_migrations())
    repo = ConversationRepository(database=conn, enabled=True)
    summaries = ConversationSummaryRepository(conn)
    return ContextAssembler(repo, summaries, max_total_chars=4000), conn


def test_assembler_injects_thinking_trace_section():
    assembler, _ = _assembler()
    result = assembler.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_trace",
        thinking_trace="思考：想拍侧面；动作：调用生图；决策：image",
    )
    system = result.messages[0]["content"]
    assert "[决策自省·上一条]" in system
    assert "想拍侧面" in system
    assert result.audit["thinking_trace_chars"] > 0
    assert result.audit["bounded"] is True


def test_assembler_skips_thinking_trace_when_absent():
    assembler, _ = _assembler()
    result = assembler.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_trace2",
    )
    system = result.messages[0]["content"]
    assert "[决策自省·上一条]" not in system
    assert result.audit["thinking_trace_chars"] == 0


def test_thinking_trace_flag_default_off():
    from core.feature_flags import FeatureFlags

    assert FeatureFlags().is_enabled("thinking_trace_injection_v1") is False

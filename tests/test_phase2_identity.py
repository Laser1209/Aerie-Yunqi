import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from communication.message import IncomingMessage
from core.database import Database
from memory.memory_store import LongTermMemory


def _fresh_database(path):
    Database.reset_instance()
    return Database(path)


def test_message_factories_expose_explicit_channel_identity():
    qq = IncomingMessage.from_onebot_event(
        {
            "sender": {"user_id": 10001},
            "message_type": "private",
            "raw_message": "你好",
        }
    )
    desktop = IncomingMessage.from_local("你好", 10001)

    assert (qq.channel, qq.channel_account_id) == ("qq", "10001")
    assert (desktop.channel, desktop.channel_account_id) == ("desktop", "local")
    assert qq.actor_id is None
    assert desktop.actor_id is None


def test_identity_repository_resolves_stable_actor_per_channel_account(tmp_path):
    from core.identity import IdentityRepository

    db = _fresh_database(tmp_path / "identity.db")
    try:
        repository = IdentityRepository(db)

        first = repository.resolve("qq", "10001")
        second = repository.resolve("qq", "10001")
        desktop = repository.resolve("desktop", "local")

        assert first.actor_id == second.actor_id
        assert desktop.actor_id != first.actor_id
        assert first.channel == "qq"
        assert first.channel_account_id == "10001"
    finally:
        Database.reset_instance()


def test_explicit_binding_shares_actor_across_channels(tmp_path):
    from core.identity import IdentityRepository

    db = _fresh_database(tmp_path / "binding.db")
    try:
        repository = IdentityRepository(db)
        qq = repository.resolve("qq", "10001")

        repository.bind(qq.actor_id, "desktop", "local")
        desktop = repository.resolve("desktop", "local")

        assert desktop.actor_id == qq.actor_id
        assert desktop.channel != qq.channel
    finally:
        Database.reset_instance()


def test_identity_resolver_populates_message_only_when_flag_enabled(tmp_path):
    from core.identity import IdentityRepository, IdentityResolver

    db = _fresh_database(tmp_path / "resolver.db")
    try:
        repository = IdentityRepository(db)
        enabled = IdentityResolver(repository, enabled=True)
        disabled = IdentityResolver(repository, enabled=False)

        current = IncomingMessage.from_local("当前", 10001)
        legacy = IncomingMessage.from_local("旧路径", 10001)

        enabled.resolve_message(current)
        disabled.resolve_message(legacy)

        assert current.actor_id is not None
        assert current.channel == "desktop"
        assert legacy.actor_id is None
    finally:
        Database.reset_instance()


def test_identity_resolver_reads_identity_feature_flag(tmp_path):
    from core.identity import IdentityRepository, IdentityResolver

    class Flags:
        def __init__(self, enabled):
            self.enabled = enabled

        def is_enabled(self, name):
            assert name == "identity_contract_v1"
            return self.enabled

    db = _fresh_database(tmp_path / "flag.db")
    try:
        repository = IdentityRepository(db)
        enabled = IdentityResolver.from_feature_flags(repository, Flags(True))
        disabled = IdentityResolver.from_feature_flags(repository, Flags(False))

        assert enabled.enabled is True
        assert disabled.enabled is False
    finally:
        Database.reset_instance()


def test_identity_migration_adds_nullable_columns_without_guessing_legacy_source(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO chat_log (user_id, role, content) VALUES (7, 'user', 'legacy')"
    )
    conn.commit()
    conn.close()

    db = _fresh_database(db_path)
    try:
        row = db.query_one(
            "SELECT actor_id, channel, channel_account_id FROM chat_log WHERE id = 1"
        )
        assert row == {
            "actor_id": None,
            "channel": None,
            "channel_account_id": None,
        }
        assert {"actors", "channel_accounts"} <= set(db.list_tables())
    finally:
        Database.reset_instance()


def test_long_term_memory_is_shared_by_actor_across_channels(tmp_path):
    from core.identity import IdentityRepository

    db = _fresh_database(tmp_path / "actor-memory.db")
    try:
        repository = IdentityRepository(db)
        qq = repository.resolve("qq", "10001")
        repository.bind(qq.actor_id, "desktop", "local")
        desktop = repository.resolve("desktop", "local")
        other = repository.resolve("qq", "20002")
        memory = LongTermMemory(db)

        memory.store(
            10001,
            "preference",
            "喜欢栀子花",
            actor_id=qq.actor_id,
        )

        assert [
            row["content"]
            for row in memory.retrieve(0, actor_id=desktop.actor_id)
        ] == ["喜欢栀子花"]
        assert memory.retrieve(20002, actor_id=other.actor_id) == []
    finally:
        Database.reset_instance()


def test_phase2_identity_migration_is_ledgered_and_idempotent(tmp_path):
    from core.migrations import MigrationRunner, phase2_identity_migrations

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE long_term_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            created_at TEXT,
            accessed_at TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO chat_log (user_id, role, content) VALUES (7, 'user', 'legacy')"
    )
    conn.execute(
        """INSERT INTO long_term_memory (user_id, memory_type, content)
           VALUES (7, 'fact', 'legacy')"""
    )
    runner = MigrationRunner(conn)
    migrations = phase2_identity_migrations()

    assert runner.run(migrations, dry_run=True) == ["002_actor_channel_identity"]
    assert "actor_id" not in {
        row["name"] for row in conn.execute("PRAGMA table_info(chat_log)")
    }

    assert runner.run(migrations) == ["002_actor_channel_identity"]
    assert runner.run(migrations) == []
    assert tuple(conn.execute(
        "SELECT actor_id, channel, channel_account_id FROM chat_log"
    ).fetchone()) == (None, None, None)
    assert tuple(conn.execute(
        "SELECT actor_id FROM long_term_memory"
    ).fetchone()) == (None,)
    ledger = conn.execute(
        "SELECT checksum, status FROM migration_ledger WHERE version = ?",
        ("002_actor_channel_identity",),
    ).fetchone()
    assert ledger["checksum"]
    assert ledger["status"] == "completed"


def test_database_runs_phase2_identity_migration_through_ledger(tmp_path):
    db = _fresh_database(tmp_path / "ledger.db")
    try:
        assert db.query_one(
            "SELECT status FROM migration_ledger WHERE version = ?",
            ("002_actor_channel_identity",),
        ) == {"status": "completed"}
    finally:
        Database.reset_instance()


def test_emotion_runtime_state_is_isolated_by_actor():
    from core.emotion_engine import EmotionEngine
    from core.emotion_threshold import reset_threshold_engine

    reset_threshold_engine()
    engine = EmotionEngine()

    engine.update_trajectory(10001, "我爱你", actor_id="actor_primary")

    primary = engine.get_state(0, actor_id="actor_primary")
    other = engine.get_state(20002, actor_id="actor_other")
    assert primary["pad"] != other["pad"]
    assert other["pad"] == {"P": 0.0, "A": 0.0, "D": 0.0}
    assert other["thresholds"]["desire"]["value"] == 0.0


def test_emotion_runtime_state_is_shared_by_actor_across_channels():
    from core.emotion_engine import EmotionEngine
    from core.emotion_threshold import reset_threshold_engine

    reset_threshold_engine()
    engine = EmotionEngine()

    engine.update_trajectory(10001, "想你了", actor_id="actor_primary")
    qq = engine.get_state(10001, actor_id="actor_primary")
    desktop = engine.get_state(0, actor_id="actor_primary")

    assert desktop == qq
    assert desktop["thresholds"]["desire"]["value"] == 15.0


def test_companion_primary_emotion_state_uses_master_qq_actor():
    from core.companion import Companion

    companion = object.__new__(Companion)
    companion.settings = {"qq": {"self_qq": "10001"}}
    companion.identity_resolver = MagicMock()
    companion.identity_resolver.resolve.return_value = MagicMock(
        actor_id="actor_primary"
    )
    companion.emotion = MagicMock()
    companion.emotion.get_state.return_value = {"label": "joy"}

    state = companion.get_primary_emotion_state()

    companion.identity_resolver.resolve.assert_called_once_with(
        "qq",
        "10001",
    )
    companion.emotion.get_state.assert_called_once_with(
        10001,
        actor_id="actor_primary",
    )
    assert state == {"label": "joy"}


def test_companion_primary_emotion_state_skips_when_master_is_unknown():
    from core.companion import Companion

    companion = object.__new__(Companion)
    companion.settings = {"qq": {"self_qq": 0}}
    companion.identity_resolver = MagicMock()
    companion.emotion = MagicMock()

    assert companion.get_primary_emotion_state() == {}
    companion.emotion.get_state.assert_not_called()


@pytest.mark.asyncio
async def test_agent_perceive_resolves_identity_and_uses_actor_emotion():
    from core.agent import Agent

    agent = object.__new__(Agent)
    agent.identity_resolver = MagicMock()

    def resolve_message(msg):
        msg.actor_id = "actor_primary"
        return msg

    agent.identity_resolver.resolve_message.side_effect = resolve_message
    agent.router = MagicMock()
    agent.router.route.return_value = "FULL"
    agent.emotion = MagicMock()
    agent.emotion.update_trajectory_async = AsyncMock()
    agent.emotion.get_state.return_value = {
        "label": "neutral",
        "pad": {"P": 0.0, "A": 0.0, "D": 0.0},
        "thresholds": {},
        "eruption": None,
    }
    agent.db = MagicMock()
    agent.db.query.return_value = []
    agent.db.query_one.return_value = None
    agent.memory = MagicMock()
    agent.memory.search = AsyncMock(return_value=[])
    agent.ctx_builder = MagicMock()
    agent.ctx_builder.build.return_value = []
    agent.provider_router = MagicMock()
    agent.provider_router.evaluate = AsyncMock(side_effect=Exception("skip"))
    agent.budget_tracker = MagicMock()
    agent.decision_engine = None
    agent._last_complexity = None
    msg = IncomingMessage.from_local("你好", 10001)

    perceived = await agent.perceive(msg)

    agent.identity_resolver.resolve_message.assert_called_once_with(msg)
    agent.emotion.update_trajectory_async.assert_awaited_once_with(
        10001,
        "你好",
        actor_id="actor_primary",
    )
    agent.emotion.get_state.assert_called_once_with(
        10001,
        actor_id="actor_primary",
    )
    history_call = next(
        call
        for call in agent.db.query.call_args_list
        if "FROM chat_log" in call.args[0]
    )
    history_sql, history_params = history_call.args
    assert "actor_id = ?" in history_sql
    assert "channel = ?" in history_sql
    assert history_params == ("actor_primary", "desktop")
    assert perceived.msg.actor_id == "actor_primary"


@pytest.mark.asyncio
async def test_agent_run_tunes_and_persists_channel_identity():
    from core.agent import Agent, Decision, PerceivedInput, Thought

    agent = object.__new__(Agent)
    agent.cognition = MagicMock()
    agent.cognition.begin.return_value = {"id": 0, "stages": {}}
    agent.db = MagicMock()
    agent.db.insert.side_effect = [11, 12]
    agent.emotion = MagicMock()
    agent.emotion.tune.side_effect = lambda text, **kwargs: text
    agent.self_evolver = None
    agent.perceive = AsyncMock(return_value=PerceivedInput(
        msg=IncomingMessage.from_local("你好", 10001),
        route_mode="FULL",
        context=[],
        emotion_info={"label": "neutral", "thresholds": {}},
        eruption_info=None,
        memory_hits=[],
        history=[],
        reply_to=None,
    ))
    perceived_msg = agent.perceive.return_value.msg
    perceived_msg.actor_id = "actor_primary"
    agent.reason = AsyncMock(return_value=Thought(
        raw_text="嗯。",
        reply_text="嗯。",
        react_trace={},
        tool_results=[],
        model="test",
        usage={},
    ))
    decision = Decision(
        intent="reply",
        selected_skill=None,
        skill_args=None,
        emotion={"label": "neutral"},
        pacing=(0.0, "normal"),
    )
    agent.decide = AsyncMock(return_value=decision)
    agent.act = AsyncMock(return_value=[])
    agent.reflect = AsyncMock(return_value=None)
    agent.express = Agent.express.__get__(agent, Agent)

    result = await agent.run(perceived_msg)

    agent.emotion.tune.assert_called_once_with(
        "嗯。",
        actor_id="actor_primary",
    )
    chat_rows = [
        call.args[1]
        for call in agent.db.insert.call_args_list
        if call.args[0] == "chat_log"
    ]
    assert len(chat_rows) == 2
    assert all(row["actor_id"] == "actor_primary" for row in chat_rows)
    assert all(row["channel"] == "desktop" for row in chat_rows)
    assert all(row["channel_account_id"] == "local" for row in chat_rows)
    assert result.user_msg_id == 11
    assert result.ai_msg_ids == [12]


def test_long_term_memory_keeps_legacy_user_scope_without_actor_guessing(tmp_path):
    db_path = tmp_path / "legacy-memory.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE long_term_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            created_at TEXT,
            accessed_at TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO long_term_memory
           (user_id, memory_type, content, importance)
           VALUES (7, 'fact', '旧记忆', 5)"""
    )
    conn.commit()
    conn.close()

    db = _fresh_database(db_path)
    try:
        memory = LongTermMemory(db)

        assert [row["content"] for row in memory.retrieve(7)] == ["旧记忆"]
        assert memory.retrieve(7, actor_id="actor_legacy") == []
        assert db.query_one(
            "SELECT actor_id FROM long_term_memory WHERE id = 1"
        ) == {"actor_id": None}
    finally:
        Database.reset_instance()

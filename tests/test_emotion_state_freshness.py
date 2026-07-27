from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock


def test_history_selects_latest_rows_then_returns_chronological_order():
    from core.emotion_state_store import EmotionStateStore

    db = MagicMock()
    db.query.return_value = []
    store = EmotionStateStore(db)

    store.history(10001, 123, limit=5000, actor_id="actor_primary")

    sql, params = db.query.call_args.args
    assert "ORDER BY ts DESC" in sql
    assert "LIMIT ?" in sql
    assert sql.rstrip().endswith("ORDER BY ts ASC, id ASC")
    assert params == ("actor_primary", 123, 5000)


def test_history_latest_query_runs_against_sqlite():
    from core.emotion_state_store import EmotionStateStore

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE emotion_state_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            actor_id TEXT
        )"""
    )
    connection.executemany(
        "INSERT INTO emotion_state_snapshot (ts, user_id, actor_id) VALUES (?, 7, 'actor')",
        [(100,), (200,), (300,), (400,), (500,)],
    )

    class Db:
        def query(self, sql, params):
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    rows = EmotionStateStore(Db()).history(
        7,
        0,
        limit=3,
        actor_id="actor",
    )

    assert [row["ts"] for row in rows] == [300, 400, 500]
    connection.close()


def test_freshness_metadata_exposes_sample_and_persistence_age():
    from core.emotion_state_store import EmotionStateStore

    db = MagicMock()
    db.query_one.return_value = {"ts": 8_000}
    store = EmotionStateStore(db)

    metadata = store.freshness_metadata(
        10001,
        actor_id="actor_primary",
        sampled_at=9_500,
        now_ms=10_000,
        stale_after_ms=1_000,
    )

    assert metadata == {
        "sampledAt": 9_500,
        "latestPersistedAt": 8_000,
        "serverNow": 10_000,
        "stale": False,
    }

    metadata = store.freshness_metadata(
        10001,
        actor_id="actor_primary",
        sampled_at=8_500,
        now_ms=10_000,
        stale_after_ms=1_000,
    )
    assert metadata["stale"] is True


def test_companion_primary_state_adds_identity_and_freshness_metadata():
    from core.companion import Companion

    companion = object.__new__(Companion)
    companion.get_primary_identity = MagicMock(
        return_value=(10001, MagicMock(actor_id="actor_primary")),
    )
    companion.emotion = MagicMock()
    companion.emotion.get_state.return_value = {
        "label": "joy",
        "pad": {"P": 0.2, "A": 0.1, "D": 0.3},
    }
    companion.state_store = MagicMock()
    companion.state_store.freshness_metadata.return_value = {
        "sampledAt": 9_500,
        "latestPersistedAt": 8_000,
        "serverNow": 10_000,
        "stale": False,
    }
    companion._emotion_last_sampled_at = 9_500

    state = companion.get_primary_emotion_state()

    assert state["primaryUserId"] == 10001
    assert state["sampledAt"] == 9_500
    assert state["stale"] is False
    companion.state_store.freshness_metadata.assert_called_once_with(
        10001,
        actor_id="actor_primary",
        sampled_at=9_500,
    )


def test_companion_primary_state_reports_unconfigured_identity():
    from core.companion import Companion

    companion = object.__new__(Companion)
    companion.get_primary_identity = MagicMock(return_value=None)

    state = companion.get_primary_emotion_state()

    assert state["status"] == "unavailable"
    assert state["primaryUserId"] is None
    assert state["stale"] is True
    assert "error" in state

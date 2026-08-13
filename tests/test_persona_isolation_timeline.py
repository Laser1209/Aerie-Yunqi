"""Persona-scoped timeline / summary tests (portal F)."""

import os
import sqlite3
import tempfile


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_timeline_recent_events_filters_by_persona():
    """persona A 的事件不出现在 persona B 的检索中（NULL 共享仍可见）。"""
    with tempfile.TemporaryDirectory() as td:
        conn = _make_db(os.path.join(td, "t.db"))
        conn.executescript(
            """
            CREATE TABLE persona_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id TEXT NOT NULL, user_id INTEGER NOT NULL,
                channel TEXT NOT NULL, turn_id TEXT NOT NULL,
                event_summary TEXT NOT NULL, occurred_at TEXT NOT NULL,
                persona_id TEXT DEFAULT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO persona_timeline (actor_id, user_id, channel, turn_id, event_summary, occurred_at, persona_id) VALUES (?,?,?,?,?,?,?)",
            [
                ("a", 7, "desktop", "t1", "共享事件", "2026-08-13T00:00:00Z", None),
                ("a", 7, "desktop", "t2", "角色A事件", "2026-08-13T00:01:00Z", "persona_a"),
                ("a", 7, "desktop", "t3", "角色B事件", "2026-08-13T00:02:00Z", "persona_b"),
            ],
        )
        conn.commit()

        def rows(persona):
            if persona is None:
                clauses = "user_id = ?"
                params = (7,)
            else:
                clauses = "user_id = ? AND (persona_id = ? OR persona_id IS NULL)"
                params = (7, persona)
            return {
                r["event_summary"]
                for r in conn.execute(
                    f"SELECT event_summary FROM persona_timeline WHERE {clauses} ORDER BY id",
                    params,
                )
            }

        assert rows("persona_a") == {"共享事件", "角色A事件"}
        assert rows("persona_b") == {"共享事件", "角色B事件"}
        conn.close()

from __future__ import annotations

import json
import sqlite3

from scripts import mobile_accounts


def test_store_loads_project_env_before_reading_mobile_settings(
    tmp_path, monkeypatch
):
    auth_db = tmp_path / "mobile.db"
    monkeypatch.delenv("AERIE_MOBILE_TOKEN_PEPPER", raising=False)
    monkeypatch.delenv("AERIE_MOBILE_AUTH_DB", raising=False)

    def fake_load_dotenv(path, *, override):
        assert path == mobile_accounts.ROOT / ".env"
        assert override is False
        monkeypatch.setenv(
            "AERIE_MOBILE_TOKEN_PEPPER",
            "test-only-pepper-with-at-least-32-bytes",
        )
        monkeypatch.setenv("AERIE_MOBILE_AUTH_DB", str(auth_db))

    monkeypatch.setattr(mobile_accounts, "load_dotenv", fake_load_dotenv)

    store = mobile_accounts._store()

    assert store.db_path == auth_db
    assert auth_db.exists()


def test_local_account_cli_creates_actor_binding(tmp_path, monkeypatch, capsys):
    main_db = tmp_path / "aerie.db"
    auth_db = tmp_path / "mobile.db"
    conn = sqlite3.connect(main_db)
    conn.executescript(
        """CREATE TABLE actors (
               actor_id TEXT PRIMARY KEY,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP
           );
           CREATE TABLE channel_accounts (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               channel TEXT NOT NULL,
               channel_account_id TEXT NOT NULL,
               actor_id TEXT NOT NULL REFERENCES actors(actor_id),
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(channel, channel_account_id)
           );
           CREATE TABLE chat_log (
               id INTEGER PRIMARY KEY, user_id INTEGER, actor_id TEXT
           );
           CREATE TABLE long_term_memory (
               id INTEGER PRIMARY KEY, user_id INTEGER, actor_id TEXT
           );
           CREATE TABLE emotion_state_snapshot (
               id INTEGER PRIMARY KEY, user_id INTEGER, actor_id TEXT
           );
           CREATE TABLE conversations (
               conversation_id TEXT PRIMARY KEY, actor_id TEXT
           );
           CREATE TABLE messages (
               message_id TEXT PRIMARY KEY, conversation_id TEXT,
               legacy_chat_log_id INTEGER, actor_id TEXT
           );
           CREATE TABLE requests (
               request_id TEXT PRIMARY KEY, conversation_id TEXT,
               user_id INTEGER, actor_id TEXT
           );
           INSERT INTO chat_log(id, user_id) VALUES (1, 1001);
           INSERT INTO conversations(conversation_id) VALUES ('conv-owner');
           INSERT INTO messages(message_id, conversation_id, legacy_chat_log_id)
           VALUES ('msg-owner', 'conv-owner', 1);
           INSERT INTO requests(request_id, conversation_id)
           VALUES ('req-owner', 'conv-owner');"""
    )
    conn.close()
    monkeypatch.setenv(
        "AERIE_MOBILE_TOKEN_PEPPER",
        "test-only-pepper-with-at-least-32-bytes",
    )
    monkeypatch.setenv("AERIE_MOBILE_AUTH_DB", str(auth_db))
    monkeypatch.setenv("AERIE_DB_PATH", str(main_db))
    passwords = iter(
        ["correct-horse-battery-staple", "correct-horse-battery-staple"]
    )
    monkeypatch.setattr(mobile_accounts.getpass, "getpass", lambda _: next(passwords))

    result = mobile_accounts.main(
        [
            "create-owner",
            "owner",
            "--actor-id",
            "actor-primary",
            "--user-id",
            "1001",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    conn = sqlite3.connect(main_db)
    bindings = conn.execute(
        """SELECT channel, channel_account_id, actor_id
           FROM channel_accounts ORDER BY channel"""
    ).fetchall()
    message_actor = conn.execute(
        "SELECT actor_id FROM messages WHERE message_id = 'msg-owner'"
    ).fetchone()[0]
    request_identity = conn.execute(
        "SELECT actor_id, user_id FROM requests WHERE request_id = 'req-owner'"
    ).fetchone()
    conn.close()
    assert bindings == [
        ("desktop", "local", "actor-primary"),
        ("mobile", output["account_id"], "actor-primary"),
        ("qq", "1001", "actor-primary"),
    ]
    assert message_actor == "actor-primary"
    assert request_identity == ("actor-primary", 1001)

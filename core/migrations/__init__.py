from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable


MIGRATION_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS migration_ledger (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    cursor TEXT
)
"""


class MigrationChecksumError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    checksum: str
    apply: Callable[[sqlite3.Connection], None]


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
        )


def _apply_phase2_identity(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS actors (
            actor_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS channel_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            channel_account_id TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES actors(actor_id),
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(channel, channel_account_id)
        )"""
    )
    for column, declaration in (
        ("actor_id", "TEXT DEFAULT NULL"),
        ("channel", "TEXT DEFAULT NULL"),
        ("channel_account_id", "TEXT DEFAULT NULL"),
    ):
        _add_column_if_missing(
            conn,
            "chat_log",
            column,
            declaration,
        )
    _add_column_if_missing(
        conn,
        "long_term_memory",
        "actor_id",
        "TEXT DEFAULT NULL",
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_memory_actor_importance
           ON long_term_memory(
               actor_id,
               importance DESC,
               created_at DESC
           )"""
    )


def _apply_phase2_emotion_snapshot(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type = 'table' AND name = ?",
        ("emotion_state_snapshot",),
    ).fetchone()
    if not table_exists:
        raise sqlite3.OperationalError(
            "required table emotion_state_snapshot is missing"
        )
    _add_column_if_missing(
        conn,
        "emotion_state_snapshot",
        "actor_id",
        "TEXT DEFAULT NULL",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_emotion_actor_ts "
        "ON emotion_state_snapshot(actor_id, ts DESC)"
    )


def _apply_phase3_conversation_model(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            actor_id TEXT DEFAULT NULL REFERENCES actors(actor_id),
            channel TEXT DEFAULT NULL,
            channel_account_id TEXT DEFAULT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS turns (
            turn_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            completed_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            turn_id TEXT NOT NULL REFERENCES turns(turn_id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            attachments TEXT,
            response_group_id TEXT,
            sequence INTEGER NOT NULL DEFAULT 0,
            channel TEXT DEFAULT NULL,
            actor_id TEXT DEFAULT NULL REFERENCES actors(actor_id),
            legacy_chat_log_id INTEGER UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            turn_id TEXT NOT NULL REFERENCES turns(turn_id),
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            completed_at TEXT,
            error TEXT
        )"""
    )


def phase3_conversation_migrations() -> list[Migration]:
    contract = """004_conversation_model
conversations(conversation_id,actor_id,channel,channel_account_id,status)
turns(turn_id,conversation_id,status)
messages(message_id,conversation_id,turn_id,role,response_group_id,sequence)
requests(request_id,conversation_id,turn_id,status)
"""
    return [
        Migration(
            version="004_conversation_model",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_phase3_conversation_model,
        )
    ]


def _apply_phase3_conversation_backfill(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type = 'table' AND name = ?",
        ("chat_log",),
    ).fetchone()
    if not table_exists:
        raise sqlite3.OperationalError(
            "required table chat_log is missing"
        )
    for column, declaration in (
        ("attachments", "TEXT DEFAULT NULL"),
        ("actor_id", "TEXT DEFAULT NULL"),
        ("channel", "TEXT DEFAULT NULL"),
        ("channel_account_id", "TEXT DEFAULT NULL"),
    ):
        _add_column_if_missing(
            conn,
            "chat_log",
            column,
            declaration,
        )
    _add_column_if_missing(
        conn,
        "messages",
        "channel_account_id",
        "TEXT DEFAULT NULL",
    )
    from core.conversation_backfill import backfill_chat_log

    version = "005_conversation_backfill"
    cursor_row = conn.execute(
        "SELECT cursor FROM migration_ledger WHERE version = ?",
        (version,),
    ).fetchone()
    after_id = int(cursor_row["cursor"] or 0) if cursor_row else 0
    while True:
        result = backfill_chat_log(
            conn,
            after_id=after_id,
            limit=500,
        )
        if result["processed"]:
            after_id = int(result["cursor"])
            conn.execute(
                "UPDATE migration_ledger SET cursor = ? WHERE version = ?",
                (str(after_id), version),
            )
        if not result["has_more"]:
            break


def phase3_backfill_migrations() -> list[Migration]:
    contract = """005_conversation_backfill
chat_log -> conversations/turns/messages/requests
legacy_chat_log_id idempotency
preserve actor/channel/attachments/order
"""
    return [
        Migration(
            version="005_conversation_backfill",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_phase3_conversation_backfill,
        )
    ]


def phase2_identity_migrations() -> list[Migration]:
    contract = """002_actor_channel_identity
actors(actor_id)
channel_accounts(channel,channel_account_id,actor_id)
chat_log(actor_id,channel,channel_account_id)
long_term_memory(actor_id)
"""
    emotion_contract = """003_actor_emotion_snapshot
emotion_state_snapshot(actor_id)
"""
    return [
        Migration(
            version="002_actor_channel_identity",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_phase2_identity,
        ),
        Migration(
            version="003_actor_emotion_snapshot",
            checksum=hashlib.sha256(
                emotion_contract.encode("utf-8")
            ).hexdigest(),
            apply=_apply_phase2_emotion_snapshot,
        ),
    ]


def initialize_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(MIGRATION_LEDGER_SQL)


class MigrationRunner:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        initialize_ledger(conn)

    def run(
        self,
        migrations: Iterable[Migration],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        pending: list[str] = []
        for migration in migrations:
            row = self._get_row(migration.version)
            self._validate_checksum(migration, row)
            if row and row["status"] == "completed":
                continue
            pending.append(migration.version)
            if not dry_run:
                self._run_one(migration, row)
        return pending

    def get_cursor(self, version: str) -> str | None:
        row = self.conn.execute(
            "SELECT cursor FROM migration_ledger WHERE version = ?",
            (version,),
        ).fetchone()
        return row["cursor"] if row else None

    def set_cursor(self, version: str, cursor: str | None) -> None:
        updated = self.conn.execute(
            "UPDATE migration_ledger SET cursor = ? WHERE version = ?",
            (cursor, version),
        ).rowcount
        if updated == 0:
            raise KeyError(f"Migration {version} has not started")

    def _get_row(self, version: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT checksum, status, cursor FROM migration_ledger WHERE version = ?",
            (version,),
        ).fetchone()

    @staticmethod
    def _validate_checksum(
        migration: Migration,
        row: sqlite3.Row | None,
    ) -> None:
        if row and row["checksum"] != migration.checksum:
            raise MigrationChecksumError(
                f"Migration {migration.version} checksum conflict"
            )

    def _run_one(
        self,
        migration: Migration,
        row: sqlite3.Row | None = None,
    ) -> None:
        row = row or self._get_row(migration.version)
        self._validate_checksum(migration, row)
        if row and row["status"] == "completed":
            return

        started_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO migration_ledger
               (version, checksum, status, started_at, completed_at, error, cursor)
               VALUES (?, ?, 'running', ?, NULL, NULL, NULL)
               ON CONFLICT(version) DO UPDATE SET
                   status = 'running', started_at = excluded.started_at,
                   completed_at = NULL, error = NULL""",
            (migration.version, migration.checksum, started_at),
        )
        try:
            migration.apply(self.conn)
        except Exception as exc:
            self.conn.execute(
                "UPDATE migration_ledger SET status = 'failed', error = ? WHERE version = ?",
                (str(exc), migration.version),
            )
            raise
        self.conn.execute(
            """UPDATE migration_ledger
               SET status = 'completed', completed_at = ?, error = NULL
               WHERE version = ?""",
            (datetime.now(timezone.utc).isoformat(), migration.version),
        )

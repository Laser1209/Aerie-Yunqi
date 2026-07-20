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


def phase2_identity_migrations() -> list[Migration]:
    contract = """002_actor_channel_identity
actors(actor_id)
channel_accounts(channel,channel_account_id,actor_id)
chat_log(actor_id,channel,channel_account_id)
long_term_memory(actor_id)
"""
    return [
        Migration(
            version="002_actor_channel_identity",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_phase2_identity,
        )
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

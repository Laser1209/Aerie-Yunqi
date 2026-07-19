from __future__ import annotations

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


def initialize_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(MIGRATION_LEDGER_SQL)


class MigrationRunner:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        initialize_ledger(conn)

    def run(self, migrations: Iterable[Migration]) -> None:
        for migration in migrations:
            self._run_one(migration)

    def _run_one(self, migration: Migration) -> None:
        row = self.conn.execute(
            "SELECT checksum, status FROM migration_ledger WHERE version = ?",
            (migration.version,),
        ).fetchone()
        if row:
            if row["checksum"] != migration.checksum:
                raise MigrationChecksumError(
                    f"Migration {migration.version} checksum conflict"
                )
            if row["status"] == "completed":
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

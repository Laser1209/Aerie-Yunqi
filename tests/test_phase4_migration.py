import sqlite3


PHASE4_COLUMNS = {
    "actor_id",
    "channel",
    "channel_account_id",
    "user_id",
    "input_content",
    "effective_content",
    "attachments",
    "reply_to_id",
    "retry_of_request_id",
    "cancel_requested_at",
    "cancelled_at",
    "started_at",
    "lease_owner",
    "lease_expires_at",
    "last_heartbeat_at",
    "error_code",
}

PHASE4_INDEXES = {
    "idx_requests_status_created",
    "idx_requests_conversation_status",
    "idx_requests_lease_expires",
}

PHASE4_CHECKSUM = (
    "2e649f6834695ca7b9250c3e2f7c110ab9c5b2c4ed2a230d1cd4fb5e0654ea05"
)
PHASE3_SCHEMA_CHECKSUM = (
    "7b808212291a457ff3ca1cc2a54e60a58192f80356f59ebefbb3de8349417702"
)
PHASE3_BACKFILL_CHECKSUM = (
    "d164d3c78ef422d3578841bfad6ec3ac0f6ad774b374fee3d36630fa227b567a"
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA index_list({table})").fetchall()
    }


def _phase3_connection() -> sqlite3.Connection:
    from core.migrations import MigrationRunner, phase3_conversation_migrations

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE actors (
            actor_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )"""
    )
    MigrationRunner(conn).run(phase3_conversation_migrations())
    return conn


def test_phase4_migration_adds_request_queue_columns_and_indexes():
    from core.migrations import MigrationRunner, phase4_request_queue_migrations

    conn = _phase3_connection()
    MigrationRunner(conn).run(phase4_request_queue_migrations())

    assert _columns(conn, "requests") >= PHASE4_COLUMNS
    assert _indexes(conn, "requests") >= PHASE4_INDEXES


def test_phase4_migration_checksum_is_fixed_and_004_005_unchanged():
    from core.migrations import (
        phase3_backfill_migrations,
        phase3_conversation_migrations,
        phase4_request_queue_migrations,
    )

    assert phase3_conversation_migrations()[0].checksum == PHASE3_SCHEMA_CHECKSUM
    assert phase3_backfill_migrations()[0].checksum == PHASE3_BACKFILL_CHECKSUM
    migration = phase4_request_queue_migrations()[0]
    assert migration.version == "006_chat_request_queue"
    assert migration.checksum == PHASE4_CHECKSUM


def test_phase4_migration_dry_run_has_zero_schema_writes():
    from core.migrations import MigrationRunner, phase4_request_queue_migrations

    conn = _phase3_connection()
    before_columns = _columns(conn, "requests")
    before_indexes = _indexes(conn, "requests")

    pending = MigrationRunner(conn).run(
        phase4_request_queue_migrations(),
        dry_run=True,
    )

    assert pending == ["006_chat_request_queue"]
    assert _columns(conn, "requests") == before_columns
    assert _indexes(conn, "requests") == before_indexes
    assert conn.execute(
        "SELECT 1 FROM migration_ledger WHERE version = ?",
        ("006_chat_request_queue",),
    ).fetchone() is None


def test_phase4_migration_is_idempotent_after_second_run():
    from core.migrations import MigrationRunner, phase4_request_queue_migrations

    conn = _phase3_connection()
    runner = MigrationRunner(conn)
    first = runner.run(phase4_request_queue_migrations())
    second = runner.run(phase4_request_queue_migrations())

    assert first == ["006_chat_request_queue"]
    assert second == []
    assert conn.execute(
        "SELECT COUNT(*) FROM migration_ledger WHERE version = ?",
        ("006_chat_request_queue",),
    ).fetchone()[0] == 1
    assert _columns(conn, "requests") >= PHASE4_COLUMNS
    assert _indexes(conn, "requests") >= PHASE4_INDEXES


def test_phase4_migration_recovers_partially_applied_columns_and_indexes():
    from core.migrations import MigrationRunner, phase4_request_queue_migrations

    conn = _phase3_connection()
    conn.execute("ALTER TABLE requests ADD COLUMN actor_id TEXT DEFAULT NULL")
    conn.execute(
        "CREATE INDEX idx_requests_status_created "
        "ON requests(status, created_at, request_id)"
    )

    MigrationRunner(conn).run(phase4_request_queue_migrations())

    assert _columns(conn, "requests") >= PHASE4_COLUMNS
    assert _indexes(conn, "requests") >= PHASE4_INDEXES


def test_phase4_migration_preserves_legacy_completed_null_snapshots():
    from core.migrations import MigrationRunner, phase4_request_queue_migrations

    conn = _phase3_connection()
    conn.execute(
        "INSERT INTO conversations (conversation_id) VALUES (?)",
        ("conv_legacy",),
    )
    conn.execute(
        "INSERT INTO turns (turn_id, conversation_id, status, completed_at) "
        "VALUES (?, ?, 'completed', ?)",
        ("turn_legacy", "conv_legacy", "2026-07-20T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO requests "
        "(request_id, conversation_id, turn_id, status, completed_at) "
        "VALUES (?, ?, ?, 'completed', ?)",
        (
            "req_legacy",
            "conv_legacy",
            "turn_legacy",
            "2026-07-20T00:00:00+00:00",
        ),
    )

    MigrationRunner(conn).run(phase4_request_queue_migrations())

    row = conn.execute(
        "SELECT * FROM requests WHERE request_id = ?",
        ("req_legacy",),
    ).fetchone()
    assert row["status"] == "completed"
    assert all(row[column] is None for column in PHASE4_COLUMNS)


def test_database_runs_006_when_migration_framework_is_on_even_queue_flag_is_off(
    monkeypatch,
    tmp_path,
):
    from core.database import Database

    monkeypatch.setenv("AERIE_FEATURE_MIGRATION_FRAMEWORK_V1", "true")
    monkeypatch.setenv("AERIE_FEATURE_CHAT_REQUEST_QUEUE_V1", "false")
    Database.reset_instance()
    try:
        db = Database(tmp_path / "phase4-migrations.db")
        with db.connection() as conn:
            assert _columns(conn, "requests") >= PHASE4_COLUMNS
            assert conn.execute(
                "SELECT status FROM migration_ledger WHERE version = ?",
                ("006_chat_request_queue",),
            ).fetchone()["status"] == "completed"
    finally:
        Database.reset_instance()


def test_database_does_not_run_versioned_006_when_migration_framework_is_off(
    monkeypatch,
    tmp_path,
):
    from core.database import Database

    monkeypatch.setenv("AERIE_FEATURE_MIGRATION_FRAMEWORK_V1", "false")
    monkeypatch.setenv("AERIE_FEATURE_CHAT_REQUEST_QUEUE_V1", "true")
    Database.reset_instance()
    try:
        db = Database(tmp_path / "phase4-legacy.db")
        with db.connection() as conn:
            assert "migration_ledger" not in {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            assert "requests" not in {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
    finally:
        Database.reset_instance()


def test_phase4_migration_quick_check_is_ok():
    from core.migrations import MigrationRunner, phase4_request_queue_migrations

    conn = _phase3_connection()
    MigrationRunner(conn).run(phase4_request_queue_migrations())

    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"

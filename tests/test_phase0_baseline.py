import json
import sqlite3

import pytest
import yaml


def _migration(version, checksum, table_name="phase0_probe"):
    from core.migrations import Migration

    def apply(conn):
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER PRIMARY KEY)")

    return Migration(version=version, checksum=checksum, apply=apply)


def test_migration_ledger_initializes_on_empty_database():
    from core.migrations import initialize_ledger

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_ledger(conn)

    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(migration_ledger)")
    }
    assert columns >= {
        "version",
        "checksum",
        "status",
        "started_at",
        "completed_at",
        "error",
        "cursor",
    }


def test_migration_runner_is_idempotent():
    from core.migrations import MigrationRunner

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    runner = MigrationRunner(conn)
    migration = _migration("001_probe", "checksum-a")

    runner.run([migration])
    runner.run([migration])

    row = conn.execute(
        "SELECT * FROM migration_ledger WHERE version = ?", ("001_probe",)
    ).fetchone()
    assert row["status"] == "completed"
    assert conn.execute(
        "SELECT COUNT(*) FROM migration_ledger WHERE version = ?", ("001_probe",)
    ).fetchone()[0] == 1


def test_migration_runner_rejects_checksum_conflict():
    from core.migrations import MigrationChecksumError, MigrationRunner

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    runner = MigrationRunner(conn)
    runner.run([_migration("001_probe", "checksum-a")])

    with pytest.raises(MigrationChecksumError):
        runner.run([_migration("001_probe", "checksum-b")])


def test_migration_runner_dry_run_does_not_apply_migration():
    from core.migrations import MigrationRunner

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    runner = MigrationRunner(conn)

    pending = runner.run(
        [_migration("001_probe", "checksum-a")],
        dry_run=True,
    )

    assert pending == ["001_probe"]
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'phase0_probe'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT * FROM migration_ledger WHERE version = ?", ("001_probe",)
    ).fetchone() is None


def test_migration_cursor_survives_failure_and_can_resume():
    from core.migrations import Migration, MigrationRunner

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    runner = MigrationRunner(conn)
    attempts = 0

    def apply(_conn):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            runner.set_cursor("001_resume", "batch-20")
            raise RuntimeError("interrupted")
        assert runner.get_cursor("001_resume") == "batch-20"

    migration = Migration("001_resume", "checksum-resume", apply)

    with pytest.raises(RuntimeError, match="interrupted"):
        runner.run([migration])
    assert runner.get_cursor("001_resume") == "batch-20"

    runner.run([migration])

    row = conn.execute(
        "SELECT status, cursor FROM migration_ledger WHERE version = ?",
        ("001_resume",),
    ).fetchone()
    assert dict(row) == {"status": "completed", "cursor": "batch-20"}


def test_database_initialization_runs_migration_framework(tmp_path):
    from core.database import Database

    Database.reset_instance()
    try:
        db = Database(tmp_path / "phase0.db")
        assert "migration_ledger" in db.list_tables()
        assert "chat_log" in db.list_tables()
    finally:
        Database.reset_instance()


def test_database_initialization_uses_legacy_schema_when_migration_flag_is_off(
    monkeypatch,
    tmp_path,
):
    from core.database import Database

    monkeypatch.setenv("AERIE_FEATURE_MIGRATION_FRAMEWORK_V1", "false")
    Database.reset_instance()
    try:
        db = Database(tmp_path / "legacy-path.db")
        assert "chat_log" in db.list_tables()
        assert "migration_ledger" not in db.list_tables()
    finally:
        Database.reset_instance()


def test_database_backup_is_consistent(tmp_path):
    from core.database import Database

    source_path = tmp_path / "source.db"
    backup_path = tmp_path / "backups" / "source.db"
    Database.reset_instance()
    try:
        db = Database(source_path)
        db.insert("chat_log", {"user_id": 7, "role": "user", "content": "backup me"})

        result = db.backup_to(backup_path)

        assert result == backup_path
        backup = sqlite3.connect(backup_path)
        try:
            assert backup.execute("SELECT content FROM chat_log").fetchone()[0] == "backup me"
        finally:
            backup.close()
    finally:
        Database.reset_instance()


def test_feature_flags_read_explicit_settings_and_default_unknown_off(tmp_path):
    from core.feature_flags import FeatureFlags

    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.safe_dump({"feature_flags": {"migration_framework_v1": True}}),
        encoding="utf-8",
    )

    flags = FeatureFlags(settings_path)

    assert flags.is_enabled("migration_framework_v1") is True
    assert flags.is_enabled("unknown_flag") is False


def test_feature_flags_parse_string_boolean_values(tmp_path):
    from core.feature_flags import FeatureFlags

    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.safe_dump(
            {
                "feature_flags": {
                    "enabled_flag": "true",
                    "disabled_flag": "false",
                }
            }
        ),
        encoding="utf-8",
    )

    flags = FeatureFlags(settings_path)

    assert flags.is_enabled("enabled_flag") is True
    assert flags.is_enabled("disabled_flag") is False


def test_feature_flag_environment_override(monkeypatch, tmp_path):
    from core.feature_flags import FeatureFlags

    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.safe_dump({"feature_flags": {"chat_stream_v1": False}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AERIE_FEATURE_CHAT_STREAM_V1", "true")

    assert FeatureFlags(settings_path).is_enabled("chat_stream_v1") is True


def test_generated_ids_are_prefixed_nonempty_and_unique():
    from core.ids import generate_id

    first = generate_id("event")
    second = generate_id("event")

    assert first.startswith("event_")
    assert second.startswith("event_")
    assert first != second


def test_event_envelope_serializes_required_contract_fields():
    from core.event_contracts import EventEnvelope

    serialized = EventEnvelope.create(
        "assistant",
        request_id="req_1",
        conversation_id="conv_1",
        turn_id="turn_1",
        message_id="msg_1",
        response_group_id="group_1",
        sequence=2,
        channel="desktop",
    ).to_dict()

    assert serialized["event_id"].startswith("event_")
    assert serialized["type"] == "assistant"
    assert serialized["ts"]
    assert serialized["request_id"] == "req_1"
    assert serialized["conversation_id"] == "conv_1"
    assert serialized["turn_id"] == "turn_1"
    assert serialized["message_id"] == "msg_1"
    assert serialized["response_group_id"] == "group_1"
    assert serialized["sequence"] == 2
    assert serialized["channel"] == "desktop"


def test_chat_events_emit_same_envelope_to_stderr_and_event_stream(monkeypatch, capsys):
    from core import event_stream
    from core.chat_events import PREFIX, emit

    published = []
    monkeypatch.setattr(
        event_stream,
        "publish",
        lambda event_type, payload: published.append((event_type, payload)),
    )

    emit(
        "assistant",
        content="兼容旧 payload",
        request_id="req_1",
        conversation_id="conv_1",
        turn_id="turn_1",
        message_id="msg_1",
        response_group_id="group_1",
        sequence=1,
        channel="desktop",
    )

    stderr_payload = json.loads(capsys.readouterr().err.split(PREFIX, 1)[1])
    event_type, stream_payload = published[0]

    assert event_type == "assistant"
    assert stderr_payload == stream_payload
    assert stderr_payload["content"] == "兼容旧 payload"
    assert stderr_payload["event_id"].startswith("event_")
    assert stderr_payload["request_id"] == "req_1"
    assert stderr_payload["conversation_id"] == "conv_1"
    assert stderr_payload["turn_id"] == "turn_1"
    assert stderr_payload["message_id"] == "msg_1"
    assert stderr_payload["response_group_id"] == "group_1"
    assert stderr_payload["sequence"] == 1
    assert stderr_payload["channel"] == "desktop"

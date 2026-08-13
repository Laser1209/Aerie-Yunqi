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


def _apply_phase4_request_queue(conn: sqlite3.Connection) -> None:
    columns = (
        ("actor_id", "TEXT DEFAULT NULL"),
        ("channel", "TEXT DEFAULT NULL"),
        ("channel_account_id", "TEXT DEFAULT NULL"),
        ("user_id", "INTEGER DEFAULT NULL"),
        ("input_content", "TEXT DEFAULT NULL"),
        ("effective_content", "TEXT DEFAULT NULL"),
        ("attachments", "TEXT DEFAULT NULL"),
        ("reply_to_id", "INTEGER DEFAULT NULL"),
        (
            "retry_of_request_id",
            "TEXT DEFAULT NULL REFERENCES requests(request_id)",
        ),
        ("cancel_requested_at", "TEXT DEFAULT NULL"),
        ("cancelled_at", "TEXT DEFAULT NULL"),
        ("started_at", "TEXT DEFAULT NULL"),
        ("lease_owner", "TEXT DEFAULT NULL"),
        ("lease_expires_at", "TEXT DEFAULT NULL"),
        ("last_heartbeat_at", "TEXT DEFAULT NULL"),
        ("error_code", "TEXT DEFAULT NULL"),
    )
    for name, declaration in columns:
        _add_column_if_missing(conn, "requests", name, declaration)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_status_created "
        "ON requests(status, created_at, request_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_conversation_status "
        "ON requests(conversation_id, status, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_lease_expires "
        "ON requests(lease_expires_at) "
        "WHERE lease_expires_at IS NOT NULL"
    )


def _apply_phase5_batch_requests(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(
        conn,
        "requests",
        "batch_id",
        "TEXT DEFAULT NULL",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_batch "
        "ON requests(batch_id, created_at, request_id) "
        "WHERE batch_id IS NOT NULL"
    )


def phase5_batch_request_migrations() -> list[Migration]:
    contract = """009_batch_request_support
requests(batch_id)
index(batch_id+created_at+request_id)
batch-aware request queue for MessageBatcher
"""
    return [
        Migration(
            version="009_batch_request_support",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_phase5_batch_requests,
        )
    ]


def phase4_request_queue_migrations() -> list[Migration]:
    contract = """006_chat_request_queue
requests(actor_id,channel,channel_account_id,user_id,input_content,effective_content,attachments,reply_to_id,retry_of_request_id,cancel_requested_at,cancelled_at,started_at,lease_owner,lease_expires_at,last_heartbeat_at,error_code)
indexes(status+created_at+request_id,conversation_id+status+created_at,lease_expires_at)
preserve legacy completed rows and nullable snapshots
"""
    return [
        Migration(
            version="006_chat_request_queue",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_phase4_request_queue,
        )
    ]


def _apply_mobile_event_log(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mobile_events (
            event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK(
                event_type IN ('message.created', 'request.updated')
            ),
            entity_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_mobile_events_actor_sequence
           ON mobile_events(actor_id, event_sequence)"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS mobile_message_created
           AFTER INSERT ON messages
           WHEN NEW.actor_id IS NOT NULL
           BEGIN
             INSERT INTO mobile_events(actor_id, event_type, entity_id)
             VALUES (NEW.actor_id, 'message.created', NEW.message_id);
           END"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS mobile_request_created
           AFTER INSERT ON requests
           WHEN NEW.actor_id IS NOT NULL
           BEGIN
             INSERT INTO mobile_events(actor_id, event_type, entity_id)
             VALUES (NEW.actor_id, 'request.updated', NEW.request_id);
           END"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS mobile_request_updated
           AFTER UPDATE OF status, updated_at, error_code ON requests
           WHEN NEW.actor_id IS NOT NULL
           BEGIN
             INSERT INTO mobile_events(actor_id, event_type, entity_id)
             VALUES (NEW.actor_id, 'request.updated', NEW.request_id);
           END"""
    )


def mobile_gateway_migrations() -> list[Migration]:
    contract = """007_mobile_event_log
mobile_events(event_sequence,actor_id,event_type,entity_id,created_at)
triggers(messages.insert,requests.insert,requests.status+updated_at+error_code)
actor-filtered resumable mobile SSE cursor
"""
    return [
        Migration(
            version="007_mobile_event_log",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_mobile_event_log,
        )
    ]


def _apply_desktop_chat_continuity(conn: sqlite3.Connection) -> None:
    """Add desktop-only continuity and attachment storage.

    The desktop attachment tables deliberately do not reference the mobile
    gateway tables.  Conversation/message identifiers remain nullable text
    links so this migration is also usable when the normalized conversation
    model feature is disabled and the desktop falls back to ``chat_log``.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            through_message_rowid INTEGER NOT NULL DEFAULT 0,
            source_message_count INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            updated_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            CHECK(through_message_rowid >= 0),
            CHECK(source_message_count >= 0),
            CHECK(revision >= 1)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS desktop_attachments (
            attachment_id TEXT PRIMARY KEY,
            conversation_id TEXT DEFAULT NULL,
            message_id TEXT DEFAULT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            storage_relpath TEXT NOT NULL,
            category TEXT NOT NULL,
            extension TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued' CHECK(
                state IN (
                    'queued', 'processing', 'ready', 'failed',
                    'quarantined', 'unsupported'
                )
            ),
            analysis_mode TEXT NOT NULL CHECK(
                analysis_mode IN ('extract', 'metadata')
            ),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT DEFAULT NULL,
            error_message TEXT DEFAULT NULL,
            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            updated_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            ready_at TEXT DEFAULT NULL,
            CHECK(size_bytes >= 0),
            CHECK(length(sha256) = 64)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS desktop_attachment_chunks (
            attachment_id TEXT NOT NULL REFERENCES desktop_attachments(
                attachment_id
            ) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            content TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            PRIMARY KEY(attachment_id, ordinal),
            CHECK(ordinal >= 0),
            CHECK(char_count >= 0),
            CHECK(length(sha256) = 64)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_desktop_attachments_state_created
           ON desktop_attachments(state, created_at, attachment_id)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_desktop_attachments_message
           ON desktop_attachments(message_id, created_at)
           WHERE message_id IS NOT NULL"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_desktop_attachments_conversation
           ON desktop_attachments(conversation_id, created_at)
           WHERE conversation_id IS NOT NULL"""
    )


def desktop_chat_continuity_migrations() -> list[Migration]:
    contract = """008_desktop_chat_continuity
conversation_summaries(conversation_id,summary,through_message_rowid,source_message_count,revision)
desktop_attachments(attachment_id,conversation_id,message_id,original_name,stored_name,storage_relpath,category,extension,mime_type,size_bytes,sha256,state,analysis_mode,metadata_json,error_code,error_message)
desktop_attachment_chunks(attachment_id,ordinal,content,char_count,sha256)
desktop-only storage; no mobile gateway table or filesystem dependency
"""
    return [
        Migration(
            version="008_desktop_chat_continuity",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_desktop_chat_continuity,
        )
    ]


def _apply_summary_buckets(conn: sqlite3.Connection) -> None:
    """Add bucketed conversation summaries (P1 分组摘要, §3.2).

    每 8 轮一段，bucket_index 递增、不覆盖旧桶；替代单层滚动摘要。
    旧 conversation_summaries 表保留只读兼容。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conversation_summary_buckets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            bucket_index INTEGER NOT NULL,
            bucket_start_rowid INTEGER NOT NULL,
            through_rowid INTEGER NOT NULL,
            source_message_count INTEGER NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            updated_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            UNIQUE (conversation_id, bucket_index),
            CHECK(bucket_index >= 1),
            CHECK(through_rowid >= 0),
            CHECK(source_message_count >= 0),
            CHECK(revision >= 1)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_summary_buckets_lookup
           ON conversation_summary_buckets (conversation_id, bucket_index DESC)"""
    )


def summary_buckets_migrations() -> list[Migration]:
    contract = """009_summary_buckets
conversation_summary_buckets(conversation_id,bucket_index,bucket_start_rowid,through_rowid,source_message_count,summary,revision)
bucketed summaries, 8 turns per bucket; old conversation_summaries kept read-only
"""
    return [
        Migration(
            version="009_summary_buckets",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_summary_buckets,
        )
    ]


def _apply_persona_timeline(conn: sqlite3.Connection) -> None:
    """Add cross-channel persona timeline table (P3-1, 附录 A.3.1).

    按 actor_id + user_id 记录跨端事件索引（不含 channel 隔离），
    供多端存在提示 / 双视图注入 / 主动回忆使用。
    UNIQUE(actor_id, user_id, turn_id) 保证幂等，重复刷新不产生重复事件。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS persona_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            event_summary TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            UNIQUE (actor_id, user_id, turn_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_timeline_lookup
           ON persona_timeline (actor_id, user_id, occurred_at DESC)"""
    )


def persona_timeline_migrations() -> list[Migration]:
    contract = """010_persona_timeline
persona_timeline(actor_id,user_id,channel,turn_id,event_summary,occurred_at)
cross-channel event index for multi-device presence / dual-view assembly / proactive recall
"""
    return [
        Migration(
            version="010_persona_timeline",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_persona_timeline,
        )
    ]


def _apply_admin_management(conn: sqlite3.Connection) -> None:
    """Add admin-platform soft-delete columns + audit log (P4b, §3.5.2).

    - messages / conversation_summary_buckets / knowledge_base 增加 deleted_at
      （软删回收站：仅标记，purge 期才物理删除，rowid 游标保持稳定）。
    - audit_log：append-only 审计（action/target_id/reason_code/timestamp/actor）。
    """
    _add_column_if_missing(conn, "messages", "deleted_at", "TEXT DEFAULT NULL")
    _add_column_if_missing(
        conn, "conversation_summary_buckets", "deleted_at", "TEXT DEFAULT NULL"
    )
    _add_column_if_missing(conn, "knowledge_base", "deleted_at", "TEXT DEFAULT NULL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target_id TEXT NOT NULL DEFAULT '',
            reason_code TEXT NOT NULL DEFAULT 'manual',
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'local_user'
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_deleted_at "
        "ON messages(deleted_at) WHERE deleted_at IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_buckets_deleted_at "
        "ON conversation_summary_buckets(deleted_at) WHERE deleted_at IS NOT NULL"
    )


def admin_management_migrations() -> list[Migration]:
    contract = """011_admin_management
messages(deleted_at)
conversation_summary_buckets(deleted_at)
knowledge_base(deleted_at)
audit_log(action,target_id,reason_code,timestamp,actor)
soft-delete recycle bin columns + append-only audit for admin platform
"""
    return [
        Migration(
            version="011_admin_management",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_admin_management,
        )
    ]


def _apply_chat_log_trash_state(conn: sqlite3.Connection) -> None:
    """给 legacy 的 chat_log 补齐软删状态（回收站后置修复）。

    admin 清空/回收站只软删了规范化 messages 表，而桌面端对话框的轮询
    （/api/chat/poll）和聊天记录（/api/chat/history）直接读 chat_log，
    导致清空后的记录依旧出现在对话框里。这里给 chat_log 加 deleted_at
    并回填：镜像 messages 已软删的行同步打上删除标记。
    """
    _add_column_if_missing(conn, "chat_log", "deleted_at", "TEXT DEFAULT NULL")
    has_messages = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    if has_messages:
        conn.execute(
            """UPDATE chat_log SET deleted_at = (
                   SELECT m.deleted_at FROM messages m
                   WHERE m.legacy_chat_log_id = chat_log.id
                     AND m.deleted_at IS NOT NULL
               )
               WHERE deleted_at IS NULL
                 AND EXISTS (
                     SELECT 1 FROM messages m
                     WHERE m.legacy_chat_log_id = chat_log.id
                       AND m.deleted_at IS NOT NULL
                 )"""
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_log_deleted_at "
        "ON chat_log(deleted_at) WHERE deleted_at IS NOT NULL"
    )


def chat_log_trash_state_migrations() -> list[Migration]:
    contract = """012_chat_log_trash_state
chat_log(deleted_at)
mirror admin soft-delete state onto the legacy chat_log so chat_log-based reads (poll / history) hide trashed conversations
"""
    return [
        Migration(
            version="012_chat_log_trash_state",
            checksum=hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            apply=_apply_chat_log_trash_state,
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

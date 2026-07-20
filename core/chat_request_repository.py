from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

UtcClock = Callable[[], datetime]


@dataclass(frozen=True)
class RequestIdentity:
    actor_id: str
    channel: str
    channel_account_id: str
    user_id: int


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    conversation_id: str
    turn_id: str
    identity: RequestIdentity
    input_content: str
    effective_content: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    reply_to_id: int = 0


@dataclass(frozen=True)
class SubmittedRequest:
    request_id: str
    conversation_id: str
    turn_id: str
    status: str = "queued"


@dataclass(frozen=True)
class ClaimedRequest:
    context: RequestContext
    lease_owner: str
    lease_expires_at: str


class ChatRequestRepository:
    def __init__(
        self,
        database: Any,
        *,
        clock: UtcClock | None = None,
    ) -> None:
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        current = self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _timestamp(self, value: datetime | None = None) -> str:
        return (value or self._now()).isoformat()

    def submit(
        self,
        *,
        context: RequestContext,
        retry_of_request_id: str | None = None,
    ) -> SubmittedRequest:
        created_at = self._timestamp()
        attachments = json.dumps(
            context.attachments,
            ensure_ascii=False,
        )
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO conversations
                       (conversation_id, actor_id, channel,
                        channel_account_id, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'active', ?, ?)""",
                    (
                        context.conversation_id,
                        context.identity.actor_id,
                        context.identity.channel,
                        context.identity.channel_account_id,
                        created_at,
                        created_at,
                    ),
                )
                conn.execute(
                    """INSERT INTO turns
                       (turn_id, conversation_id, status, created_at)
                       VALUES (?, ?, 'pending', ?)""",
                    (
                        context.turn_id,
                        context.conversation_id,
                        created_at,
                    ),
                )
                conn.execute(
                    """INSERT INTO requests
                       (request_id, conversation_id, turn_id, status,
                        created_at, updated_at, actor_id, channel,
                        channel_account_id, user_id, input_content,
                        effective_content, attachments, reply_to_id,
                        retry_of_request_id)
                       VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        context.request_id,
                        context.conversation_id,
                        context.turn_id,
                        created_at,
                        created_at,
                        context.identity.actor_id,
                        context.identity.channel,
                        context.identity.channel_account_id,
                        context.identity.user_id,
                        context.input_content,
                        context.effective_content,
                        attachments,
                        context.reply_to_id,
                        retry_of_request_id,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return SubmittedRequest(
            request_id=context.request_id,
            conversation_id=context.conversation_id,
            turn_id=context.turn_id,
        )

    def _row_to_context(self, row: sqlite3.Row) -> RequestContext:
        attachments = json.loads(row["attachments"] or "[]")
        return RequestContext(
            request_id=row["request_id"],
            conversation_id=row["conversation_id"],
            turn_id=row["turn_id"],
            identity=RequestIdentity(
                actor_id=row["actor_id"],
                channel=row["channel"],
                channel_account_id=row["channel_account_id"],
                user_id=int(row["user_id"]),
            ),
            input_content=row["input_content"] or "",
            effective_content=row["effective_content"] or "",
            attachments=attachments,
            reply_to_id=int(row["reply_to_id"] or 0),
        )

    def get_owned(
        self,
        *,
        request_id: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """SELECT * FROM requests
                   WHERE request_id = ? AND actor_id = ?""",
                (request_id, actor_id),
            ).fetchone()
            if row is None:
                return None
            messages = conn.execute(
                """SELECT role, legacy_chat_log_id, sequence
                   FROM messages
                   WHERE turn_id = ?
                   ORDER BY sequence ASC""",
                (row["turn_id"],),
            ).fetchall()

        result = dict(row)
        result["user_message_id"] = next(
            (
                int(message["legacy_chat_log_id"])
                for message in messages
                if message["role"] == "user"
                and message["legacy_chat_log_id"] is not None
            ),
            None,
        )
        result["assistant_message_ids"] = tuple(
            int(message["legacy_chat_log_id"])
            for message in messages
            if message["role"] == "assistant"
            and message["legacy_chat_log_id"] is not None
        )
        return result

    def reply_to_belongs_to_context(
        self,
        *,
        legacy_chat_log_id: int,
        actor_id: str,
        channel: str,
        channel_account_id: str,
        conversation_id: str,
    ) -> bool:
        with self.database.connection() as conn:
            row = conn.execute(
                """SELECT 1
                   FROM messages
                   WHERE legacy_chat_log_id = ?
                     AND actor_id = ?
                     AND channel = ?
                     AND channel_account_id = ?
                     AND conversation_id = ?
                   LIMIT 1""",
                (
                    legacy_chat_log_id,
                    actor_id,
                    channel,
                    channel_account_id,
                    conversation_id,
                ),
            ).fetchone()
        return row is not None

    def claim_next(
        self,
        *,
        lease_owner: str,
        lease_seconds: int,
    ) -> ClaimedRequest | None:
        now = self._now()
        now_text = self._timestamp(now)
        expiry_text = self._timestamp(
            now + timedelta(seconds=lease_seconds)
        )
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """SELECT r.*
                       FROM requests r
                       WHERE r.status = 'queued'
                         AND NOT EXISTS (
                           SELECT 1 FROM requests active
                           WHERE active.conversation_id = r.conversation_id
                             AND active.status IN ('running', 'cancelling')
                         )
                       ORDER BY r.created_at ASC, r.request_id ASC
                       LIMIT 1"""
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                changed = conn.execute(
                    """UPDATE requests
                       SET status = 'running', started_at = ?,
                           updated_at = ?, lease_owner = ?,
                           lease_expires_at = ?, last_heartbeat_at = ?,
                           error = NULL, error_code = NULL
                       WHERE request_id = ? AND status = 'queued'""",
                    (
                        now_text,
                        now_text,
                        lease_owner,
                        expiry_text,
                        now_text,
                        row["request_id"],
                    ),
                ).rowcount
                if changed != 1:
                    conn.execute("ROLLBACK")
                    return None
                conn.execute(
                    "UPDATE turns SET status = 'running' WHERE turn_id = ?",
                    (row["turn_id"],),
                )
                claimed_row = conn.execute(
                    "SELECT * FROM requests WHERE request_id = ?",
                    (row["request_id"],),
                ).fetchone()
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return ClaimedRequest(
            context=self._row_to_context(claimed_row),
            lease_owner=lease_owner,
            lease_expires_at=expiry_text,
        )

    def heartbeat(
        self,
        *,
        request_id: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> bool:
        now = self._now()
        now_text = self._timestamp(now)
        expiry_text = self._timestamp(
            now + timedelta(seconds=lease_seconds)
        )
        with self.database.connection() as conn:
            changed = conn.execute(
                """UPDATE requests
                   SET lease_expires_at = ?, last_heartbeat_at = ?,
                       updated_at = ?
                   WHERE request_id = ? AND lease_owner = ?
                     AND status IN ('running', 'cancelling')
                     AND lease_expires_at > ?""",
                (
                    expiry_text,
                    now_text,
                    now_text,
                    request_id,
                    lease_owner,
                    now_text,
                ),
            ).rowcount
        return changed == 1

    def request_cancel(
        self,
        *,
        request_id: str,
        actor_id: str,
    ) -> str | None:
        now_text = self._timestamp()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT status, turn_id FROM requests "
                    "WHERE request_id = ? AND actor_id = ?",
                    (request_id, actor_id),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                status = row["status"]
                if status == "queued":
                    conn.execute(
                        """UPDATE requests
                           SET status = 'cancelled', cancelled_at = ?,
                               updated_at = ?, lease_owner = NULL,
                               lease_expires_at = NULL
                           WHERE request_id = ?""",
                        (now_text, now_text, request_id),
                    )
                    conn.execute(
                        "UPDATE turns SET status = 'cancelled', "
                        "completed_at = ? WHERE turn_id = ?",
                        (now_text, row["turn_id"]),
                    )
                    result = "cancelled"
                elif status == "running":
                    conn.execute(
                        """UPDATE requests
                           SET status = 'cancelling',
                               cancel_requested_at = ?, updated_at = ?
                           WHERE request_id = ?""",
                        (now_text, now_text, request_id),
                    )
                    result = "cancelling"
                else:
                    result = status
                conn.execute("COMMIT")
                return result
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def mark_completed(
        self,
        *,
        request_id: str,
        lease_owner: str,
        result: dict[str, Any],
    ) -> None:
        del result  # Canonical reply data is persisted by ConversationRepository.
        self._mark_claimed_terminal(
            request_id=request_id,
            lease_owner=lease_owner,
            source_status="running",
            terminal_status="completed",
            cancelled=False,
        )

    def mark_cancelled(
        self,
        *,
        request_id: str,
        lease_owner: str | None,
    ) -> None:
        self._mark_claimed_terminal(
            request_id=request_id,
            lease_owner=lease_owner,
            source_status="cancelling",
            terminal_status="cancelled",
            cancelled=True,
        )

    def mark_failed(
        self,
        *,
        request_id: str,
        lease_owner: str | None,
        error_code: str,
    ) -> None:
        if lease_owner is not None:
            self._mark_claimed_failed(
                request_id=request_id,
                lease_owner=lease_owner,
                error_code=error_code,
            )
            return
        self._mark_terminal(
            request_id=request_id,
            lease_owner=lease_owner,
            status="failed",
            error_code=error_code,
        )

    def _mark_terminal(
        self,
        *,
        request_id: str,
        lease_owner: str | None,
        status: str,
        error_code: str | None,
    ) -> None:
        now_text = self._timestamp()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if lease_owner is None:
                    where = "request_id = ?"
                    params: tuple[Any, ...] = (request_id,)
                else:
                    where = "request_id = ? AND lease_owner = ?"
                    params = (request_id, lease_owner)
                updated = conn.execute(
                    f"""UPDATE requests
                        SET status = ?, error_code = ?, updated_at = ?,
                            completed_at = ?, lease_owner = NULL,
                            lease_expires_at = NULL
                        WHERE {where}
                          AND status IN ('running', 'cancelling', 'queued')""",
                    (
                        status,
                        error_code,
                        now_text,
                        now_text,
                        *params,
                    ),
                ).rowcount
                if updated != 1:
                    raise ValueError("request is not claim-owned")
                conn.execute(
                    """UPDATE turns SET status = ?, completed_at = ?
                       WHERE turn_id = (
                         SELECT turn_id FROM requests WHERE request_id = ?
                       )""",
                    (status, now_text, request_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _mark_claimed_terminal(
        self,
        *,
        request_id: str,
        lease_owner: str | None,
        source_status: str,
        terminal_status: str,
        cancelled: bool,
    ) -> None:
        now_text = self._timestamp()
        cancelled_at = now_text if cancelled else None
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                request_updated = conn.execute(
                    """UPDATE requests
                       SET status = ?, error = NULL, error_code = NULL,
                           updated_at = ?, completed_at = ?,
                           cancel_requested_at = CASE
                             WHEN ? THEN cancel_requested_at ELSE NULL END,
                           cancelled_at = ?, lease_owner = NULL,
                           lease_expires_at = NULL
                       WHERE request_id = ? AND lease_owner = ?
                         AND status = ? AND lease_expires_at > ?""",
                    (
                        terminal_status,
                        now_text,
                        now_text,
                        cancelled,
                        cancelled_at,
                        request_id,
                        lease_owner,
                        source_status,
                        now_text,
                    ),
                ).rowcount
                if request_updated != 1:
                    raise ValueError("request is not claim-owned")

                turn_updated = conn.execute(
                    """UPDATE turns SET status = ?, completed_at = ?
                       WHERE turn_id = (
                         SELECT turn_id FROM requests WHERE request_id = ?
                       ) AND status = 'running'""",
                    (terminal_status, now_text, request_id),
                ).rowcount
                if turn_updated != 1:
                    raise ValueError("request is not claim-owned")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _mark_claimed_failed(
        self,
        *,
        request_id: str,
        lease_owner: str,
        error_code: str,
    ) -> None:
        now_text = self._timestamp()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                request_updated = conn.execute(
                    """UPDATE requests
                       SET status = 'failed', error = NULL, error_code = ?,
                           updated_at = ?, completed_at = ?,
                           cancelled_at = NULL, lease_owner = NULL,
                           lease_expires_at = NULL
                       WHERE request_id = ? AND lease_owner = ?
                         AND status IN ('running', 'cancelling')""",
                    (
                        error_code,
                        now_text,
                        now_text,
                        request_id,
                        lease_owner,
                    ),
                ).rowcount
                if request_updated != 1:
                    raise ValueError("request is not claim-owned")

                turn_updated = conn.execute(
                    """UPDATE turns SET status = 'failed', completed_at = ?
                       WHERE turn_id = (
                         SELECT turn_id FROM requests WHERE request_id = ?
                       ) AND status = 'running'""",
                    (now_text, request_id),
                ).rowcount
                if turn_updated != 1:
                    raise ValueError("request is not claim-owned")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def recover_interrupted(self) -> int:
        now_text = self._timestamp()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    """SELECT request_id, turn_id FROM requests
                       WHERE status IN ('running', 'cancelling')
                          OR (status = 'running'
                              AND lease_expires_at <= ?)""",
                    (now_text,),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        """UPDATE requests
                           SET status = 'failed', error_code = 'process_interrupted',
                               updated_at = ?, completed_at = ?,
                               lease_owner = NULL, lease_expires_at = NULL
                           WHERE request_id = ?""",
                        (now_text, now_text, row["request_id"]),
                    )
                    conn.execute(
                        """UPDATE turns SET status = 'failed', completed_at = ?
                           WHERE turn_id = ?""",
                        (now_text, row["turn_id"]),
                    )
                conn.execute("COMMIT")
                return len(rows)
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def create_retry(
        self,
        *,
        source_request_id: str,
        actor_id: str,
        request_id: str,
        turn_id: str,
    ) -> dict[str, str]:
        created_at = self._timestamp()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                source = conn.execute(
                    "SELECT * FROM requests WHERE request_id = ? "
                    "AND actor_id = ?",
                    (source_request_id, actor_id),
                ).fetchone()
                if source is None:
                    raise LookupError("request not found")
                if source["status"] not in ("failed", "cancelled"):
                    raise ValueError("request is not retryable")
                conn.execute(
                    """INSERT INTO turns
                       (turn_id, conversation_id, status, created_at)
                       VALUES (?, ?, 'pending', ?)""",
                    (turn_id, source["conversation_id"], created_at),
                )
                conn.execute(
                    """INSERT INTO requests
                       (request_id, conversation_id, turn_id, status,
                        created_at, updated_at, actor_id, channel,
                        channel_account_id, user_id, input_content,
                        effective_content, attachments, reply_to_id,
                        retry_of_request_id)
                       VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        request_id,
                        source["conversation_id"],
                        turn_id,
                        created_at,
                        created_at,
                        source["actor_id"],
                        source["channel"],
                        source["channel_account_id"],
                        source["user_id"],
                        source["input_content"],
                        source["effective_content"],
                        source["attachments"],
                        source["reply_to_id"],
                        source_request_id,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {
            "request_id": request_id,
            "conversation_id": source["conversation_id"],
            "turn_id": turn_id,
            "status": "queued",
        }

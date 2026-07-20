from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from core.ids import generate_id


class RequestConflict(RuntimeError):
    pass


def resolve_conversation_id(
    *,
    actor_id: str | None,
    channel: str | None,
    channel_account_id: str | None,
    user_id: int,
) -> str:
    payload = "\x1f".join(
        (
            actor_id or "",
            channel or "",
            channel_account_id or "",
            str(user_id),
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"conv_{digest[:32]}"


class ConversationRepository:
    def __init__(self, database: Any, *, enabled: bool) -> None:
        self.database = database
        self.enabled = enabled

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if isinstance(self.database, sqlite3.Connection):
            yield self.database
            return
        with self.database.connection() as conn:
            yield conn

    def ensure_conversation(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO conversations
               (conversation_id, actor_id, channel, channel_account_id, status)
               VALUES (?, ?, ?, ?, 'active')""",
            (
                conversation_id,
                actor_id,
                channel,
                channel_account_id,
            ),
        )

    def persist_turn(
        self,
        *,
        request_id: str,
        user_id: int,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_content: str,
        user_attachments: list[dict[str, Any]] | None,
        assistant_segments: list[str],
        conversation_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, str] | None:
        if not self.enabled:
            return None

        resolved_conversation_id = conversation_id or resolve_conversation_id(
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_id=user_id,
        )
        attachments = (
            json.dumps(user_attachments, ensure_ascii=False)
            if user_attachments
            else None
        )
        with self._connection() as conn:
            conn.execute("SAVEPOINT persist_conversation_turn")
            try:
                request = conn.execute(
                    "SELECT * FROM requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if request is not None:
                    result = self._complete_existing_request(
                        conn,
                        request=request,
                        request_id=request_id,
                        user_id=user_id,
                        conversation_id=resolved_conversation_id,
                        turn_id=turn_id,
                        actor_id=actor_id,
                        channel=channel,
                        channel_account_id=channel_account_id,
                        user_content=user_content,
                        attachments=attachments,
                        assistant_segments=assistant_segments,
                    )
                else:
                    result = self._persist_legacy_turn(
                        conn,
                        request_id=request_id,
                        conversation_id=resolved_conversation_id,
                        turn_id=turn_id or generate_id("turn"),
                        actor_id=actor_id,
                        channel=channel,
                        channel_account_id=channel_account_id,
                        user_content=user_content,
                        attachments=attachments,
                        assistant_segments=assistant_segments,
                    )
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT persist_conversation_turn")
                conn.execute("RELEASE SAVEPOINT persist_conversation_turn")
                raise
            conn.execute("RELEASE SAVEPOINT persist_conversation_turn")
        return result

    def _complete_existing_request(
        self,
        conn: sqlite3.Connection,
        *,
        request: sqlite3.Row,
        request_id: str,
        user_id: int,
        conversation_id: str,
        turn_id: str | None,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_content: str,
        attachments: str | None,
        assistant_segments: list[str],
    ) -> dict[str, str]:
        existing_turn_id = request["turn_id"]
        if (
            request["conversation_id"] != conversation_id
            or (turn_id is not None and turn_id != existing_turn_id)
        ):
            raise RequestConflict("request identity conflict")

        self._validate_request_snapshot(
            request,
            user_id=user_id,
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_content=user_content,
            attachments=attachments,
        )
        turn = conn.execute(
            "SELECT conversation_id, status FROM turns WHERE turn_id = ?",
            (existing_turn_id,),
        ).fetchone()
        if turn is None or turn["conversation_id"] != conversation_id:
            raise RequestConflict("request identity conflict")

        if request["status"] == "completed":
            if turn["status"] != "completed":
                raise RequestConflict("request status conflict")
            return self._completed_result(
                conn,
                request_id=request_id,
                conversation_id=conversation_id,
                turn_id=existing_turn_id,
                user_content=user_content,
                attachments=attachments,
                assistant_segments=assistant_segments,
            )
        if request["status"] != "running" or turn["status"] != "running":
            raise RequestConflict("request status conflict")
        if conn.execute(
            "SELECT 1 FROM messages WHERE turn_id = ? LIMIT 1",
            (existing_turn_id,),
        ).fetchone():
            raise RequestConflict("request contains partial messages conflict")

        response_group_id = generate_id("group")
        self.ensure_conversation(
            conn,
            conversation_id=conversation_id,
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
        )
        self._insert_turn_messages(
            conn,
            conversation_id=conversation_id,
            turn_id=existing_turn_id,
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_content=user_content,
            attachments=attachments,
            assistant_segments=assistant_segments,
            response_group_id=response_group_id,
        )
        completed_at = datetime.now(timezone.utc).isoformat()
        request_updated = conn.execute(
            """UPDATE requests
               SET status = 'completed',
                   updated_at = ?, completed_at = ?,
                   error = NULL, error_code = NULL,
                   lease_owner = NULL, lease_expires_at = NULL,
                   cancel_requested_at = NULL, cancelled_at = NULL
               WHERE request_id = ?
                 AND conversation_id = ?
                 AND turn_id = ?
                 AND status = 'running'""",
            (
                completed_at,
                completed_at,
                request_id,
                conversation_id,
                existing_turn_id,
            ),
        ).rowcount
        if request_updated != 1:
            raise RequestConflict("request status conflict")
        turn_updated = conn.execute(
            """UPDATE turns
               SET status = 'completed', completed_at = ?
               WHERE turn_id = ?
                 AND conversation_id = ?
                 AND status = 'running'""",
            (completed_at, existing_turn_id, conversation_id),
        ).rowcount
        if turn_updated != 1:
            raise RequestConflict("request status conflict")
        return {
            "conversation_id": conversation_id,
            "turn_id": existing_turn_id,
            "request_id": request_id,
            "response_group_id": response_group_id,
        }

    @staticmethod
    def _validate_request_snapshot(
        request: sqlite3.Row,
        *,
        user_id: int,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_content: str,
        attachments: str | None,
    ) -> None:
        keys = set(request.keys())
        snapshot_columns = {
            "actor_id",
            "channel",
            "channel_account_id",
            "user_id",
            "input_content",
            "attachments",
        }
        if not snapshot_columns.issubset(keys):
            return
        if not any(request[column] is not None for column in snapshot_columns):
            return

        try:
            stored_attachments = json.loads(request["attachments"] or "[]")
            supplied_attachments = json.loads(attachments or "[]")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RequestConflict("request snapshot conflict") from exc
        if not isinstance(stored_attachments, list) or not isinstance(
            supplied_attachments,
            list,
        ):
            raise RequestConflict("request snapshot conflict")

        expected = (
            request["actor_id"],
            request["channel"],
            request["channel_account_id"],
            int(request["user_id"]),
            request["input_content"] or "",
            stored_attachments,
        )
        supplied = (
            actor_id,
            channel,
            channel_account_id,
            int(user_id),
            user_content,
            supplied_attachments,
        )
        if expected != supplied:
            raise RequestConflict("request snapshot conflict")

    def _completed_result(
        self,
        conn: sqlite3.Connection,
        *,
        request_id: str,
        conversation_id: str,
        turn_id: str,
        user_content: str,
        attachments: str | None,
        assistant_segments: list[str],
    ) -> dict[str, str]:
        rows = conn.execute(
            """SELECT role, content, attachments,
                      response_group_id, sequence
               FROM messages
               WHERE turn_id = ?
               ORDER BY sequence ASC""",
            (turn_id,),
        ).fetchall()
        expected = [("user", user_content, attachments, 0)]
        expected.extend(
            ("assistant", content, None, sequence)
            for sequence, content in enumerate(
                assistant_segments,
                start=1,
            )
        )
        actual = [
            (
                row["role"],
                row["content"],
                row["attachments"],
                row["sequence"],
            )
            for row in rows
        ]
        if actual != expected:
            raise RequestConflict("completed request result conflict")
        response_group_id = next(
            (
                row["response_group_id"]
                for row in rows
                if row["role"] == "assistant"
            ),
            None,
        )
        return {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "request_id": request_id,
            "response_group_id": response_group_id or "",
        }

    def _persist_legacy_turn(
        self,
        conn: sqlite3.Connection,
        *,
        request_id: str,
        conversation_id: str,
        turn_id: str,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_content: str,
        attachments: str | None,
        assistant_segments: list[str],
    ) -> dict[str, str]:
        response_group_id = generate_id("group")
        self.ensure_conversation(
            conn,
            conversation_id=conversation_id,
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
        )
        conn.execute(
            """INSERT INTO turns
               (turn_id, conversation_id, status, completed_at)
               VALUES (?, ?, 'completed', datetime('now', 'localtime'))""",
            (turn_id, conversation_id),
        )
        conn.execute(
            """INSERT INTO requests
               (request_id, conversation_id, turn_id, status,
                completed_at)
               VALUES (?, ?, ?, 'completed', datetime('now', 'localtime'))""",
            (request_id, conversation_id, turn_id),
        )
        self._insert_turn_messages(
            conn,
            conversation_id=conversation_id,
            turn_id=turn_id,
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_content=user_content,
            attachments=attachments,
            assistant_segments=assistant_segments,
            response_group_id=response_group_id,
        )
        return {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "request_id": request_id,
            "response_group_id": response_group_id,
        }

    def _insert_turn_messages(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        turn_id: str,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_content: str,
        attachments: str | None,
        assistant_segments: list[str],
        response_group_id: str,
    ) -> None:
        self._insert_message(
            conn,
            conversation_id=conversation_id,
            turn_id=turn_id,
            role="user",
            content=user_content,
            attachments=attachments,
            response_group_id=None,
            sequence=0,
            channel=channel,
            channel_account_id=channel_account_id,
            actor_id=actor_id,
        )
        for sequence, content in enumerate(assistant_segments, start=1):
            self._insert_message(
                conn,
                conversation_id=conversation_id,
                turn_id=turn_id,
                role="assistant",
                content=content,
                attachments=None,
                response_group_id=response_group_id,
                sequence=sequence,
                channel=channel,
                channel_account_id=channel_account_id,
                actor_id=actor_id,
            )

    def recent_turn_history(
        self,
        *,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_id: int,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        conversation_id = resolve_conversation_id(
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_id=user_id,
        )
        with self._connection() as conn:
            rows = conn.execute(
                """WITH recent_turns AS (
                       SELECT turn_id, created_at, rowid AS turn_order
                       FROM turns
                       WHERE conversation_id = ?
                         AND status = 'completed'
                       ORDER BY created_at DESC, turn_order DESC
                       LIMIT ?
                   )
                   SELECT m.role, m.content, m.sequence, m.channel
                   FROM recent_turns rt
                   JOIN messages m ON m.turn_id = rt.turn_id
                   ORDER BY rt.created_at ASC, rt.turn_order ASC, m.sequence ASC""",
                (conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _insert_message(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        turn_id: str,
        role: str,
        content: str,
        attachments: str | None,
        response_group_id: str | None,
        sequence: int,
        channel: str | None,
        channel_account_id: str | None,
        actor_id: str | None,
    ) -> None:
        conn.execute(
            """INSERT INTO messages
               (message_id, conversation_id, turn_id, role, content,
                attachments, response_group_id, sequence, channel,
                channel_account_id, actor_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                generate_id("msg"),
                conversation_id,
                turn_id,
                role,
                content,
                attachments,
                response_group_id,
                sequence,
                channel,
                channel_account_id,
                actor_id,
            ),
        )

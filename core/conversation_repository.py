from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from core.ids import generate_id


def _conversation_id(
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
    ) -> dict[str, str] | None:
        if not self.enabled:
            return None

        conversation_id = _conversation_id(
            actor_id,
            channel,
            channel_account_id,
            user_id,
        )
        turn_id = generate_id("turn")
        response_group_id = generate_id("group")
        attachments = (
            json.dumps(user_attachments, ensure_ascii=False)
            if user_attachments
            else None
        )
        with self._connection() as conn:
            conn.execute("SAVEPOINT persist_conversation_turn")
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO conversations
                       (conversation_id, actor_id, channel, channel_account_id, status)
                       VALUES (?, ?, ?, ?, 'active')""",
                    (conversation_id, actor_id, channel, channel_account_id),
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
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT persist_conversation_turn")
                conn.execute("RELEASE SAVEPOINT persist_conversation_turn")
                raise
            conn.execute("RELEASE SAVEPOINT persist_conversation_turn")
        return {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "request_id": request_id,
            "response_group_id": response_group_id,
        }

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
        conversation_id = _conversation_id(
            actor_id,
            channel,
            channel_account_id,
            user_id,
        )
        with self._connection() as conn:
            rows = conn.execute(
                """WITH recent_turns AS (
                       SELECT turn_id, created_at, rowid AS turn_order
                       FROM turns
                       WHERE conversation_id = ?
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

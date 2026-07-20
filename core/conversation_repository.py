from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

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
    def __init__(self, conn: sqlite3.Connection, *, enabled: bool) -> None:
        self.conn = conn
        self.enabled = enabled

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
        self.conn.execute(
            """INSERT OR IGNORE INTO conversations
               (conversation_id, actor_id, channel, channel_account_id, status)
               VALUES (?, ?, ?, ?, 'active')""",
            (conversation_id, actor_id, channel, channel_account_id),
        )
        self.conn.execute(
            """INSERT INTO turns
               (turn_id, conversation_id, status, completed_at)
               VALUES (?, ?, 'completed', datetime('now', 'localtime'))""",
            (turn_id, conversation_id),
        )
        self.conn.execute(
            """INSERT INTO requests
               (request_id, conversation_id, turn_id, status,
                completed_at)
               VALUES (?, ?, ?, 'completed', datetime('now', 'localtime'))""",
            (request_id, conversation_id, turn_id),
        )
        attachments = (
            json.dumps(user_attachments, ensure_ascii=False)
            if user_attachments
            else None
        )
        self._insert_message(
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
        return {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "request_id": request_id,
            "response_group_id": response_group_id,
        }

    def _insert_message(
        self,
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
        self.conn.execute(
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

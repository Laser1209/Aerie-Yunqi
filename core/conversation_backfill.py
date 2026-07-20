from __future__ import annotations

import hashlib
import sqlite3
from typing import Any


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


def _conversation_id(row: sqlite3.Row) -> str:
    return _stable_id(
        "conv",
        "legacy_chat_log",
        row["actor_id"],
        row["channel"],
        row["channel_account_id"],
        row["user_id"],
    )


def backfill_chat_log(conn: sqlite3.Connection) -> dict[str, int]:
    """Backfill legacy chat rows without inferring missing identity fields."""
    rows = conn.execute("SELECT * FROM chat_log ORDER BY id ASC").fetchall()
    inserted = 0
    current_turns: dict[str, str] = {}
    next_sequence: dict[str, int] = {}

    for row in rows:
        conversation_id = _conversation_id(row)
        conn.execute(
            """INSERT OR IGNORE INTO conversations
               (conversation_id, actor_id, channel, channel_account_id,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (
                conversation_id,
                row["actor_id"],
                row["channel"],
                row["channel_account_id"],
                row["created_at"],
                row["created_at"],
            ),
        )

        role = row["role"]
        if role == "user" or conversation_id not in current_turns:
            turn_id = _stable_id("turn", "legacy_chat_log", row["id"])
            current_turns[conversation_id] = turn_id
            next_sequence[turn_id] = 0
            conn.execute(
                """INSERT OR IGNORE INTO turns
                   (turn_id, conversation_id, status, created_at)
                   VALUES (?, ?, 'completed', ?)""",
                (turn_id, conversation_id, row["created_at"]),
            )
            request_id = _stable_id("req", "legacy_chat_log", row["id"])
            conn.execute(
                """INSERT OR IGNORE INTO requests
                   (request_id, conversation_id, turn_id, status,
                    created_at, updated_at, completed_at)
                   VALUES (?, ?, ?, 'completed', ?, ?, ?)""",
                (
                    request_id,
                    conversation_id,
                    turn_id,
                    row["created_at"],
                    row["created_at"],
                    row["created_at"],
                ),
            )
        else:
            turn_id = current_turns[conversation_id]

        sequence = next_sequence.get(turn_id, 0)
        response_group_id = None
        if role == "assistant":
            response_group_id = _stable_id("group", turn_id, "assistant")

        message_id = _stable_id("msg", "legacy_chat_log", row["id"])
        cursor = conn.execute(
            """INSERT OR IGNORE INTO messages
               (message_id, conversation_id, turn_id, role, content,
                attachments, response_group_id, sequence, channel,
                channel_account_id, actor_id, legacy_chat_log_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                conversation_id,
                turn_id,
                role,
                row["content"],
                row["attachments"],
                response_group_id,
                sequence,
                row["channel"],
                row["channel_account_id"],
                row["actor_id"],
                row["id"],
                row["created_at"],
            ),
        )
        if cursor.rowcount:
            inserted += 1
        next_sequence[turn_id] = sequence + 1

    return {"processed": len(rows), "inserted": inserted}

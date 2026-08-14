from __future__ import annotations

import hashlib
import json
import sqlite3
from base64 import urlsafe_b64decode, urlsafe_b64encode
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from core.ids import generate_id


def active_persona_id() -> str | None:
    """Return the currently-active persona id, or None on any failure.

    Role dimension for dialogue/memory isolation; NULL keeps legacy shared rows.
    """
    try:
        from core.persona_hub.persona_manager import get_persona_manager
        return get_persona_manager().get_active_id()
    except Exception:
        return None


class RequestConflict(RuntimeError):
    pass


class InvalidHistoryCursor(ValueError):
    pass


def _encode_history_cursor(row_id: int) -> str:
    payload = json.dumps(
        {"v": 1, "row": int(row_id)},
        separators=(",", ":"),
    ).encode("ascii")
    return urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_history_cursor(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 128:
        raise InvalidHistoryCursor("invalid history cursor")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(urlsafe_b64decode(padded.encode("ascii")))
        if payload.get("v") != 1:
            raise ValueError
        row_id = int(payload["row"])
        if row_id <= 0:
            raise ValueError
        return row_id
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise InvalidHistoryCursor("invalid history cursor") from None


def resolve_conversation_id(
    *,
    actor_id: str | None,
    channel: str | None,
    channel_account_id: str | None,
    user_id: int,
    persona_id: str | None = None,
) -> str:
    payload = "\x1f".join(
        (
            actor_id or "",
            channel or "",
            channel_account_id or "",
            str(user_id),
            persona_id or "",  # NULL == 共享（存量会话）
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"conv_{digest[:32]}"


def _legacy_conversation_id(
    actor_id: str | None,
    channel: str | None,
    channel_account_id: str | None,
    user_id: int,
    persona_id: str | None = None,
) -> str:
    payload = "\x1f".join(
        (
            "legacy_chat_log",
            actor_id or "",
            channel or "",
            channel_account_id or "",
            str(user_id),
            persona_id or "",  # 角色隔离：NULL == 共享（存量会话）
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"conv_{digest[:32]}"


def _resolve_related_conversation_ids(
    *,
    actor_id: str | None,
    channel: str | None,
    channel_account_id: str | None,
    user_id: int,
    persona_id: str | None = None,
) -> list[str]:
    primary = resolve_conversation_id(
        actor_id=actor_id,
        channel=channel,
        channel_account_id=channel_account_id,
        user_id=user_id,
    )
    candidates = [
        primary,
        _legacy_conversation_id(actor_id, channel, channel_account_id, user_id),
        _legacy_conversation_id(None, channel, channel_account_id, user_id),
        _legacy_conversation_id(actor_id, None, None, user_id),
        _legacy_conversation_id(None, None, None, user_id),
    ]
    # 角色隔离：追加 persona 相关候选（NULL persona 的 legacy 候选已在上面）
    if persona_id:
        candidates.append(
            resolve_conversation_id(
                actor_id=actor_id,
                channel=channel,
                channel_account_id=channel_account_id,
                user_id=user_id,
                persona_id=persona_id,
            )
        )
        candidates.append(
            _legacy_conversation_id(actor_id, channel, channel_account_id, user_id, persona_id)
        )
    seen = set()
    result = []
    for cid in candidates:
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


class ConversationRepository:
    def __init__(self, database: Any, *, enabled: bool) -> None:
        self.database = database
        self.enabled = enabled
        self._soft_delete = None  # None=未知；True/False=已缓存列检测结果
        self._persona_columns: dict[str, bool] = {}  # 表名 → 是否含 persona_id 列（角色隔离）
        self._reply_to_columns: dict[str, bool] = {}  # "表:reply_to" → 是否含 Quote V2 列

    def _has_reply_to_columns(self, conn: sqlite3.Connection, table: str) -> bool:
        """表是否已带 Quote V2 reply_to 列（迁移 015）。旧库/裸连接无该列时跳过。"""
        key = f"{table}:reply_to"
        if key not in self._reply_to_columns:
            try:
                cols = {
                    row["name"]
                    for row in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }
                self._reply_to_columns[key] = "reply_to_id" in cols
            except Exception:
                self._reply_to_columns[key] = False
        return self._reply_to_columns[key]

    def _has_persona_column(self, conn: sqlite3.Connection, table: str) -> bool:
        """表是否已带 persona_id 列（迁移 013）。旧库无该列时跳过 persona 写入。"""
        if table not in self._persona_columns:
            try:
                cols = {
                    row["name"]
                    for row in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }
                self._persona_columns[table] = "persona_id" in cols
            except Exception:
                self._persona_columns[table] = False
        return self._persona_columns[table]

    def _has_soft_delete(self, conn: sqlite3.Connection) -> bool:
        """messages 是否已带 deleted_at（迁移 011）。旧库无该列时跳过过滤。"""
        if self._soft_delete is None:
            try:
                cols = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(messages)").fetchall()
                }
                self._soft_delete = "deleted_at" in cols
            except Exception:
                self._soft_delete = False
        return self._soft_delete

    def _find_user_conversation_ids(
        self,
        conn: sqlite3.Connection,
        *,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_id: int,
        persona_id: str | None = None,
    ) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()

        def add(cid: str | None) -> None:
            if cid and cid not in seen:
                seen.add(cid)
                ids.append(cid)

        # 角色隔离：显式 persona 优先，否则取 active persona；
        # 仍为 None（无激活角色或异常）则退化为不过滤（保持现状全量）
        persona = persona_id if persona_id is not None else active_persona_id()

        primary = resolve_conversation_id(
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_id=user_id,
        )
        add(primary)

        if self._table_exists(conn, "chat_log"):
            chat_log_persona = persona is not None and self._has_persona_column(
                conn, "chat_log"
            )
            if chat_log_persona:
                linked_rows = conn.execute(
                    """SELECT DISTINCT m.conversation_id
                       FROM messages m
                       JOIN chat_log cl ON cl.id = m.legacy_chat_log_id
                       WHERE cl.user_id = ?
                         AND (cl.persona_id = ? OR cl.persona_id IS NULL)""",
                    (int(user_id), persona),
                ).fetchall()
            else:
                linked_rows = conn.execute(
                    """SELECT DISTINCT m.conversation_id
                       FROM messages m
                       JOIN chat_log cl ON cl.id = m.legacy_chat_log_id
                       WHERE cl.user_id = ?""",
                    (int(user_id),),
                ).fetchall()
            for row in linked_rows:
                add(row["conversation_id"])

        for cid in _resolve_related_conversation_ids(
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_id=user_id,
            persona_id=persona,
        ):
            add(cid)

        existing: list[str] = []
        conversations_persona = persona is not None and self._has_persona_column(
            conn, "conversations"
        )
        for cid in ids:
            if conversations_persona:
                hit = conn.execute(
                    "SELECT 1 FROM conversations WHERE conversation_id = ? "
                    "AND (persona_id = ? OR persona_id IS NULL) LIMIT 1",
                    (cid, persona),
                ).fetchone()
            else:
                hit = conn.execute(
                    "SELECT 1 FROM conversations WHERE conversation_id = ? LIMIT 1",
                    (cid,),
                ).fetchone()
            if hit:
                existing.append(cid)
        if not existing:
            existing = [primary]
        return existing

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
        persona_id: str | None = None,
    ) -> None:
        if self._has_persona_column(conn, "conversations"):
            # 角色隔离：conversations 行记录 persona_id
            conn.execute(
                """INSERT OR IGNORE INTO conversations
                   (conversation_id, actor_id, channel, channel_account_id,
                    status, persona_id)
                   VALUES (?, ?, ?, ?, 'active', ?)""",
                (
                    conversation_id,
                    actor_id,
                    channel,
                    channel_account_id,
                    persona_id,
                ),
            )
            return
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
        user_legacy_chat_log_id: int | None = None,
        assistant_legacy_chat_log_ids: list[int] | None = None,
        persona_id: str | None = None,
        user_reply_to: dict[str, Any] | None = None,
    ) -> dict[str, str] | None:
        if not self.enabled:
            return None

        resolved_conversation_id = conversation_id or resolve_conversation_id(
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_id=user_id,
            persona_id=persona_id,
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
                        user_legacy_chat_log_id=user_legacy_chat_log_id,
                        assistant_legacy_chat_log_ids=assistant_legacy_chat_log_ids,
                        persona_id=persona_id,
                        user_reply_to=user_reply_to,
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
                        user_legacy_chat_log_id=user_legacy_chat_log_id,
                        assistant_legacy_chat_log_ids=assistant_legacy_chat_log_ids,
                        persona_id=persona_id,
                        user_reply_to=user_reply_to,
                    )
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT persist_conversation_turn")
                conn.execute("RELEASE SAVEPOINT persist_conversation_turn")
                raise
            conn.execute("RELEASE SAVEPOINT persist_conversation_turn")
        return result

    def persist_proactive_message(
        self,
        *,
        user_id: int,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        content: str,
        legacy_chat_log_id: int,
        persona_id: str | None = None,
    ) -> str | None:
        """把主动推送（主动消息/生图消息）补齐进 normalized messages 层。

        主动消息/生图消息直接写 chat_log、不经过请求队列，因此没有 messages 行，
        导致管理平台聊天记录看不到它们、级联删除也漏掉它们。这里为其补一条
        assistant messages 行，归入对应角色在该通道的会话（conversation_id 与
        普通消息一致，通过 legacy_chat_log_id 关联回 chat_log）。
        """
        if not self.enabled:
            return None
        conversation_id = resolve_conversation_id(
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_id=user_id,
            persona_id=persona_id,
        )
        turn_id = generate_id("turn")
        with self._connection() as conn:
            self.ensure_conversation(
                conn,
                conversation_id=conversation_id,
                actor_id=actor_id,
                channel=channel,
                channel_account_id=channel_account_id,
                persona_id=persona_id,
            )
            if self._has_persona_column(conn, "turns"):
                conn.execute(
                    """INSERT INTO turns
                       (turn_id, conversation_id, status, completed_at, persona_id)
                       VALUES (?, ?, 'completed', datetime('now', 'localtime'), ?)""",
                    (turn_id, conversation_id, persona_id),
                )
            else:
                conn.execute(
                    """INSERT INTO turns
                       (turn_id, conversation_id, status, completed_at)
                       VALUES (?, ?, 'completed', datetime('now', 'localtime'))""",
                    (turn_id, conversation_id),
                )
            self._insert_message(
                conn,
                conversation_id=conversation_id,
                turn_id=turn_id,
                role="assistant",
                content=content,
                attachments=None,
                response_group_id=None,
                sequence=1,
                channel=channel,
                channel_account_id=channel_account_id,
                actor_id=actor_id,
                legacy_chat_log_id=legacy_chat_log_id,
                persona_id=persona_id,
            )
        return conversation_id

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
        user_legacy_chat_log_id: int | None = None,
        assistant_legacy_chat_log_ids: list[int] | None = None,
        persona_id: str | None = None,
        user_reply_to: dict[str, Any] | None = None,
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
            persona_id=persona_id,
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
            user_legacy_chat_log_id=user_legacy_chat_log_id,
            assistant_legacy_chat_log_ids=assistant_legacy_chat_log_ids,
            persona_id=persona_id,
            user_reply_to=user_reply_to,
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
        user_legacy_chat_log_id: int | None = None,
        assistant_legacy_chat_log_ids: list[int] | None = None,
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
        user_legacy_chat_log_id: int | None = None,
        assistant_legacy_chat_log_ids: list[int] | None = None,
        persona_id: str | None = None,
        user_reply_to: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        response_group_id = generate_id("group")
        self.ensure_conversation(
            conn,
            conversation_id=conversation_id,
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            persona_id=persona_id,
        )
        if self._has_persona_column(conn, "turns"):
            conn.execute(
                """INSERT INTO turns
                   (turn_id, conversation_id, status, completed_at, persona_id)
                   VALUES (?, ?, 'completed', datetime('now', 'localtime'), ?)""",
                (turn_id, conversation_id, persona_id),
            )
        else:
            conn.execute(
                """INSERT INTO turns
                   (turn_id, conversation_id, status, completed_at)
                   VALUES (?, ?, 'completed', datetime('now', 'localtime'))""",
                (turn_id, conversation_id),
            )
        if self._has_persona_column(conn, "requests"):
            conn.execute(
                """INSERT INTO requests
                   (request_id, conversation_id, turn_id, status,
                    completed_at, persona_id)
                   VALUES (?, ?, ?, 'completed', datetime('now', 'localtime'), ?)""",
                (request_id, conversation_id, turn_id, persona_id),
            )
        else:
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
            user_legacy_chat_log_id=user_legacy_chat_log_id,
            assistant_legacy_chat_log_ids=assistant_legacy_chat_log_ids,
            persona_id=persona_id,
            user_reply_to=user_reply_to,
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
        user_legacy_chat_log_id: int | None,
        assistant_legacy_chat_log_ids: list[int] | None,
        persona_id: str | None = None,
        user_reply_to: dict[str, Any] | None = None,
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
            legacy_chat_log_id=user_legacy_chat_log_id,
            persona_id=persona_id,
            reply_to_id=(
                int(user_reply_to.get("id") or 0) if user_reply_to else None
            ),
            reply_to_content=(
                user_reply_to.get("content") if user_reply_to else None
            ),
            reply_to_role=(
                user_reply_to.get("role") if user_reply_to else None
            ),
            reply_to_attachments=(
                json.dumps(
                    user_reply_to.get("attachments") or [],
                    ensure_ascii=False,
                )
                if user_reply_to and user_reply_to.get("attachments")
                else None
            ),
        )
        legacy_ids = assistant_legacy_chat_log_ids or []
        for sequence, content in enumerate(assistant_segments, start=1):
            legacy_chat_log_id = (
                legacy_ids[sequence - 1]
                if sequence - 1 < len(legacy_ids)
                else None
            )
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
                legacy_chat_log_id=legacy_chat_log_id,
                persona_id=persona_id,
            )

    def recent_turn_history(
        self,
        *,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_id: int,
        limit: int = 20,
        persona_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._connection() as conn:
            conversation_ids = self._find_user_conversation_ids(
                conn,
                actor_id=actor_id,
                channel=channel,
                channel_account_id=channel_account_id,
                user_id=user_id,
                persona_id=persona_id,
            )
            ex_ph = ",".join("?" * len(conversation_ids))
            deleted_filter = " AND m.deleted_at IS NULL" if self._has_soft_delete(conn) else ""
            rows = conn.execute(
                f"""WITH recent_turns AS (
                       SELECT turn_id, created_at, rowid AS turn_order
                       FROM turns
                       WHERE conversation_id IN ({ex_ph})
                         AND status = 'completed'
                       ORDER BY created_at DESC, turn_order DESC
                       LIMIT ?
                   )
                   SELECT m.role, m.content, m.sequence, m.channel, rt.created_at
                   FROM recent_turns rt
                   JOIN messages m ON m.turn_id = rt.turn_id{deleted_filter}
                   ORDER BY rt.created_at ASC, rt.turn_order ASC, m.sequence ASC""",
                tuple(conversation_ids) + (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def history_page(
        self,
        *,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_id: int,
        conversation_id: str | None = None,
        cursor: str | None = None,
        direction: str = "older",
        limit: int = 50,
        persona_id: str | None = None,
    ) -> dict[str, Any]:
        """Read a stable cursor page without imposing a history ceiling.

        ``items`` are always returned in chronological order.  The cursor is
        opaque to callers and is based on SQLite insertion order, which also
        disambiguates messages sharing the same timestamp.  When the
        normalized conversation model is disabled, the same contract is
        served from the legacy ``chat_log`` table.
        """
        if direction not in {"older", "newer"}:
            raise ValueError("direction must be 'older' or 'newer'")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, 200))
        anchor = _decode_history_cursor(cursor)
        if direction == "newer" and anchor is None:
            raise InvalidHistoryCursor("newer history requires a cursor")

        with self._connection() as conn:
            if not self.enabled or not self._table_exists(conn, "messages"):
                return self._legacy_history_page(
                    conn,
                    user_id=user_id,
                    anchor=anchor,
                    direction=direction,
                    limit=limit,
                )
            resolved_conversation_id = conversation_id or resolve_conversation_id(
                actor_id=actor_id,
                channel=channel,
                channel_account_id=channel_account_id,
                user_id=user_id,
            )
            if anchor is None and direction == "older":
                related_ids = self._find_user_conversation_ids(
                    conn,
                    actor_id=actor_id,
                    channel=channel,
                    channel_account_id=channel_account_id,
                    user_id=user_id,
                    persona_id=persona_id,
                )
                if len(related_ids) <= 1:
                    # 角色隔离：related_ids 已按 persona 过滤（可能只有 persona 专属会话，
                    # 无 NULL 共享会话），此时必须跟随该会话 ID，而不是无 persona 维度的
                    # resolved_conversation_id，否则纯 persona 会话读链返回空。
                    # 但调用方显式传入 conversation_id 时保持原语义（存量桌面/连续性路径
                    # 依赖显式会话 ID，不能被子查询 fallback 的 primary 覆盖）。
                    if conversation_id is not None:
                        page_conversation_id = conversation_id
                    else:
                        page_conversation_id = (
                            related_ids[0] if related_ids else resolved_conversation_id
                        )
                    return self._normalized_history_page(
                        conn,
                        conversation_id=page_conversation_id,
                        anchor=anchor,
                        direction=direction,
                        limit=limit,
                    )
                return self._merged_history_page(
                    conn,
                    conversation_ids=related_ids,
                    primary_conversation_id=resolved_conversation_id,
                    limit=limit,
                )
            return self._normalized_history_page(
                conn,
                conversation_id=resolved_conversation_id,
                anchor=anchor,
                direction=direction,
                limit=limit,
            )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None

    def _normalized_history_page(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        anchor: int | None,
        direction: str,
        limit: int,
    ) -> dict[str, Any]:
        comparator = "<" if direction == "older" else ">"
        order = "DESC" if direction == "older" else "ASC"
        params: list[Any] = [conversation_id]
        anchor_sql = ""
        if anchor is not None:
            anchor_sql = f" AND rowid {comparator} ?"
            params.append(anchor)
        params.append(limit + 1)
        deleted_filter = " AND deleted_at IS NULL" if self._has_soft_delete(conn) else ""
        reply_to_cols = (
            ", reply_to_id, reply_to_content, reply_to_role, reply_to_attachments"
            if self._has_reply_to_columns(conn, "messages")
            else ""
        )
        rows = conn.execute(
            f"""SELECT rowid AS history_rowid, message_id, conversation_id,
                       turn_id, role, content, attachments,
                       response_group_id, sequence, channel,
                       channel_account_id, actor_id, created_at{reply_to_cols}
                FROM messages
                WHERE conversation_id = ?{anchor_sql}{deleted_filter}
                ORDER BY rowid {order}
                LIMIT ?""",
            tuple(params),
        ).fetchall()
        selected = list(rows[:limit])
        if direction == "older":
            selected.reverse()
        return self._build_page(
            conn,
            selected,
            table="messages",
            partition_sql="conversation_id = ?",
            partition_params=(conversation_id,),
            direction=direction,
        )

    def _merged_history_page(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_ids: list[str],
        primary_conversation_id: str,
        limit: int,
    ) -> dict[str, Any]:
        placeholders = ",".join("?" * len(conversation_ids))
        deleted_filter = " AND deleted_at IS NULL" if self._has_soft_delete(conn) else ""
        reply_to_cols = (
            ", reply_to_id, reply_to_content, reply_to_role, reply_to_attachments"
            if self._has_reply_to_columns(conn, "messages")
            else ""
        )
        rows = conn.execute(
            f"""SELECT rowid AS history_rowid, message_id, conversation_id,
                       turn_id, role, content, attachments,
                       response_group_id, sequence, channel,
                       channel_account_id, actor_id, created_at{reply_to_cols}
                FROM messages
                WHERE conversation_id IN ({placeholders}){deleted_filter}
                ORDER BY rowid DESC
                LIMIT ?""",
            tuple(conversation_ids) + (limit + 1,),
        ).fetchall()
        selected = list(rows[:limit])
        selected.reverse()
        if not selected:
            return self._empty_page()
        oldest_rowid = int(selected[0]["history_rowid"])
        newest_rowid = int(selected[-1]["history_rowid"])
        has_older = conn.execute(
            f"SELECT 1 FROM messages WHERE conversation_id IN ({placeholders}) "
            f"AND rowid < ?{deleted_filter} LIMIT 1",
            tuple(conversation_ids) + (oldest_rowid,),
        ).fetchone() is not None
        items: list[dict[str, Any]] = []
        for row in selected:
            item = dict(row)
            row_id = int(item.pop("history_rowid"))
            item["cursor"] = _encode_history_cursor(row_id)
            item["id"] = item["message_id"]
            item["ts"] = item.get("created_at")
            item["attachments"] = self._decode_attachments(
                item.get("attachments")
            )
            item["reply_to_attachments"] = self._decode_attachments(
                item.get("reply_to_attachments")
            )
            items.append(item)
        older_cursor = _encode_history_cursor(oldest_rowid) if has_older else None
        return {
            "items": items,
            "nextCursor": older_cursor,
            "hasMore": has_older,
            "olderCursor": older_cursor,
            "newerCursor": None,
            "hasOlder": has_older,
            "hasNewer": False,
        }

    def _legacy_history_page(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        anchor: int | None,
        direction: str,
        limit: int,
    ) -> dict[str, Any]:
        if not self._table_exists(conn, "chat_log"):
            return self._empty_page()
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(chat_log)")}
        deleted_sql = " AND deleted_at IS NULL" if "deleted_at" in cols else ""
        comparator = "<" if direction == "older" else ">"
        order = "DESC" if direction == "older" else "ASC"
        params: list[Any] = [int(user_id)]
        anchor_sql = ""
        if anchor is not None:
            anchor_sql = f" AND id {comparator} ?"
            params.append(anchor)
        params.append(limit + 1)
        reply_to_cols = (
            ", reply_to_id, reply_to_content, reply_to_role, reply_to_attachments"
            if self._has_reply_to_columns(conn, "chat_log")
            else ""
        )
        rows = conn.execute(
            f"""SELECT id AS history_rowid, id, role, content,
                       attachments, created_at{reply_to_cols}
                FROM chat_log
                WHERE user_id = ?{anchor_sql}{deleted_sql}
                ORDER BY id {order}
                LIMIT ?""",
            tuple(params),
        ).fetchall()
        selected = list(rows[:limit])
        if direction == "older":
            selected.reverse()
        partition_sql = "user_id = ?" + deleted_sql
        return self._build_page(
            conn,
            selected,
            table="chat_log",
            partition_sql=partition_sql,
            partition_params=(int(user_id),),
            direction=direction,
        )

    def _build_page(
        self,
        conn: sqlite3.Connection,
        rows: list[sqlite3.Row],
        *,
        table: str,
        partition_sql: str,
        partition_params: tuple[Any, ...],
        direction: str,
    ) -> dict[str, Any]:
        if not rows:
            return self._empty_page()
        oldest = int(rows[0]["history_rowid"])
        newest = int(rows[-1]["history_rowid"])
        key = "rowid" if table == "messages" else "id"
        has_older = conn.execute(
            f"SELECT 1 FROM {table} WHERE {partition_sql} "
            f"AND {key} < ? LIMIT 1",
            partition_params + (oldest,),
        ).fetchone() is not None
        has_newer = conn.execute(
            f"SELECT 1 FROM {table} WHERE {partition_sql} "
            f"AND {key} > ? LIMIT 1",
            partition_params + (newest,),
        ).fetchone() is not None

        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            row_id = int(item.pop("history_rowid"))
            item["cursor"] = _encode_history_cursor(row_id)
            if "message_id" in item:
                item["id"] = item["message_id"]
            if not item.get("ts"):
                item["ts"] = item.get("created_at")
            item["attachments"] = self._decode_attachments(
                item.get("attachments")
            )
            item["reply_to_attachments"] = self._decode_attachments(
                item.get("reply_to_attachments")
            )
            items.append(item)
        older_cursor = _encode_history_cursor(oldest) if has_older else None
        newer_cursor = _encode_history_cursor(newest) if has_newer else None
        next_cursor = older_cursor if direction == "older" else newer_cursor
        has_more = has_older if direction == "older" else has_newer
        return {
            "items": items,
            "nextCursor": next_cursor,
            "hasMore": has_more,
            "olderCursor": older_cursor,
            "newerCursor": newer_cursor,
            "hasOlder": has_older,
            "hasNewer": has_newer,
        }

    @staticmethod
    def _decode_attachments(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if not value:
            return []
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _empty_page() -> dict[str, Any]:
        return {
            "items": [],
            "nextCursor": None,
            "hasMore": False,
            "olderCursor": None,
            "newerCursor": None,
            "hasOlder": False,
            "hasNewer": False,
        }

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
        legacy_chat_log_id: int | None,
        persona_id: str | None = None,
        reply_to_id: int | None = None,
        reply_to_content: str | None = None,
        reply_to_role: str | None = None,
        reply_to_attachments: str | None = None,
    ) -> None:
        reply_to_cols = (
            ", reply_to_id, reply_to_content, reply_to_role, reply_to_attachments"
            if self._has_reply_to_columns(conn, "messages")
            else ""
        )
        reply_to_vals = ", ?, ?, ?, ?" if reply_to_cols else ""
        reply_to_params = (
            (reply_to_id, reply_to_content, reply_to_role, reply_to_attachments)
            if reply_to_cols
            else ()
        )
        if self._has_persona_column(conn, "messages"):
            # 角色隔离：messages 行记录 persona_id
            conn.execute(
                f"""INSERT INTO messages
                   (message_id, conversation_id, turn_id, role, content,
                    attachments, response_group_id, sequence, channel,
                    channel_account_id, actor_id, legacy_chat_log_id,
                    persona_id{reply_to_cols})
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?{reply_to_vals})""",
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
                    legacy_chat_log_id,
                    persona_id,
                    *reply_to_params,
                ),
            )
            return
        conn.execute(
            f"""INSERT INTO messages
               (message_id, conversation_id, turn_id, role, content,
                attachments, response_group_id, sequence, channel,
                channel_account_id, actor_id, legacy_chat_log_id{reply_to_cols})
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?{reply_to_vals})""",
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
                legacy_chat_log_id,
                *reply_to_params,
            ),
        )

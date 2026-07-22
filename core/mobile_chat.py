"""Actor-scoped persistent chat facade for the isolated mobile gateway."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from core.chat_request_repository import (
    ChatRequestRepository,
    RequestContext,
    RequestIdentity,
)
from core.conversation_repository import resolve_conversation_id
from core.ids import generate_id
from core.mobile_identity import MobileIdentityStore, MobilePrincipal


class MobileChatError(Exception):
    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class MobileChatService:
    def __init__(self, database: Any, identity_store: MobileIdentityStore) -> None:
        self.database = database
        self.identity_store = identity_store
        self.requests = ChatRequestRepository(database)

    def _conversation_id(self, principal: MobilePrincipal) -> str:
        with self.database.connection() as conn:
            row = conn.execute(
                """SELECT conversation_id FROM conversations
                   WHERE actor_id = ? AND status = 'active'
                   ORDER BY updated_at DESC, created_at DESC LIMIT 1""",
                (principal.actor_id,),
            ).fetchone()
        if row is not None:
            return row["conversation_id"]
        return resolve_conversation_id(
            actor_id=principal.actor_id,
            channel="mobile",
            channel_account_id=principal.account_id,
            user_id=principal.user_id,
        )

    @staticmethod
    def _deterministic_id(prefix: str, account_id: str, client_id: str) -> str:
        digest = hashlib.sha256(
            f"{account_id}\x1f{client_id}\x1f{prefix}".encode("utf-8")
        ).hexdigest()
        return f"{prefix}_{digest[:32]}"

    def submit_request(
        self,
        principal: MobilePrincipal,
        *,
        client_request_id: str,
        text: str,
        file_ids: list[str],
    ) -> dict[str, Any]:
        try:
            parsed = uuid.UUID(client_request_id)
        except (ValueError, AttributeError) as exc:
            raise MobileChatError("invalid_client_request_id") from exc
        normalized_client_id = str(parsed)
        content = text.strip()
        if len(content) > 20_000:
            raise MobileChatError("text_too_long")
        if file_ids:
            raise MobileChatError("files_not_available", status_code=409)
        if not content:
            raise MobileChatError("empty_request")

        request_id = self._deterministic_id(
            "req", principal.account_id, normalized_client_id
        )
        existing = self.requests.get_owned(
            request_id=request_id,
            actor_id=principal.actor_id,
        )
        if existing is not None:
            return self._request_response(existing)

        conversation_id = self._conversation_id(principal)
        turn_id = self._deterministic_id(
            "turn", principal.account_id, normalized_client_id
        )
        submitted = self.requests.submit(
            context=RequestContext(
                request_id=request_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                identity=RequestIdentity(
                    actor_id=principal.actor_id,
                    channel="mobile",
                    channel_account_id=principal.account_id,
                    user_id=principal.user_id,
                ),
                input_content=content,
                effective_content=content,
            )
        )
        return {
            "requestId": submitted.request_id,
            "conversationId": submitted.conversation_id,
            "status": submitted.status,
            "clientRequestId": normalized_client_id,
        }

    @staticmethod
    def _request_response(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "requestId": row["request_id"],
            "conversationId": row["conversation_id"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "completedAt": row["completed_at"],
            "errorCode": row.get("error_code"),
            "retryOfRequestId": row.get("retry_of_request_id"),
        }

    def get_request(
        self,
        principal: MobilePrincipal,
        request_id: str,
    ) -> dict[str, Any]:
        row = self.requests.get_owned(
            request_id=request_id,
            actor_id=principal.actor_id,
        )
        if row is None:
            raise MobileChatError("not_found", status_code=404)
        return self._request_response(row)

    def cancel_request(
        self,
        principal: MobilePrincipal,
        request_id: str,
    ) -> dict[str, Any]:
        status = self.requests.request_cancel(
            request_id=request_id,
            actor_id=principal.actor_id,
        )
        if status is None:
            raise MobileChatError("not_found", status_code=404)
        return {"requestId": request_id, "status": status}

    def retry_request(
        self,
        principal: MobilePrincipal,
        request_id: str,
    ) -> dict[str, Any]:
        try:
            result = self.requests.create_retry(
                source_request_id=request_id,
                actor_id=principal.actor_id,
                request_id=generate_id("req"),
                turn_id=generate_id("turn"),
            )
        except LookupError as exc:
            raise MobileChatError("not_found", status_code=404) from exc
        except ValueError as exc:
            raise MobileChatError("request_not_retryable", status_code=409) from exc
        return {
            "requestId": result["request_id"],
            "conversationId": result["conversation_id"],
            "status": result["status"],
            "retryOfRequestId": request_id,
        }

    def list_messages(
        self,
        principal: MobilePrincipal,
        *,
        before_id: str | None = None,
        after_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if before_id and after_id:
            raise MobileChatError("invalid_cursor")
        if not 1 <= limit <= 100:
            raise MobileChatError("invalid_limit")
        clauses = ["actor_id = ?"]
        params: list[Any] = [principal.actor_id]
        with self.database.connection() as conn:
            if before_id or after_id:
                cursor_id = before_id or after_id
                cursor = conn.execute(
                    """SELECT rowid FROM messages
                       WHERE message_id = ? AND actor_id = ?""",
                    (cursor_id, principal.actor_id),
                ).fetchone()
                if cursor is None:
                    raise MobileChatError("invalid_cursor")
                clauses.append(f"rowid {'<' if before_id else '>'} ?")
                params.append(cursor["rowid"])
            direction = "DESC" if before_id or not after_id else "ASC"
            rows = conn.execute(
                f"""SELECT rowid, message_id, conversation_id, turn_id, role,
                            content, attachments, created_at
                     FROM messages WHERE {' AND '.join(clauses)}
                     ORDER BY rowid {direction} LIMIT ?""",
                (*params, limit),
            ).fetchall()
        items = [
            {
                "messageId": row["message_id"],
                "conversationId": row["conversation_id"],
                "turnId": row["turn_id"],
                "role": row["role"],
                "content": row["content"],
                "attachments": json.loads(row["attachments"] or "[]"),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]
        if direction == "DESC":
            items.reverse()
        return {
            "items": items,
            "hasMore": len(rows) == limit,
        }

    def list_events(
        self,
        principal: MobilePrincipal,
        *,
        after_event_id: str | None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sequence = 0
        if after_event_id:
            if not after_event_id.startswith("evt_"):
                raise MobileChatError("invalid_cursor")
            try:
                sequence = int(after_event_id.removeprefix("evt_"))
            except ValueError as exc:
                raise MobileChatError("invalid_cursor") from exc
        with self.database.connection() as conn:
            rows = conn.execute(
                """SELECT event_sequence, event_type, entity_id, created_at
                   FROM mobile_events
                   WHERE actor_id = ? AND event_sequence > ?
                   ORDER BY event_sequence LIMIT ?""",
                (principal.actor_id, sequence, limit),
            ).fetchall()
            events = []
            for row in rows:
                payload = self._event_payload(
                    conn,
                    principal.actor_id,
                    row["event_type"],
                    row["entity_id"],
                )
                if payload is not None:
                    events.append(
                        {
                            "id": f"evt_{row['event_sequence']}",
                            "type": row["event_type"],
                            "createdAt": row["created_at"],
                            "data": payload,
                        }
                    )
        return events

    @staticmethod
    def _event_payload(
        conn: Any,
        actor_id: str,
        event_type: str,
        entity_id: str,
    ) -> dict[str, Any] | None:
        if event_type == "message.created":
            row = conn.execute(
                """SELECT message_id, conversation_id, role, content, created_at
                   FROM messages WHERE message_id = ? AND actor_id = ?""",
                (entity_id, actor_id),
            ).fetchone()
            if row is None:
                return None
            return {
                "messageId": row["message_id"],
                "conversationId": row["conversation_id"],
                "role": row["role"],
                "content": row["content"],
                "createdAt": row["created_at"],
            }
        row = conn.execute(
            """SELECT request_id, conversation_id, status, error_code,
                      updated_at
               FROM requests WHERE request_id = ? AND actor_id = ?""",
            (entity_id, actor_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "requestId": row["request_id"],
            "conversationId": row["conversation_id"],
            "status": row["status"],
            "errorCode": row["error_code"],
            "updatedAt": row["updated_at"],
        }

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from config.persona_loader import get_master_qq
from core.chat_request_repository import RequestContext, RequestIdentity
from core.conversation_repository import resolve_conversation_id
from core.ids import generate_id


PURE_ATTACHMENT_EFFECTIVE_CONTENT = "请结合用户提供的附件内容进行回应。"
ATTACHMENT_FIELDS = ("name", "url", "state", "size", "type")
SAFE_UPLOAD_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ChatRequestError(RuntimeError):
    def __init__(self, error_code: str, *, status: str | None = None) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.status = status


class RequestNotFound(ChatRequestError):
    def __init__(self) -> None:
        super().__init__("request_not_found")


class RequestConflict(ChatRequestError):
    def __init__(self, *, status: str | None = None) -> None:
        super().__init__("request_state_conflict", status=status)


class QueueUnavailable(ChatRequestError):
    def __init__(self) -> None:
        super().__init__("queue_dependencies_unavailable")


class InvalidChatInput(ChatRequestError):
    pass


@dataclass(frozen=True)
class RequestStatusView:
    request_id: str
    conversation_id: str
    turn_id: str
    status: str
    error_code: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    cancelled_at: str | None
    can_cancel: bool
    can_retry: bool
    user_message_id: int | None
    assistant_message_ids: tuple[int, ...]
    retry_of_request_id: str | None = None


class ChatRequestService:
    def __init__(
        self,
        *,
        repository: Any,
        identity_repository: Any,
        worker: Any = None,
        master_user_id_provider: Callable[[], int] = get_master_qq,
        id_factory: Callable[[str], str] = generate_id,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.worker = worker
        self.master_user_id_provider = master_user_id_provider
        self.id_factory = id_factory

    def set_worker(self, worker: Any) -> None:
        self.worker = worker

    def submit(
        self,
        *,
        text: str,
        attachments: list[dict],
        reply_to_id: int,
        user_id: int | None,
    ) -> RequestStatusView:
        if text is None:
            visible_content = ""
        elif isinstance(text, str):
            visible_content = text.strip()
        else:
            raise InvalidChatInput("invalid_message")
        validated_attachments = self._validate_attachments(attachments)
        if not visible_content and not validated_attachments:
            raise InvalidChatInput("empty_message")

        try:
            legacy_user_id = int(
                user_id
                if user_id is not None
                else self.master_user_id_provider()
            )
            normalized_reply_to_id = int(reply_to_id or 0)
        except (TypeError, ValueError) as exc:
            raise InvalidChatInput("invalid_message") from exc
        if normalized_reply_to_id < 0:
            raise InvalidChatInput("invalid_message")

        identity = self.identity_repository.resolve("desktop", "local")
        request_identity = RequestIdentity(
            actor_id=identity.actor_id,
            channel=identity.channel,
            channel_account_id=identity.channel_account_id,
            user_id=legacy_user_id,
        )
        conversation_id = resolve_conversation_id(
            actor_id=request_identity.actor_id,
            channel=request_identity.channel,
            channel_account_id=request_identity.channel_account_id,
            user_id=request_identity.user_id,
        )
        if normalized_reply_to_id and not self.repository.reply_to_belongs_to_context(
            legacy_chat_log_id=normalized_reply_to_id,
            actor_id=request_identity.actor_id,
            channel=request_identity.channel,
            channel_account_id=request_identity.channel_account_id,
            conversation_id=conversation_id,
        ):
            raise RequestNotFound()
        context = RequestContext(
            request_id=self.id_factory("req"),
            conversation_id=conversation_id,
            turn_id=self.id_factory("turn"),
            identity=request_identity,
            input_content=visible_content,
            effective_content=(
                visible_content
                if visible_content
                else PURE_ATTACHMENT_EFFECTIVE_CONTENT
            ),
            attachments=validated_attachments,
            reply_to_id=normalized_reply_to_id,
        )
        self.repository.submit(context=context)
        self._notify_worker()
        row = self.repository.get_owned(
            request_id=context.request_id,
            actor_id=request_identity.actor_id,
        )
        if row is None:
            raise QueueUnavailable()
        return self._to_view(row)

    def get(
        self,
        *,
        request_id: str,
        user_id: int | None,
    ) -> RequestStatusView:
        del user_id
        return self._to_view(self._get_owned(request_id))

    async def cancel(
        self,
        *,
        request_id: str,
        user_id: int | None,
    ) -> RequestStatusView:
        del user_id
        row = self._get_owned(request_id)
        status = row["status"]
        if status in ("completed", "failed", "cancelled"):
            return self._to_view(row)
        if status == "cancelling":
            raise RequestConflict(status=status)
        if status not in ("queued", "running"):
            raise RequestConflict(status=status)
        if (
            self.worker is None
            or not callable(getattr(self.worker, "cancel_running", None))
        ):
            raise QueueUnavailable()

        changed_status = self.repository.request_cancel(
            request_id=request_id,
            actor_id=row["actor_id"],
        )
        if changed_status is None:
            raise RequestNotFound()
        if changed_status in ("completed", "failed", "cancelled"):
            return self._to_view(self._get_owned(request_id))
        if changed_status == "cancelling":
            try:
                await self.worker.cancel_running(request_id)
            except Exception as exc:
                raise QueueUnavailable() from exc
            return self._to_view(self._get_owned(request_id))
        raise RequestConflict(status=changed_status)

    def retry(
        self,
        *,
        request_id: str,
        user_id: int | None,
    ) -> RequestStatusView:
        del user_id
        source = self._get_owned(request_id)
        if source["status"] not in ("failed", "cancelled"):
            raise RequestConflict(status=source["status"])
        new_request_id = self.id_factory("req")
        try:
            self.repository.create_retry(
                source_request_id=request_id,
                actor_id=source["actor_id"],
                request_id=new_request_id,
                turn_id=self.id_factory("turn"),
            )
        except LookupError as exc:
            raise RequestNotFound() from exc
        except ValueError as exc:
            current = self.repository.get_owned(
                request_id=request_id,
                actor_id=source["actor_id"],
            )
            raise RequestConflict(
                status=current["status"] if current else None
            ) from exc
        self._notify_worker()
        return self._to_view(self._get_owned(new_request_id))

    def _get_owned(self, request_id: str) -> dict[str, Any]:
        identity = self.identity_repository.resolve("desktop", "local")
        row = self.repository.get_owned(
            request_id=request_id,
            actor_id=identity.actor_id,
        )
        if row is None:
            raise RequestNotFound()
        return row

    def _notify_worker(self) -> None:
        notify = getattr(self.worker, "notify", None)
        if callable(notify):
            notify()

    @staticmethod
    def _validate_attachments(attachments: Any) -> list[dict[str, Any]]:
        if attachments is None:
            return []
        if not isinstance(attachments, list):
            raise InvalidChatInput("invalid_attachment")

        validated: list[dict[str, Any]] = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                raise InvalidChatInput("invalid_attachment")
            if attachment.get("state") != "ready":
                raise InvalidChatInput("attachment_not_ready")
            if set(attachment) != set(ATTACHMENT_FIELDS):
                raise InvalidChatInput("invalid_attachment")
            name = attachment.get("name")
            size = attachment.get("size")
            media_type = attachment.get("type")
            if (
                not isinstance(name, str)
                or not name.strip()
                or name in (".", "..")
                or "/" in name
                or "\\" in name
                or "\x00" in name
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(media_type, str)
                or not media_type.strip()
            ):
                raise InvalidChatInput("invalid_attachment")
            url = attachment.get("url")
            if not isinstance(url, str):
                raise InvalidChatInput("invalid_attachment")
            normalized = url[1:] if url.startswith("/") else url
            parts = normalized.split("/")
            if (
                "\\" in url
                or "\x00" in url
                or ".." in url
                or len(parts) != 2
                or parts[0] != "uploads"
                or not parts[1]
                or SAFE_UPLOAD_FILENAME.fullmatch(parts[1]) is None
            ):
                raise InvalidChatInput("invalid_attachment")
            validated.append(
                {field: attachment[field] for field in ATTACHMENT_FIELDS}
            )
        return validated

    @staticmethod
    def _to_view(row: dict[str, Any]) -> RequestStatusView:
        status = row["status"]
        return RequestStatusView(
            request_id=row["request_id"],
            conversation_id=row["conversation_id"],
            turn_id=row["turn_id"],
            status=status,
            error_code=row.get("error_code"),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            cancelled_at=row.get("cancelled_at"),
            can_cancel=status in ("queued", "running"),
            can_retry=status in ("failed", "cancelled"),
            user_message_id=row.get("user_message_id"),
            assistant_message_ids=tuple(row.get("assistant_message_ids", ())),
            retry_of_request_id=row.get("retry_of_request_id"),
        )

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any
from urllib.parse import urlparse

from communication.ilink.errors import ILinkProtocolError


class AuthStatus(str, Enum):
    WAIT = "wait"
    SCANED = "scaned"
    SCANED_BUT_REDIRECT = "scaned_but_redirect"
    EXPIRED = "expired"
    CONFIRMED = "confirmed"


class MessageType(IntEnum):
    NONE = 0
    USER = 1
    BOT = 2


class MessageState(IntEnum):
    NEW = 0
    GENERATING = 1
    FINISH = 2


class MessageItemType(IntEnum):
    NONE = 0
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ILinkProtocolError(f"{field} must be an object")
    return value


def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ILinkProtocolError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field, allow_empty=True)


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ILinkProtocolError(f"{field} must be an integer")
    return value


def _optional_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _enum(value: Any, enum_type: type[IntEnum], field: str):
    integer = _integer(value, field)
    try:
        return enum_type(integer)
    except ValueError as exc:
        raise ILinkProtocolError(f"{field} has an unknown value") from exc


@dataclass(frozen=True)
class QRCodeChallenge:
    qrcode: str
    image_content: str

    @classmethod
    def from_dict(cls, value: Any) -> QRCodeChallenge:
        data = _mapping(value, "qrcode response")
        return cls(
            qrcode=_string(data.get("qrcode"), "qrcode"),
            image_content=_string(data.get("qrcode_img_content"), "qrcode_img_content"),
        )


@dataclass(frozen=True)
class ILinkCredentials:
    bot_token: str
    bot_id: str
    user_id: str
    base_url: str

    def __post_init__(self) -> None:
        for field, value in (
            ("bot_token", self.bot_token),
            ("ilink_bot_id", self.bot_id),
            ("ilink_user_id", self.user_id),
            ("baseurl", self.base_url),
        ):
            _string(value, field)
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ILinkProtocolError("baseurl must be an HTTPS origin")


@dataclass(frozen=True)
class AuthPollResult:
    status: AuthStatus
    credentials: ILinkCredentials | None = None
    redirect_host: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> AuthPollResult:
        data = _mapping(value, "qrcode status response")
        raw_status = _string(data.get("status"), "status")
        try:
            status = AuthStatus(raw_status)
        except ValueError as exc:
            raise ILinkProtocolError("status has an unknown value") from exc
        if status is AuthStatus.CONFIRMED:
            credentials = ILinkCredentials(
                bot_token=_string(data.get("bot_token"), "bot_token"),
                bot_id=_string(data.get("ilink_bot_id"), "ilink_bot_id"),
                user_id=_string(data.get("ilink_user_id"), "ilink_user_id"),
                base_url=_string(data.get("baseurl"), "baseurl"),
            )
            return cls(status=status, credentials=credentials)
        redirect_host = None
        if status is AuthStatus.SCANED_BUT_REDIRECT:
            redirect_host = _string(data.get("redirect_host"), "redirect_host")
        return cls(status=status, redirect_host=redirect_host)


@dataclass(frozen=True)
class MessageItem:
    type: MessageItemType
    text: str | None = None
    image: dict[str, Any] | None = None
    voice: dict[str, Any] | None = None
    file: dict[str, Any] | None = None
    video: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Any) -> MessageItem:
        data = _mapping(value, "message item")
        item_type = _enum(data.get("type"), MessageItemType, "item_list.type")
        text = None
        if item_type is MessageItemType.TEXT:
            text_item = _mapping(data.get("text_item"), "text_item")
            text = _string(text_item.get("text"), "text_item.text", allow_empty=True)
        media_fields = {}
        for item_value, field in (
            (MessageItemType.IMAGE, "image"),
            (MessageItemType.VOICE, "voice"),
            (MessageItemType.FILE, "file"),
            (MessageItemType.VIDEO, "video"),
        ):
            if item_type is item_value:
                media_fields[field] = _mapping(data.get(f"{field}_item"), f"{field}_item")
        return cls(type=item_type, text=text, **media_fields)


@dataclass(frozen=True)
class WeixinMessage:
    message_id: int
    from_user_id: str
    to_user_id: str
    client_id: str
    create_time_ms: int
    message_type: MessageType
    message_state: MessageState
    items: tuple[MessageItem, ...]
    context_token: str | None = None
    session_id: str | None = None
    group_id: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> WeixinMessage:
        data = _mapping(value, "message")
        raw_items = data.get("item_list")
        if not isinstance(raw_items, list):
            raise ILinkProtocolError("item_list must be an array")
        return cls(
            message_id=_integer(data.get("message_id"), "message_id"),
            from_user_id=_string(data.get("from_user_id"), "from_user_id"),
            to_user_id=_string(data.get("to_user_id"), "to_user_id"),
            client_id=_string(data.get("client_id"), "client_id"),
            create_time_ms=_integer(data.get("create_time_ms"), "create_time_ms"),
            message_type=_enum(data.get("message_type"), MessageType, "message_type"),
            message_state=_enum(data.get("message_state"), MessageState, "message_state"),
            items=tuple(MessageItem.from_dict(item) for item in raw_items),
            context_token=_optional_string(data.get("context_token"), "context_token"),
            session_id=_optional_string(data.get("session_id"), "session_id"),
            group_id=_optional_string(data.get("group_id"), "group_id"),
        )


@dataclass(frozen=True)
class GetUpdatesResponse:
    ret: int
    errcode: int | None
    errmsg: str | None
    messages: tuple[WeixinMessage, ...]
    cursor: str
    longpolling_timeout_ms: int | None = None

    @classmethod
    def from_dict(cls, value: Any) -> GetUpdatesResponse:
        data = _mapping(value, "getupdates response")
        raw_messages = data.get("msgs")
        if not isinstance(raw_messages, list):
            raise ILinkProtocolError("msgs must be an array")
        return cls(
            ret=_integer(data.get("ret"), "ret"),
            errcode=_optional_integer(data.get("errcode"), "errcode"),
            errmsg=_optional_string(data.get("errmsg"), "errmsg"),
            messages=tuple(WeixinMessage.from_dict(message) for message in raw_messages),
            cursor=_string(data.get("get_updates_buf"), "get_updates_buf", allow_empty=True),
            longpolling_timeout_ms=_optional_integer(
                data.get("longpolling_timeout_ms"), "longpolling_timeout_ms"
            ),
        )

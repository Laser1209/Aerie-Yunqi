"""Aerie · 云栖 v9.0 — Message DTOs.

IncomingMessage / OutgoingReply are the canonical DTOs.
Internal messages must NOT reuse these (per MR1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


MAX_MESSAGE_LENGTH = 2000  # Per spec MR1


class MessageType(str, Enum):
    PRIVATE = "private"
    GROUP = "group"
    PROACTIVE = "proactive"
    INTERNAL = "internal"


class Intent(str, Enum):
    """Detected user intent (best-effort classification)."""
    CHAT = "chat"
    QUESTION = "question"
    COMMAND = "command"
    COMPLAINT = "complaint"
    PRAISE = "praise"
    EMOTIONAL = "emotional"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class RouteMode(str, Enum):
    FULL = "FULL"               # Master account — full AI pipeline
    AUTO_REPLY = "AUTO"         # Friends — auto-reply template
    BASIC = "BASIC"             # Strangers — short canned reply


@dataclass
class IncomingMessage:
    """Canonical inbound message DTO. All QQ events become this."""

    user_id: int
    content: str
    msg_type: MessageType = MessageType.PRIVATE
    group_id: Optional[int] = None
    sender_name: Optional[str] = None
    intent: Intent = Intent.UNKNOWN
    raw_event: dict = field(default_factory=dict)
    parse_error: bool = False
    timestamp: str = ""

    @property
    def is_private(self) -> bool:
        return self.msg_type == MessageType.PRIVATE

    @property
    def is_group(self) -> bool:
        return self.msg_type == MessageType.GROUP

    @property
    def is_empty(self) -> bool:
        return not self.content or not self.content.strip()

    @property
    def is_negative(self) -> bool:
        """Detect negative keywords for recall trigger."""
        if not self.content:
            return False
        lowered = self.content.lower()
        keywords = ["别这样", "不要", "闭嘴", "停下", "够了", "烦", "滚"]
        return any(kw in self.content for kw in keywords) or \
               any(kw in lowered for kw in ["stop", "shut up"])

    @classmethod
    def from_onebot_event(cls, event: dict) -> "IncomingMessage":
        """Factory: parse a NapCat OneBot11 message event.

        Auto-truncates to 2000 chars and marks parse_error if malformed.
        """
        parse_error = False
        try:
            msg_type_str = event.get("message_type", "private")
            msg_type = MessageType.GROUP if msg_type_str == "group" else MessageType.PRIVATE
            user_id = int(event.get("user_id", 0))
            group_id = event.get("group_id")
            sender = event.get("sender", {}) or {}
            sender_name = sender.get("nickname") or sender.get("card")

            raw_message = event.get("raw_message") or event.get("message") or ""
            if isinstance(raw_message, list):
                # OneBot11 message segment array
                parts: list[str] = []
                for seg in raw_message:
                    if isinstance(seg, dict):
                        t = seg.get("type", "text")
                        if t == "text":
                            parts.append(seg.get("data", {}).get("text", ""))
                        elif t in ("at", "face", "image"):
                            parts.append(f"[{t}]")
                    elif isinstance(seg, str):
                        parts.append(seg)
                content = "".join(parts)
            else:
                content = str(raw_message)

            parse_error = False
            if not content:
                parse_error = True

            if len(content) > MAX_MESSAGE_LENGTH:
                content = content[:MAX_MESSAGE_LENGTH]
                parse_error = True

            timestamp = str(event.get("time", ""))

            return cls(
                user_id=user_id,
                content=content,
                msg_type=msg_type,
                group_id=int(group_id) if group_id is not None else None,
                sender_name=sender_name,
                raw_event=event,
                parse_error=parse_error,
                timestamp=timestamp,
            )
        except Exception:
            return cls(
                user_id=0,
                content="",
                parse_error=True,
                raw_event=event,
            )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["msg_type"] = self.msg_type.value
        d["intent"] = self.intent.value
        return d


@dataclass
class OutgoingReply:
    """Canonical outbound reply DTO. Sent to QQ via SendQueue."""

    user_id: int
    content: str
    msg_type: MessageType = MessageType.PRIVATE
    group_id: Optional[int] = None
    scene: str = "daily"            # daily | emotional | proactive | report | urgent
    mood: Optional[str] = None      # joy | sad | anger | fear | neutral
    recall_eligible: bool = False
    auto_recall_after_seconds: int = 0
    related_message_id: Optional[int] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.content) > MAX_MESSAGE_LENGTH:
            self.content = self.content[:MAX_MESSAGE_LENGTH]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["msg_type"] = self.msg_type.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

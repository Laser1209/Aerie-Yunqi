"""Aerie · 云栖 v9.0 — Incoming and outgoing message models."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncomingMessage:
    user_id: int
    content: str
    msg_type: str = "private"    # private | group
    source: str = "qq"           # qq | local
    raw_event: dict = field(default_factory=dict)

    @staticmethod
    def from_onebot_event(event: dict) -> "IncomingMessage":
        sender = event.get("sender", {})
        user_id = int(sender.get("user_id", 0))
        msg_type = event.get("message_type", "private")
        raw = str(event.get("raw_message", ""))
        content = raw.strip()
        return IncomingMessage(
            user_id=user_id,
            content=content,
            msg_type=msg_type,
            source="qq",
            raw_event=event,
        )

    @staticmethod
    def from_local(content: str, user_id: int) -> "IncomingMessage":
        return IncomingMessage(
            user_id=user_id,
            content=content.strip(),
            msg_type="private",
            source="local",
        )


@dataclass
class OutgoingReply:
    user_id: int
    content: str
    render_mode: str = "plain"   # plain | markdown
    msg_id: int = 0              # chat_log DB id

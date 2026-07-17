"""Aerie · 云栖 v9.0 — Incoming and outgoing message models."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class IncomingMessage:
    user_id: int
    content: str
    msg_type: str = "private"    # private | group
    source: str = "qq"           # qq | local
    raw_event: dict = field(default_factory=dict)
    # Phase 4: quote / reply context
    reply_to_id: int = 0                    # chat_log.id being replied to
    reply_to_content: str = ""
    reply_to_role: str = ""
    # Phase 4: attachments (Phase 5 will fill these)
    attachments: list[dict] = field(default_factory=list)

    @staticmethod
    def from_onebot_event(event: dict) -> "IncomingMessage":
        sender = event.get("sender", {})
        user_id = int(sender.get("user_id", 0))
        msg_type = event.get("message_type", "private")
        raw = str(event.get("raw_message", ""))
        content = raw.strip()

        # Phase 4: extract OneBot11 reply segment if present
        reply_to_id = 0
        msg_array = event.get("message", [])
        if isinstance(msg_array, list):
            for seg in msg_array:
                if isinstance(seg, dict) and seg.get("type") == "reply":
                    reply_to_id = int(seg.get("data", {}).get("id", 0))
                    break

        return IncomingMessage(
            user_id=user_id,
            content=content,
            msg_type=msg_type,
            source="qq",
            raw_event=event,
            reply_to_id=reply_to_id,
        )

    @staticmethod
    def from_local(
        content: str,
        user_id: int,
        reply_to_id: int = 0,
        attachments: list[dict] | None = None,
    ) -> "IncomingMessage":
        return IncomingMessage(
            user_id=user_id,
            content=content.strip(),
            msg_type="private",
            source="local",
            reply_to_id=reply_to_id,
            attachments=attachments or [],
        )


@dataclass
class OutgoingReply:
    user_id: int
    content: str
    render_mode: str = "plain"   # plain | markdown
    msg_id: int = 0              # chat_log DB id
    # Phase 4: quote context for sending (OneBot11 reply segment)
    reply_to_qq_message_id: int = 0
    # Phase 4: optional attachments echoed back
    attachments: list[dict] = field(default_factory=list)
    # Phase 9 Batch 7 (B7.2): link this reply to the originating
    # cognition_log row so SendQueue can append pacing decisions back
    # into the trace after the segments have actually been sent.
    cognition_id: int = 0

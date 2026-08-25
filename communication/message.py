"""Aerie · 云栖 v0.1.0-beta.1 — Incoming and outgoing message models."""

from __future__ import annotations
import asyncio
from dataclasses import dataclass, field


class CancellationTooLate(RuntimeError):
    def __init__(self, reason: str = "terminal_side_effect_committed") -> None:
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False
        self.reason = "user_cancel"

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self, reason: str | None = None) -> None:
        self._cancelled = True
        if reason:
            self.reason = reason

    def throw_if_cancelled(
        self,
        *,
        boundary: str | None = None,
        terminal_side_effect_committed: bool = False,
        completed: bool = False,
    ) -> None:
        del boundary
        if not self._cancelled:
            return
        if completed:
            return
        if terminal_side_effect_committed:
            raise CancellationTooLate("terminal_side_effect_committed")
        raise asyncio.CancelledError(self.reason)


@dataclass
class QuoteContext:
    """Unified quote/reply context across QQ / desktop / mobile / WeChat.

    ``chat_log_id`` is the single system-wide addressing key. On inbound
    QQ quotes the platform id arrives in ``platform_message_id`` (OneBot11
    message_id) and is mapped to ``chat_log_id`` via ``chat_log.qq_message_id``
    when the direct id lookup misses.
    """

    chat_log_id: int = 0
    platform_message_id: int = 0
    role: str = ""
    content: str = ""
    msg_type: str = "private"
    attachments: list[dict] = field(default_factory=list)
    # which AI persona produced the quoted message (empty = legacy/unknown);
    # lets multi-persona setups attribute quotes to the right speaker.
    persona_id: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.chat_log_id or self.content)

    def to_prompt_dict(self) -> dict:
        return {
            "id": self.chat_log_id,
            "role": self.role,
            "content": self.content,
            "attachments": self.attachments,
            "persona_id": self.persona_id,
        }


@dataclass
class IncomingMessage:
    user_id: int
    content: str
    msg_type: str = "private"    # private | group
    source: str = "qq"           # qq | local
    raw_event: dict = field(default_factory=dict)
    # Phase 4: quote / reply context.
    # reply_to_id: id of the quoted message — chat_log.id on desktop/mobile,
    #              QQ message_id on inbound QQ quotes (resolved in pipeline).
    reply_to_id: int = 0
    # platform-native id of the quoted message (OneBot11 message_id on QQ).
    platform_message_id: int = 0
    # resolved quoted context (pipeline fills; unified across channels).
    reply_to: QuoteContext | None = None
    # Phase 4: attachments (Phase 5 will fill these)
    attachments: list[dict] = field(default_factory=list)
    # Phase 2: normalized identity contract (legacy fields remain above)
    actor_id: str | None = None
    channel: str | None = None
    channel_account_id: str | None = None
    context: dict = field(default_factory=dict)
    # 消息到达时间戳(epoch 秒)。会话聚合层算时间窗口用;None 表示未捕获。
    timestamp: float | None = None

    @staticmethod
    def from_onebot_event(event: dict) -> "IncomingMessage":
        sender = event.get("sender", {})
        user_id = int(sender.get("user_id", 0))
        msg_type = event.get("message_type", "private")
        raw = str(event.get("raw_message", ""))
        content = raw.strip()

        # Phase 4: extract OneBot11 reply segment if present.
        # OneBot11 reply segments carry the QQ platform message_id; keep it
        # in both reply_to_id (as the raw quoted id) and platform_message_id
        # so pipeline can resolve chat_log.id via the id mapping.
        reply_to_id = 0
        platform_message_id = 0
        msg_array = event.get("message", [])
        if isinstance(msg_array, list):
            for seg in msg_array:
                if isinstance(seg, dict) and seg.get("type") == "reply":
                    platform_message_id = int(seg.get("data", {}).get("id", 0))
                    break
        reply_to_id = platform_message_id

        # OneBot11 事件自带 time 字段(epoch 秒);会话聚合层算窗口用。
        _ts = event.get("time")
        timestamp = float(_ts) if isinstance(_ts, (int, float)) else None

        return IncomingMessage(
            user_id=user_id,
            content=content,
            msg_type=msg_type,
            source="qq",
            raw_event=event,
            reply_to_id=reply_to_id,
            platform_message_id=platform_message_id,
            channel="qq",
            channel_account_id=str(user_id),
            timestamp=timestamp,
        )

    @staticmethod
    def from_local(
        content: str,
        user_id: int,
        reply_to_id: int = 0,
        attachments: list[dict] | None = None,
        platform_message_id: int = 0,
    ) -> "IncomingMessage":
        import time

        return IncomingMessage(
            user_id=user_id,
            content=content.strip(),
            msg_type="private",
            source="local",
            reply_to_id=reply_to_id,
            platform_message_id=platform_message_id,
            attachments=attachments or [],
            channel="desktop",
            channel_account_id="local",
            timestamp=time.time(),
        )


@dataclass
class OutgoingReply:
    user_id: int
    content: str
    channel: str = "qq"
    channel_account_id: str = ""
    context: dict = field(default_factory=dict)
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
    # Task 4: Batch processing support
    batch_id: str | None = None
    sequence_index: int = 0

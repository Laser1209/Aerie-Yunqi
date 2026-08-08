"""Task P1-D.4: CompanionChannel 通道抽象 (本地桩).

提供一个稳定的 CompanionChannel Protocol 契约 (health / echo / send / receive)
以及两个本地桩适配器: QQ 与 ClawBot。

安全边界: 适配器仅为本地桩, 只操作进程内内存 (inbox / outbox),
绝不调用真实 QQ / NapCat 或任何外部消息服务。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

CHANNEL_QQ = "qq"
CHANNEL_CLAWBOT = "clawbot"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ChannelHealth:
    """通道健康检查结果."""

    channel: str
    healthy: bool
    status: str
    latency_ms: int = 0
    detail: str = ""


@dataclass(frozen=True)
class ChannelMessage:
    """通道内的单条消息 (入/出向)."""

    channel: str
    text: str
    direction: str = "out"
    created_at: str = ""


@dataclass(frozen=True)
class SendReceipt:
    """发送动作的本地回执 (仅入队, 不产生真实发送)."""

    channel: str
    accepted: bool
    queued: int
    error: str = ""


class CompanionChannel(Protocol):
    """消息通道抽象契约.

    Core 依赖此接口, 而不依赖任何具体外部服务; 所有动作均应为本地桩语义,
    以便在无真实网络环境下测试与回退。
    """

    def health(self) -> ChannelHealth:
        ...

    def echo(self, text: str) -> str:
        ...

    def send(self, payload: dict) -> SendReceipt:
        ...

    def receive(self) -> list[ChannelMessage]:
        ...


class _LocalStubChannel:
    """本地桩通道基类: 只操作进程内 inbox/outbox."""

    channel: str = ""

    def __init__(self, *, inbox_texts: list[str] | None = None) -> None:
        self._inbox: list[ChannelMessage] = [
            ChannelMessage(
                channel=self.channel,
                text=str(text),
                direction="in",
                created_at=_now_iso(),
            )
            for text in (inbox_texts or [])
            if str(text)
        ]
        self._outbox: list[ChannelMessage] = []

    @property
    def outbox(self) -> list[ChannelMessage]:
        return self._outbox

    def health(self) -> ChannelHealth:
        return ChannelHealth(
            channel=self.channel,
            healthy=True,
            status="stub_ok",
            latency_ms=0,
            detail="local stub adapter",
        )

    def echo(self, text: str) -> str:
        # 回显仅为进程内字符串往返, 不经过任何外部服务
        return str(text)

    def send(self, payload: dict) -> SendReceipt:
        text = str((payload or {}).get("text") or "")
        self._outbox.append(
            ChannelMessage(
                channel=self.channel,
                text=text,
                direction="out",
                created_at=_now_iso(),
            )
        )
        return SendReceipt(
            channel=self.channel,
            accepted=True,
            queued=len(self._outbox),
        )

    def receive(self) -> list[ChannelMessage]:
        messages = list(self._inbox)
        self._inbox.clear()
        return messages


class QQChannelAdapter(_LocalStubChannel):
    """QQ 通道本地桩."""

    channel: str = CHANNEL_QQ


class ClawBotChannelAdapter(_LocalStubChannel):
    """ClawBot 通道本地桩."""

    channel: str = CHANNEL_CLAWBOT

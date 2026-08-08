"""RecallAdapter 协议与撤回结果类型.

设计原则: 撤回能力按 channel 分派, 各端适配器自洽, 不与单一 user_id 绑定。
record 为鸭子类型: 需具备 channel / channel_account_id / msg_id / qq_message_id。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class RecallOutcome:
    """一次撤回动作的结果."""

    channel: str
    recalled: bool                  # 平台侧是否真的撤回了
    reason: str                     # ok / unsupported / no_msg_id / local_mark / ...
    msg_id: int = 0
    remote_message_id: str | None = None
    detail: str = ""


class RecallAdapter(Protocol):
    """端口撤回适配器契约."""

    channel: str

    def can_recall(self, record: Any) -> tuple[bool, str]:
        """返回 (是否可撤, 原因)."""

    async def recall(self, record: Any) -> RecallOutcome:
        """执行平台侧撤回, 返回结果."""

    def local_mark_only(self) -> bool:
        """True = 仅本地标记, 无真实平台撤回."""

"""本地/桌面端撤回适配器.

本地消息无真实协议撤回, 撤回 = DB 标记 is_recalled=1 + 前端事件。
平台侧 always 视为"已撤回"(由上层负责标记与 emit)。
"""
from __future__ import annotations

from typing import Any

from communication.recall.base import RecallOutcome

CHANNEL = "local"


class LocalRecallAdapter:
    """本地端撤回: 仅本地标记, 无真实平台撤回."""

    channel: str = CHANNEL

    def can_recall(self, record: Any) -> tuple[bool, str]:
        return (True, "ok") if record else (False, "no_record")

    async def recall(self, record: Any) -> RecallOutcome:
        return RecallOutcome(
            channel=self.channel,
            recalled=True,
            reason="local_mark",
            msg_id=getattr(record, "msg_id", 0) or 0,
        )

    def local_mark_only(self) -> bool:
        return True

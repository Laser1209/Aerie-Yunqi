"""微信(ClawBot)撤回适配器 — 架构预留桩.

当前不接真实微信; 未来接入腾讯 OpenClaw「微信 ClawBot」(iLink 协议) 时,
只需在此补充真实 recall 实现, 无需改动上层 RecallManager。
"""
from __future__ import annotations

from typing import Any

from communication.recall.base import RecallOutcome

CHANNEL = "clawbot"


class WeChatClawbotAdapter:
    """微信端撤回: 预留桩, 尚未实现."""

    channel: str = CHANNEL

    def can_recall(self, record: Any) -> tuple[bool, str]:
        return (False, "not_implemented")

    async def recall(self, record: Any) -> RecallOutcome:
        return RecallOutcome(
            channel=self.channel,
            recalled=False,
            reason="unsupported",
            msg_id=getattr(record, "msg_id", 0) or 0,
        )

    def local_mark_only(self) -> bool:
        return True

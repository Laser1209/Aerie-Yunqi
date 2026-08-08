"""QQ 端撤回适配器 (NapCat delete_msg)."""
from __future__ import annotations

import logging
from typing import Any

from communication.recall.base import RecallOutcome

logger = logging.getLogger(__name__)

CHANNEL = "qq"


class QQRecallAdapter:
    """通过 qq_client 调 NapCat delete_msg 真实撤回."""

    channel: str = CHANNEL

    def __init__(self, qq_client: Any = None) -> None:
        self._qq = qq_client

    def can_recall(self, record: Any) -> tuple[bool, str]:
        if not record:
            return False, "no_record"
        if not getattr(record, "qq_message_id", None):
            return False, "no_msg_id"
        if self._qq is None or not getattr(self._qq, "is_connected", False):
            return False, "not_connected"
        return True, "ok"

    async def recall(self, record: Any) -> RecallOutcome:
        qq_message_id = getattr(record, "qq_message_id", None)
        msg_id = getattr(record, "msg_id", 0) or 0
        if not qq_message_id:
            return RecallOutcome(
                channel=self.channel,
                recalled=False,
                reason="no_msg_id",
                msg_id=msg_id,
            )
        if self._qq is None:
            return RecallOutcome(
                channel=self.channel,
                recalled=False,
                reason="no_client",
                msg_id=msg_id,
                remote_message_id=str(qq_message_id),
            )
        try:
            ok = await self._qq.recall_message(int(qq_message_id))
            return RecallOutcome(
                channel=self.channel,
                recalled=bool(ok),
                reason="ok" if ok else "qq_recall_failed",
                msg_id=msg_id,
                remote_message_id=str(qq_message_id),
            )
        except Exception:
            logger.exception("QQ recall error for msg_id=%s", msg_id)
            return RecallOutcome(
                channel=self.channel,
                recalled=False,
                reason="error",
                msg_id=msg_id,
                remote_message_id=str(qq_message_id),
            )

    def local_mark_only(self) -> bool:
        return False

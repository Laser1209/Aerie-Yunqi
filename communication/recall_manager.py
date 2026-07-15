"""Aerie · 云栖 v9.0 — Recall manager.

When user sends a negative keyword within 2 minutes of Yita's last
message, recall that message and send an apology. Per spec R13.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from communication.qq_client import QQClient


logger = logging.getLogger(__name__)


NEGATIVE_KEYWORDS = ["别这样", "不要", "闭嘴", "停下", "够了", "烦", "滚", "stop", "shut up"]
RECALL_WINDOW_SECONDS = 120
APOLOGY_TEMPLATE = "……我刚才说重了。"


@dataclass
class LastSentRecord:
    user_id: int
    message_id: Optional[int]
    content: str
    timestamp: float


class RecallManager:
    """Tracks the last sent message per user and triggers recall on user negative."""

    def __init__(self, qq_client: QQClient) -> None:
        self.qq = qq_client
        self._last_sent: dict[int, LastSentRecord] = {}

    def on_message_sent(self, user_id: int, content: str, message_id: Optional[int] = None) -> None:
        self._last_sent[int(user_id)] = LastSentRecord(
            user_id=int(user_id),
            message_id=message_id,
            content=content,
            timestamp=time.time(),
        )

    def is_negative(self, text: str) -> bool:
        if not text:
            return False
        return any(kw in text for kw in NEGATIVE_KEYWORDS)

    async def handle_user_negative(self, user_id: int, user_text: str) -> bool:
        """If user is negative within 2 min, recall + apologize.

        Returns True if a recall was triggered.
        """
        user_id = int(user_id)
        if not self.is_negative(user_text):
            return False
        last = self._last_sent.get(user_id)
        if not last:
            return False
        if (time.time() - last.timestamp) > RECALL_WINDOW_SECONDS:
            return False
        # Recall
        if last.message_id is not None:
            try:
                await self.qq.recall_message(last.message_id)
            except Exception as e:
                logger.warning("recall failed: %s", e)
        # Apologize
        try:
            await self.qq.send_message(user_id, APOLOGY_TEMPLATE)
        except Exception as e:
            logger.warning("apology send failed: %s", e)
        # Clear last sent to avoid double-trigger
        self._last_sent.pop(user_id, None)
        return True

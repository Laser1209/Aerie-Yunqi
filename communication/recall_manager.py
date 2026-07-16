"""Aerie · 云栖 v9.0 — Message recall manager.

Handles recall-on-negative and silence poke logic.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

NEGATIVE_KEYWORDS = {"别说了", "别这样", "不想听", "别发了", "别这样了", "别说了行吗"}


@dataclass
class SentRecord:
    user_id: int
    content: str
    timestamp: float = field(default_factory=time.time)


class RecallManager:
    """Manage last-sent message for recall and poke logic."""

    def __init__(self, qq_client: Any = None) -> None:
        self._qq = qq_client
        self._last_sent: dict[int, SentRecord] = {}

    def on_message_sent(self, user_id: int, content: str) -> None:
        """Record a sent message for potential recall."""
        self._last_sent[user_id] = SentRecord(
            user_id=user_id,
            content=content,
        )

    async def handle_user_negative(self, user_id: int, text: str) -> bool:
        """Check if user message is negative; if so, attempt recall."""
        for kw in NEGATIVE_KEYWORDS:
            if kw in text:
                record = self._last_sent.get(user_id)
                if record and (time.time() - record.timestamp) < 120:
                    # Within 2-minute recall window
                    if self._qq:
                        try:
                            await self._qq.recall_message(user_id)
                        except Exception:
                            pass
                    return True
        return False

    async def maybe_poke_on_silence(self, user_id: int) -> bool:
        """If last message was >5min ago, send a gentle poke."""
        record = self._last_sent.get(user_id)
        if record and (time.time() - record.timestamp) > 300:
            if self._qq:
                try:
                    await self._qq.send_poke(user_id)
                except Exception:
                    pass
            return True
        return False

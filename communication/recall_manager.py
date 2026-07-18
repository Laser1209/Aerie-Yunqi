"""Aerie · 云栖 v13.9.8 — Message recall manager.

Phase 4 upgrade: hooks into Companion + Pipeline + SendQueue. Supports
personality-aware recall (Ita's 闷骚 trait triggers proactive recall).

R8.1 (Persona 9/10 · screen-aware): 9/10 直球版更易"说完就后悔"
—— Etta 一旦发现自己措辞过猛，会更频繁触发撤回保护。
max_recalls_per_session 默认值 5→7（单 session 撤回预算提高），
让 9/10 行为不被撤回预算提前截断。

Reads persona.yaml `recall.*` configuration:
  - window_seconds: max time after send during which recall is allowed
  - min_recall_gap_seconds: cooldown between consecutive recalls
  - max_recalls_per_session: per-session recall budget
  - triggers: which LLM-emitted signals may trigger recall
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


NEGATIVE_KEYWORDS = {
    "别说了", "别这样", "不想听", "别发了", "别这样了", "别说了行吗",
}


@dataclass
class SentRecord:
    user_id: int
    content: str
    timestamp: float = field(default_factory=time.time)
    msg_id: int = 0                       # local chat_log.id
    qq_message_id: int | None = None      # NapCat OneBot11 message_id
    segments: list[str] = field(default_factory=list)


@dataclass
class RecallConfig:
    """Loaded from persona.yaml > recall.*

    R8.1 (Persona 9/10): max_recalls_per_session 默认 5→7。
    9/10 直球行为下 Etta 更易"说完就后悔"，撤回预算需提高。
    window_seconds 维持 120s（QQ 撤回技术限制），min_recall_gap_seconds
    维持 60s（防刷屏）。
    """
    enabled: bool = True
    window_seconds: int = 120             # 2-minute recall window (QQ-aligned)
    min_recall_gap_seconds: int = 60
    max_recalls_per_session: int = 7      # R8.1: 9/10 → 5→7
    triggers: list[str] = field(default_factory=lambda: [
        "send_after_thinking", "regret_correction", "personality_blush",
    ])


def load_recall_config() -> RecallConfig:
    """Parse persona.yaml for recall section; fall back to defaults."""
    try:
        from config.persona_loader import load_persona
        data = load_persona().get("recall", {})
        true_feelings = load_persona().get("true_feelings", {})
        return RecallConfig(
            enabled=bool(data.get("enabled", True)),
            window_seconds=int(true_feelings.get("recall_window_seconds", data.get("window_seconds", 120))),
            min_recall_gap_seconds=int(data.get("min_recall_gap_seconds", 60)),
            max_recalls_per_session=int(data.get("max_recalls_per_session", 5)),
            triggers=list(data.get("triggers", [
                "send_after_thinking", "regret_correction", "personality_blush",
            ])),
        )
    except Exception:
        return RecallConfig()


class RecallManager:
    """Manage last-sent message + session recall budget + poke logic.

    Phase 4 surface:
      - record_sent(msg_id, qq_message_id, segments)  hook from SendQueue
      - try_recall(msg_id, reason)                     manual + LLM-triggered
      - handle_user_negative(text)                    user said "别说了" etc
      - maybe_poke_on_silence()                       5-min idle
      - attach_qq_message_id(msg_id, qq_mid)          retroactive from Pipeline
    """

    def __init__(self, qq_client: Any = None, config: RecallConfig | None = None) -> None:
        self._qq = qq_client
        self.config = config or load_recall_config()
        self._last_sent: dict[int, SentRecord] = {}
        self._last_recall_at: dict[int, float] = {}
        self._session_recall_count: dict[int, int] = {}

    def record_sent(
        self,
        user_id: int,
        content: str,
        msg_id: int = 0,
        qq_message_id: int | None = None,
        segments: list[str] | None = None,
    ) -> None:
        """Record a sent message so it can be recalled within window."""
        self._last_sent[user_id] = SentRecord(
            user_id=user_id,
            content=content,
            msg_id=msg_id,
            qq_message_id=qq_message_id,
            segments=segments or [content],
        )

    # Backward-compat alias (legacy tests used on_message_sent)
    def on_message_sent(self, user_id: int, content: str) -> None:
        self.record_sent(user_id, content)

    def attach_qq_message_id(self, user_id: int, qq_message_id: int) -> None:
        """Retroactively attach a QQ message_id once NapCat reports it."""
        record = self._last_sent.get(user_id)
        if record:
            record.qq_message_id = qq_message_id

    def can_recall(self, user_id: int) -> tuple[bool, str]:
        """Check whether a recall is allowed right now for this user."""
        if not self.config.enabled:
            return False, "disabled"
        record = self._last_sent.get(user_id)
        if not record:
            return False, "no_recent_message"
        age = time.time() - record.timestamp
        if age > self.config.window_seconds:
            return False, "window_expired"
        last = self._last_recall_at.get(user_id, 0)
        if time.time() - last < self.config.min_recall_gap_seconds:
            return False, "cooldown"
        used = self._session_recall_count.get(user_id, 0)
        if used >= self.config.max_recalls_per_session:
            return False, "session_limit"
        return True, "ok"

    async def try_recall(
        self,
        user_id: int,
        reason: str = "manual",
    ) -> dict[str, Any]:
        """Attempt to recall last sent message.

        Returns:
            {status, reason, content, msg_id, qq_recalled}
        """
        can, why = self.can_recall(user_id)
        if not can:
            return {"status": "skipped", "reason": why}

        record = self._last_sent[user_id]
        qq_recalled = False

        # QQ side recall via NapCat delete_msg
        if record.qq_message_id and self._qq:
            try:
                qq_recalled = await self._qq.recall_message(record.qq_message_id)
            except Exception:
                logger.exception("QQ recall error for user %s", user_id)

        self._last_recall_at[user_id] = time.time()
        self._session_recall_count[user_id] = self._session_recall_count.get(user_id, 0) + 1

        return {
            "status": "ok",
            "reason": reason,
            "content": record.content,
            "msg_id": record.msg_id,
            "qq_recalled": qq_recalled,
        }

    async def handle_user_negative(self, user_id: int, text: str) -> bool:
        """If user says '别说了' etc within recall window, auto-recall."""
        for kw in NEGATIVE_KEYWORDS:
            if kw in text:
                result = await self.try_recall(user_id, reason="user_negative")
                return result.get("status") == "ok"
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

    def reset_session(self, user_id: int) -> None:
        self._session_recall_count[user_id] = 0

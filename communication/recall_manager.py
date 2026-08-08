"""Aerie · 云栖 v0.2.0 — Message recall manager (三端解耦版).

Gate 1 重构: 撤回能力按 channel 分派, 不再与单一 user_id 绑定。
- QQ     : 通过 RecallAdapter(QQ) → NapCat delete_msg 真实撤回
- local  : RecallAdapter(Local) → 仅 DB 标记 + 前端事件
- clawbot: RecallAdapter(WeChatClawbot) → 预留桩

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

from communication.recall.base import RecallOutcome
from communication.recall.factory import get_recall_adapter

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
    qq_message_id: int | None = None      # NapCat OneBot11 message_id (QQ 专用)
    segments: list[str] = field(default_factory=list)
    channel: str = "qq"
    channel_account_id: str = ""


@dataclass
class RecallConfig:
    """Loaded from persona.yaml > recall.*

    R8.1 (Persona 9/10): max_recalls_per_session 默认 5→7。
    window_seconds 维持 120s (QQ 撤回技术限制), min_recall_gap_seconds
    维持 60s (防刷屏)。
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


def _account_of(user_id: int, channel_account_id: str | None) -> str:
    """派生 channel 内账号标识 (缺省用 user_id 字符串)."""
    return channel_account_id or str(user_id)


class RecallManager:
    """Manage last-sent message + session recall budget + poke logic.

    Phase 4 surface:
      - record_sent(msg_id, qq_message_id, segments)  hook from SendQueue
      - try_recall(msg_id, reason)                     manual + LLM-triggered
      - handle_user_negative(text)                    user said "别说了" etc
      - maybe_poke_on_silence()                       5-min idle
      - attach_qq_message_id(msg_id, qq_mid)          retroactive from Pipeline

    Gate 1 (三端解耦): 所有记录与预算按 (channel, channel_account_id) 分key,
    真实撤回经 RecallAdapter 按 channel 分派。
    """

    def __init__(self, qq_client: Any = None, config: RecallConfig | None = None) -> None:
        self._qq = qq_client
        self.config = config or load_recall_config()
        # key = (channel, channel_account_id) -> SentRecord
        self._last_sent: dict[tuple[str, str], SentRecord] = {}
        self._last_recall_at: dict[tuple[str, str], float] = {}
        self._session_recall_count: dict[tuple[str, str], int] = {}

    def _adapter(self, channel: str) -> Any:
        return get_recall_adapter(channel, qq_client=self._qq)

    def _key(self, channel: str, channel_account_id: str | None, user_id: int) -> tuple[str, str]:
        return (channel, _account_of(user_id, channel_account_id))

    def record_sent(
        self,
        user_id: int,
        content: str,
        msg_id: int = 0,
        qq_message_id: int | None = None,
        segments: list[str] | None = None,
        *,
        channel: str = "qq",
        channel_account_id: str | None = None,
    ) -> None:
        """Record a sent message so it can be recalled within window."""
        key = self._key(channel, channel_account_id, user_id)
        self._last_sent[key] = SentRecord(
            user_id=user_id,
            content=content,
            msg_id=msg_id,
            qq_message_id=qq_message_id,
            segments=segments or [content],
            channel=channel,
            channel_account_id=_account_of(user_id, channel_account_id),
        )

    # Backward-compat alias (legacy tests used on_message_sent)
    def on_message_sent(self, user_id: int, content: str) -> None:
        self.record_sent(user_id, content)

    def attach_qq_message_id(self, user_id: int, qq_message_id: int) -> None:
        """Retroactively attach a QQ message_id once NapCat reports it."""
        # 兼容旧签名: 作用于任意 channel 最近记录 (以 qq 为先)
        for key, record in self._last_sent.items():
            if record.user_id == user_id and record.channel == "qq":
                record.qq_message_id = qq_message_id
                return

    def can_recall(
        self,
        user_id: int,
        *,
        channel: str = "qq",
        channel_account_id: str | None = None,
    ) -> tuple[bool, str]:
        """Check whether a recall is allowed right now for this user/channel."""
        if not self.config.enabled:
            return False, "disabled"
        key = self._key(channel, channel_account_id, user_id)
        record = self._last_sent.get(key)
        if not record:
            return False, "no_recent_message"
        age = time.time() - record.timestamp
        if age > self.config.window_seconds:
            return False, "window_expired"
        last = self._last_recall_at.get(key, 0)
        if time.time() - last < self.config.min_recall_gap_seconds:
            return False, "cooldown"
        used = self._session_recall_count.get(key, 0)
        if used >= self.config.max_recalls_per_session:
            return False, "session_limit"
        return True, "ok"

    async def try_recall(
        self,
        user_id: int,
        reason: str = "manual",
        *,
        channel: str = "qq",
        channel_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Attempt to recall last sent message.

        Returns:
            {status, reason, content, msg_id, qq_recalled, channel, outcome}
        """
        can, why = self.can_recall(user_id, channel=channel, channel_account_id=channel_account_id)
        if not can:
            return {"status": "skipped", "reason": why, "channel": channel}

        key = self._key(channel, channel_account_id, user_id)
        record = self._last_sent[key]

        # 平台侧撤回经 adapter 按 channel 分派
        adapter = self._adapter(channel)
        outcome: RecallOutcome
        try:
            outcome = await adapter.recall(record)
        except Exception:
            logger.exception("recall adapter error for channel=%s user=%s", channel, user_id)
            outcome = RecallOutcome(
                channel=channel,
                recalled=False,
                reason="adapter_error",
                msg_id=record.msg_id,
            )

        # 预算/冷却更新 (无论平台是否成功, 都记录动作, 防刷屏)
        self._last_recall_at[key] = time.time()
        self._session_recall_count[key] = self._session_recall_count.get(key, 0) + 1

        return {
            "status": "ok",
            "reason": reason,
            "content": record.content,
            "msg_id": record.msg_id,
            "qq_recalled": bool(outcome.recalled),
            "channel": channel,
            "outcome": outcome,
        }

    async def handle_user_negative(
        self,
        user_id: int,
        text: str,
        *,
        channel: str = "qq",
        channel_account_id: str | None = None,
    ) -> bool:
        """If user says '别说了' etc within recall window, auto-recall."""
        for kw in NEGATIVE_KEYWORDS:
            if kw in text:
                result = await self.try_recall(
                    user_id,
                    reason="user_negative",
                    channel=channel,
                    channel_account_id=channel_account_id,
                )
                return result.get("status") == "ok"
        return False

    async def maybe_poke_on_silence(self, user_id: int) -> bool:
        """If last message was >5min ago, send a gentle poke."""
        for record in self._last_sent.values():
            if record.user_id == user_id and (time.time() - record.timestamp) > 300:
                if self._qq:
                    try:
                        await self._qq.send_poke(user_id)
                    except Exception:
                        pass
                return True
        return False

    def reset_session(self, user_id: int, *, channel: str | None = None) -> None:
        if channel is None:
            self._session_recall_count.clear()
            return
        keys = [k for k in self._session_recall_count if k[0] == channel and k[1] == str(user_id)]
        for k in keys:
            self._session_recall_count.pop(k, None)

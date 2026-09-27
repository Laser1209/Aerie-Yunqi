from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Awaitable, Callable

from communication.ilink.client import ILinkClient
from communication.ilink.models import (
    MessageItem,
    MessageItemType,
    MessageState,
    MessageType,
    WeixinMessage,
)
from communication.message import IncomingMessage
from core.ilink_state import ILinkStateStore

logger = logging.getLogger(__name__)

# 未绑定设备收到消息时的引导回复（节流），避免用户面对"已连接却绝对静默"。
_PAIRING_HINT_TEXT = (
    "我还没认下这台设备。"
    "把云栖面板上那串 8 位配对码发给我，就能开始聊了。"
)
_PAIRING_HINT_INTERVAL_SEC = 600.0


TextCallback = Callable[[IncomingMessage], Awaitable[object] | object]


def _describe_items(items: tuple[MessageItem, ...]) -> str:
    """入站项的**只含字段名**结构描述，供诊断用。

    媒体项（图片/语音/文件）当前不进入主链路。只记 ``items=1`` 时，
    "用户发的文件到底去哪了"完全不可见；这里输出每项的类型与媒体子对象的
    字段名，用来确认协议形状。

    **绝不输出字段值**：``file_item`` 里的 ``encrypt_query_param`` 与
    ``aes_key`` 是 CDN 凭据，落盘即等同于泄露。
    """
    if not items:
        return "none"
    parts: list[str] = []
    for item in items:
        name = getattr(item.type, "name", str(item.type))
        for field in ("image", "voice", "file", "video"):
            payload = getattr(item, field, None)
            if isinstance(payload, dict):
                name = f"{name}:{field}({','.join(sorted(payload.keys()))})"
                break
        parts.append(name)
    return "; ".join(parts)


class ILinkChannel:
    def __init__(
        self,
        client: ILinkClient,
        state_store: ILinkStateStore,
        bot_id: str,
        primary_user_id: int,
        on_text: TextCallback,
    ) -> None:
        self.client = client
        self.state_store = state_store
        self.bot_id = bot_id
        self.primary_user_id = primary_user_id
        self.on_text = on_text
        self._pairing_hint_at: float = 0.0

    async def poll_once(self) -> None:
        current_cursor = self.state_store.get_cursor(self.bot_id)
        response = await self.client.get_updates(current_cursor)
        if response.messages:
            # 收到即留痕：这是判断"连接是否真的在收消息"的唯一可靠信号。
            # 没有这一行时，入站被后续任一环节过滤都会表现为完全静默。
            logger.info(
                "iLink poll: bot=%s received=%d skipped=%d",
                self.bot_id,
                len(response.messages),
                getattr(response, "skipped_messages", 0),
            )
        for message in response.messages:
            await self._handle_message(message)
        self.state_store.set_cursor(self.bot_id, response.cursor)

    async def _handle_message(self, message: WeixinMessage) -> None:
        text, skip_reason = self._private_finished_user_text(message)
        if text is None:
            # 用户消息被过滤必须留痕（仅 DEBUG 记录机器人自身回声，避免刷屏）：
            # 否则"连上了但收不到"无从定位。
            if message.message_type is MessageType.USER:
                logger.info(
                    "iLink user message skipped: bot=%s reason=%s state=%s group=%s items=%d shape=%s",
                    self.bot_id,
                    skip_reason,
                    getattr(message.message_state, "name", message.message_state),
                    bool(message.group_id),
                    len(message.items),
                    _describe_items(message.items),
                )
            else:
                logger.debug(
                    "iLink non-user message ignored: bot=%s type=%s",
                    self.bot_id,
                    getattr(message.message_type, "name", message.message_type),
                )
            return
        binding = self.state_store.get_binding(self.bot_id)
        if binding is None:
            # 未绑定：这条消息只可能是"用户发来的配对码"。无论成功与否都必须留痕，
            # 否则消息被静默丢弃、外部只看到"已连接却不回复"，无从定位
            # （2026-09-27 实测：ilink_bindings 为空 + 零日志 = 故障不可见）。
            paired = self.state_store.verify_pairing(
                self.bot_id,
                message.from_user_id,
                text,
                self.primary_user_id,
            )
            sender = self._mask_sender(message.from_user_id)
            if paired:
                logger.info(
                    "iLink pairing succeeded: bot=%s sender=%s; 该条消息被当作配对码消费，"
                    "下一条消息才会进入对话主链路",
                    self.bot_id,
                    sender,
                )
            else:
                logger.warning(
                    "iLink message dropped (not bound): bot=%s sender=%s reason=%s; "
                    "需在微信向机器人发送面板上展示的 8 位配对码",
                    self.bot_id,
                    sender,
                    self._pairing_failure_reason(),
                )
                # 让用户知道该做什么，而不是对着"已连接"干等（节流，见常量）。
                await self._maybe_hint_pairing(message)
            return
        if message.from_user_id != binding.ilink_user_id:
            logger.debug(
                "iLink message ignored: sender does not match the bound user "
                "(bot=%s sender=%s)",
                self.bot_id,
                self._mask_sender(message.from_user_id),
            )
            return
        dedupe_key = f"{self.bot_id}:{message.message_id}:{message.client_id}"
        if self.state_store.is_message_processed(self.bot_id, dedupe_key):
            return
        if message.context_token:
            self.state_store.set_context_token(self.bot_id, message.context_token)
        incoming = IncomingMessage(
            user_id=binding.primary_user_id,
            content=text,
            msg_type="private",
            source="ilink",
            raw_event={},
            platform_message_id=message.message_id,
            channel="ilink",
            channel_account_id=message.from_user_id,
            context={"token": message.context_token},
            timestamp=message.create_time_ms / 1000,
        )
        result = self.on_text(incoming)
        if inspect.isawaitable(result):
            await result
        self.state_store.mark_message_processed(self.bot_id, dedupe_key)

    async def _maybe_hint_pairing(self, message: WeixinMessage) -> None:
        """未绑定且配对码有效时，回一条引导（节流）。

        入站包自带 context_token，因此这条回复不依赖绑定态；这是让
        "已连接却收不到任何回应"不再发生的产品级闭环。
        """
        token = str(message.context_token or "")
        if not token:
            return
        now = time.monotonic()
        if now - self._pairing_hint_at < _PAIRING_HINT_INTERVAL_SEC:
            return
        try:
            info = self.state_store.get_pairing_info(self.bot_id)
        except Exception:
            logger.debug("iLink pairing hint skipped: state unavailable", exc_info=True)
            return
        if not info or not info.get("active"):
            return
        self._pairing_hint_at = now
        try:
            await self.client.send_text(
                message.from_user_id, _PAIRING_HINT_TEXT, token
            )
            logger.info(
                "iLink pairing hint sent: bot=%s sender=%s",
                self.bot_id,
                self._mask_sender(message.from_user_id),
            )
        except Exception:
            logger.warning("iLink pairing hint send failed", exc_info=True)

    def _pairing_failure_reason(self) -> str:
        """未绑定入站消息被丢弃时的可诊断原因（不泄露 code_hash / salt）。"""
        try:
            info = self.state_store.get_pairing_info(self.bot_id)
        except Exception:
            logger.debug("iLink pairing info unavailable", exc_info=True)
            return "pairing_state_unavailable"
        if info is None:
            return "no_pairing_code_issued"
        if not info.get("active"):
            return "pairing_code_expired_or_locked"
        return "text_did_not_match_pairing_code"

    @staticmethod
    def _mask_sender(ilink_user_id: str) -> str:
        """发送者标识脱敏，保留可关联性但不在日志里落全量 ID。"""
        raw = str(ilink_user_id or "")
        if len(raw) <= 6:
            return "***"
        return f"{raw[:3]}***{raw[-3:]}"

    @staticmethod
    def _private_finished_user_text(message: WeixinMessage) -> tuple[str | None, str]:
        """提取"已完成私聊文本"并返回 (文本, 跳过原因)。

        文本为 None 时第二个元素说明被哪一条规则过滤，供上层记录——
        这是把"连上却收不到"从不可见变成可定位的关键。
        """
        if message.message_type is not MessageType.USER:
            return None, "not_user_message"
        if message.message_state is not MessageState.FINISH or message.group_id:
            return None, "not_finished_private_message"
        text = "".join(
            item.text or ""
            for item in message.items
            if item.type is MessageItemType.TEXT
        ).strip()
        if not text:
            return None, "no_text_item"
        return text, ""

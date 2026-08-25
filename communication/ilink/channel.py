from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from communication.ilink.client import ILinkClient
from communication.ilink.models import MessageItemType, MessageState, MessageType, WeixinMessage
from communication.message import IncomingMessage
from core.ilink_state import ILinkStateStore


TextCallback = Callable[[IncomingMessage], Awaitable[object] | object]


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

    async def poll_once(self) -> None:
        current_cursor = self.state_store.get_cursor(self.bot_id)
        response = await self.client.get_updates(current_cursor)
        for message in response.messages:
            await self._handle_message(message)
        self.state_store.set_cursor(self.bot_id, response.cursor)

    async def _handle_message(self, message: WeixinMessage) -> None:
        text = self._private_finished_user_text(message)
        if text is None:
            return
        binding = self.state_store.get_binding(self.bot_id)
        if binding is None:
            self.state_store.verify_pairing(
                self.bot_id,
                message.from_user_id,
                text,
                self.primary_user_id,
            )
            return
        if message.from_user_id != binding.ilink_user_id:
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

    @staticmethod
    def _private_finished_user_text(message: WeixinMessage) -> str | None:
        if message.message_type is not MessageType.USER:
            return None
        if message.message_state is not MessageState.FINISH or message.group_id:
            return None
        text = "".join(
            item.text or ""
            for item in message.items
            if item.type is MessageItemType.TEXT
        ).strip()
        return text or None

"""Aerie · 云栖 v9.0 — NapCat OneBot11 WebSocket client.

Connects to ws://127.0.0.1:3001, parses incoming events, and sends
outbound messages via action=send_msg.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional

import websockets

from communication.message import IncomingMessage, MessageType, OutgoingReply
from config.persona_loader import load_settings


logger = logging.getLogger(__name__)


class QQClient:
    """WebSocket client for NapCat OneBot11 protocol."""

    def __init__(self, config: Optional[dict] = None) -> None:
        cfg = config or load_settings()
        qq = cfg.get("qq", {}) if isinstance(cfg, dict) else {}
        self.self_qq: int = int(qq.get("self_qq", 0))
        self.friends_qq: list[int] = [int(x) for x in qq.get("friends_qq", []) or []]
        self.ws_url: str = qq.get("napcat_ws_url", "ws://127.0.0.1:3001")
        self.access_token: str = qq.get("napcat_access_token", "")
        self._ws: Optional[Any] = None
        self._stopped = asyncio.Event()
        self._reconnect_delay = 5.0
        self._max_reconnect_delay = 30.0
        self._message_handler: Optional[Callable[[IncomingMessage], Awaitable[None]]] = None
        self._connected = False
        self._last_echo: float = 0.0

    def set_message_handler(self, handler: Callable[[IncomingMessage], Awaitable[None]]) -> None:
        self._message_handler = handler

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Open the WebSocket connection (with auto-reconnect)."""
        while not self._stopped.is_set():
            try:
                headers = []
                if self.access_token:
                    headers.append(("Authorization", f"Bearer {self.access_token}"))
                logger.info("connecting to %s", self.ws_url)
                async with websockets.connect(
                    self.ws_url,
                    extra_headers=headers,
                    ping_interval=30,
                    ping_timeout=10,
                    max_size=10 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_delay = 5.0
                    logger.info("NapCat WS connected")
                    await self._message_loop()
            except Exception as e:
                logger.warning("NapCat WS error: %s", e)
            finally:
                self._connected = False
                self._ws = None
            if self._stopped.is_set():
                break
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._max_reconnect_delay, self._reconnect_delay * 2)

    async def _message_loop(self) -> None:
        """Receive and dispatch incoming events."""
        assert self._ws is not None
        async for raw in self._ws:
            if self._stopped.is_set():
                break
            try:
                event = json.loads(raw)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            post_type = event.get("post_type", "")
            if post_type == "meta_event":
                continue
            if post_type == "message":
                await self._handle_message_event(event)
            elif post_type == "notice":
                # Group join/leave, friend add, etc. — no-op for now.
                continue

    async def _handle_message_event(self, event: dict) -> None:
        msg = IncomingMessage.from_onebot_event(event)
        if not self._message_handler:
            return
        try:
            await self._message_handler(msg)
        except Exception as e:
            logger.exception("message handler error: %s", e)

    async def _send_action(self, action: str, params: dict[str, Any]) -> dict:
        if not self._connected or not self._ws:
            return {"retcode": -1, "errmsg": "not connected"}
        payload = {"action": action, "params": params, "echo": str(time.time())}
        try:
            await self._ws.send(json.dumps(payload))
            return {"retcode": 0, "errmsg": "ok"}
        except Exception as e:
            return {"retcode": -1, "errmsg": str(e)[:200]}

    async def send_message(self, user_id: int, content: str, render_mode: str = "text") -> bool:
        """Send a private message to a user. Supports text and markdown render modes."""
        msg_type = "markdown" if render_mode == "markdown" else "text"
        result = await self._send_action(
            "send_msg",
            {
                "message_type": "private",
                "user_id": int(user_id),
                "message": [{"type": msg_type, "data": {"text": content if msg_type == "text" else "", "content": content}}],
            },
        )
        return result.get("retcode") == 0

    async def send_group_message(self, group_id: int, content: str) -> bool:
        result = await self._send_action(
            "send_msg",
            {
                "message_type": "group",
                "group_id": int(group_id),
                "message": [{"type": "text", "data": {"text": content}}],
            },
        )
        return result.get("retcode") == 0

    async def recall_message(self, message_id: int) -> bool:
        result = await self._send_action("delete_msg", {"message_id": int(message_id)})
        return result.get("retcode") == 0

    async def send_image(self, user_id: int, image_path: str) -> bool:
        """Send a local image file (uses file:// scheme)."""
        result = await self._send_action(
            "send_msg",
            {
                "message_type": "private",
                "user_id": int(user_id),
                "message": [
                    {
                        "type": "image",
                        "data": {"file": f"file:///{image_path.replace(chr(92), '/')}"},
                    }
                ],
            },
        )
        return result.get("retcode") == 0

    async def send_poke(self, user_id: int) -> bool:
        """Send a poke (戳一戳) to a user via NapCat OneBot11 friend_poke action."""
        result = await self._send_action(
            "friend_poke",
            {"user_id": int(user_id)},
        )
        return result.get("retcode") == 0

    async def send_voice(self, user_id: int, file_path: str) -> bool:
        """Send a voice (record) message to a user.

        The file should be in a format NapCat supports (Silk v3 recommended).
        """
        result = await self._send_action(
            "send_record",
            {
                "message_type": "private",
                "user_id": int(user_id),
                "file": file_path.replace("\\", "/"),
            },
        )
        return result.get("retcode") == 0

    async def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "self_qq": self.self_qq,
            "ws_url": self.ws_url,
        }

    async def stop(self) -> None:
        self._stopped.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

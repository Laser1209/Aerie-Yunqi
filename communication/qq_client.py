"""Aerie · 云栖 v9.0 — NapCat OneBot11 WebSocket client.

Connects to NapCat's OneBot11 WS server (port 3001).
Receives QQ messages, passes them to the message handler.
Sends replies back via the same WS connection.

Key change from v8: does NOT auto-start NapCat.
NapCat startup is controlled by the Electron UI panel.
"""

from __future__ import annotations
import asyncio
import json
import logging
import socket
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from communication.message import IncomingMessage, OutgoingReply

logger = logging.getLogger(__name__)

MessageHandler = Callable[[IncomingMessage], Any]


def _port_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


class QQClient:
    def __init__(self, config: dict) -> None:
        self.host = "127.0.0.1"
        self.port = int(config.get("napcat_ws_url", "ws://127.0.0.1:3001").split(":")[-1])
        # Also parse port from direct field if present
        if "ws_port" in config:
            self.port = int(config["ws_port"])
        self._handler: Optional[MessageHandler] = None
        self._running = False
        self._connected = False
        # R7.5+: bot's own QQ, learned from OneBot11 self_id field.
        self.self_id: int = 0

    @property
    def is_connected(self) -> bool:
        return self._connected and _port_is_open(self.host, self.port)

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def connect(self) -> None:
        """Connect to NapCat WS. Does NOT start NapCat — just waits for port."""
        self._running = True
        url = f"ws://{self.host}:{self.port}"

        while self._running:
            if not _port_is_open(self.host, self.port):
                await asyncio.sleep(3)
                continue

            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._connected = True
                    logger.info("QQ WS connected to %s", url)
                    # R7.5+: ask NapCat for our own login info so we know
                    # which user_id to address push messages to. Run in
                    # background — don't block the inbound event loop.
                    asyncio.create_task(self._learn_self_id())
                    await self._listen(ws)
            except Exception as e:
                logger.warning("QQ WS connection error: %s", e)
                self._connected = False
                await asyncio.sleep(5)

    async def _listen(self, ws: ClientConnection) -> None:
        """Receive and dispatch OneBot11 events."""
        try:
            async for raw in ws:
                if not self._running:
                    break
                try:
                    event = json.loads(raw)
                    await self._dispatch(event)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON WS frame: %.80s", raw)
                except Exception:
                    logger.exception("dispatch error")
        except websockets.ConnectionClosed:
            logger.info("QQ WS connection closed")
        finally:
            self._connected = False

    async def _dispatch(self, event: dict) -> None:
        """Route OneBot11 events to handler."""
        # R7.5+: every OneBot11 message event carries ``self_id``
        # (the bot's own QQ). Cache the first one we see so push
        # dispatchers can target the master without a separate
        # settings.yaml entry.
        sid = event.get("self_id")
        if sid and not self.self_id:
            self.self_id = int(sid)
            logger.info("QQ client learned self_id=%s", self.self_id)
        post_type = event.get("post_type", "")
        if post_type == "message":
            msg_type = event.get("message_type", "")
            if msg_type == "private":
                msg = IncomingMessage.from_onebot_event(event)
                logger.info(
                    "QQ <- %s %s: %.60s",
                    msg.user_id, msg.msg_type, msg.content,
                )
                if self._handler:
                    try:
                        result = self._handler(msg)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("handler error for user %s", msg.user_id)
        elif post_type == "meta_event":
            logger.debug("QQ meta: %s", event.get("meta_event_type", "?"))
        elif post_type == "notice":
            logger.debug("QQ notice: %s", event.get("notice_type", "?"))

    async def send_message(
        self, user_id: int, content: str, render_mode: str = "plain"
    ) -> bool:
        """Send a private message via NapCat OneBot11 API."""
        if not self.is_connected:
            logger.warning("Cannot send: QQ WS not connected")
            return False

        # R7.5+: tag the request with a unique echo so we can pick our
        # own response out of the inbound event stream. NapCat's
        # lifecycle meta_event is broadcast on every (re)connect and
        # would otherwise be mistaken for the send_private_msg reply.
        import uuid
        echo_tag = f"send_msg_{uuid.uuid4().hex[:12]}"
        payload = {
            "action": "send_private_msg",
            "params": {
                "user_id": user_id,
                "message": content,
            },
            "echo": echo_tag,
        }
        url = f"ws://{self.host}:{self.port}"
        try:
            async with websockets.connect(url, ping_interval=None, close_timeout=2) as ws:
                await ws.send(json.dumps(payload))
                # Walk the inbound stream until we see *our* echo or
                # we run out of patience. Skip meta_events.
                deadline = asyncio.get_event_loop().time() + 5.0
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        resp = await asyncio.wait_for(
                            ws.recv(),
                            timeout=max(0.5, deadline - asyncio.get_event_loop().time()),
                        )
                    except asyncio.TimeoutError:
                        logger.warning("QQ send timeout for user %s", user_id)
                        return False
                    data = json.loads(resp)
                    # Match by echo (preferred) or by status field.
                    if data.get("echo") == echo_tag:
                        if data.get("status") == "ok":
                            logger.info("QQ -> %s: %.80s", user_id, content)
                            return True
                        logger.warning("QQ send failed: %s", data)
                        return False
                    # Otherwise it's a meta_event / heartbeat / unrelated
                    # inbound — keep scanning.
                    logger.debug("QQ send: skip non-echo frame: %.80s", resp)
        except Exception as e:
            logger.warning("QQ send error: %s", e)
            return False

    async def _learn_self_id(self) -> None:
        """R7.5+: ask NapCat for our own login user_id.

        NapCat's OneBot11 ``get_login_info`` returns ``{"user_id": ...}``.
        We need this to address push messages back to the master before
        any inbound message arrives (which would otherwise teach us via
        the ``self_id`` field of the event payload).
        """
        # Retry a few times to ride out the WS handshake.
        for attempt in range(5):
            await asyncio.sleep(1 + attempt)
            if not self.is_connected:
                continue
            try:
                url = f"ws://{self.host}:{self.port}"
                async with websockets.connect(
                    url, ping_interval=None, close_timeout=2,
                ) as ws:
                    await ws.send(json.dumps({
                        "action": "get_login_info",
                        "params": {},
                        "echo": "learn_self_id",
                    }))
                    resp = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(resp)
                    uid = (data.get("data") or {}).get("user_id")
                    if uid:
                        self.self_id = int(uid)
                        logger.info(
                            "QQ client learned self_id=%s via get_login_info",
                            self.self_id,
                        )
                        return
            except Exception as e:
                logger.debug(
                    "get_login_info attempt %s failed: %s", attempt + 1, e,
                )
        logger.warning("QQ client could not learn self_id via get_login_info")

    async def recall_message(self, message_id: int) -> bool:
        """Recall a previously sent message via NapCat OneBot11 delete_msg.

        Args:
            message_id: OneBot11 message_id (NOT chat_log.id)
        Returns:
            True if recall succeeded
        """
        if not self.is_connected:
            logger.warning("Cannot recall: QQ WS not connected")
            return False

        payload = {
            "action": "delete_msg",
            "params": {"message_id": int(message_id)},
        }
        url = f"ws://{self.host}:{self.port}"
        try:
            async with websockets.connect(url, ping_interval=None, close_timeout=2) as ws:
                await ws.send(json.dumps(payload))
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(resp)
                    if data.get("status") == "ok":
                        logger.info("QQ recalled message_id=%s", message_id)
                        return True
                    logger.warning("QQ recall failed: %s", data)
                    return False
                except asyncio.TimeoutError:
                    logger.warning("QQ recall timeout for message_id=%s", message_id)
                    return False
        except Exception as e:
            logger.warning("QQ recall error: %s", e)
            return False

    async def send_poke(self, user_id: int) -> bool:
        """Send a poke (戳一戳) to a user via NapCat OneBot11."""
        if not self.is_connected:
            return False
        payload = {
            "action": "send_poke",
            "params": {"user_id": int(user_id), "type": "私人"},
        }
        url = f"ws://{self.host}:{self.port}"
        try:
            async with websockets.connect(url, ping_interval=None, close_timeout=2) as ws:
                await ws.send(json.dumps(payload))
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(resp)
                    return data.get("status") == "ok"
                except asyncio.TimeoutError:
                    return False
        except Exception:
            return False

    async def send_message_with_segments(
        self,
        user_id: int,
        segments: list[dict],
        render_mode: str = "array",
    ) -> bool:
        """Send a private message composed of message segments (OneBot11 message array).

        Example segments:
          [{"type": "reply", "data": {"id": 12345}},
           {"type": "text", "data": {"text": "我也在想你"}}]
        """
        if not self.is_connected:
            return False

        payload = {
            "action": "send_private_msg",
            "params": {"user_id": int(user_id), "message": segments},
        }
        url = f"ws://{self.host}:{self.port}"
        try:
            async with websockets.connect(url, ping_interval=None, close_timeout=2) as ws:
                await ws.send(json.dumps(payload))
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(resp)
                    if data.get("status") == "ok":
                        # data.data.message_id is the new OneBot11 message_id
                        msg_id = (data.get("data") or {}).get("message_id")
                        return True
                    return False
                except asyncio.TimeoutError:
                    return False
        except Exception as e:
            logger.warning("QQ segments send error: %s", e)
            return False

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        logger.info("QQ client stopped")

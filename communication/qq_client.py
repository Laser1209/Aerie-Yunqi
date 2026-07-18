"""Aerie · 云栖 v13.9.8 — NapCat OneBot11 WebSocket client.

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
import re
import socket
import uuid
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from communication.message import IncomingMessage

logger = logging.getLogger(__name__)

MessageHandler = Callable[[IncomingMessage], Any]
StateHandler = Callable[[str], Any]

STATE_DISCONNECTED = "disconnected"
STATE_WS_CONNECTED = "ws_connected"
STATE_LOGGED_IN = "logged_in"

# ── v13.9: thought/action 标签过滤 ──

def strip_thought_action_tags(text: str) -> str:
    """移除 <thought> 和 <action> 标签及其内容，QQ 只输出纯对话文本。"""
    if not text:
        return text
    # 移除 <thought>...</thought>（支持跨行）
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # 移除 <action>...</action>（支持跨行）
    text = re.sub(r'<action>.*?</action>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # 清理多余空行（连续多个换行合并为 2 个以内）
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 清理首尾空白
    text = text.strip()
    return text


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
        # R8.1+: QQ account login state. ``_connected`` only reflects the
        # WS layer (backend <-> NapCat); ``_logged_in`` reflects whether
        # the QQ account is actually online (NapCat <-> Tencent server).
        # Without this distinction, proactive pushes (boot_greeting etc.)
        # get "ghost-sent" while QQ is still logging in.
        self._logged_in = False
        self._login_event = asyncio.Event()
        # R7.5+: bot's own QQ, learned from OneBot11 self_id field.
        self.self_id: int = 0
        # v13.9: QQ whitelist manager (injected later via setter)
        self._whitelist = None
        # R9.0+: state machine + change callbacks
        self._state = STATE_DISCONNECTED
        self._state_handlers: list[StateHandler] = []

    def set_whitelist(self, whitelist_manager) -> None:
        """设置白名单管理器。"""
        self._whitelist = whitelist_manager

    def update_config(self, config: dict) -> None:
        """Hot-reload QQ client config (port, host, etc.).

        Note: changing port won't affect an already-established connection.
        The new config will be used on the next reconnect.
        """
        new_port = int(config.get("napcat_ws_url", f"ws://127.0.0.1:{self.port}").split(":")[-1])
        if "ws_port" in config:
            new_port = int(config["ws_port"])
        if new_port != self.port:
            logger.info("QQ client config updated: port %s -> %s (will take effect on next reconnect)", self.port, new_port)
            self.port = new_port
        else:
            logger.debug("QQ client config unchanged (port=%s)", self.port)

    @property
    def is_connected(self) -> bool:
        return self._connected and _port_is_open(self.host, self.port)

    @property
    def is_logged_in(self) -> bool:
        """True only when the QQ account is actually online.

        Distinct from ``is_connected`` (which only means the WS link to
        NapCat is up). ``is_logged_in`` becomes True after either:
          - ``get_login_info`` RPC succeeds (NapCat can reach Tencent), or
          - a OneBot11 ``lifecycle.connect`` meta_event arrives.
        Use this (or :meth:`wait_for_login`) before proactive pushes so
        they don't get ghost-sent during QQ login warm-up.
        """
        return self._logged_in and self.is_connected

    @property
    def state(self) -> str:
        """Current QQ client state: "disconnected" | "ws_connected" | "logged_in"."""
        return self._state

    def on_state_change(self, handler: StateHandler) -> None:
        """Register a callback invoked on every state transition.

        The handler receives the new state string. Exceptions in handlers
        are caught and logged so one bad handler doesn't break the chain.
        """
        self._state_handlers.append(handler)

    def _emit_state(self, new_state: str) -> None:
        """Transition to a new state and notify handlers if changed."""
        if new_state == self._state:
            return
        old_state = self._state
        self._state = new_state
        logger.info("QQ state: %s -> %s", old_state, new_state)
        for h in self._state_handlers:
            try:
                result = h(new_state)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                logger.exception("state handler error for state=%s", new_state)

    async def wait_until_ready(self, timeout: float = 30.0) -> bool:
        """Block until QQ is fully logged in, or until timeout.

        Alias of :meth:`wait_for_login` with a longer default timeout
        suitable for startup-phase waiting. Returns True if ready within
        the deadline, False on timeout.
        """
        return await self.wait_for_login(timeout=timeout)

    async def wait_for_login(self, timeout: float = 15.0) -> bool:
        """Block until QQ account is logged in, or until ``timeout``.

        Returns True if logged in within the deadline, False on timeout.
        Proactive callers (boot_greeting, scheduled pushes) should use
        this instead of a fixed ``sleep`` so they don't fire while NapCat
        is still handshaking with Tencent servers.
        """
        if self.is_logged_in:
            return True
        try:
            await asyncio.wait_for(self._login_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self.is_logged_in

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
                    # R8.1+: every (re)connect must re-confirm QQ login.
                    # The WS link being up says nothing about whether the
                    # QQ account is online on the Tencent side, and a
                    # reconnect may happen after a QQ re-login. Clear the
                    # flag so wait_for_login callers block until the next
                    # lifecycle connect / get_login_info success.
                    self._logged_in = False
                    self._login_event.clear()
                    self._emit_state(STATE_WS_CONNECTED)
                    logger.info("QQ WS connected to %s", url)
                    # R7.5+: ask NapCat for our own login info so we know
                    # which user_id to address push messages to. Run in
                    # background — don't block the inbound event loop.
                    asyncio.create_task(self._learn_self_id())
                    await self._listen(ws)
            except Exception as e:
                logger.warning("QQ WS connection error: %s", e)
                self._connected = False
                self._logged_in = False
                self._login_event.clear()
                self._emit_state(STATE_DISCONNECTED)
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
            self._logged_in = False
            self._login_event.clear()
            self._emit_state(STATE_DISCONNECTED)

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
                # v13.9: QQ whitelist check
                if self._whitelist and not self._whitelist.is_allowed(msg.user_id):
                    logger.debug(
                        "QQ user %s not in whitelist, skipped",
                        msg.user_id,
                    )
                    return
                # 更新最后消息时间
                if self._whitelist:
                    self._whitelist.update_last_message(msg.user_id)
                if self._handler:
                    try:
                        result = self._handler(msg)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("handler error for user %s", msg.user_id)
        elif post_type == "meta_event":
            meta_type = event.get("meta_event_type", "")
            sub_type = event.get("sub_type", "")
            # R8.1+: lifecycle.connect is NapCat's "QQ account is online"
            # signal. It fires after a successful QQ login (and on every
            # OneBot11 (re)connect that follows). Treat it as a reliable
            # login-ready signal so wait_for_login callers can proceed.
            if meta_type == "lifecycle" and sub_type == "connect":
                if not self._logged_in:
                    self._logged_in = True
                    self._login_event.set()
                    self._emit_state(STATE_LOGGED_IN)
                    logger.info(
                        "QQ lifecycle connect: account online (self_id=%s)",
                        self.self_id or "?",
                    )
            logger.debug("QQ meta: %s/%s", meta_type, sub_type)
        elif post_type == "notice":
            logger.debug("QQ notice: %s", event.get("notice_type", "?"))

    async def send_message(
        self, user_id: int, content: str, render_mode: str = "plain"
    ) -> bool:
        """Send a private message via NapCat OneBot11 API."""
        if not self.is_connected:
            logger.warning("Cannot send: QQ WS not connected")
            return False

        # v13.9: 过滤 thought/action 标签，QQ 只输出纯对话文本
        content = strip_thought_action_tags(content)
        if not content:
            logger.warning("QQ send: content empty after stripping tags, skip")
            return False

        # R7.5+: tag the request with a unique echo so we can pick our
        # own response out of the inbound event stream. NapCat's
        # lifecycle meta_event is broadcast on every (re)connect and
        # would otherwise be mistaken for the send_private_msg reply.
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

    async def _rpc_call(
        self, action: str, params: dict, timeout: float = 5.0
    ) -> dict | None:
        """Send a OneBot11 RPC on a fresh WS, loop recv until echo match.

        NapCat pushes lifecycle/heartbeat events on every new WS connection.
        We must loop recv() and skip non-matching frames (like send_message
        does), otherwise the first frame received is a lifecycle event, not
        our RPC reply.

        Returns the full response dict (with echo/status/data fields), or
        None on timeout/failure. Caller is responsible for checking
        status/data.
        """
        if not self.is_connected:
            return None
        echo_tag = f"rpc_{uuid.uuid4().hex[:12]}"
        payload = {"action": action, "params": params, "echo": echo_tag}
        url = f"ws://{self.host}:{self.port}"
        try:
            async with websockets.connect(
                url, ping_interval=None, close_timeout=2,
            ) as ws:
                await ws.send(json.dumps(payload))
                deadline = asyncio.get_event_loop().time() + timeout
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        resp = await asyncio.wait_for(
                            ws.recv(),
                            timeout=max(0.5, deadline - asyncio.get_event_loop().time()),
                        )
                    except asyncio.TimeoutError:
                        return None
                    data = json.loads(resp)
                    if data.get("echo") == echo_tag:
                        return data
                    # skip non-echo frames (lifecycle/heartbeat/unrelated)
                    logger.debug("RPC %s: skip non-echo frame: %.80s", action, resp)
        except Exception as e:
            logger.debug("RPC %s failed: %s", action, e)
            return None
        return None

    async def _learn_self_id(self) -> None:
        """R7.5+: ask NapCat for our own login user_id.

        NapCat's OneBot11 ``get_login_info`` returns ``{"user_id": ...}``.
        We need this to address push messages back to the master before
        any inbound message arrives (which would otherwise teach us via
        the ``self_id`` field of the event payload).
        """
        # Retry a few times to ride out the WS handshake. Each retry uses
        # _rpc_call which loops recv() and matches by echo, so lifecycle
        # events pushed by NapCat on each new WS connect are skipped.
        for attempt in range(5):
            await asyncio.sleep(1 + attempt)
            if not self.is_connected:
                continue
            resp = await self._rpc_call("get_login_info", {}, timeout=3)
            if resp is None:
                continue
            uid = (resp.get("data") or {}).get("user_id")
            if uid:
                self.self_id = int(uid)
                # R8.1+: a successful get_login_info means NapCat can
                # reach Tencent — QQ is logged in. Signal the login event
                # so wait_for_login callers proceed.
                if not self._logged_in:
                    self._logged_in = True
                    self._login_event.set()
                    self._emit_state(STATE_LOGGED_IN)
                logger.info(
                    "QQ client learned self_id=%s via get_login_info",
                    self.self_id,
                )
                return
            logger.debug(
                "get_login_info attempt %s: no user_id in resp", attempt + 1,
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
        resp = await self._rpc_call(
            "delete_msg", {"message_id": int(message_id)}, timeout=5,
        )
        if resp is None:
            logger.warning("QQ recall timeout for message_id=%s", message_id)
            return False
        if resp.get("status") == "ok":
            logger.info("QQ recalled message_id=%s", message_id)
            return True
        logger.warning("QQ recall failed: %s", resp)
        return False

    async def send_poke(self, user_id: int) -> bool:
        """Send a poke (戳一戳) to a user via NapCat OneBot11."""
        if not self.is_connected:
            return False
        resp = await self._rpc_call(
            "send_poke", {"user_id": int(user_id), "type": "私人"}, timeout=3,
        )
        if resp is None:
            return False
        return resp.get("status") == "ok"

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

        # v13.9: 过滤 text 类型 segment 中的 thought/action 标签
        # 非 text 类型（image/face/reply 等）一律保留，不做过滤
        cleaned_segments = []
        has_usable_content = False
        for seg in segments:
            if seg.get("type") == "text" and "text" in (seg.get("data") or {}):
                cleaned = strip_thought_action_tags(seg["data"]["text"])
                cleaned_segments.append({**seg, "data": {**seg["data"], "text": cleaned}})
                if cleaned:
                    has_usable_content = True
            else:
                cleaned_segments.append(seg)
                has_usable_content = True
        if not has_usable_content:
            logger.warning("QQ segments send: no usable content after stripping tags, skip")
            return False

        resp = await self._rpc_call(
            "send_private_msg",
            {"user_id": int(user_id), "message": cleaned_segments},
            timeout=5,
        )
        if resp is None:
            return False
        if resp.get("status") == "ok":
            # data.data.message_id is the new OneBot11 message_id
            # (currently logged for debugging; not consumed by caller)
            _msg_id = (resp.get("data") or {}).get("message_id")
            return True
        return False

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        self._logged_in = False
        self._login_event.clear()
        self._emit_state(STATE_DISCONNECTED)
        logger.info("QQ client stopped")

"""Aerie · 云栖 v0.1.0-beta.1 — NapCat OneBot11 WebSocket client.

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
import os
import secrets
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from communication.message import IncomingMessage
from core.model_output import sanitize_outbound_text

logger = logging.getLogger(__name__)

MessageHandler = Callable[[IncomingMessage], Any]
StateHandler = Callable[[str], Any]

STATE_DISCONNECTED = "disconnected"
STATE_WS_CONNECTED = "ws_connected"
STATE_LOGGED_IN = "logged_in"

# 携带媒体段的私聊消息要等 NapCat 先上传完才回响应，用长超时；纯文本 5s 足够。
# 与 send_file 的 60s 取同一口径：都是"上传完才回话"的操作。
_SEGMENT_UPLOAD_TIMEOUT_SEC = 60

# 输出端清洗统一由 core.model_output 提供（唯一实现，所有通道共用）：
#   - strip_thought_action_tags：剥 <thought>/<action> 标签
#   - sanitize_outbound_text    ：出站唯一闸门（标签 + 历史元信息标记 + 伪图片语法）
# 此前 QQ 本地维护了 4 个剥离函数、iLink 一个都没有，两套实现各自演进，
# 于是"桌面端正常、QQ/微信端露标记"的同类 bug 反复复发（2026-09-27）。
# 正则不再在本地复制。


def _port_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def _qq_disabled_by_env() -> bool:
    return os.environ.get("AERIE_DISABLE_QQ", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _qq_connectivity_test_by_env() -> bool:
    return os.environ.get("AERIE_QQ_CONNECTIVITY_TEST", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        self._disabled = _qq_disabled_by_env()
        self._connectivity_test = _qq_connectivity_test_by_env()
        # 断连探测：独立 WS 存活心跳（周期性发 get_login_info 探活）。
        # 半开/静默断开时不再依赖 _listen 抛异常，而是由心跳主动判定并强制重连。
        self._heartbeat_interval = float(config.get("heartbeat_interval", 30))
        self._heartbeat_timeout = float(config.get("heartbeat_timeout", 10))
        self._probe_echo: str | None = None
        self._probe_event = asyncio.Event()
        self._heartbeat_log: Optional[Callable[[str], None]] = None
        self._force_reconnect: bool = False
        # 主动拉起 NapCat：等待端口超过阈值仍未就绪时，尝试经 launcher 拉起，
        # 用 backoff 防重复 spawn（launcher.start 自身也有 already-running 守卫）。
        self._port_wait_started: float | None = None
        self._launch_backoff_until: float = 0.0
        self._port_wait_threshold = float(config.get("proactive_launch_wait", 15))
        self._launch_backoff_sec = float(config.get("proactive_launch_backoff", 60))

    @property
    def connectivity_test(self) -> bool:
        """Whether this process is restricted to QQ connectivity checks."""
        return self._connectivity_test

    def set_whitelist(self, whitelist_manager) -> None:
        """设置白名单管理器。"""
        self._whitelist = whitelist_manager

    def set_heartbeat_log(self, callback: Callable[[str], None] | None) -> None:
        """Register a sink for heartbeat liveness lines (shown in the Status page running-log box)."""
        self._heartbeat_log = callback

    def _emit_heartbeat(self, text: str) -> None:
        """Forward a heartbeat liveness line to the Status page running-log sink."""
        if self._heartbeat_log is not None:
            try:
                self._heartbeat_log(text)
            except Exception:
                logger.exception("heartbeat log sink failed")

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
        if self._disabled:
            return False
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
        """Connect to NapCat WS. Waits for the port, proactively launching NapCat
        via the launcher if the port stays closed too long."""
        if self._disabled:
            logger.info("QQ client disabled by AERIE_DISABLE_QQ")
            self._running = False
            self._emit_state(STATE_DISCONNECTED)
            return
        self._running = True
        url = f"ws://{self.host}:{self.port}"

        while self._running:
            if not _port_is_open(self.host, self.port):
                await self._maybe_launch_napcat()
                await asyncio.sleep(3)
                continue

            self._port_wait_started = None  # port is up, stop waiting
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=3,
                ) as ws:
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

    async def _maybe_launch_napcat(self) -> None:
        """Proactively launch NapCat if the WS port has been closed too long.

        Tracks how long we have been waiting for the port; after
        ``_port_wait_threshold`` seconds it asks the launcher to start
        NapCat (only if not already running), then backs off for
        ``_launch_backoff_sec`` to avoid a respawn storm. This covers the
        case where NapCat died and nobody restarted it — the backend
        triggers the recovery itself instead of waiting forever.
        """
        now = time.monotonic()
        if self._port_wait_started is None:
            self._port_wait_started = now
            return
        if now - self._port_wait_started < self._port_wait_threshold:
            return
        if now < self._launch_backoff_until:
            return
        self._launch_backoff_until = now + self._launch_backoff_sec
        # Reset so the next cycle re-triggers only after another threshold window.
        self._port_wait_started = None
        logger.info(
            "QQ WS port %s closed for > %.0fs, proactively launching NapCat",
            self.port, self._port_wait_threshold,
        )
        try:
            from core.napcat_launcher import get_launcher

            launcher = get_launcher()
            if launcher.user_stopped:
                # The user explicitly stopped NapCat; never relaunch it behind
                # their back. A manual start clears the latch.
                self._port_wait_started = None
                return
            result = await launcher.start()
            logger.info("QQ proactive NapCat launch result: %s", result.get("ok"))
        except Exception:
            logger.exception("QQ proactive NapCat launch failed")

    async def _listen(self, ws: ClientConnection) -> None:
        """Receive and dispatch OneBot11 events.

        使用 recv 带 1s 超时的轮询循环，确保本协程永不卡死在半开连接上：
        - 心跳判定连接死亡时会置 _force_reconnect，本循环 1s 内可见并退出，
          从而触发 connect() 外层循环重连（不依赖 WS close 握手完成）。
        - 心跳探活的 echo 回包在此匹配确认存活，不派发。
        """
        self._probe_echo = None
        self._probe_event = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(ws))
        try:
            while self._running:
                if self._force_reconnect:
                    logger.info("QQ WS dead detected; tearing down to reconnect")
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    logger.info("QQ WS connection closed")
                    break
                except Exception:
                    logger.exception("QQ WS recv error")
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON WS frame: %.80s", raw)
                    continue
                # 心跳探活回包：与 _heartbeat 的 echo 匹配即确认存活，不派发
                if self._probe_echo is not None and event.get("echo") == self._probe_echo:
                    self._probe_echo = None
                    self._probe_event.set()
                    continue
                try:
                    await self._dispatch(event)
                except Exception:
                    logger.exception("dispatch error")
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._force_reconnect = False
            self._connected = False
            self._logged_in = False
            self._login_event.clear()
            self._emit_state(STATE_DISCONNECTED)

    async def _heartbeat(self, ws: ClientConnection) -> None:
        """独立存活心跳：周期性向 NapCat 发 get_login_info 探活。

        若在超时内未收到对应 echo 回包，判定 WS 半开/静默断开，
        仅置 _force_reconnect 标志（不在此处 close 连接），由 _listen
        的轮询循环 1s 内感知并收尾退出，从而触发 connect() 重连。
        心跳结果（正常/超时）会同步到状态页「运行日志」黑框。
        """
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)
            if not self._connected or self._force_reconnect:
                continue
            echo = f"hb_{secrets.token_hex(8)}"
            self._probe_echo = echo
            self._probe_event.clear()
            try:
                await ws.send(json.dumps({"action": "get_login_info", "echo": echo}))
            except Exception as exc:
                logger.warning("QQ heartbeat send failed (%s), forcing reconnect", exc)
                self._emit_heartbeat("QQ 心跳发送失败，强制重连")
                self._force_reconnect = True
                return
            try:
                await asyncio.wait_for(self._probe_event.wait(), timeout=self._heartbeat_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "QQ heartbeat timeout: no get_login_info reply within %.0fs, "
                    "WS likely dead, forcing reconnect",
                    self._heartbeat_timeout,
                )
                self._emit_heartbeat(
                    f"QQ 心跳超时（{int(self._heartbeat_timeout)}s 无响应），WS 疑似断开，强制重连"
                )
                self._force_reconnect = True
                return
            logger.info("QQ heartbeat OK: get_login_info replied")
            self._emit_heartbeat("QQ 心跳正常")

    async def _dispatch(self, event: dict) -> None:
        """Route OneBot11 events to handler."""
        post_type = event.get("post_type", "")
        if self._connectivity_test and post_type in {"message", "notice", "request"}:
            logger.debug("QQ connectivity test discarded non-meta event")
            return
        # R7.5+: every OneBot11 message event carries ``self_id``
        # (the bot's own QQ). Cache the first one we see so push
        # dispatchers can target the master without a separate
        # settings.yaml entry.
        sid = event.get("self_id")
        if sid and not self.self_id:
            self.self_id = int(sid)
            logger.info("QQ client learned self_id=%s", self.self_id)
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
        if self._disabled or self._connectivity_test:
            logger.info("QQ send skipped by process safety mode")
            return False
        if not self.is_connected:
            logger.warning("Cannot send: QQ WS not connected")
            return False

        # v13.9: 出站唯一闸门——剥 thought/action 标签、剥模型回显的历史元信息
        # 标记（时间戳 / [桌面] 等跨通道前缀）、剥伪图片 markdown。QQ 只输出纯对话文本。
        content = sanitize_outbound_text(content)
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
                            # Quote V2: return the platform message_id so the
                            # caller can backfill chat_log.qq_message_id.
                            mid = (data.get("data") or {}).get("message_id")
                            return int(mid) if mid else True
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
        if self._connectivity_test and action != "get_login_info":
            logger.info("QQ mutating RPC skipped by connectivity test mode")
            return None
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
                if self._connectivity_test:
                    logger.info("QQ connectivity test confirmed login identity")
                else:
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
        if self._disabled or self._connectivity_test:
            logger.info("QQ recall skipped by process safety mode")
            return False
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

    async def get_msg(self, message_id: int, timeout: float = 8.0) -> dict | None:
        """Fetch a single message's raw content via OneBot11 ``get_msg``.

        Used to resolve inbound quotes whose quoted message is not stored in
        chat_log (e.g. the user quotes a message the bot never persisted).
        Returns the full response dict (``data.message`` holds the segment
        array) or None on failure.
        """
        if self._disabled or not self.is_connected:
            return None
        return await self._rpc_call(
            "get_msg", {"message_id": int(message_id)}, timeout=timeout,
        )

    async def send_poke(self, user_id: int) -> bool:
        """Send a poke (戳一戳) to a user via NapCat OneBot11."""
        if self._disabled or self._connectivity_test:
            logger.info("QQ poke skipped by process safety mode")
            return False
        if not self.is_connected:
            return False
        resp = await self._rpc_call(
            "send_poke", {"user_id": int(user_id), "type": "私人"}, timeout=3,
        )
        if resp is None:
            return False
        return resp.get("status") == "ok"

    async def get_record(self, file: str, out_format: str = "mp3", timeout: float = 25.0) -> dict | None:
        """Fetch a voice message file via NapCat OneBot11 ``get_record``.

        NapCat downloads the QQ silk voice and transcodes it (via its bundled
        silk/ffmpeg) into ``out_format``. Returns the raw RPC response whose
        ``data.file`` is a local path (or base64 when remote). ``file`` is the
        ``data.file`` of an incoming ``[CQ:record]`` segment.
        """
        if not self.is_connected:
            return None
        return await self._rpc_call(
            "get_record",
            {"file": str(file), "out_format": out_format},
            timeout=timeout,
        )

    async def get_image(self, file: str, timeout: float = 25.0) -> dict | None:
        """Fetch an image/sticker local file via NapCat OneBot11 ``get_image``.

        ``file`` is the ``data.file`` of an incoming ``[CQ:image]`` segment.
        On success ``data.file`` is a local path (or base64 when remote) and
        ``data.url`` is a downloadable URL.
        """
        if not self.is_connected:
            return None
        return await self._rpc_call("get_image", {"file": str(file)}, timeout=timeout)

    async def fetch_custom_face(self, count: int = 48, timeout: float = 25.0) -> list[str]:
        """Fetch the account's favorite/custom stickers via NapCat ``fetch_custom_face``.

        Returns a list of sticker URLs. ``count`` caps how many are returned
        (NapCat default 48). On failure returns an empty list so callers can
        degrade gracefully.
        """
        if not self.is_connected:
            return []
        resp = await self._rpc_call(
            "fetch_custom_face", {"count": int(count)}, timeout=timeout
        )
        if not resp or resp.get("status") != "ok":
            return []
        data = resp.get("data") or []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if str(x).strip()]

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
        if self._disabled or self._connectivity_test:
            logger.info("QQ segmented send skipped by process safety mode")
            return False
        if not self.is_connected:
            return False

        # 出站唯一闸门：text 段同样过清洗，非 text 段（image/face/reply）原样保留
        cleaned_segments = []
        has_usable_content = False
        for seg in segments:
            if seg.get("type") == "text" and "text" in (seg.get("data") or {}):
                cleaned = sanitize_outbound_text(seg["data"]["text"])
                cleaned_segments.append({**seg, "data": {**seg["data"], "text": cleaned}})
                if cleaned:
                    has_usable_content = True
            else:
                cleaned_segments.append(seg)
                has_usable_content = True
        if not has_usable_content:
            logger.warning("QQ segments send: no usable content after stripping tags, skip")
            return False

        # 超时按内容定：image/file 段要先上传到腾讯服务器才回响应，纯文本则是即时的。
        # 实测 2026-09-28：3.3 MB 配图首发耗时超过 5s，RPC 在 5s 处放弃等待，
        # 于是 send_image 返回 False、上层记成"未确认投递"——而消息其实已经送达
        # （用户截图可见）。这与 send_file 用 60s 处理同类上传是同一条道理，
        # 这里补齐，避免把"慢"误报成"失败"。
        needs_upload = any(
            seg.get("type") in ("image", "file", "record", "video")
            for seg in cleaned_segments
        )
        resp = await self._rpc_call(
            "send_private_msg",
            {"user_id": int(user_id), "message": cleaned_segments},
            timeout=_SEGMENT_UPLOAD_TIMEOUT_SEC if needs_upload else 5,
        )
        if resp is None:
            return False
        if resp.get("status") == "ok":
            # Quote V2: return the platform message_id so callers can
            # backfill chat_log.qq_message_id (reply segments reference
            # this id). Falls back to True when NapCat omits message_id.
            mid = (resp.get("data") or {}).get("message_id")
            return int(mid) if mid else True
        return False

    async def send_image(self, user_id: int, image_ref: str, caption: str = "") -> bool:
        """Send a single image (optionally with a caption) to a QQ private user.

        ``image_ref`` is passed to OneBot11's image ``file`` field: an
        absolute local path, a ``file://`` URI, or an http(s) URL NapCat can
        fetch.  Safe to call while QQ is offline — it returns False instead
        of raising, so proactive deliveries degrade gracefully.
        """
        if self._disabled or self._connectivity_test:
            logger.info("QQ send_image skipped by process safety mode")
            return False
        if not self.is_connected:
            logger.warning("Cannot send image: QQ WS not connected")
            return False

        segments: list[dict] = []
        caption_clean = sanitize_outbound_text(caption or "")
        if caption_clean:
            segments.append({"type": "text", "data": {"text": caption_clean}})
        segments.append({"type": "image", "data": {"file": image_ref}})
        return await self.send_message_with_segments(int(user_id), segments)

    async def send_file(self, user_id: int, file_path: str, name: str = "") -> bool:
        """Send a local file to a QQ private user via ``upload_private_file``.

        ``file_path`` must be an absolute local path readable by NapCat.
        ``name`` overrides the name the receiver sees (defaults to the
        on-disk basename). Returns False instead of raising when QQ is
        offline or the file is missing, so deliveries degrade gracefully.
        """
        if self._disabled or self._connectivity_test:
            logger.info("QQ send_file skipped by process safety mode")
            return False
        if not self.is_connected:
            logger.warning("Cannot send file: QQ WS not connected")
            return False

        path = Path(file_path)
        if not path.is_file():
            logger.warning("Cannot send file: not found: %s", file_path)
            return False

        resp = await self._rpc_call(
            "upload_private_file",
            {
                "user_id": int(user_id),
                "file": str(path.resolve()),
                "name": str(name or path.name),
            },
            timeout=60,
        )
        if resp is None:
            return False
        return resp.get("status") == "ok"

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        self._logged_in = False
        self._login_event.clear()
        self._emit_state(STATE_DISCONNECTED)
        logger.info("QQ client stopped")

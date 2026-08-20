"""Aerie · 云栖 — QQ 接入客户端（自研 OneBot11 协议的 Aerie 语义包装层）。

协议层为自研实现 :class:`communication.onebot11.client.OneBot11Client`，
本模块在其之上附加 Aerie 业务语义：

- 保留业务层全部对外接口（send_message / send_image / send_poke / recall / ...）。
- 输出端兜底清洗：``<thought>/<action>`` 标签、对话时间戳、伪图片 markdown。
- QQ 白名单、登录态闸门、心跳运行日志、引擎进程主动拉起。

协议层不感知业务（无白名单/无清洗/无引擎拉起），业务层不感知协议细节。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Callable, Optional

from communication.message import IncomingMessage
from communication.onebot11 import actions as A
from communication.onebot11 import messages as M
from communication.onebot11.client import (
    OneBot11Client,
    STATE_DISCONNECTED,
    STATE_WS_CONNECTED,
    STATE_LOGGED_IN,
)

logger = logging.getLogger(__name__)

MessageHandler = Callable[[IncomingMessage], Any]
StateHandler = Callable[[str], Any]


# ── 输出端清洗（发送前统一执行）────────────────────────

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


# 输出端兜底：剥离 LLM 回显的对话历史时间戳标记（开头/中间、带空格/不带、
# 带年份/带秒），仅保留正文。与 core.pipeline._HIST_LABEL_RE 保持一致，确保
# 任何来源（含主动消息/陪伴通道）发往 QQ 的内容都不漏 `[MM-DD HH:MM]`。
_TIMESTAMP_MARKER_RE = re.compile(
    r"\[\d{2,4}-\d{2}(?:-\d{2})? ?\d{2}:\d{2}(?::\d{2})?\]\s*"
)


def strip_timestamp_markers(text: str) -> str:
    if not text:
        return text
    return _TIMESTAMP_MARKER_RE.sub("", text).strip()


# 伪图片 markdown 过滤（P4 兜底）：LLM 偶发把"生图提示词"写进回复文本，形如
# `[图片](一张局部特写。昏暗的光线下…)` 或 `![图片](描述)`。这些是给后台生图系统的
# 输入，不该出现在 QQ 文本里。正则只剥 `[图片](...)` / `![图片](...)` 且括号内
# **不是合法 http(s) URL** 的片段——真实图片消息 `![图片](http://127.0.0.1:7890/...)`
# 是附件渲染语法，不受影响。与 strip_timestamp_markers 同为输出端兜底。
_FAKE_IMAGE_MARKDOWN_RE = re.compile(
    r"!?\[图片\]\((?!https?://)(?![^)]*https?://)[^)]*\)"
)


def strip_fake_image_markdown(text: str) -> str:
    """剥除 LLM 误写的伪图片 markdown（`[图片](描述)` / `![图片](描述)`）。

    仅匹配完整语法形态（含括号与"图片"字样），不误伤裸词"图片"；
    括号内含 http(s) URL 的真实图片语法被负向前瞻排除，保留不动。
    """
    if not text:
        return ""
    cleaned = _FAKE_IMAGE_MARKDOWN_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _port_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with __import__("socket").create_connection((host, port), timeout=timeout):
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
    """QQ 接入客户端（Aerie 业务语义层，协议内核为自研 OneBot11Client）。

    Args:
        config: 来自 settings.yaml ``qq`` 段。支持键：
            ws_url / ws_port（引擎 WS 地址）、token（鉴权令牌）、
            heartbeat_interval / heartbeat_timeout（心跳）、
            proactive_launch_wait / proactive_launch_backoff（端口长期未开时拉起引擎）。
    """

    def __init__(self, config: dict) -> None:
        self.host = "127.0.0.1"
        self.port = int(config.get("ws_url", "ws://127.0.0.1:3001").split(":")[-1])
        # Also parse port from direct field if present
        if "ws_port" in config:
            self.port = int(config["ws_port"])

        engine = OneBot11Client(
            host=self.host,
            port=self.port,
            token=str(config.get("token", "") or ""),
            heartbeat_interval=float(config.get("heartbeat_interval", 30)),
            heartbeat_timeout=float(config.get("heartbeat_timeout", 10)),
        )
        # 状态迁移（登录闸门/前端状态）由 SDK 统一管理，这里透传
        engine.on_state_change(self._on_engine_state_change)
        engine.on_event(self._on_engine_event)
        self._engine = engine

        self._handler: Optional[MessageHandler] = None
        self._state_handlers: list[StateHandler] = []
        self._whitelist = None
        self._disabled = _qq_disabled_by_env()
        self._connectivity_test = _qq_connectivity_test_by_env()

        # 引擎主动拉起：端口关闭超过阈值后尝试经 QQ 网关拉起，带 backoff。
        self._port_wait_started: float | None = None
        self._launch_backoff_until: float = 0.0
        self._port_wait_threshold = float(config.get("proactive_launch_wait", 15))
        self._launch_backoff_sec = float(config.get("proactive_launch_backoff", 60))

    # ── 只读状态（兼容既有调用点）────────────────────────

    @property
    def connectivity_test(self) -> bool:
        """Whether this process is restricted to QQ connectivity checks."""
        return self._connectivity_test

    @property
    def is_connected(self) -> bool:
        return self._engine.connected

    @property
    def is_logged_in(self) -> bool:
        """True only when the QQ account is actually online (engine ⇄ Tencent)."""
        return self._engine.logged_in

    @property
    def state(self) -> str:
        """Current QQ client state: "disconnected" | "ws_connected" | "logged_in"."""
        return self._engine.state

    @property
    def self_id(self) -> int:
        """Bot's own QQ, learned from the engine (self_id / get_login_info)."""
        return self._engine.self_id

    # ── 配置/依赖注入 ─────────────────────────────────────

    def set_whitelist(self, whitelist_manager) -> None:
        """设置白名单管理器。"""
        self._whitelist = whitelist_manager

    def set_heartbeat_log(self, callback: Callable[[str], None] | None) -> None:
        """Register a sink for heartbeat liveness lines (Status page running-log box)."""
        self._engine.set_heartbeat_log(callback)

    def update_config(self, config: dict) -> None:
        """Hot-reload QQ client config (port, token, etc.).

        Note: changing port won't affect an already-established connection.
        The new config will be used on the next reconnect.
        """
        new_port = int(config.get("ws_url", f"ws://127.0.0.1:{self.port}").split(":")[-1])
        if "ws_port" in config:
            new_port = int(config["ws_port"])
        if new_port != self.port:
            logger.info("QQ client config updated: port %s -> %s (will take effect on next reconnect)", self.port, new_port)
            self.port = new_port
            self._engine.port = new_port
        else:
            logger.debug("QQ client config unchanged (port=%s)", self.port)

    def on_state_change(self, handler: StateHandler) -> None:
        """Register a callback invoked on every state transition."""
        self._state_handlers.append(handler)

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    def _on_engine_state_change(self, new_state: str) -> None:
        """SDK 状态迁移 → 透传业务层注册的回调。"""
        for h in self._state_handlers:
            try:
                result = h(new_state)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                logger.exception("state handler error for state=%s", new_state)

    async def _on_engine_event(self, event: dict) -> None:
        """SDK 事件 → 既有 OneBot11 事件路由（白名单/消息处理）。"""
        post_type = event.get("post_type", "")
        if self._connectivity_test and post_type in {"message", "notice", "request"}:
            logger.debug("QQ connectivity test discarded non-meta event")
            return
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
            # 群消息等其余类型：事件已透传到 _emit_event，业务层按需扩展
        elif post_type == "meta_event":
            logger.debug("QQ meta: %s/%s", event.get("meta_event_type", "?"), event.get("sub_type", "?"))
        elif post_type == "notice":
            logger.debug("QQ notice: %s", event.get("notice_type", "?"))

    # ── 登录闸门 ──────────────────────────────────────────

    async def wait_until_ready(self, timeout: float = 30.0) -> bool:
        """Block until QQ is fully logged in, or until timeout."""
        return await self.wait_for_login(timeout=timeout)

    async def wait_for_login(self, timeout: float = 15.0) -> bool:
        """Block until QQ account is logged in, or until ``timeout``.

        Proactive callers (boot_greeting, scheduled pushes) should use
        this instead of a fixed ``sleep`` so they don't fire while the
        engine is still handshaking with Tencent servers.
        """
        if self._disabled:
            return False
        return await self._engine.wait_for_login(timeout=timeout)

    # ── 连接生命周期 ──────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the QQ engine WS, auto-reconnecting.

        While the port stays closed, proactively launch the engine via
        the QQ gateway after ``proactive_launch_wait`` seconds (backoff
        applied), so a dead engine gets recovered by the backend itself.
        """
        if self._disabled:
            logger.info("QQ client disabled by AERIE_DISABLE_QQ")
            await self._engine.stop()
            return
        await self._engine.connect(before_connect=self._maybe_launch_engine)

    async def _maybe_launch_engine(self) -> None:
        """端口长期未开时经 QQ 网关拉起引擎（带 backoff 防重启风暴）。"""
        import time

        now = time.monotonic()
        if self._port_wait_started is None:
            self._port_wait_started = now
            return
        if now - self._port_wait_started < self._port_wait_threshold:
            return
        if now < self._launch_backoff_until:
            return
        self._launch_backoff_until = now + self._launch_backoff_sec
        self._port_wait_started = None
        logger.info(
            "QQ WS port %s closed for > %.0fs, proactively launching engine",
            self.port, self._port_wait_threshold,
        )
        try:
            from core.qq_gateway import get_gateway
            result = await get_gateway().start()
            logger.info("QQ proactive engine launch result: %s", result.get("ok"))
        except Exception:
            logger.exception("QQ proactive engine launch failed")

    # ── 发送：文本 ────────────────────────────────────────

    @staticmethod
    def _ok(resp: dict | None) -> bool:
        return resp is not None and resp.get("status") == "ok"

    async def send_message(
        self, user_id: int, content: str, render_mode: str = "plain"
    ):
        """Send a private message via the OneBot11 API."""
        if self._disabled or self._connectivity_test:
            logger.info("QQ send skipped by process safety mode")
            return False
        if not self.is_connected:
            logger.warning("Cannot send: QQ WS not connected")
            return False

        # 输出端清洗：thought/action 标签、时间戳、伪图片 markdown
        content = strip_thought_action_tags(content)
        content = strip_timestamp_markers(content)
        content = strip_fake_image_markdown(content)
        if not content:
            logger.warning("QQ send: content empty after stripping tags, skip")
            return False

        resp = await self._rpc_call(
            A.ACTION_SEND_PRIVATE_MSG,
            {A.PARAM_USER_ID: int(user_id), A.PARAM_MESSAGE: content},
        )
        if not self._ok(resp):
            logger.warning("QQ send failed: %s", resp)
            return False
        logger.info("QQ -> %s: %.80s", user_id, content)
        mid = (resp.get("data") or {}).get("message_id")
        return int(mid) if mid else True

    async def _rpc_call(
        self, action: str, params: dict, timeout: float = 5.0
    ) -> dict | None:
        """Send a OneBot11 RPC, loop recv until echo match.

        Unified outbound for every business action (test/audit friendly);
        delegates to the self-developed protocol client.
        """
        if self._connectivity_test and action != A.ACTION_GET_LOGIN_INFO:
            logger.info("QQ mutating RPC skipped by connectivity test mode")
            return None
        if not self.is_connected:
            return None
        return await self._engine.call(action, params, timeout=timeout)

    # ── 发送：富文本/媒体 ────────────────────────────────

    async def send_message_with_segments(
        self,
        user_id: int,
        segments: list[dict],
        render_mode: str = "array",
    ):
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

        # 输出端清洗：text 段剥 thought/action 标签与时间戳；非 text 段保留
        cleaned_segments = []
        has_usable_content = False
        for seg in segments:
            if seg.get("type") == "text" and "text" in (seg.get("data") or {}):
                cleaned = strip_thought_action_tags(seg["data"]["text"])
                cleaned = strip_timestamp_markers(cleaned)
                cleaned = strip_fake_image_markdown(cleaned)
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
            A.ACTION_SEND_PRIVATE_MSG,
            {A.PARAM_USER_ID: int(user_id), A.PARAM_MESSAGE: cleaned_segments},
        )
        if not self._ok(resp):
            return False
        mid = (resp.get("data") or {}).get("message_id")
        return int(mid) if mid else True

    async def send_image(self, user_id: int, image_ref: str, caption: str = "") -> bool:
        """Send a single image (optionally with a caption) to a QQ private user.

        ``image_ref`` is passed to the engine's image ``file`` field: an
        absolute local path, a ``file://`` URI, or an http(s) URL it can
        fetch. Safe to call while QQ is offline — returns False instead of
        raising, so proactive deliveries degrade gracefully.
        """
        if self._disabled or self._connectivity_test:
            logger.info("QQ send_image skipped by process safety mode")
            return False
        if not self.is_connected:
            logger.warning("Cannot send image: QQ WS not connected")
            return False

        segments: list[dict] = []
        caption_clean = strip_thought_action_tags(caption or "")
        if caption_clean:
            segments.append(M.text(caption_clean))
        segments.append(M.image(image_ref))
        return await self.send_message_with_segments(int(user_id), segments)

    # ── 撤回 / 消息查询 ──────────────────────────────────

    async def recall_message(self, message_id: int) -> bool:
        """Recall a previously sent message via OneBot11 delete_msg.

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
            A.ACTION_DELETE_MSG,
            {A.PARAM_MESSAGE_ID: int(message_id)},
            timeout=5,
        )
        if self._ok(resp):
            logger.info("QQ recalled message_id=%s", message_id)
            return True
        logger.warning("QQ recall failed for message_id=%s: %s", message_id, resp)
        return False

    async def get_msg(self, message_id: int, timeout: float = 8.0) -> dict | None:
        """Fetch a single message's raw content via OneBot11 ``get_msg``.

        Used to resolve inbound quotes whose quoted message is not stored in
        chat_log. Returns the full response dict (``data.message`` holds the
        segment array) or None on failure.
        """
        if self._disabled or not self.is_connected:
            return None
        return await self._rpc_call(
            A.ACTION_GET_MSG, {A.PARAM_MESSAGE_ID: int(message_id)}, timeout=timeout,
        )

    # ── 社交互动 ─────────────────────────────────────────

    async def send_poke(self, user_id: int) -> bool:
        """Send a poke (戳一戳) to a user via the engine."""
        if self._disabled or self._connectivity_test:
            logger.info("QQ poke skipped by process safety mode")
            return False
        if not self.is_connected:
            return False
        resp = await self._rpc_call(
            A.EXT_SEND_POKE, {A.PARAM_USER_ID: int(user_id)}, timeout=3,
        )
        return self._ok(resp)

    # ── 媒体下载 ─────────────────────────────────────────

    async def get_record(self, file: str, out_format: str = "mp3", timeout: float = 25.0) -> dict | None:
        """Fetch a voice message file via OneBot11 ``get_record``.

        The engine downloads the QQ silk voice and transcodes it (via its
        bundled ffmpeg) into ``out_format``. Returns the raw RPC response whose
        ``data.file`` is a local path (or base64 when remote). ``file`` is the
        ``data.file`` of an incoming ``[CQ:record]`` segment.
        """
        if not self.is_connected:
            return None
        return await self._rpc_call(
            A.ACTION_GET_RECORD,
            {A.PARAM_FILE: str(file), A.PARAM_OUT_FORMAT: out_format},
            timeout=timeout,
        )

    async def get_image(self, file: str, timeout: float = 25.0) -> dict | None:
        """Fetch an image/sticker local file via OneBot11 ``get_image``.

        ``file`` is the ``data.file`` of an incoming ``[CQ:image]`` segment.
        On success ``data.file`` is a local path (or base64 when remote) and
        ``data.url`` is a downloadable URL.
        """
        if not self.is_connected:
            return None
        return await self._rpc_call(
            A.ACTION_GET_IMAGE, {A.PARAM_FILE: str(file)}, timeout=timeout,
        )

    async def fetch_custom_face(self, count: int = 48, timeout: float = 25.0) -> list[str]:
        """Fetch the account's favorite/custom stickers via the engine.

        Returns a list of sticker URLs. ``count`` caps how many are returned.
        On failure returns an empty list so callers can degrade gracefully.
        """
        if not self.is_connected:
            return []
        resp = await self._rpc_call(
            A.EXT_FETCH_CUSTOM_FACE, {A.PARAM_COUNT: int(count)}, timeout=timeout,
        )
        if not self._ok(resp):
            return []
        data = resp.get("data") or []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if str(x).strip()]

    # ── 停止 ─────────────────────────────────────────────

    async def stop(self) -> None:
        self._engine.stop()
        logger.info("QQ client stopped")

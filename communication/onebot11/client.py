"""OneBot11 WebSocket 客户端（自研实现）。

自研的 OneBot11 协议客户端：连接任意 OneBot11 兼容引擎（本地 QQ 引擎），
负责收事件、发动作、心跳探活与登录态追踪。不依赖任何第三方 OneBot SDK，
只基于 ``websockets`` 标准库风格实现。

设计要点（沿自 Aerie QQ 链路多年稳定性经验）：

- **独立心跳探活**：周期发 ``get_login_info`` 并匹配 echo。半开/静默断开时
  由心跳主动判定并强制重连，不依赖 recv 异常（静默断开不会抛异常）。
- **RPC 短连接 + echo 匹配**：每个动作请求独立 WS 短连接，循环收帧直到
  echo 命中。引擎推送的 lifecycle/heartbeat 帧被跳过，不会干扰请求-响应。
- **登录态闸门**：``logged_in`` 与 WS 连接状态分离——WS 通了不代表 QQ
  账号在线。``lifecycle.connect`` 事件或 ``get_login_info`` 成功才置位，
  主动推送前必须等登录闸门，避免消息"幽灵发出"。
- **事件分发**：非 echo 帧统一走 ``on_event`` 回调，业务层按
  ``post_type`` 自行路由。
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import socket
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable

import websockets
from websockets.asyncio.client import ClientConnection

from communication.onebot11 import actions as A
from communication.onebot11 import events as E

logger = logging.getLogger(__name__)

# ── 连接状态常量（对外保持稳定，业务层依赖）────────────────
STATE_DISCONNECTED = "disconnected"
STATE_WS_CONNECTED = "ws_connected"
STATE_LOGGED_IN = "logged_in"

EventCallback = Callable[[dict], Any]
StateCallback = Callable[[str], Any]


def _port_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """TCP 端口探活：引擎 WS 端口是否在监听。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


class OneBot11Client:
    """OneBot11 WebSocket 客户端。

    Args:
        host: 引擎 WS 服务地址（默认 127.0.0.1）。
        port: 引擎 WS 服务端口（默认 3001）。
        token: 引擎配置的鉴权 token；非空时连接携带 ``Authorization: Bearer``。
        heartbeat_interval: 心跳探活周期（秒）。
        heartbeat_timeout: 心跳响应超时（秒），超时判定连接死亡。
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 3001,
        token: str = "",
        heartbeat_interval: float = 30.0,
        heartbeat_timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.token = token or ""
        self.heartbeat_interval = float(heartbeat_interval)
        self.heartbeat_timeout = float(heartbeat_timeout)

        # 引擎侧账号信息：从 get_login_info / 事件 self_id 学习
        self.self_id: int = 0

        self._running = False
        self._connected = False
        self._logged_in = False
        self._login_event = asyncio.Event()
        self._state = STATE_DISCONNECTED

        self._event_handlers: list[EventCallback] = []
        self._state_handlers: list[StateCallback] = []

        # 心跳探活
        self._force_reconnect = False
        self._probe_echo: str | None = None
        self._probe_event = asyncio.Event()
        self._heartbeat_log: Callable[[str], None] | None = None

    # ── 只读状态 ──────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """WS 层已连接（后端 ⇄ 引擎链路通）。"""
        return self._connected

    @property
    def logged_in(self) -> bool:
        """QQ 账号真实在线（引擎 ⇄ 腾讯链路通）。"""
        return self._logged_in and self._connected

    @property
    def state(self) -> str:
        return self._state

    def set_heartbeat_log(self, sink: Callable[[str], None] | None) -> None:
        """注册心跳探活的 liveness 回调（如前端运行日志黑框）。"""
        self._heartbeat_log = sink

    def _emit_heartbeat(self, text: str) -> None:
        if self._heartbeat_log is not None:
            try:
                self._heartbeat_log(text)
            except Exception:
                logger.exception("heartbeat log sink failed")

    # ── 事件订阅 ──────────────────────────────────────────

    def on_event(self, handler: EventCallback) -> None:
        """注册事件回调：每个 OneBot11 事件（含 heartbeat 外帧）都会送达。

        回调可以是同步函数或协程；异常被捕获记录，不中断事件链。
        """
        self._event_handlers.append(handler)

    def on_state_change(self, handler: StateCallback) -> None:
        """注册状态迁移回调（disconnected/ws_connected/logged_in）。"""
        self._state_handlers.append(handler)

    def _emit_state(self, new_state: str) -> None:
        if new_state == self._state:
            return
        self._state = new_state
        logger.info("QQ engine state: %s", new_state)
        for h in self._state_handlers:
            try:
                result = h(new_state)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                logger.exception("state handler error for state=%s", new_state)

    async def _emit_event(self, event: dict) -> None:
        for h in self._event_handlers:
            try:
                result = h(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("event handler error: %s", event.get("post_type"))

    # ── 登录闸门 ──────────────────────────────────────────

    async def wait_for_login(self, timeout: float = 15.0) -> bool:
        """阻塞至 QQ 账号登录就绪，超时返回 False。

        主动推送类调用方应先用本闸门，避免登录预热期消息幽灵发出。
        """
        if self.logged_in:
            return True
        try:
            await asyncio.wait_for(self._login_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self.logged_in

    def _mark_logged_in(self) -> None:
        if self._logged_in:
            return
        self._logged_in = True
        self._login_event.set()
        self._emit_state(STATE_LOGGED_IN)

    # ── 连接生命周期 ──────────────────────────────────────

    def _ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def _headers(self) -> dict | None:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return None

    @asynccontextmanager
    async def _open_ws(self, url: str, **overrides):
        kwargs = {
            "additional_headers": self._headers(),
            "ping_interval": 20,
            "ping_timeout": 10,
            "close_timeout": 3,
        }
        kwargs.update(overrides)
        try:
            async with websockets.connect(url, **kwargs) as ws:
                yield ws
        except TypeError as exc:
            if "additional_headers" not in str(exc):
                raise
            kwargs["extra_headers"] = kwargs.pop("additional_headers")
            async with websockets.connect(url, **kwargs) as ws:
                yield ws

    async def connect(
        self,
        *,
        before_connect: Callable[[], Any] | None = None,
    ) -> None:
        """连接引擎 WS，断线自动重连，直到 :meth:`stop` 被调用。

        Args:
            before_connect: 可选钩子。每次发现端口未就绪（等待重连）时调用，
                用于业务层尝试拉起本地引擎进程（如 QQ 引擎网关）。
        """
        self._running = True
        url = self._ws_url()
        while self._running:
            if not _port_is_open(self.host, self.port):
                if before_connect is not None:
                    try:
                        result = before_connect()
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("before_connect hook failed")
                await asyncio.sleep(3)
                continue
            try:
                async with self._open_ws(url) as ws:
                    self._connected = True
                    # 每次 (重)连接都重置登录态：WS 通 ≠ 账号在线
                    self._logged_in = False
                    self._login_event.clear()
                    self._emit_state(STATE_WS_CONNECTED)
                    logger.info("QQ engine WS connected to %s", url)
                    asyncio.create_task(self._learn_self_id())
                    await self._listen(ws)
            except Exception as e:
                logger.warning("QQ engine WS connection error: %s", e)
                self._connected = False
                self._logged_in = False
                self._login_event.clear()
                self._emit_state(STATE_DISCONNECTED)
                await asyncio.sleep(5)

    async def _listen(self, ws: ClientConnection) -> None:
        """主连接收帧循环：1s 超时轮询，心跳 echo 匹配 / 事件分发。

        用带超时的 recv 轮询，确保本协程不卡死在半开连接上：
        心跳判定死亡时置 ``_force_reconnect``，本循环 1s 内可见并退出，
        触发 connect() 外层重连（不依赖 WS close 握手完成）。
        """
        self._probe_echo = None
        self._probe_event = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(ws))
        try:
            while self._running:
                if self._force_reconnect:
                    logger.info("QQ engine WS dead detected; tearing down to reconnect")
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    logger.info("QQ engine WS connection closed")
                    break
                except Exception:
                    logger.exception("QQ engine WS recv error")
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON WS frame: %.80s", raw)
                    continue
                # 心跳探活回包：命中即确认存活，不派发
                if self._probe_echo is not None and event.get(A.PARAM_ECHO) == self._probe_echo:
                    self._probe_echo = None
                    self._probe_event.set()
                    continue
                try:
                    await self._handle_inbound(event)
                except Exception:
                    logger.exception("QQ engine inbound event error")
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

    async def _handle_inbound(self, event: dict) -> None:
        """处理引擎上行帧：登录态追踪 + 事件分发。"""
        # 任何事件都可能携带 self_id（引擎自身账号），第一时间学习
        sid = event.get("self_id")
        if sid and not self.self_id:
            self.self_id = int(sid)
            logger.info("QQ engine learned self_id=%s", self.self_id)

        # lifecycle.connect = 账号上线信号
        if E.is_connected_lifecycle(event):
            if not self._logged_in:
                self._mark_logged_in()
                logger.info("QQ engine lifecycle connect: account online (self_id=%s)",
                            self.self_id or "?")

        await self._emit_event(event)

    async def _heartbeat(self, ws: ClientConnection) -> None:
        """独立存活心跳：周期发 ``get_login_info`` 探活。

        超时未收到对应 echo 判定 WS 半开/静默断开，仅置
        ``_force_reconnect`` 标志，由 _listen 轮询循环 1s 内感知收尾。
        """
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            if not self._connected or self._force_reconnect:
                continue
            echo = f"hb_{secrets.token_hex(8)}"
            self._probe_echo = echo
            self._probe_event.clear()
            try:
                await ws.send(json.dumps({
                    "action": A.ACTION_GET_LOGIN_INFO,
                    A.PARAM_ECHO: echo,
                }))
            except Exception as exc:
                logger.warning("QQ engine heartbeat send failed (%s), forcing reconnect", exc)
                self._emit_heartbeat("QQ 引擎心跳发送失败，强制重连")
                self._force_reconnect = True
                return
            try:
                await asyncio.wait_for(
                    self._probe_event.wait(), timeout=self.heartbeat_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "QQ engine heartbeat timeout (%.0fs), WS likely dead, forcing reconnect",
                    self.heartbeat_timeout,
                )
                self._emit_heartbeat(
                    f"QQ 引擎心跳超时（{int(self.heartbeat_timeout)}s 无响应），WS 疑似断开，强制重连"
                )
                self._force_reconnect = True
                return
            logger.debug("QQ engine heartbeat OK")
            self._emit_heartbeat("QQ 引擎心跳正常")

    async def _learn_self_id(self) -> None:
        """通过 ``get_login_info`` 学习引擎账号并确认登录态。

        重试几次以覆盖 WS 握手窗口；成功即置登录就绪，供
        ``wait_for_login`` 调用方放行。
        """
        for attempt in range(5):
            await asyncio.sleep(1 + attempt)
            if not self._connected:
                continue
            resp = await self.call(A.ACTION_GET_LOGIN_INFO, {}, timeout=3)
            if resp is None:
                continue
            uid = (resp.get("data") or {}).get("user_id")
            if uid:
                self.self_id = int(uid)
                self._mark_logged_in()
                logger.info("QQ engine learned self_id=%s via get_login_info", self.self_id)
                return
            logger.debug("get_login_info attempt %s: no user_id in resp", attempt + 1)
        logger.warning("QQ engine could not learn self_id via get_login_info")

    # ── RPC：请求-响应（echo 匹配）─────────────────────────

    async def call(self, action: str, params: dict | None = None,
                   timeout: float = 5.0) -> dict | None:
        """发送 OneBot11 动作请求，返回完整响应 dict（含 status/data/echo）。

        在独立短连接上发送，循环收帧直到 echo 命中。引擎推送的
        lifecycle/heartbeat 等非目标帧被跳过。失败返回 None。
        """
        if not self._connected:
            logger.debug("RPC %s skipped: engine WS not connected", action)
            return None
        echo = f"rpc_{uuid.uuid4().hex[:12]}"
        payload = {
            "action": action,
            "params": params or {},
            A.PARAM_ECHO: echo,
        }
        url = self._ws_url()
        try:
            async with self._open_ws(url, ping_interval=None, close_timeout=2) as ws:
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
                    try:
                        data = json.loads(resp)
                    except json.JSONDecodeError:
                        continue
                    if data.get(A.PARAM_ECHO) == echo:
                        return data
                    logger.debug("RPC %s: skip non-echo frame: %.80s", action, resp)
        except Exception as e:
            logger.debug("RPC %s failed: %s", action, e)
            return None
        return None

    def _ok(self, resp: dict | None) -> bool:
        return resp is not None and resp.get("status") == "ok"

    # ── 便捷动作：消息 ─────────────────────────────────────

    async def send_private_msg(self, user_id: int, message, timeout: float = 5.0):
        """发送私聊消息。返回平台消息 id（引擎未回则 True），失败 False。"""
        resp = await self.call(
            A.ACTION_SEND_PRIVATE_MSG,
            {A.PARAM_USER_ID: int(user_id), A.PARAM_MESSAGE: message},
            timeout=timeout,
        )
        if not self._ok(resp):
            return False
        mid = (resp.get("data") or {}).get("message_id")
        return int(mid) if mid else True

    async def send_group_msg(self, group_id: int, message, timeout: float = 5.0):
        """发送群消息。返回平台消息 id（引擎未回则 True），失败 False。"""
        resp = await self.call(
            A.ACTION_SEND_GROUP_MSG,
            {A.PARAM_GROUP_ID: int(group_id), A.PARAM_MESSAGE: message},
            timeout=timeout,
        )
        if not self._ok(resp):
            return False
        mid = (resp.get("data") or {}).get("message_id")
        return int(mid) if mid else True

    async def delete_msg(self, message_id: int, timeout: float = 5.0) -> bool:
        """撤回消息。"""
        resp = await self.call(
            A.ACTION_DELETE_MSG, {A.PARAM_MESSAGE_ID: int(message_id)}, timeout=timeout,
        )
        return self._ok(resp)

    async def get_msg(self, message_id: int, timeout: float = 8.0) -> dict | None:
        """获取单条消息完整内容（用于解析引用的历史消息）。"""
        return await self.call(
            A.ACTION_GET_MSG, {A.PARAM_MESSAGE_ID: int(message_id)}, timeout=timeout,
        )

    # ── 便捷动作：社交互动 ─────────────────────────────────

    async def send_poke(self, user_id: int, timeout: float = 3.0) -> bool:
        """戳一戳（好友）。"""
        resp = await self.call(
            A.EXT_SEND_POKE, {A.PARAM_USER_ID: int(user_id)}, timeout=timeout,
        )
        return self._ok(resp)

    async def send_like(self, user_id: int, times: int = 1, timeout: float = 3.0) -> bool:
        """给好友点赞。"""
        resp = await self.call(
            A.ACTION_SEND_LIKE, {A.PARAM_USER_ID: int(user_id), "times": int(times)},
            timeout=timeout,
        )
        return self._ok(resp)

    # ── 便捷动作：媒体 ─────────────────────────────────────

    async def get_record(self, file: str, out_format: str = "mp3",
                         timeout: float = 25.0) -> dict | None:
        """语音下载并按需转码，返回原始响应（data.file 为本地路径或 base64）。"""
        return await self.call(
            A.ACTION_GET_RECORD,
            {A.PARAM_FILE: str(file), A.PARAM_OUT_FORMAT: out_format},
            timeout=timeout,
        )

    async def get_image(self, file: str, timeout: float = 25.0) -> dict | None:
        """图片本地化，返回原始响应（data.file 为本地路径，data.url 可下载）。"""
        return await self.call(
            A.ACTION_GET_IMAGE, {A.PARAM_FILE: str(file)}, timeout=timeout,
        )

    async def ocr_image(self, image: str, timeout: float = 15.0) -> dict | None:
        """图片 OCR，返回原始响应（data.texts 为文本块列表）。"""
        return await self.call(A.ACTION_OCR_IMAGE, {"image": str(image)}, timeout=timeout)

    # ── 便捷动作：收藏表情 ─────────────────────────────────

    async def fetch_custom_face(self, count: int = 48, timeout: float = 25.0) -> list[str]:
        """拉取账号收藏表情 URL 列表；失败返回空列表。"""
        resp = await self.call(
            A.EXT_FETCH_CUSTOM_FACE, {A.PARAM_COUNT: int(count)}, timeout=timeout,
        )
        if not self._ok(resp):
            return []
        data = resp.get("data") or []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if str(x).strip()]

    # ── 便捷动作：关系/群组 ────────────────────────────────

    async def get_friend_list(self, timeout: float = 10.0) -> list[dict]:
        """获取好友列表。"""
        resp = await self.call(A.ACTION_GET_FRIEND_LIST, {}, timeout=timeout)
        if not self._ok(resp):
            return []
        data = resp.get("data")
        return data if isinstance(data, list) else []

    async def get_group_list(self, timeout: float = 10.0) -> list[dict]:
        """获取群列表。"""
        resp = await self.call(A.ACTION_GET_GROUP_LIST, {}, timeout=timeout)
        if not self._ok(resp):
            return []
        data = resp.get("data")
        return data if isinstance(data, list) else []

    async def get_group_member_list(self, group_id: int, timeout: float = 15.0) -> list[dict]:
        """获取群成员列表。"""
        resp = await self.call(
            A.ACTION_GET_GROUP_MEMBER_LIST, {A.PARAM_GROUP_ID: int(group_id)},
            timeout=timeout,
        )
        if not self._ok(resp):
            return []
        data = resp.get("data")
        return data if isinstance(data, list) else []

    async def get_login_info(self, timeout: float = 5.0) -> dict | None:
        """获取引擎登录账号信息（user_id / nickname）。"""
        return await self.call(A.ACTION_GET_LOGIN_INFO, {}, timeout=timeout)

    async def get_status(self, timeout: float = 5.0) -> dict | None:
        """获取引擎运行状态。"""
        return await self.call(A.ACTION_GET_STATUS, {}, timeout=timeout)

    # ── 停止 ──────────────────────────────────────────────

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        self._logged_in = False
        self._login_event.clear()
        self._emit_state(STATE_DISCONNECTED)
        logger.info("QQ engine client stopped")

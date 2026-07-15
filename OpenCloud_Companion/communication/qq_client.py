"""NapCatQQ WebSocket 客户端

负责：
- 连接 NapCat OneBot11 WebSocket
- 接收消息事件并解析
- 发送回复消息
- 断线自动重连（指数退避）
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, Optional

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed, WebSocketException

from communication.message import IncomingMessage, OutgoingReply
from loguru import logger


# 消息处理器类型：接收 IncomingMessage，返回 Optional[OutgoingReply]
MessageHandler = Callable[[IncomingMessage], Awaitable[Optional[OutgoingReply]]]


class QQClient:
    """NapCatQQ WebSocket 客户端"""

    def __init__(self, uri: str = "ws://localhost:3001"):
        """
        Args:
            uri: NapCat OneBot11 WebSocket 地址
        """
        self.uri: str = uri
        self._ws: Optional[ClientConnection] = None
        self._reconnect_delay: float = 1.0
        self._max_reconnect_delay: float = 60.0
        self._running: bool = False
        self._handler: Optional[MessageHandler] = None
        self._echo_callbacks: Dict[str, asyncio.Future] = {}

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    async def connect(self) -> None:
        """建立 WebSocket 连接，带指数退避重连"""
        while self._running:
            try:
                logger.info(f"正在连接 NapCatQQ: {self.uri}")
                self._ws = await websockets.connect(
                    self.uri,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                )
                self._reconnect_delay = 1.0
                logger.success(f"已连接 NapCatQQ: {self.uri}")
                return
            except (OSError, WebSocketException) as e:
                logger.error(f"连接失败: {e}，{self._reconnect_delay:.0f}s 后重试")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )

    async def listen(self, handler: MessageHandler) -> None:
        """
        监听 WebSocket 消息，收到消息时回调 handler。

        Args:
            handler: 消息处理函数，接收 IncomingMessage，返回可选的 OutgoingReply
        """
        self._running = True
        self._handler = handler

        while self._running:
            await self.connect()

            if not self._ws:
                continue

            try:
                async for raw in self._ws:
                    if not self._running:
                        break
                    await self._handle_raw_message(raw)

            except ConnectionClosed as e:
                logger.warning(f"WebSocket 连接断开: {e}")
                self._ws = None
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)

            except Exception as e:
                logger.error(f"WebSocket 异常: {e}")
                self._ws = None
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)

        logger.info("QQClient 已停止监听")

    async def _handle_raw_message(self, raw: str | bytes) -> None:
        """处理原始 WebSocket 消息"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug(f"收到非 JSON 消息: {raw[:200]}")
            return

        # 检查是否是之前请求的 echo 响应
        echo = data.get("echo")
        if echo and echo in self._echo_callbacks:
            future = self._echo_callbacks.pop(echo)
            if not future.done():
                future.set_result(data)
            return

        # 解析 OneBot11 事件
        msg = IncomingMessage.from_onebot_event(data)
        if msg is None:
            return

        # 只处理私聊消息
        if not msg.is_private:
            logger.debug(f"忽略非私聊消息: {msg.summary()}")
            return

        logger.info(f"收到: {msg.summary()}")

        # 调用处理器
        if self._handler:
            try:
                reply = await self._handler(msg)
                if reply:
                    await self.send_reply(reply)
            except Exception as e:
                logger.exception(f"消息处理异常: {e}")

    async def send_reply(self, reply: OutgoingReply) -> bool:
        """
        发送回复消息。

        Args:
            reply: 待发送的回复

        Returns:
            是否发送成功
        """
        if not self._ws:
            logger.error("WebSocket 未连接，无法发送")
            return False

        action = reply.to_onebot_action()
        payload = json.dumps(action, ensure_ascii=False)

        try:
            await self._ws.send(payload)
            logger.info(f"已发送: -> {reply.user_id}: {reply.content[:80]}...")
            return True
        except ConnectionClosed:
            logger.error("WebSocket 连接已断开，发送失败")
            self._ws = None
            return False
        except Exception as e:
            logger.error(f"发送失败: {e}")
            return False

    async def send_message(
        self, user_id: int, message: str
    ) -> Optional[Dict[str, Any]]:
        """
        发送私聊消息并等待响应（带 echo）。

        Args:
            user_id: 目标 QQ 号
            message: 消息内容

        Returns:
            包含 status/retcode/data 的响应字典，失败返回 None
        """
        if not self._ws:
            logger.error("WebSocket 未连接")
            return None

        reply = OutgoingReply(user_id=user_id, content=message)

        # 注册 echo 回调
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._echo_callbacks[reply.echo] = future

        action = reply.to_onebot_action()
        payload = json.dumps(action, ensure_ascii=False)

        try:
            await self._ws.send(payload)
            resp = await asyncio.wait_for(future, timeout=10.0)
            return resp
        except asyncio.TimeoutError:
            logger.warning(f"消息 echo 超时: echo={reply.echo}")
            self._echo_callbacks.pop(reply.echo, None)
            return None
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            self._echo_callbacks.pop(reply.echo, None)
            return None

    async def stop(self) -> None:
        """停止客户端，关闭连接"""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        logger.info("QQClient 已停止")

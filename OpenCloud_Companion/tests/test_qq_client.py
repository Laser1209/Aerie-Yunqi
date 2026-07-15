"""QQ WebSocket 客户端单元测试"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from communication.message import (
    IncomingMessage,
    OutgoingReply,
    MessageType,
    Sender,
)
from communication.qq_client import QQClient


class TestQQClient:
    def test_init_default_uri(self):
        client = QQClient()
        assert client.uri == "ws://localhost:3001"
        assert client.is_connected is False
        assert client._running is False

    def test_init_custom_uri(self):
        client = QQClient(uri="ws://192.168.1.1:8080")
        assert client.uri == "ws://192.168.1.1:8080"

    @pytest.mark.asyncio
    async def test_send_reply_not_connected(self):
        client = QQClient()
        reply = OutgoingReply(user_id=123, content="test")
        result = await client.send_reply(reply)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self):
        client = QQClient()
        result = await client.send_message(user_id=123, message="test")
        assert result is None

    @pytest.mark.asyncio
    async def test_stop_clean(self):
        client = QQClient()
        await client.stop()
        assert client._running is False
        assert client._ws is None

    def test_outgoing_reply_to_onebot_format(self):
        """验证 OutgoingReply 生成的 OneBot11 格式正确"""
        reply = OutgoingReply(user_id=3489352115, content="测试回复")
        action = reply.to_onebot_action()
        assert "action" in action
        assert "params" in action
        assert "echo" in action
        assert action["action"] in ("send_private_msg", "send_group_msg")
        assert action["params"]["message"] == "测试回复"

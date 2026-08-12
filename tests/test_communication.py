"""Tests for communication layer: router, splitter, recall manager."""

import time

import pytest

from communication import qq_client as qq_client_module
from communication.qq_client import QQClient
from communication.qq_client import STATE_DISCONNECTED
from communication.router import RouteMode
from communication.router import Router
from communication.splitter import SemanticMessageSplitter
from communication.recall_manager import RecallManager

MASTER_QQ = 3998874040
FRIEND_QQ = 12345678


class TestQQClient:
    """Test QQ lifecycle behavior without touching NapCat or the network."""

    @pytest.mark.asyncio
    async def test_connect_returns_cleanly_when_disabled(self, monkeypatch):
        monkeypatch.setenv("AERIE_DISABLE_QQ", "true")

        def fail_if_port_checked(*_args, **_kwargs):
            raise AssertionError("disabled QQ must not probe the network")

        monkeypatch.setattr(qq_client_module, "_port_is_open", fail_if_port_checked)
        client = QQClient({"ws_port": 3001})

        await client.connect()

        assert client._running is False
        assert client.state == STATE_DISCONNECTED


class TestRouter:
    """Test three-tier routing."""

    @pytest.fixture
    def router(self):
        return Router(self_qq=MASTER_QQ, friends_qq=[FRIEND_QQ])

    def test_master_routes_full(self, router):
        assert router.route(MASTER_QQ) == RouteMode.FULL

    def test_friend_routes_auto(self, router):
        assert router.route(FRIEND_QQ) == RouteMode.AUTO_REPLY

    def test_stranger_routes_basic(self, router):
        assert router.route(99999) == RouteMode.BASIC

    def test_is_master(self, router):
        assert router.is_master(MASTER_QQ) is True
        assert router.is_master(99999) is False

    def test_is_friend(self, router):
        assert router.is_friend(FRIEND_QQ) is True
        assert router.is_friend(99999) is False


class TestSplitter:
    """Test semantic message splitter."""

    @pytest.fixture
    def splitter(self):
        return SemanticMessageSplitter()

    def test_short_text_single_segment(self, splitter):
        parts = splitter.split("你好，今天天气真好。")
        assert len(parts) == 1

    def test_long_text_multiple_segments(self, splitter):
        text = "第一句话。第二句话。第三句话。" * 40
        parts = splitter.split(text)
        assert len(parts) >= 2

    def test_returns_list_of_strings(self, splitter):
        parts = splitter.split("测试内容。")
        assert isinstance(parts, list)
        for p in parts:
            assert isinstance(p, str)


class TestRecallManager:
    """Test recall (撤回) mechanism — async methods."""

    @pytest.fixture
    def rm(self, mock_qq_client):
        return RecallManager(mock_qq_client)

    @pytest.mark.asyncio
    async def test_handle_negative_within_window(self, rm):
        rm.on_message_sent(1, "之前发的消息")
        result = await rm.handle_user_negative(1, "别这样")
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_negative_outside_window(self, rm):
        rm.on_message_sent(1, "很久之前的消息")
        rm._last_sent[("qq", "1")].timestamp = time.time() - 300
        result = await rm.handle_user_negative(1, "别说了")
        assert result is False

    @pytest.mark.asyncio
    async def test_non_negative_no_trigger(self, rm):
        rm.on_message_sent(1, "hello")
        result = await rm.handle_user_negative(1, "你好啊")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_last_sent_no_recall(self, rm):
        result = await rm.handle_user_negative(1, "别说了")
        assert result is False

    @pytest.mark.asyncio
    async def test_maybe_poke_on_silence_triggers(self, rm):
        rm.on_message_sent(1, "你在吗")
        rm._last_sent[("qq", "1")].timestamp = time.time() - 320
        result = await rm.maybe_poke_on_silence(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_maybe_poke_no_last_sent(self, rm):
        result = await rm.maybe_poke_on_silence(1)
        assert result is False


# ── P4：QQ 输出端伪图片 markdown 过滤（提示词外泄兜底） ──
from communication.qq_client import strip_fake_image_markdown  # noqa: E402


def test_strip_fake_image_markdown_removes_prompt_text():
    # LLM 误把生图提示词写进回复 → 整体剥除
    text = "[图片](一张局部特写。昏暗的光线下，视线顺着锁骨向下延伸，是一条修长笔直的腿。)喏，看到了吗?"
    out = strip_fake_image_markdown(text)
    assert "[图片]" not in out
    assert "一张局部特写" not in out
    assert "喏，看到了吗?" in out


def test_strip_fake_image_markdown_removes_bang_variant():
    out = strip_fake_image_markdown("给你看这张！![图片](自拍一张，背景是重庆江景)。怎么样？")
    assert "![图片]" not in out
    assert "自拍一张" not in out
    assert "给你看这张" in out


def test_strip_fake_image_markdown_keeps_real_url_image():
    # 真实图片消息（URL 附件语法）必须保留
    text = "![图片](http://127.0.0.1:7890/uploads/abc.png)"
    assert strip_fake_image_markdown(text) == text


def test_strip_fake_image_markdown_keeps_plain_word():
    # 裸词"图片"不被误伤
    assert strip_fake_image_markdown("这张图片很好看") == "这张图片很好看"


def test_strip_fake_image_markdown_empty():
    assert strip_fake_image_markdown("") == ""
    assert strip_fake_image_markdown(None) == ""


class _RpcSpy:
    def __init__(self, resp: dict) -> None:
        self.resp = resp
        self.calls: list[dict] = []

    async def __call__(self, action: str, params: dict, timeout: float = 5.0) -> dict | None:
        self.calls.append({"action": action, "params": params})
        return self.resp


@pytest.mark.asyncio
async def test_send_message_with_segments_strips_fake_markdown(monkeypatch):
    """发送出口把 `[图片](...)` 伪 markdown 从 text segment 剥掉，payload 不含。"""
    monkeypatch.setattr(qq_client_module, "_port_is_open", lambda *a, **k: True)
    client = QQClient({"ws_port": 3001})
    client._disabled = False
    client._connected = True
    spy = _RpcSpy({"status": "ok"})
    client._rpc_call = spy

    ok = await client.send_message_with_segments(
        12345,
        [
            {"type": "text", "data": {"text": "[图片](一张局部特写。)喏，看到了吗?"}},
        ],
    )
    assert ok is True
    assert spy.calls
    message = spy.calls[0]["params"]["message"]
    assert message[0]["type"] == "text"
    assert "[图片](" not in message[0]["data"]["text"]
    assert "一张局部特写" not in message[0]["data"]["text"]
    assert "喏，看到了吗?" in message[0]["data"]["text"]


@pytest.mark.asyncio
async def test_send_message_with_segments_keeps_real_image(monkeypatch):
    """真实图片 segment 不受过滤影响（非 text 类型一律保留）。"""
    monkeypatch.setattr(qq_client_module, "_port_is_open", lambda *a, **k: True)
    client = QQClient({"ws_port": 3001})
    client._disabled = False
    client._connected = True
    spy = _RpcSpy({"status": "ok"})
    client._rpc_call = spy

    ok = await client.send_message_with_segments(
        12345,
        [
            {"type": "text", "data": {"text": "给你看"}},
            {"type": "image", "data": {"file": "uploads/x.png"}},
        ],
    )
    assert ok is True
    message = spy.calls[0]["params"]["message"]
    assert message[1]["type"] == "image"
    assert message[1]["data"]["file"] == "uploads/x.png"

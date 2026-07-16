"""Tests for communication layer: router, splitter, recall manager."""

import time

import pytest

from communication.router import RouteMode
from communication.router import Router
from communication.splitter import SemanticMessageSplitter
from communication.recall_manager import RecallManager

MASTER_QQ = 3998874040
FRIEND_QQ = 12345678


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
        rm._last_sent[1].timestamp = time.time() - 300
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
        rm._last_sent[1].timestamp = time.time() - 320
        result = await rm.maybe_poke_on_silence(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_maybe_poke_no_last_sent(self, rm):
        result = await rm.maybe_poke_on_silence(1)
        assert result is False

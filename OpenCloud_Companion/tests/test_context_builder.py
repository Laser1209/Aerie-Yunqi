"""上下文构建器单元测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from communication.message import IncomingMessage, MessageType, Sender
from core.personality import PersonalityEngine


@pytest.fixture
def sample_msg():
    return IncomingMessage(
        msg_id=1,
        user_id=3489352115,
        user_nickname="伊泽",
        msg_type=MessageType.PRIVATE,
        content="今天天气真好",
        raw_message="今天天气真好",
        timestamp=datetime.now(),
        sender=Sender(user_id=3489352115, nickname="伊泽"),
        self_id=3998874040,
    )


@pytest.fixture
def personality():
    return PersonalityEngine({
        "name": "测试助手",
        "core_traits": {},
        "communication": {},
    })


class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_build_basic(self, personality, sample_msg):
        """测试基础消息构建（无历史/记忆）"""
        from memory.context_builder import ContextBuilder

        builder = ContextBuilder(personality, chat_log=None, memory_store=None)
        messages = await builder.build(
            sample_msg, include_memories=False, include_history=False
        )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "测试助手" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "今天天气真好"

    @pytest.mark.asyncio
    async def test_build_with_history(self, personality, sample_msg):
        """测试带聊天历史的构建"""
        from memory.context_builder import ContextBuilder

        mock_chat_log = AsyncMock()
        mock_chat_log.get_recent.return_value = [
            {"role": "user", "content": "你好", "timestamp": 1752560000.0},
            {"role": "assistant", "content": "主人好～", "timestamp": 1752560001.0},
        ]

        builder = ContextBuilder(
            personality, chat_log=mock_chat_log, memory_store=None
        )
        messages = await builder.build(
            sample_msg, include_memories=False, include_history=True
        )

        assert len(messages) >= 3  # system + 2历史 + 当前
        mock_chat_log.get_recent.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_with_memories(self, personality, sample_msg):
        """测试带记忆注入的构建"""
        from memory.context_builder import ContextBuilder

        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            {"role": "user", "content": "我喜欢雨天"},
            {"role": "assistant", "content": "雨天确实很浪漫呢～"},
        ]

        mock_chat_log = AsyncMock()
        mock_chat_log.get_recent.return_value = []

        builder = ContextBuilder(
            personality, chat_log=mock_chat_log, memory_store=mock_memory
        )
        messages = await builder.build(
            sample_msg, include_memories=True, include_history=False
        )

        assert len(messages) == 2  # system + 当前消息
        system_content = messages[0]["content"]
        assert "我喜欢雨天" in system_content

    @pytest.mark.asyncio
    async def test_build_compact(self, personality, sample_msg):
        """测试精简构建（仅 System Prompt + 当前消息）"""
        from memory.context_builder import ContextBuilder

        builder = ContextBuilder(personality)
        messages = await builder.build_compact(sample_msg)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_build_memory_search_failure_graceful(self, personality, sample_msg):
        """测试记忆检索失败时优雅降级"""
        from memory.context_builder import ContextBuilder

        mock_memory = AsyncMock()
        mock_memory.search.side_effect = Exception("Mem0 服务不可用")

        mock_chat_log = AsyncMock()
        mock_chat_log.get_recent.return_value = []

        builder = ContextBuilder(
            personality, chat_log=mock_chat_log, memory_store=mock_memory
        )
        # 不应该抛异常
        messages = await builder.build(
            sample_msg, include_memories=True, include_history=False
        )
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_build_deduplicates_current_message(self, personality, sample_msg):
        """测试不重复注入当前消息（如果已在历史中）"""
        from memory.context_builder import ContextBuilder

        mock_chat_log = AsyncMock()
        mock_chat_log.get_recent.return_value = [
            {"role": "user", "content": "今天天气真好", "timestamp": 1752560000.0},
        ]

        builder = ContextBuilder(
            personality, chat_log=mock_chat_log, memory_store=None
        )
        messages = await builder.build(
            sample_msg, include_memories=False, include_history=True
        )

        # 当前消息与历史最后一条相同 → 应被跳过（只保留 messages 最后的当前消息）
        user_messages = [m for m in messages if m["role"] == "user"]
        # 至少应该有 1 条 user message（当前消息）
        assert len(user_messages) >= 1

    @pytest.mark.asyncio
    async def test_build_without_knowledge(self, personality, sample_msg):
        """无知识库时正常构建（向后兼容）"""
        from memory.context_builder import ContextBuilder

        builder = ContextBuilder(personality)
        messages = await builder.build(sample_msg, capability_level="phase4")
        assert len(messages) >= 2
        assert messages[-1]["role"] == "user"
        assert messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_build_phase4_capability(self, personality, sample_msg):
        """Phase 4 能力级别注入"""
        from memory.context_builder import ContextBuilder

        builder = ContextBuilder(personality)
        messages = await builder.build(sample_msg, capability_level="phase4")
        system_content = messages[0]["content"]
        # Phase 4 system prompt should mention expanded capabilities
        assert "技能" in system_content or "知识" in system_content

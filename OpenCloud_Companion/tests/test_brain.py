"""AI 核心模块单元测试 — Phase 3"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from communication.message import IncomingMessage, OutgoingReply, MessageType, Sender
from datetime import datetime


def sample_msg(content: str = "你好") -> IncomingMessage:
    return IncomingMessage(
        msg_id=1,
        user_id=3489352115,
        user_nickname="伊泽",
        msg_type=MessageType.PRIVATE,
        content=content,
        raw_message=content,
        timestamp=datetime.now(),
        sender=Sender(user_id=3489352115, nickname="伊泽"),
        self_id=3998874040,
    )


def _mock_response(content: str = "默认回复"):
    """创建模拟的 OpenAI ChatCompletion response"""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = MagicMock()
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    return resp


class TestAIBrain:
    def test_init_without_api_keys(self):
        """测试没有 API Key 时抛出异常"""
        import os
        from core.brain import AIBrain

        old_keys = {}
        for key in ["SILICONFLOW_API_KEY", "DEEPSEEK_API_KEY", "ZHIPUAI_API_KEY"]:
            old_keys[key] = os.environ.pop(key, None)

        try:
            with pytest.raises(RuntimeError, match="没有配置任何 AI API Key"):
                AIBrain({})
        finally:
            for key, val in old_keys.items():
                if val is not None:
                    os.environ[key] = val

    def test_init_with_siliconflow_key(self, monkeypatch):
        """测试硅基流动 API Key 初始化"""
        monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test-siliconflow")
        from core.brain import AIBrain

        brain = AIBrain({})
        assert len(brain._providers) == 1
        assert brain._providers[0]["name"] == "siliconflow"

    def test_init_multiple_providers(self, monkeypatch):
        """测试多个提供商初始化与优先级"""
        monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test-sf")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-ds")
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test.zhipu")
        from core.brain import AIBrain

        brain = AIBrain({})
        assert len(brain._providers) == 3
        assert brain._providers[0]["name"] == "siliconflow"

    @pytest.mark.asyncio
    async def test_generate_reply_accepts_messages(self, monkeypatch):
        """测试 generate_reply() 接受 pre-built messages 列表"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
        from core.brain import AIBrain

        brain = AIBrain({})
        messages = [
            {"role": "system", "content": "你是一个测试助手"},
            {"role": "user", "content": "你好"},
        ]

        with patch.object(brain, "_call_api_raw", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = _mock_response("你好！有什么可以帮你的？")
            reply = await brain.generate_reply(messages)
            assert reply == "你好！有什么可以帮你的？"
            mock_call.assert_called_once_with(messages)

    @pytest.mark.asyncio
    async def test_classify_intent(self, monkeypatch):
        """测试意图分类方法"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
        from core.brain import AIBrain

        brain = AIBrain({})

        with patch.object(brain, "_call_api_raw", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = _mock_response("chat")
            result = await brain.classify_intent("你好呀", "分类 prompt")
            assert result == "chat"

    @pytest.mark.asyncio
    async def test_fallback_on_provider_failure(self, monkeypatch):
        """测试 Provider 容灾：第一个失败，第二个成功"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key1")
        from core.brain import AIBrain
        from openai import AsyncOpenAI

        brain = AIBrain({})
        messages = [{"role": "user", "content": "测试"}]

        mock_client_bad = MagicMock(spec=AsyncOpenAI)
        mock_client_bad.chat = MagicMock()
        mock_client_bad.chat.completions = MagicMock()
        mock_client_bad.chat.completions.create = AsyncMock(
            side_effect=Exception("服务不可用")
        )

        mock_client_good = MagicMock(spec=AsyncOpenAI)
        mock_resp = _mock_response("备用回复")
        mock_client_good.chat.completions.create = AsyncMock(return_value=mock_resp)

        brain._providers = [
            {"name": "bad", "client": mock_client_bad, "model": "test"},
            {"name": "good", "client": mock_client_good, "model": "test"},
        ]

        resp = await brain._call_api_raw(messages)
        assert resp.choices[0].message.content == "备用回复"
        mock_client_bad.chat.completions.create.assert_called_once()
        mock_client_good.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_with_tools(self, monkeypatch):
        """测试 Function Calling 工具调用"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
        from core.brain import AIBrain, ToolCallResult
        import json

        brain = AIBrain({})
        messages = [{"role": "user", "content": "打开记事本"}]
        tools = [{"type": "function", "function": {"name": "open_app", "description": "...", "parameters": {"type": "object", "properties": {}}}}]

        # 模拟 AI 返回 tool_call
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message = MagicMock()
        resp.choices[0].message.content = None
        tc = MagicMock()
        tc.id = "call_123"
        tc.function = MagicMock()
        tc.function.name = "open_app"
        tc.function.arguments = json.dumps({"app_name": "记事本"})
        resp.choices[0].message.tool_calls = [tc]
        resp.choices[0].finish_reason = "tool_calls"

        with patch.object(brain, "_call_api_raw", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = resp
            result = await brain.generate_with_tools(messages, tools)
            assert isinstance(result, ToolCallResult)
            assert result.tool_calls is not None
            assert result.tool_calls[0]["name"] == "open_app"
            assert result.tool_calls[0]["arguments"] == {"app_name": "记事本"}

    @pytest.mark.asyncio
    async def test_generate_with_tools_text_only(self, monkeypatch):
        """测试 AI 选择不调工具（直接返回文本）"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
        from core.brain import AIBrain, ToolCallResult

        brain = AIBrain({})
        messages = [{"role": "user", "content": "你好"}]
        tools = [{"type": "function", "function": {"name": "test", "description": "...", "parameters": {}}}]

        resp = _mock_response("你好呀！")
        resp.choices[0].message.tool_calls = None

        with patch.object(brain, "_call_api_raw", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = resp
            result = await brain.generate_with_tools(messages, tools)
            assert result.content == "你好呀！"
            assert result.tool_calls is None

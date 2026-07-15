"""AI 核心模块单元测试 — Phase 2"""

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
        # 硅基流动应该是第一个（主 provider）
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

        with patch.object(brain, "_call_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "你好！有什么可以帮你的？"
            reply = await brain.generate_reply(messages)
            assert reply == "你好！有什么可以帮你的？"
            mock_call.assert_called_once_with(messages)

    @pytest.mark.asyncio
    async def test_classify_intent(self, monkeypatch):
        """测试意图分类方法"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
        from core.brain import AIBrain

        brain = AIBrain({})

        with patch.object(brain, "_call_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "chat"
            result = await brain.classify_intent("你好呀", "分类 prompt")
            assert result == "chat"
            # 验证低温度、低 token 参数被正确传递
            call_args = mock_call.call_args[0][0]
            assert call_args[0]["content"] == "分类 prompt"
            assert call_args[1]["content"] == "你好呀"
            assert mock_call.call_args[1] == {
                "temperature": 0.1,
                "max_tokens": 10,
                "timeout": 5,
            }

    @pytest.mark.asyncio
    async def test_fallback_on_provider_failure(self, monkeypatch):
        """测试 Provider 容灾：第一个失败，第二个成功"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key1")
        from core.brain import AIBrain
        from openai import AsyncOpenAI
        from unittest.mock import AsyncMock, MagicMock

        brain = AIBrain({})
        messages = [{"role": "user", "content": "测试"}]

        # 模拟两个 provider：第一个抛异常，第二个成功
        mock_client_bad = MagicMock(spec=AsyncOpenAI)
        mock_client_bad.chat = MagicMock()
        mock_client_bad.chat.completions = MagicMock()
        mock_client_bad.chat.completions.create = AsyncMock(
            side_effect=Exception("服务不可用")
        )

        mock_client_good = MagicMock(spec=AsyncOpenAI)
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "备用回复"
        mock_client_good.chat.completions.create = AsyncMock(return_value=mock_resp)

        brain._providers = [
            {"name": "bad", "client": mock_client_bad, "model": "test"},
            {"name": "good", "client": mock_client_good, "model": "test"},
        ]

        result = await brain._call_api(messages)
        assert result == "备用回复"
        # 验证两个 provider 都被尝试了
        mock_client_bad.chat.completions.create.assert_called_once()
        mock_client_good.chat.completions.create.assert_called_once()

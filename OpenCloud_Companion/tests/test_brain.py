"""AI 核心模块单元测试"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from communication.message import IncomingMessage, MessageType, Sender
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

        # 临时清空环境变量
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

    def test_build_system_prompt(self):
        """测试 System Prompt 构建"""
        from core.brain import AIBrain

        persona = {
            "name": "测试小助手",
            "core_traits": {
                "basic_personality": "友善、乐于助人",
                "speaking_style": "热情洋溢",
                "attitude": "积极乐观",
                "emotional_expression": "开心时多说话",
            },
            "communication": {
                "addresses_you_as": "老板",
                "emoticon_frequency": "很少用颜文字",
                "sentence_style": "正式得体",
            },
        }

        # 需要至少一个 API key 来实例化
        import os

        os.environ["ZHIPUAI_API_KEY"] = "test-key"
        try:
            brain = AIBrain({}, persona=persona)
            prompt = brain.system_prompt
            assert "测试小助手" in prompt
            assert "友善、乐于助人" in prompt
            assert "热情洋溢" in prompt
            assert "老板" in prompt
            assert "正式得体" in prompt
        finally:
            del os.environ["ZHIPUAI_API_KEY"]

    def test_init_with_siliconflow_key(self, monkeypatch):
        """测试硅基流动 API Key 初始化"""
        monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test-siliconflow")
        from core.brain import AIBrain

        brain = AIBrain({})
        assert len(brain._providers) == 1
        assert brain._providers[0]["name"] == "siliconflow"

    def test_format_reply(self):
        """测试格式化回复"""
        import os
        from core.brain import AIBrain

        os.environ["ZHIPUAI_API_KEY"] = "test-key"
        try:
            brain = AIBrain({})
            msg = sample_msg("测试消息")
            reply = brain.format_reply(msg, "这是 AI 回复")
            assert reply.user_id == 3489352115
            assert reply.content == "这是 AI 回复"
            assert reply.msg_type == MessageType.PRIVATE
        finally:
            del os.environ["ZHIPUAI_API_KEY"]

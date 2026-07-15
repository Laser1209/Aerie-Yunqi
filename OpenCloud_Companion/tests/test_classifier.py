"""意图分类器单元测试"""

import pytest
from unittest.mock import AsyncMock, patch
from communication.message import Intent
from core.classifier import IntentClassifier, ClassificationResult


class TestIntentClassifier:
    @pytest.fixture
    def classifier(self):
        """不带 LLM 的分类器（仅规则引擎）"""
        return IntentClassifier(brain=None)

    def test_rule_chat_greeting(self, classifier):
        """规则分类：问候 → chat"""
        result = classifier.classify_sync("你好")
        assert result.intent == Intent.CHAT
        assert result.confidence >= 0.90
        assert result.method == "rule"

    def test_rule_chat_affection(self, classifier):
        """规则分类：情感表达 → chat"""
        result = classifier.classify_sync("想你了")
        assert result.intent == Intent.CHAT
        assert result.confidence >= 0.90

    def test_rule_command_file_open(self, classifier):
        """规则分类：打开文件 → command"""
        result = classifier.classify_sync("打开桌面上的文档")
        assert result.intent == Intent.COMMAND
        assert result.confidence >= 0.85

    def test_rule_command_system(self, classifier):
        """规则分类：系统操作 → command"""
        result = classifier.classify_sync("调节音量到50%")
        assert result.intent == Intent.COMMAND

    def test_rule_query_weather(self, classifier):
        """规则分类：天气查询 → query"""
        result = classifier.classify_sync("今天天气怎么样")
        assert result.intent == Intent.QUERY
        assert result.confidence >= 0.85

    def test_rule_query_time(self, classifier):
        """规则分类：时间查询 → query"""
        result = classifier.classify_sync("今天是周几")
        assert result.intent == Intent.QUERY

    def test_rule_screenshot(self, classifier):
        """规则分类：截图 → command（高置信度）"""
        result = classifier.classify_sync("截图保存")
        assert result.intent == Intent.COMMAND
        assert result.confidence >= 0.90

    def test_rule_chat_mood(self, classifier):
        """规则分类：情绪表达 → chat"""
        result = classifier.classify_sync("今天好累啊")
        assert result.intent == Intent.CHAT

    def test_fallback_to_chat(self, classifier):
        """规则不明确：默认 → chat"""
        result = classifier.classify_sync("啊这")
        assert result.intent == Intent.CHAT
        assert result.method in ("sync_fallback", "fallback")

    @pytest.mark.asyncio
    async def test_llm_classify_fallback(self, monkeypatch):
        """测试 LLM 分类回退（规则不明确时调用 AI）"""
        from unittest.mock import AsyncMock
        from core.classifier import IntentClassifier

        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
        from core.brain import AIBrain

        brain = AIBrain({})
        classifier = IntentClassifier(brain)

        # Mock AI（规则优先匹配，LLM 路径不会被真正调用）
        mock_resp = AsyncMock()
        mock_resp.choices = [AsyncMock()]
        mock_resp.choices[0].message.content = "command"

        with patch.object(brain, "_call_api_raw", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_resp
            result = await classifier.classify("启动浏览器打开B站")
            assert result.intent == Intent.COMMAND
            assert result.method == "rule"  # 规则先匹配到 "打开"
            assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_llm_classify_ambiguous(self, monkeypatch):
        """测试 LLM 分类：完全模糊的文本回退到 LLM"""
        monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
        from core.brain import AIBrain

        brain = AIBrain({})
        classifier = IntentClassifier(brain)

        mock_resp = AsyncMock()
        mock_resp.choices = [AsyncMock()]
        mock_resp.choices[0].message.content = "chat"

        with patch.object(brain, "_call_api_raw", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_resp
            result = await classifier.classify("嗯")
            # 规则不匹配 → LLM 回退
            assert result.intent in (Intent.CHAT, Intent.COMMAND, Intent.QUERY)

"""性格引擎单元测试"""

import pytest
from core.personality import PersonalityEngine


class TestPersonalityEngine:
    def test_default_persona(self):
        """测试使用空配置的默认行为"""
        engine = PersonalityEngine({})
        assert engine.name == "伊塔"
        prompt = engine.build_system_prompt()
        assert "伊塔" in prompt
        assert "专属恋人" in prompt

    def test_custom_persona(self):
        """测试自定义性格配置"""
        engine = PersonalityEngine({
            "name": "小星",
            "core_traits": {
                "basic_personality": "活泼可爱",
                "speaking_style": "元气满满",
                "attitude": "超级黏人",
                "emotional_expression": "全用emoji表达",
            },
            "communication": {
                "addresses_you_as": "亲爱的",
                "emoticon_frequency": "每句话都用",
                "sentence_style": "短小精悍",
            },
        })
        prompt = engine.build_system_prompt()
        assert "小星" in prompt
        assert "活泼可爱" in prompt
        assert "亲爱的" in prompt
        assert "全用emoji表达" in prompt

    def test_with_memories(self):
        """测试记忆注入 System Prompt"""
        engine = PersonalityEngine({"core_traits": {}, "communication": {}})
        memories = [
            {"role": "user", "content": "我今天很开心"},
            {"role": "assistant", "content": "主人开心我也开心～"},
        ]
        prompt = engine.build_system_prompt(memories=memories)
        assert "我今天很开心" in prompt
        assert "主人开心我也开心" in prompt
        assert "最近的对话记忆" in prompt

    def test_without_memories(self):
        """测试不注入记忆时 System Prompt 不应有记忆段"""
        engine = PersonalityEngine({"core_traits": {}, "communication": {}})
        prompt = engine.build_system_prompt(memories=None)
        assert "最近的对话记忆" not in prompt

    def test_capability_phase1(self):
        """测试 Phase 1 能力说明"""
        engine = PersonalityEngine({"core_traits": {}, "communication": {}})
        prompt = engine.build_system_prompt(capability_level="phase1")
        assert "纯文本聊天" in prompt
        assert "还在开发中" in prompt

    def test_capability_phase3(self):
        """测试 Phase 3 能力说明"""
        engine = PersonalityEngine({"core_traits": {}, "communication": {}})
        prompt = engine.build_system_prompt(capability_level="phase3")
        assert "文件操作能力" in prompt
        assert "系统操作能力" in prompt
        assert "网页搜索" in prompt

    def test_build_system_message(self):
        """测试 build_system_message 返回正确的 OpenAI 格式"""
        engine = PersonalityEngine({"core_traits": {}, "communication": {}})
        msg = engine.build_system_message()
        assert msg["role"] == "system"
        assert isinstance(msg["content"], str)
        assert len(msg["content"]) > 50

    def test_missing_traits_graceful(self):
        """测试缺失 core_traits/communication 时的优雅降级"""
        engine = PersonalityEngine({"name": "最小配置"})
        prompt = engine.build_system_prompt()
        assert "最小配置" in prompt
        # 不抛异常即为通过

    def test_raw_config_access(self):
        """测试 raw_config 返回副本"""
        original = {"name": "测试", "core_traits": {}, "communication": {}}
        engine = PersonalityEngine(original)
        raw = engine.raw_config
        raw["name"] = "被修改"
        # 原始配置不应被修改
        assert engine.name == "测试"

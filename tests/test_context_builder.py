"""Tests for ContextBuilder v9.0 — four-layer persona system prompt."""

import pytest

from core.context_builder import ContextBuilder


class TestContextBuilderModes:
    """Test system prompt assembly per route mode."""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_build_full_mode_includes_all_layers(self, builder):
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "伊塔" in system
        assert "四爱主导位" in system  # L2
        assert "语言风格铁律" in system  # L4

    def test_build_auto_mode_excludes_l2(self, builder):
        msgs = builder.build(3489352115, "你好", "AUTO")
        system = msgs[0]["content"]
        assert "伊塔" in system  # L1
        assert "四爱主导位" not in system  # L2 excluded
        assert "语言风格铁律" in system  # L4

    def test_build_basic_mode_l1_only(self, builder):
        msgs = builder.build(99999, "你好", "BASIC")
        system = msgs[0]["content"]
        assert "伊塔" in system  # L1
        assert "四爱主导位" not in system  # L2 excluded
        assert "语言风格铁律" not in system  # L4 excluded

    def test_build_returns_list_of_role_content_dicts(self, builder):
        msgs = builder.build(3998874040, "测试消息", "FULL")
        assert isinstance(msgs, list)
        assert len(msgs) >= 2
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "测试消息"


class TestContextBuilderEmotion:
    """Test emotion info injection."""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_build_injects_emotion_info_full_mode(self, builder):
        emotion_info = {
            "label": "joy",
            "pad": {"P": 0.6, "A": 0.5, "D": 0.3},
            "thresholds": {
                "patience": {"value": 10, "threshold": 100, "label": "忍耐值", "pct": 10},
            },
        }
        msgs = builder.build(3998874040, "你好", "FULL", emotion_info=emotion_info)
        system = msgs[0]["content"]
        assert "基本情绪" in system
        assert "joy" in system

    def test_build_injects_threshold_info(self, builder):
        emotion_info = {
            "label": "neutral",
            "pad": {"P": 0.0, "A": 0.0, "D": 0.0},
            "thresholds": {
                "patience": {"value": 80, "threshold": 100, "label": "忍耐值", "pct": 80},
                "anxiety": {"value": 30, "threshold": 100, "label": "不安值", "pct": 30},
            },
        }
        msgs = builder.build(3998874040, "不用你管", "FULL", emotion_info=emotion_info)
        system = msgs[0]["content"]
        assert "隐藏槽位" in system
        assert "忍耐值" in system

    def test_build_auto_mode_skips_emotion_info(self, builder):
        emotion_info = {"label": "joy", "pad": {"P": 0.6, "A": 0.5, "D": 0.3}}
        msgs = builder.build(3489352115, "你好", "AUTO", emotion_info=emotion_info)
        system = msgs[0]["content"]
        assert "基本情绪" not in system

    def test_build_basic_mode_skips_emotion_info(self, builder):
        emotion_info = {"label": "joy", "pad": {"P": 0.6, "A": 0.5, "D": 0.3}}
        msgs = builder.build(99999, "你好", "BASIC", emotion_info=emotion_info)
        system = msgs[0]["content"]
        assert "基本情绪" not in system


class TestContextBuilderEruption:
    """Test eruption mode injection into system prompt."""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_build_injects_patience_eruption(self, builder):
        eruption_info = {"slot": "patience", "mode": "冷暴模式"}
        msgs = builder.build(3998874040, "你好", "FULL", eruption_info=eruption_info)
        system = msgs[0]["content"]
        assert "冷暴" in system
        assert "≤3字" in system

    def test_build_injects_anxiety_eruption(self, builder):
        eruption_info = {"slot": "anxiety", "mode": "坍塌模式"}
        msgs = builder.build(3998874040, "你在哪", "FULL", eruption_info=eruption_info)
        system = msgs[0]["content"]
        assert "坍塌" in system
        assert "病娇" in system

    def test_build_injects_desire_eruption(self, builder):
        eruption_info = {"slot": "desire", "mode": "索求模式"}
        msgs = builder.build(3998874040, "过来", "FULL", eruption_info=eruption_info)
        system = msgs[0]["content"]
        assert "索求" in system

    def test_build_injects_tenderness_eruption(self, builder):
        eruption_info = {"slot": "tenderness", "mode": "反扑模式"}
        msgs = builder.build(3998874040, "你好温柔", "FULL", eruption_info=eruption_info)
        system = msgs[0]["content"]
        assert "反扑" in system
        assert "失语" in system

    def test_build_no_eruption_info_no_injection(self, builder):
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "情绪爆发" not in system


class TestContextBuilderHistory:
    """Test history message handling."""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_build_full_mode_history_limit_8(self, builder):
        history = [{"role": "user", "content": f"msg_{i}"} for i in range(20)]
        msgs = builder.build(3998874040, "最新", "FULL", history_msgs=history)
        # 1 system + last 8 history + 1 user = 10 total
        assert len(msgs) <= 10

    def test_build_auto_mode_history_limit_5(self, builder):
        history = [{"role": "user", "content": f"msg_{i}"} for i in range(20)]
        msgs = builder.build(3489352115, "最新", "AUTO", history_msgs=history)
        assert len(msgs) <= 7  # 1 system + max 5 history + 1 user

    def test_build_basic_mode_no_history(self, builder):
        history = [{"role": "user", "content": f"msg_{i}"} for i in range(20)]
        msgs = builder.build(99999, "最新", "BASIC", history_msgs=history)
        # Should be 1 system + 1 user (no history)
        assert len(msgs) == 2

    def test_build_no_history_works(self, builder):
        msgs = builder.build(3998874040, "你好", "FULL")
        assert len(msgs) == 2  # system + user only


class TestContextBuilderPersona9_10:
    """R8.1 (Persona 9/10): 守门 9/10 基线在 L1/L2/L4 都已显式标注，
    防止未来无意改回 7/10（暗涌克制版）。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_persona_l1_marks_9_10_baseline(self, builder):
        """_PERSONA_L1 必须显式标注 9/10 基线。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "9/10" in system, "L1 must include 9/10 baseline marker"
        # 验证 extraversion 数值
        assert "0.78" in system, "L1 must include 0.78 extraversion value"
        assert "extraversion" in system.lower() or "外向" in system

    def test_persona_l2_has_direct_expression(self, builder):
        """_PERSONA_L2 必须含 9/10 直球表达关键词。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        # 至少含 "不许不接" 或 "直球" 之一
        assert ("不许不接" in system) or ("直球" in system), \
            "L2 must include direct-expression markers (不许不接/直球)"

    def test_persona_l4_has_screen_aware_9_10(self, builder):
        """_PERSONA_L4 必须含屏幕隔空铁律 + 9/10 基线。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "屏幕隔空" in system, "L4 must include 屏幕隔空 iron rule"
        # 9/10 或 "9 分" 任一即可
        assert ("9/10" in system) or ("9 分" in system), \
            "L4 must include 9/10 baseline marker"

    def test_full_mode_includes_all_9_10_layers(self, builder):
        """FULL 模式下 L1/L2/L4 三层都应该含 9/10 信号。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        # 至少 3 处 "9/10" 出现（L1 + L2 + L4）
        count = system.count("9/10")
        assert count >= 3, f"FULL mode system prompt should have ≥3 '9/10' markers, got {count}"

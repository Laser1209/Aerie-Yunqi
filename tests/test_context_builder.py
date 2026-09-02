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
        assert "Aerie Companion" in system
        assert "关系定位" in system  # L2
        assert "语言风格铁律" in system  # L4

    def test_build_auto_mode_excludes_l2(self, builder):
        msgs = builder.build(3489352115, "你好", "AUTO")
        system = msgs[0]["content"]
        assert "Aerie Companion" in system  # L1
        assert "四爱主导位" not in system  # L2 excluded
        assert "语言风格铁律" in system  # L4

    def test_build_basic_mode_l1_only(self, builder):
        msgs = builder.build(99999, "你好", "BASIC")
        system = msgs[0]["content"]
        assert "Aerie Companion" in system  # L1
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


class TestContextBuilderPersonaBaseline:
    """商业默认 persona 的中性表达基线。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_persona_l1_marks_neutral_baseline(self, builder):
        """L1 必须显式标注中性热情度基线。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "3/10" in system, "L1 must include neutral baseline marker"
        assert "Aerie Companion" in system

    def test_persona_l2_has_boundary_expression(self, builder):
        """L2 必须表达中性关系和边界，不得注入亲密设定。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "关系定位" in system
        assert "尊重" in system
        assert "四爱主导位" not in system

    def test_persona_l4_has_screen_aware_neutral_baseline(self, builder):
        """L4 必须含屏幕隔空铁律 + 中性基线。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "屏幕隔空" in system, "L4 must include 屏幕隔空 iron rule"
        assert ("3/10" in system) or ("3 分" in system), \
            "L4 must include neutral baseline marker"

    def test_full_mode_includes_all_neutral_layers(self, builder):
        """FULL 模式下应包含 L1/L2/L4 的中性信号。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert system.count("3/10") >= 3


class TestContextBuilderTimePerception:
    """时间感知修复：时间快照含时分+中文时段、world phase 中文映射、历史带时间前缀。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_time_snapshot_includes_datetime_and_period(self, builder):
        time_context = {
            "date": "2026-08-09",
            "datetime": "2026-08-09 16:48",
            "time_period_cn": "下午",
            "today_events": [],
            "today_todos": [],
            "upcoming_anniversaries": [],
        }
        msgs = builder.build(3998874040, "看看腿我就去", "FULL", time_context=time_context)
        system = msgs[0]["content"]
        assert "当前时间：2026-08-09 16:48" in system
        assert "当前时段：下午" in system

    def test_world_phase_mapped_to_chinese(self, builder):
        world_snapshot = {
            "phase": "afternoon",
            "location": "studio",
            "activity": "drawing",
            "energy": 0.5,
        }
        msgs = builder.build(3998874040, "看看腿我就去", "FULL", world_snapshot=world_snapshot)
        system = msgs[0]["content"]
        assert "时段：下午" in system
        assert "afternoon" not in system

    def test_history_messages_get_timestamp_prefix(self, builder):
        history = [
            {"role": "user", "content": "我睡觉去了", "created_at": "2026-08-09 04:06:47"},
            {"role": "assistant", "content": "晚安", "created_at": "2026-08-09 04:06:47"},
        ]
        msgs = builder.build(3998874040, "看看腿我就去", "FULL", history_msgs=history)
        contents = [m["content"] for m in msgs[1:-1]]
        assert "[08-09 04:06] 我睡觉去了" in contents
        assert "[08-09 04:06] 晚安" in contents

    def test_history_without_timestamp_unchanged(self, builder):
        history = [{"role": "user", "content": "没有时间的消息"}]
        msgs = builder.build(3998874040, "看看腿我就去", "FULL", history_msgs=history)
        contents = [m["content"] for m in msgs[1:-1]]
        assert "没有时间的消息" in contents


class TestContextBuilderImageCapability:
    """L6 · 图片能力认知段注入行为验证。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_full_mode_includes_expression_hierarchy(self, builder):
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "表达层次认知" in system
        assert "表情包" in system and "虚拟世界的存在感" in system
        assert "语言的调味剂" in system

    def test_auto_mode_includes_expression_hierarchy(self, builder):
        msgs = builder.build(3489352115, "你好", "AUTO")
        system = msgs[0]["content"]
        assert "表达层次认知" in system

    def test_basic_mode_excludes_expression_hierarchy(self, builder):
        msgs = builder.build(99999, "你好", "BASIC")
        system = msgs[0]["content"]
        assert "表达层次认知" not in system

    def test_existing_layers_unchanged(self, builder):
        """兼容性：L6 注入不破坏 L1/L2/L4/L5 既有内容。"""
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "Aerie Companion" in system  # L1
        assert "语言风格铁律" in system  # L4
        # L6 作为独立段追加在 L5 之后
        assert system.index("表达层次认知") > system.index("语言风格铁律")

    def test_l6_serializes_as_distinct_segment(self, builder):
        """L6 用独立标题分隔，与其它层保持一致的分段风格。"""
        text = ContextBuilder._build_l6_image_capability()
        assert text.startswith("【表达层次认知 · Expression Hierarchy】")
        assert "适度主动" in text
        assert "语言的调味剂" in text and "虚拟世界的存在感" in text

    def test_capability_flag_off_skips_injection(self, builder, monkeypatch):
        """关闭 world_image_candidates_v1 时，L6 不应注入（兼容性）。"""
        monkeypatch.setenv("AERIE_FEATURE_WORLD_IMAGE_CANDIDATES_V1", "false")
        msgs = builder.build(3998874040, "你好", "FULL")
        system = msgs[0]["content"]
        assert "表达层次认知" not in system


class TestExpressionHierarchyIntent:
    """L6 表达层次：验证"表情包=语言调味 / 图片=虚拟存在"的意图分层检测。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_image_intent_ranked_above_sticker(self, builder):
        """同时含图片+表情包关键词时，应优先标记为图片层级。"""
        hint = builder._detect_image_intent("发张你的自拍还有表情包", [])
        assert hint is not None
        assert "层级[图片image]" in hint

    def test_sticker_intent_detected(self, builder):
        hint = builder._detect_image_intent("发个表情包给我", [])
        assert hint is not None
        assert "层级[表情包sticker]" in hint

    def test_image_intent_detected_selfie(self, builder):
        hint = builder._detect_image_intent("想看你的样子，自拍一张", [])
        assert "层级[图片image]" in hint
        assert "自拍" in hint

    def test_no_intent_returns_none(self, builder):
        assert builder._detect_image_intent("今天天气不错", []) is None

    def test_history_image_intent_detected(self, builder):
        hint = builder._detect_image_intent("", [{"role": "user", "content": "发张你的照片"}])
        assert "层级[图片image]" in hint
        assert "发张你的" in hint

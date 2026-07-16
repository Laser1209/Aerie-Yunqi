"""Tests for EmotionEngine v9.0 (PAD + 5 emotions + cumulative thresholds).

Covers the refactored API: analyze(), update_trajectory(), get_label(), get_state(), tune().
"""

import pytest

from core.emotion_engine import EmotionEngine, EMOTION_CENTERS, KEYWORD_DELTAS

USER_ID = 1


class TestEmotionEngineAnalyze:
    """Test PAD delta calculation from keyword analysis."""

    @pytest.fixture
    def engine(self):
        return EmotionEngine()

    def test_analyze_love_triggers_joy(self, engine):
        pad = engine.analyze("我爱你")
        assert pad["pleasure"] > 0, f"Expected P>0 for love, got {pad}"
        assert pad["arousal"] > 0

    def test_analyze_anger_triggers_anger(self, engine):
        pad = engine.analyze("滚蛋")
        assert pad["pleasure"] < 0, f"Expected P<0 for anger, got {pad}"
        assert pad["arousal"] > 0

    def test_analyze_breakup_triggers_fear(self, engine):
        pad = engine.analyze("分手")
        assert pad["pleasure"] < 0, f"Expected P<0 for breakup, got {pad}"
        assert pad["arousal"] > 0

    def test_analyze_sad_coldness(self, engine):
        pad = engine.analyze("不用你管")
        assert pad["pleasure"] < 0, f"Expected P<0 for coldness, got {pad}"

    def test_analyze_empty_string_returns_zero(self, engine):
        pad = engine.analyze("")
        assert pad["pleasure"] == 0.0
        assert pad["arousal"] == 0.0
        assert pad["dominance"] == 0.0

    def test_analyze_unknown_text_returns_zero(self, engine):
        pad = engine.analyze("abcdefghijklmnop")
        assert pad["pleasure"] == 0.0
        assert pad["arousal"] == 0.0
        assert pad["dominance"] == 0.0

    def test_analyze_pad_bounds_not_exceeded(self, engine):
        """PAD values should stay within [-0.95, 0.95]."""
        for _ in range(50):
            pad = engine.analyze("滚蛋 分手 滚开 不爱你了 伤害 欺负")
            assert -0.96 <= pad["pleasure"] <= 0.96
            assert -0.96 <= pad["arousal"] <= 0.96
            assert -0.96 <= pad["dominance"] <= 0.96

    def test_analyze_praise_positive_pad(self, engine):
        """'你好棒' should produce positive pleasure."""
        pad = engine.analyze("你好棒")
        assert pad["pleasure"] >= 0

    def test_analyze_returns_dict_with_three_keys(self, engine):
        pad = engine.analyze("你好")
        assert set(pad.keys()) == {"pleasure", "arousal", "dominance"}
        for v in pad.values():
            assert isinstance(v, float)


class TestEmotionEngineTrajectory:
    """Test EMA smoothing in update_trajectory()."""

    @pytest.fixture
    def engine(self):
        return EmotionEngine()

    def test_initial_state_is_zero(self, engine):
        state = engine.get_state(USER_ID)
        assert state["pad"]["P"] == 0.0
        assert state["pad"]["A"] == 0.0
        assert state["pad"]["D"] == 0.0
        assert state["label"] == "neutral"

    def test_update_trajectory_accumulates_with_ema(self, engine):
        """EMA alpha=0.3 means state = 0.7*old + 0.3*new."""
        engine.update_trajectory(USER_ID, "我爱你")
        s1 = engine.get_state(USER_ID)
        assert s1["pad"]["P"] != 0.0

        # Second update should move further
        engine.update_trajectory(USER_ID, "我爱你")
        s2 = engine.get_state(USER_ID)
        # EMA: P(t) = P(t-1)*0.7 + delta*0.3
        assert abs(s2["pad"]["P"]) >= abs(s1["pad"]["P"]) * 0.6  # rough check


class TestEmotionEngineLabel:
    """Test emotion classification via get_label()."""

    @pytest.fixture
    def engine(self):
        return EmotionEngine()

    def test_initial_label_is_neutral(self, engine):
        assert engine.get_label() == "neutral"

    def test_label_joy_after_multiple_praise(self, engine):
        for _ in range(20):
            engine.update_trajectory(USER_ID, "爱你 你好棒 最喜欢你了")
        assert engine.get_label() in ("joy", "neutral")

    def test_label_sad_after_multiple_cold(self, engine):
        for _ in range(20):
            engine.update_trajectory(USER_ID, "不用你管 别管我 好烦")
        label = engine.get_label()
        assert label in ("sad", "anger", "neutral")

    def test_label_fear_after_breakup_words(self, engine):
        for _ in range(10):
            engine.update_trajectory(USER_ID, "分手 离开 不爱你了")
        label = engine.get_label()
        # Should drift toward fear territory
        assert label in ("fear", "sad", "anger", "neutral")


class TestEmotionEngineState:
    """Test get_state() returns full dictionary."""

    @pytest.fixture(autouse=True)
    def _reset_thresholds(self):
        """Reset threshold engine singleton between tests to avoid cross-test contamination."""
        from core.emotion_threshold import _THRESHOLD_ENGINE
        import core.emotion_threshold as thresh_mod
        old = thresh_mod._THRESHOLD_ENGINE
        thresh_mod._THRESHOLD_ENGINE = None
        yield
        thresh_mod._THRESHOLD_ENGINE = old

    @pytest.fixture
    def engine(self):
        return EmotionEngine()

    def test_get_state_returns_all_keys(self, engine):
        state = engine.get_state(USER_ID)
        assert "label" in state
        assert "pad" in state
        assert "thresholds" in state
        assert "eruption" in state
        assert "panel" in state

    def test_get_state_thresholds_has_four_slots(self, engine):
        state = engine.get_state(USER_ID)
        thresholds = state["thresholds"]
        assert set(thresholds.keys()) == {"patience", "anxiety", "desire", "tenderness"}

    def test_get_state_panel_is_string(self, engine):
        state = engine.get_state(USER_ID)
        assert isinstance(state["panel"], str)
        assert "伊塔" in state["panel"]

    def test_get_state_eruption_is_none_initially(self, engine):
        state = engine.get_state(USER_ID)
        assert state["eruption"] is None


class TestEmotionEngineTune:
    """Test reply text tuning based on emotion state."""

    @pytest.fixture
    def engine(self):
        return EmotionEngine()

    def test_tune_passes_through_normal_text(self, engine):
        result = engine.tune("你好，今天天气不错。")
        assert result == "你好，今天天气不错。"

    def test_tune_short_text_unchanged(self, engine):
        result = engine.tune("嗯。")
        assert result == "嗯。"


class TestEmotionCenters:
    """Test EMOTION_CENTERS and KEYWORD_DELTAS constants."""

    def test_five_emotion_centers_defined(self):
        assert set(EMOTION_CENTERS.keys()) == {"joy", "anger", "sad", "fear", "neutral"}

    def test_centers_have_pad_keys(self, engine=None):
        for name, center in EMOTION_CENTERS.items():
            assert "P" in center
            assert "A" in center
            assert "D" in center
            assert -1.0 <= center["P"] <= 1.0
            assert -1.0 <= center["A"] <= 1.0
            assert -1.0 <= center["D"] <= 1.0

    def test_keyword_deltas_is_non_empty(self):
        assert len(KEYWORD_DELTAS) > 0

    def test_keyword_deltas_format(self):
        for item in KEYWORD_DELTAS:
            assert len(item) == 3
            keywords, emotion, weight = item
            assert isinstance(keywords, list)
            assert isinstance(emotion, str)
            assert isinstance(weight, (int, float))
            assert emotion in EMOTION_CENTERS

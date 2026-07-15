"""Tests for emotion engine (PAD + cumulative threshold)."""

import pytest

from core.emotion_engine import EmotionEngine, PADState
from core.emotion_threshold import CumulativeEmotionEngine

USER_ID = 1


class TestEmotionEngine:
    """Test PAD-based emotion engine."""

    @pytest.fixture
    def engine(self):
        return EmotionEngine()

    def test_initial_state(self, engine):
        state = engine.get_state(USER_ID)
        assert isinstance(state, PADState)
        assert state.pleasure == 0.0
        assert state.arousal == 0.0
        assert state.dominance == 0.5
        assert state.label == "neutral"

    def test_trigger_praise_adds_pleasure(self, engine):
        before = engine.get_state(USER_ID).pleasure
        engine.trigger("user_praise", USER_ID, 3)
        after = engine.get_state(USER_ID).pleasure
        assert after > before

    def test_trigger_cold_reduces_pleasure(self, engine):
        before = engine.get_state(USER_ID).pleasure
        engine.trigger("user_cold", USER_ID, 3)
        after = engine.get_state(USER_ID).pleasure
        assert after < before

    def test_trigger_attack(self, engine):
        before = engine.get_state(USER_ID).arousal
        engine.trigger("user_attack", USER_ID, 5)
        after = engine.get_state(USER_ID).arousal
        assert after > before

    def test_trigger_builds_label(self, engine):
        """Multiple praise events → label shifts toward joy eventually."""
        for _ in range(10):
            engine.trigger("user_praise", USER_ID, 5)
        state = engine.get_state(USER_ID)
        # After heavy praise, should be in joy or at least not sad
        assert state.pleasure > 0
        assert state.label in ("joy", "neutral")

    def test_multiple_events_accumulate(self, engine):
        before = engine.get_state(USER_ID).pleasure
        engine.trigger("user_praise", USER_ID, 2)
        engine.trigger("user_praise", USER_ID, 2)
        after = engine.get_state(USER_ID).pleasure
        assert after > before

    def test_get_label_with_pad_object(self, engine):
        pad = PADState(pleasure=0.5, arousal=0.3, dominance=0.3)
        label = engine.get_label(pad)
        assert label == "joy"

        pad2 = PADState(pleasure=-0.5, arousal=-0.2, dominance=0.0)
        label2 = engine.get_label(pad2)
        assert label2 == "sad"

    def test_get_current_mood(self, engine):
        mood = engine.get_current_mood(USER_ID)
        assert mood in ("joy", "sad", "anger", "fear", "neutral")


class TestCumulativeEmotionEngine:
    """Test 4-slot cumulative threshold system."""

    @pytest.fixture
    def cem(self):
        return CumulativeEmotionEngine()

    def test_four_slots_initialized(self, cem):
        slots = cem.get_all_slots(USER_ID)
        names = set(slots.keys())
        assert names == {"patience", "anxiety", "desire", "tenderness"}

    def test_add_increases_value(self, cem):
        cem.add(USER_ID, "patience", 30, "test")
        slot = cem.get_slot(USER_ID, "patience")
        assert slot.value == 30

    def test_add_under_threshold_no_eruption(self, cem):
        result = cem.add(USER_ID, "patience", 30, "test")
        # No eruption events at low value
        assert result["value"] == 30
        assert len(result["events"]) == 0

    def test_daily_decay_reduces_value(self, cem):
        cem.add(USER_ID, "patience", 30, "test")
        cem.add(USER_ID, "anxiety", 30, "test")
        cem.daily_decay(USER_ID)
        after = cem.get_slot(USER_ID, "patience").value
        assert after < 30

    def test_eruption_lowers_threshold(self, cem):
        result = cem.add(USER_ID, "patience", 200, "test_erupt")
        if result["events"]:
            slot = cem.get_slot(USER_ID, "patience")
            assert slot.threshold < 100.0  # Character wear
            assert len(slot.threshold_history) >= 2

    def test_get_panel_returns_string(self, cem):
        panel = cem.get_panel(USER_ID)
        assert isinstance(panel, str)
        assert "忍耐" in panel or "patience" in panel.lower()

    def test_add_allows_negative_value(self, cem):
        cem.add(USER_ID, "patience", -500, "clamp")
        assert cem.get_slot(USER_ID, "patience").value == -500

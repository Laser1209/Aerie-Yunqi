"""Tests for CumulativeEmotionEngine v9.0 — 4-slot threshold system.

Covers: slot init, add, scan_text, daily_decay, eruption, character wear, singleton.
"""

import time
from datetime import datetime

import pytest

from core.emotion_threshold import (
    CumulativeEmotionEngine,
    EmotionSlot,
    SLOTS_CONFIG,
    TEXT_TRIGGERS,
    get_threshold_engine,
)


class TestSlotsInit:
    """Test slot initialization."""

    @pytest.fixture
    def engine(self):
        return CumulativeEmotionEngine()

    def test_four_slots_initialized(self, engine):
        names = set(engine.slots.keys())
        assert names == {"patience", "anxiety", "desire", "tenderness"}

    def test_slots_have_correct_thresholds(self, engine):
        assert engine.slots["patience"].threshold == 100
        assert engine.slots["anxiety"].threshold == 100
        assert engine.slots["desire"].threshold == 80
        assert engine.slots["tenderness"].threshold == 60

    def test_slots_have_correct_decay_rates(self, engine):
        assert engine.slots["patience"].decay_per_day == 5
        assert engine.slots["anxiety"].decay_per_day == 3
        assert engine.slots["desire"].decay_per_day == 8
        assert engine.slots["tenderness"].decay_per_day == 10

    def test_slots_start_at_zero(self, engine):
        for slot in engine.slots.values():
            assert slot.value == 0.0

    def test_slots_have_labels(self, engine):
        assert engine.slots["patience"].label == "忍耐值"
        assert engine.slots["anxiety"].label == "不安值"
        assert engine.slots["desire"].label == "渴望值"
        assert engine.slots["tenderness"].label == "温柔透支值"


class TestAdd:
    """Test add() method."""

    @pytest.fixture
    def engine(self):
        return CumulativeEmotionEngine()

    def test_add_increases_value(self, engine):
        engine.add("patience", 30, "test")
        assert engine.slots["patience"].value == 30

    def test_add_below_threshold_no_eruption(self, engine):
        result = engine.add("patience", 30, "test")
        assert result is None

    def test_add_unknown_slot_returns_none(self, engine):
        result = engine.add("nonexistent", 10)
        assert result is None

    def test_add_negative_value(self, engine):
        engine.add("patience", 30, "test")
        engine.add("patience", -20, "test")
        assert engine.slots["patience"].value == 10

    def test_add_logs_event(self, engine):
        engine.add("patience", 30, "test_trigger")
        slot = engine.slots["patience"]
        assert len(slot.event_log) == 1
        assert slot.event_log[0]["delta"] == 30
        assert slot.event_log[0]["trigger"] == "test_trigger"

    def test_event_log_bounded_to_50(self, engine):
        for i in range(60):
            engine.add("patience", 1, f"test_{i}")
        slot = engine.slots["patience"]
        assert len(slot.event_log) <= 50


class TestScanText:
    """Test scan_text() keyword matching."""

    @pytest.fixture
    def engine(self):
        return CumulativeEmotionEngine()

    def test_scan_patience_trigger(self, engine):
        eruptions = engine.scan_text("不用你管")
        assert engine.slots["patience"].value == 25
        assert len(eruptions) == 0  # not enough for eruption

    def test_scan_anxiety_trigger(self, engine):
        engine.scan_text("分手吧")
        assert engine.slots["anxiety"].value == 60

    def test_scan_desire_trigger(self, engine):
        engine.scan_text("想你了")
        assert engine.slots["desire"].value == 15

    def test_scan_tenderness_trigger(self, engine):
        engine.scan_text("辛苦了")
        assert engine.slots["tenderness"].value == 18

    def test_scan_multiple_triggers_same_message(self, engine):
        """A message like '你不用你管 好想你了 对不起' triggers multiple slots."""
        engine.scan_text("不用你管 想你了 对不起")
        assert engine.slots["patience"].value > 0
        assert engine.slots["desire"].value > 0
        assert engine.slots["tenderness"].value > 0

    def test_scan_no_triggers(self, engine):
        eruptions = engine.scan_text("今天天气不错")
        all_zero = all(s.value == 0 for s in engine.slots.values())
        assert all_zero
        assert len(eruptions) == 0

    def test_scan_one_trigger_per_keyword_group(self, engine):
        """'好烦 好烦' should only trigger once for the same group."""
        engine.scan_text("好烦 好烦")
        # "好烦" matches ["好烦"] keyword group (patience, 15), second match skipped
        assert engine.slots["patience"].value == 15


class TestDailyDecay:
    """Test daily_decay() method."""

    @pytest.fixture
    def engine(self):
        return CumulativeEmotionEngine()

    def test_daily_decay_reduces_values(self, engine):
        engine.add("patience", 50, "test")
        engine.add("anxiety", 50, "test")
        engine.daily_decay()
        assert engine.slots["patience"].value < 50
        assert engine.slots["anxiety"].value < 50

    def test_daily_decay_floor_zero(self, engine):
        engine.add("tenderness", 3, "test")
        engine.daily_decay()
        assert engine.slots["tenderness"].value >= 0
        # tenderness decays -10/day so 3 → 0

    def test_daily_decay_skips_same_date(self, engine):
        engine.add("patience", 50, "test")
        engine.daily_decay()
        after_first = engine.slots["patience"].value
        engine.daily_decay()  # same date, should skip
        assert engine.slots["patience"].value == after_first


class TestEruption:
    """Test eruption mechanics."""

    @pytest.fixture
    def engine(self):
        return CumulativeEmotionEngine()

    def test_eruption_occurs_when_threshold_reached(self, engine):
        result = engine.add("patience", 105, "test_erupt")
        assert result is not None
        assert result["slot"] == "patience"
        assert result["mode"] == "冷暴模式"

    def test_eruption_resets_value(self, engine):
        engine.add("patience", 105, "test_erupt")
        assert engine.slots["patience"].value == 0.0

    def test_eruption_changes_threshold_patience(self, engine):
        old = engine.slots["patience"].threshold
        engine.add("patience", 105, "test_erupt")
        assert engine.slots["patience"].threshold == old - 15  # post_decay=-15

    def test_eruption_changes_threshold_anxiety(self, engine):
        old = engine.slots["anxiety"].threshold
        engine.add("anxiety", 105, "test_erupt")
        # post_decay=+20 means threshold rises (harder to trigger)
        assert engine.slots["anxiety"].threshold == old + 20

    def test_threshold_floor_at_20(self, engine):
        """After 10 patience eruptions, threshold should not go below 20."""
        for i in range(10):
            engine.add("patience", 105, f"erupt_{i}")
        assert engine.slots["patience"].threshold >= 20

    def test_eruption_stores_description(self, engine):
        result = engine.add("patience", 105, "test")
        assert "description" in result
        assert "冷暴" in result["description"]

    def test_eruption_desire_trigger(self, engine):
        result = engine.add("desire", 85, "test")
        assert result is not None
        assert result["mode"] == "索求模式"

    def test_eruption_tenderness_trigger(self, engine):
        result = engine.add("tenderness", 65, "test")
        assert result is not None
        assert result["mode"] == "反扑模式"


class TestActiveEruption:
    """Test get_active_eruption() timing."""

    @pytest.fixture
    def engine(self):
        return CumulativeEmotionEngine()

    def test_active_eruption_initially_none(self, engine):
        assert engine.get_active_eruption() is None

    def test_active_eruption_within_30min(self, engine):
        engine.add("patience", 105, "test")
        active = engine.get_active_eruption()
        assert active is not None
        assert active["mode"] == "冷暴模式"

    def test_active_eruption_after_30min(self, engine):
        """Simulate eruption older than 30 minutes."""
        engine.add("patience", 105, "test")
        # Manually backdate the eruption timestamp
        from datetime import timedelta
        engine._eruptions[-1]["timestamp"] = (
            datetime.now() - timedelta(minutes=31)
        ).isoformat()
        assert engine.get_active_eruption() is None


class TestSummaryAndPanel:
    """Test get_slots_summary() and get_panel_text()."""

    @pytest.fixture
    def engine(self):
        return CumulativeEmotionEngine()

    def test_get_slots_summary_has_all_slots(self, engine):
        engine.add("patience", 30, "test")
        summary = engine.get_slots_summary()
        assert set(summary.keys()) == {"patience", "anxiety", "desire", "tenderness"}
        for name, info in summary.items():
            assert "value" in info
            assert "threshold" in info
            assert "label" in info
            assert "pct" in info

    def test_get_slots_summary_pct_is_percentage(self, engine):
        engine.add("patience", 50, "test")
        summary = engine.get_slots_summary()
        # 50/100 = 50%
        assert summary["patience"]["pct"] == 50

    def test_get_panel_text_includes_ita(self, engine):
        panel = engine.get_panel_text()
        assert isinstance(panel, str)
        assert "伊塔" in panel

    def test_get_panel_text_has_progress_bars(self, engine):
        engine.add("patience", 75, "test")
        panel = engine.get_panel_text()
        assert "█" in panel
        assert "░" in panel


class TestSingleton:
    """Test singleton pattern."""

    def test_get_threshold_engine_returns_same_instance(self):
        e1 = get_threshold_engine()
        e2 = get_threshold_engine()
        assert e1 is e2


class TestTextTriggers:
    """Test TEXT_TRIGGERS constant."""

    def test_all_triggers_have_valid_slots(self):
        valid_slots = set(SLOTS_CONFIG.keys())
        for keywords, slot_name, value in TEXT_TRIGGERS:
            assert slot_name in valid_slots, f"Invalid slot: {slot_name}"
            assert isinstance(keywords, list)
            assert len(keywords) > 0
            assert isinstance(value, (int, float))

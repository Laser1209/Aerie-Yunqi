"""Tests for ContextBuilder 内在状态·模拟 注入（Task 3）."""

import pytest

from core.context_builder import ContextBuilder


def _metric(value: float) -> dict:
    return {"value": value, "source": "test", "confidence": 0.8}


def _internal_snapshot() -> dict:
    return {
        "sampledAt": 0,
        "label": "计算模型，非生物测量",
        "needs": {
            "social": _metric(0.8),
            "companion": _metric(0.7),
            "exploration": _metric(0.6),
            "rest": _metric(0.5),
        },
        "fatigue": _metric(0.42),
        "neurochemicals": {
            "vitality": _metric(0.66),
            "calm": _metric(0.55),
            "strain": _metric(0.23),
        },
    }


class TestContextBuilderInternalState:
    """Test 内在状态·模拟 注入块。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_full_mode_injects_internal_state(self, builder):
        msgs = builder.build(
            3998874040, "你好", "FULL", internal_snapshot=_internal_snapshot()
        )
        system = msgs[0]["content"]
        assert "【内在状态·模拟】" in system
        assert "需求：社交 0.80，陪伴 0.70，探索 0.60，休息 0.50" in system
        assert "疲劳：0.42" in system
        assert "活力 0.66（类多巴胺），平静 0.55（类血清素），压力 0.23（类皮质醇）" in system
        assert "只用于调节语气与主动性，不得向用户报数" in system

    def test_full_mode_skips_missing_need_type(self, builder):
        snapshot = _internal_snapshot()
        del snapshot["needs"]["rest"]
        msgs = builder.build(
            3998874040, "你好", "FULL", internal_snapshot=snapshot
        )
        system = msgs[0]["content"]
        assert "社交 0.80" in system
        assert "陪伴 0.70" in system
        assert "探索 0.60" in system
        assert "休息" not in system

    def test_none_snapshot_skips_injection(self, builder):
        msgs = builder.build(3998874040, "你好", "FULL", internal_snapshot=None)
        assert "内在状态" not in msgs[0]["content"]

    def test_non_full_mode_skips_injection(self, builder):
        msgs = builder.build(
            3489352115, "你好", "AUTO", internal_snapshot=_internal_snapshot()
        )
        assert "内在状态" not in msgs[0]["content"]

    def test_basic_mode_skips_injection(self, builder):
        msgs = builder.build(
            99999, "你好", "BASIC", internal_snapshot=_internal_snapshot()
        )
        assert "内在状态" not in msgs[0]["content"]
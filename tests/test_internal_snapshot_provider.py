"""Task 1: companion._internal_snapshot_for_context provider contract.

Verifies the internal-state provider mirrors self_model_snapshot_provider:
returns a snapshot with needs/fatigue/neurochemicals and is deterministic
for identical inputs. Uses a lightweight SimpleNamespace to avoid the heavy
full-Companion construction.
"""

from __future__ import annotations

from types import MethodType, SimpleNamespace

from core.companion import Companion
from core.internal_state import InternalStateEngine
from core.pipeline import Pipeline


def _make_context_companion():
    """Build a minimal companion exposing only the fields the provider needs."""
    engine = InternalStateEngine()
    companion = SimpleNamespace(
        internal_state=engine,
        get_primary_emotion_state=lambda: {"pad": {"P": 0.5, "A": 0.5, "D": 0.5}},
    )
    companion._internal_snapshot_for_context = MethodType(
        Companion._internal_snapshot_for_context,
        companion,
    )
    return companion


_WORLD = {"activity": "working", "phase": "day", "energy": 0.6}
_RELATIONSHIP = {"attachment": 0.7, "trust": 0.6, "security": 0.5, "conflict": 0.1}


def test_internal_snapshot_for_context_returns_expected_keys():
    """TR-1.1: 非空 world+relationship 输入 → 返回含 needs/fatigue/neurochemicals 的 dict。"""
    companion = _make_context_companion()
    snap = companion._internal_snapshot_for_context(_WORLD, _RELATIONSHIP)
    assert snap is not None
    assert "needs" in snap
    assert "fatigue" in snap
    assert "neurochemicals" in snap
    assert len(snap["needs"]) >= 1
    assert len(snap["neurochemicals"]) >= 1


def test_internal_snapshot_for_context_deterministic():
    """TR-1.2: 相同输入两次调用结果一致（确定性、可复现）。"""
    companion = _make_context_companion()
    snap1 = companion._internal_snapshot_for_context(_WORLD, _RELATIONSHIP)
    snap2 = companion._internal_snapshot_for_context(_WORLD, _RELATIONSHIP)
    assert snap1["needs"] == snap2["needs"]
    assert snap1["fatigue"] == snap2["fatigue"]
    assert snap1["neurochemicals"] == snap2["neurochemicals"]


def test_internal_snapshot_for_context_returns_none_when_engine_missing():
    """引擎不可用时返回 None（与 self_model 风格一致，异常/缺省安全）。"""
    companion = SimpleNamespace(
        internal_state=None,
        get_primary_emotion_state=lambda: {"pad": {"P": 0.5, "A": 0.5, "D": 0.5}},
    )
    companion._internal_snapshot_for_context = MethodType(
        Companion._internal_snapshot_for_context,
        companion,
    )
    assert companion._internal_snapshot_for_context(_WORLD, _RELATIONSHIP) is None


def test_pipeline_internal_snapshot_provider_unregistered_returns_none():
    """TR-2.1: provider 未注册时 _call_optional_context_provider 返回 None，不影响构建流程。"""
    pipeline = SimpleNamespace()
    pipeline._call_optional_context_provider = MethodType(
        Pipeline._call_optional_context_provider,
        pipeline,
    )
    assert pipeline._call_optional_context_provider(
        "internal_snapshot_provider", _WORLD, _RELATIONSHIP
    ) is None
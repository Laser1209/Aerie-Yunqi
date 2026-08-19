"""Unit tests for core/pad_tone_rules.py (Phase 0)."""

import pytest

from core.pad_tone_rules import band_of, classify

_HI, _MID, _LO = "高", "中", "低"


def test_band_of_boundaries():
    assert band_of(0.99) == "高"
    assert band_of(0.34) == "高"
    assert band_of(0.33) == "中"
    assert band_of(0.0) == "中"
    assert band_of(-0.33) == "中"
    assert band_of(-0.34) == "低"
    assert band_of(-0.99) == "低"


def test_classify_known_combos():
    r = classify({"pleasure": 0.7, "arousal": 0.6, "dominance": 0.5})
    assert r["key"] == (_HI_HI := ("高", "高", "高"))
    assert r["label"] == "兴致冲冲·占有型"
    assert r["fragment"]

    r2 = classify({"pleasure": -0.6, "arousal": 0.8, "dominance": -0.4})
    assert r2["key"] == ("低", "高", "低")
    assert r2["label"] == "心慌粘人型"


def test_classify_fallback_unknown_combo():
    # (中, 高, 低) 不在高频表 -> 走默认逐轴拼接
    r = classify({"pleasure": 0.0, "arousal": 0.5, "dominance": -0.4})
    assert r["key"] == ("中", "高", "低")
    assert r["label"] == "状态型组合"


def test_classify_none_and_neutral():
    r = classify(None)
    assert r["key"] == ("中", "中", "中")
    assert r["pad"] == {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0}


def test_classify_defaults_missing_keys():
    r = classify({"pleasure": 1.0})
    assert r["key"] == ("高", "中", "中")
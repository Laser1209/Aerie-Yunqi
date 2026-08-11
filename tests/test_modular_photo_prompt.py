"""TDD tests for the modular photo-spec prompt composer.

背景：旧实现里用户指令"看看腿"只被 VisualIntentRouter 路由成 role_selfie，
"腿/床上/躺/仰视"全部丢失，提示词永远以完整人物+固定场景为基准。
本测试验证：_extract_photo_spec 能从原始指令按维度提取主体/姿态/机位/场景/风格，
_compose_modular_prompt 把命中维度组合进基础提示词，且缺值兜底不返空串。
"""

from __future__ import annotations

from core.companion import _compose_modular_prompt, _extract_photo_spec


def _spec(text: str) -> dict:
    return _extract_photo_spec(text)


# ── 指令分析：主体识别 ───────────────────────────
def test_extract_focus_legs():
    assert _spec("看看腿")["focus"] == "双腿"


def test_extract_focus_no_keyword_returns_empty():
    assert _spec("拍一张")["focus"] == ""


# ── 多维度同时命中 ─────────────────────────────
def test_extract_multi_dimension():
    spec = _spec("在床上躺着，仰视低角度拍腿，要诱惑感")
    assert spec["focus"] == "双腿"
    assert spec["pose"] == "平躺"  # "躺着" 命中平躺
    assert spec["angle"] == "仰视低角度"
    assert spec["scene"] == "床上"
    assert spec["style"] == "诱惑感"


def test_extract_scene_bed():
    assert _spec("在床上")["scene"] == "床上"


# ── 组合器：命中维度拼进提示词 ─────────────────────
def test_compose_focus_legs():
    base = "一张写实生活照，人物是伊塔。"
    out = _compose_modular_prompt(base, _spec("看看腿"))
    assert "画面重点聚焦在双腿" in out
    assert "其余虚化" in out
    assert out.startswith(base)


def test_compose_bed_lying_angle():
    base = "一张写实生活照。"
    out = _compose_modular_prompt(base, _spec("在床上躺着，仰视低角度"))
    assert "场景是床上" in out
    assert "平躺" in out
    assert "仰视低角度" in out


# ── 缺值兜底：不命中任何维度 → 原样返回 base，绝不空串 ──────────
def test_compose_empty_spec_returns_base():
    base = "一张写实生活照，人物是伊塔。"
    assert _compose_modular_prompt(base, _spec("拍一张")) == base
    assert _compose_modular_prompt(base, {}) == base


def test_compose_none_base_never_empty():
    out = _compose_modular_prompt("", _spec("看看腿"))
    assert isinstance(out, str)
    assert len(out) > 0

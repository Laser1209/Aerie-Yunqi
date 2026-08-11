"""TDD tests for the modular photo-spec prompt composer.

背景：旧实现里用户指令"看看腿"只被 VisualIntentRouter 路由成 role_selfie，
"腿/床上/躺/仰视"全部丢失，提示词永远以完整人物+固定场景为基准。
本测试验证：_extract_photo_spec 能从原始指令按维度提取主体/姿态/机位/场景/风格，
_compose_modular_prompt 把命中维度组合进基础提示词，且缺值兜底不返空串。
"""

from __future__ import annotations

from core.companion import (
    _compose_modular_prompt,
    _extract_llm_json,
    _extract_photo_spec,
    _normalize_spec_value,
    _PHOTO_FOCUS_TABLE,
    _PHOTO_POSE_TABLE,
)


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


# ── 方向2：构图协同覆盖 ─────────────────────────
def test_focus_legs_auto_fills_pose():
    # 用户只给 focus（未给姿态）→ 自动补默认姿态"坐"，避免落回 base 固定场景
    out = _compose_modular_prompt("base", _spec("看看你的大腿"))
    assert "画面重点聚焦在双腿" in out
    assert "她坐着" in out


def test_explicit_pose_wins_over_coverage():
    # 用户显式给了"躺着"→ 尊重用户，不覆盖成"坐"
    spec = _spec("在床上躺着拍腿")
    assert spec["pose"] == "平躺"
    out = _compose_modular_prompt("base", spec)
    assert "她平躺着" in out
    assert "她坐着" not in out


def test_focus_back_auto_fills_angle():
    out = _compose_modular_prompt("base", _spec("给我看背影"))
    assert "拍摄机位：从后面" in out


def test_coverage_does_not_mutate_input():
    spec = _spec("看看你的大腿")
    snapshot = dict(spec)
    _compose_modular_prompt("base", spec)
    assert spec == snapshot


# ── 方向1：语义自补的辅助函数（LLM JSON 解析 + 标签归一化） ──────
def test_normalize_spec_value_exact_label():
    # LLM 返回完全一致的标签 → 直接命中
    assert _normalize_spec_value("双腿", _PHOTO_FOCUS_TABLE) == "双腿"


def test_normalize_spec_value_keyword_hit():
    # LLM 返回近似表述（如"腿部特写"）→ 关键词回退命中"双腿"
    assert _normalize_spec_value("腿部", _PHOTO_FOCUS_TABLE) == "双腿"


def test_normalize_spec_value_unknown_returns_empty():
    # LLM 返回未知标签（如"全身照"在 angle 表里找不到）→ 空串，防脏值
    assert _normalize_spec_value("全身照", _PHOTO_POSE_TABLE) == ""


def test_extract_llm_json_plain():
    assert _extract_llm_json('{"focus":"双腿","pose":"坐"}') == {
        "focus": "双腿",
        "pose": "坐",
    }


def test_extract_llm_json_with_fence():
    # 容忍 markdown 代码围栏
    out = _extract_llm_json('```json\n{"focus":"双腿"}\n```')
    assert out == {"focus": "双腿"}


def test_extract_llm_json_with_surrounding_text():
    # 容忍前后杂文
    out = _extract_llm_json('好的，这是分析结果：\n{"focus":"腿","pose":"坐"} 完毕')
    assert out == {"focus": "腿", "pose": "坐"}


def test_extract_llm_json_invalid_returns_none():
    assert _extract_llm_json("这不是 JSON") is None
    assert _extract_llm_json("") is None


def test_semantic_spec_compose_uses_llm_result():
    # 语义自补返回的 spec（如"看看腿"推断出 focus+pose+angle）直接组合进提示词，
    # 语义命中任一维度即视为有效，绝不被关键词表限制。
    spec = {"focus": "双腿", "pose": "坐", "angle": "特写", "scene": "", "style": ""}
    out = _compose_modular_prompt("base", spec)
    assert "画面重点聚焦在双腿" in out
    assert "她坐着" in out
    assert "拍摄机位：特写" in out

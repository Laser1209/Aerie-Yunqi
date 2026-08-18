"""验证 P4 模块化提示词：局部特写 vs 全身照的 base prompt 分支逻辑。

背景：P4 引入 _CLOSEUP_FOCUS_SET，当用户指定 focus 命中局部特写集合时，
base prompt 应走精简路线（「人物外貌以参考图为准」），不含身高/体重/三围/
杯数/发色/眼色等全身数据；而全身/无 focus/默认场景应走完整人设路线。

本测试通过直接调用 Companion._compose_base_image_prompt（实例方法）验证各分支。
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from core.companion import (
    _CLOSEUP_FOCUS_SET,
    _extract_photo_spec,
    _compose_modular_prompt,
    Companion,
)

# ── 测试用 persona fixture ──────────────────────────

_FAKE_PERSONA = {
    "persona": {
        "appearance": {
            "hair": "银灰色长发",
            "eyes": "深灰蓝色眼睛",
            "skin": "健康肤色",
        },
        "profile": {
            "height_cm": 184,
            "body_type": "身材修长",
            "measurements": "90-60-90",
            "weight_kg": 55,
            "body_fat_pct": 18,
            "cup_size": "C",
        },
    }
}

# 不应出现在局部特写 base 中的关键词
_FORBIDDEN_CLOSEUP_KEYWORDS = [
    "伊塔", "身高", "三围", "杯", "体重", "体脂率",
    "银灰色长发", "深灰蓝色眼睛",  # 发色、眼色
]


def _call(prompt_key: str, candidate: dict | None = None, spec: dict | None = None) -> str:
    """用 mock self 调用 _compose_base_image_prompt，patch load_persona。"""
    mock_self = MagicMock()
    with patch("config.persona_loader.load_persona", return_value=_FAKE_PERSONA):
        return Companion._compose_base_image_prompt(mock_self, prompt_key, candidate, spec=spec)


# ══════════════════════════════════════════════════════
# 1. _CLOSEUP_FOCUS_SET 完整性校验
# ══════════════════════════════════════════════════════

class TestCloseupFocusSet:
    def test_contains_expected_labels(self):
        expected = {"双腿", "双脚", "手", "腰", "肩颈锁骨", "背影", "头发", "脸庞", "眼睛"}
        assert expected == _CLOSEUP_FOCUS_SET

    def test_does_not_contain_full_body(self):
        assert "全身" not in _CLOSEUP_FOCUS_SET


# ══════════════════════════════════════════════════════
# 2. 局部特写场景：base 走精简路线
# ══════════════════════════════════════════════════════

class TestCloseupBasePrompt:
    """每个局部特写 focus 都应走精简 base，不含人设详细数据。"""

    @pytest.mark.parametrize(
        "user_raw, expected_focus",
        [
            ("看看手", "手"),
            ("看看腿", "双腿"),
            ("看看脚", "双脚"),
            ("看看锁骨", "肩颈锁骨"),
            ("拍个背影", "背影"),
        ],
    )
    def test_closeup_focus(self, user_raw: str, expected_focus: str):
        spec = {
            "focus": expected_focus,
            "pose": "",
            "angle": "",
            "scene": "",
            "style": "",
        }
        candidate = {"scene": "local_send", "user_raw": user_raw}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[{user_raw}] focus={expected_focus}")
        print(f"  => {result}")

        # 应包含精简 base 关键短语
        assert "人物外貌以参考图为准" in result, "局部特写应包含「人物外貌以参考图为准」"
        assert f"画面重点聚焦在{expected_focus}" in result, f"应包含「画面重点聚焦在{expected_focus}」"

        # 不应包含全身人设数据
        for kw in _FORBIDDEN_CLOSEUP_KEYWORDS:
            assert kw not in result, f"局部特写不应包含「{kw}」，实际输出: {result}"

    def test_closeup_hand_detail(self):
        """看看手 → 详细验证。"""
        spec = {"focus": "手", "pose": "", "angle": "", "scene": "", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "看看手"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[详细-看看手] => {result}")

        assert "人物外貌以参考图为准" in result
        assert "画面重点聚焦在手" in result
        assert "其余虚化" in result
        # 自拍 POV
        assert "手持手机" in result or "自拍" in result
        # 不应有伊塔
        assert "伊塔" not in result
        assert "身高" not in result

    def test_closeup_legs_detail(self):
        """看看腿 → 详细验证。"""
        spec = {"focus": "双腿", "pose": "", "angle": "", "scene": "", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "看看腿"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[详细-看看腿] => {result}")

        assert "画面重点聚焦在双腿" in result
        for kw in _FORBIDDEN_CLOSEUP_KEYWORDS:
            assert kw not in result

    def test_closeup_feet_detail(self):
        """看看脚 → 详细验证。"""
        spec = {"focus": "双脚", "pose": "", "angle": "", "scene": "", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "看看脚"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[详细-看看脚] => {result}")

        assert "画面重点聚焦在双脚" in result
        for kw in _FORBIDDEN_CLOSEUP_KEYWORDS:
            assert kw not in result

    def test_closeup_collarbone_detail(self):
        """看看锁骨 → 详细验证。"""
        spec = {"focus": "肩颈锁骨", "pose": "", "angle": "", "scene": "", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "看看锁骨"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[详细-看看锁骨] => {result}")

        assert "画面重点聚焦在肩颈锁骨" in result
        for kw in _FORBIDDEN_CLOSEUP_KEYWORDS:
            assert kw not in result

    def test_closeup_back_view_detail(self):
        """拍个背影 → 详细验证。"""
        spec = {"focus": "背影", "pose": "", "angle": "", "scene": "", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "拍个背影"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[详细-拍个背影] => {result}")

        assert "画面重点聚焦在背影" in result
        for kw in _FORBIDDEN_CLOSEUP_KEYWORDS:
            assert kw not in result

    def test_closeup_with_pose_and_angle(self):
        """局部特写 + 姿态 + 机位：modular 叠加应正常工作。"""
        spec = {"focus": "双腿", "pose": "坐", "angle": "仰视低角度", "scene": "床上", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "在床上坐着，仰视拍腿"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[局部+姿态+机位] => {result}")

        assert "画面重点聚焦在双腿" in result
        assert "人物外貌以参考图为准" in result
        # 模块化叠加：姿态、机位、场景
        assert "坐" in result
        # 不应有全身数据
        for kw in _FORBIDDEN_CLOSEUP_KEYWORDS:
            assert kw not in result


# ══════════════════════════════════════════════════════
# 3. 全身照场景：base 走完整人设
# ══════════════════════════════════════════════════════

class TestFullBodyBasePrompt:
    """focus=全身 或无 focus 时，base 应包含完整人设数据。"""

    def test_full_body_focus(self):
        """全身照 → spec.focus=全身，不在 _CLOSEUP_FOCUS_SET，走完整人设。"""
        spec = {"focus": "全身", "pose": "", "angle": "", "scene": "", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "全身照"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[全身照] => {result}")

        assert "伊塔" in result, "全身照应包含「伊塔」"
        assert "身高" in result, "全身照应包含身高"
        assert "184" in result, "全身照应包含身高数值"

    def test_no_focus_default_role_selfie(self):
        """无 focus、默认 role_selfie → 走完整人设。"""
        result = _call("role_selfie", candidate=None, spec=None)

        print(f"\n[默认 role_selfie] => {result}")

        assert "伊塔" in result, "默认 role_selfie 应包含「伊塔」"
        assert "身高" in result, "默认 role_selfie 应包含身高"
        assert "银灰色长发" in result, "默认 role_selfie 应包含发色"
        assert "深灰蓝色眼睛" in result, "默认 role_selfie 应包含眼色"

    def test_no_focus_role_in_scene(self):
        """无 focus、role_in_scene → 走完整人设。"""
        result = _call("role_in_scene", candidate=None, spec=None)

        print(f"\n[role_in_scene] => {result}")

        assert "伊塔" in result
        assert "身高" in result

    def test_full_body_includes_body_data(self):
        """全身照应包含三围/杯数/体重/体脂率等数据（persona 有值时）。"""
        spec = {"focus": "全身", "pose": "", "angle": "", "scene": "", "style": ""}
        candidate = {"scene": "local_send", "user_raw": "全身照"}
        result = _call("role_selfie", candidate=candidate, spec=spec)

        print(f"\n[全身照-身体数据] => {result}")

        assert "三围" in result
        assert "C杯" in result
        assert "体重" in result
        assert "体脂率" in result


# ══════════════════════════════════════════════════════
# 4. 环境/物件照：不含人物描述
# ══════════════════════════════════════════════════════

class TestEnvironmentBasePrompt:
    """environment_object → 第一人称视角，不含伊塔人物描述。"""

    def test_environment_no_person(self):
        result = _call("environment_object", candidate=None, spec=None)

        print(f"\n[environment_object] => {result}")

        assert "伊塔" not in result, "环境照不应包含「伊塔」"
        assert "身高" not in result, "环境照不应包含身高"
        assert "第一人称" in result, "环境照应包含第一人称视角"

    def test_environment_with_topic(self):
        """带 reason_code 的环境照。"""
        candidate = {"reason_code": "world_visual:object_book"}
        result = _call("environment_object", candidate=candidate, spec=None)

        print(f"\n[environment_object+topic] => {result}")

        assert "伊塔" not in result
        assert "第一人称" in result


# ══════════════════════════════════════════════════════
# 5. _extract_photo_spec 与 _CLOSEUP_FOCUS_SET 联动
# ══════════════════════════════════════════════════════

class TestExtractAndCloseupIntegration:
    """验证 _extract_photo_spec 提取的 focus 正确落入 _CLOSEUP_FOCUS_SET。"""

    @pytest.mark.parametrize(
        "user_raw, expected_focus",
        [
            ("看看手", "手"),
            ("看看腿", "双腿"),
            ("看看脚", "双脚"),
            ("看看腰", "腰"),
            ("看看锁骨", "肩颈锁骨"),
            ("拍个背影", "背影"),
            ("看看头发", "头发"),
            ("看脸", "脸庞"),
            ("看看眼睛", "眼睛"),
        ],
    )
    def test_extracted_focus_in_closeup_set(self, user_raw: str, expected_focus: str):
        spec = _extract_photo_spec(user_raw)
        assert spec["focus"] == expected_focus
        assert spec["focus"] in _CLOSEUP_FOCUS_SET

    def test_full_body_not_in_closeup_set(self):
        spec = _extract_photo_spec("全身照")
        assert spec["focus"] == "全身"
        assert spec["focus"] not in _CLOSEUP_FOCUS_SET

    def test_no_focus_not_in_closeup_set(self):
        spec = _extract_photo_spec("拍一张照片")
        assert spec["focus"] == ""
        assert spec["focus"] not in _CLOSEUP_FOCUS_SET

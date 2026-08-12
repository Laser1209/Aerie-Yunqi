"""TDD tests for the modular photo-spec prompt composer.

背景：旧实现里用户指令"看看腿"只被 VisualIntentRouter 路由成 role_selfie，
"腿/床上/躺/仰视"全部丢失，提示词永远以完整人物+固定场景为基准。
本测试验证：_extract_photo_spec 能从原始指令按维度提取主体/姿态/机位/场景/风格，
_compose_modular_prompt 把命中维度组合进基础提示词，且缺值兜底不返空串。
"""

from __future__ import annotations

from core.companion import (
    _compose_modular_prompt,
    _ensure_selfie_pov,
    _extract_llm_json,
    _extract_photo_spec,
    _image_event_desc,
    _normalize_spec_value,
    _PHOTO_FOCUS_TABLE,
    _PHOTO_POSE_TABLE,
    _prompt_key_for_visual_topic,
    _visual_topic_zh,
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
    # 机位措辞自拍化（POV 约束）：解析仍命中"仰视低角度"，但输出不再是
    # 第三方"从下往上拍她"，而是"她手持手机放低自拍取景"。
    assert "她手持手机放低，从低处自拍取景" in out


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
    # 背影机位自拍化：默认角度从"从后面"改为"她举手机到身后自拍背影"。
    assert "拍摄机位：她把手机举到身后，用后置摄像头拍自己的背影" in out
    assert "从后面" not in out.split("拍摄机位：", 1)[1]


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
    # 机位措辞自拍化（POV 约束）："特写"输出为"她手持手机近距离特写自拍"。
    assert "拍摄机位：她手持手机近距离特写自拍" in out


# ── POV 约束：手持自拍视角出口兜底 ─────────────────────────
def test_ensure_selfie_pov_appends_when_missing():
    # 人物类提示词无手持约束 → 自动追加 _SELFIE_POV_PHRASE
    out = _ensure_selfie_pov("一张写实生活照，人物是伊塔。", "role_selfie")
    assert "她本人手持手机拍摄" in out
    assert "绝无他人拍摄" in out


def test_ensure_selfie_pov_idempotent_when_present():
    # 已含手持关键词（如组合器已注入"手持手机"）→ 不重复追加，幂等
    out = _ensure_selfie_pov("她手持手机前置自拍，人物是伊塔。", "role_in_scene")
    assert out.count("她本人手持手机拍摄") == 0
    assert out.count("手持手机") == 1


def test_ensure_selfie_pov_skips_environment_object():
    # 环境照不强制带人物，第一人称由模板保证，跳过追加
    out = _ensure_selfie_pov("一张写实照片，第一人称视角。", "environment_object")
    assert "她本人手持手机拍摄" not in out


def test_ensure_selfie_pov_accepts_selfie_phrase():
    # 含"自拍"关键词（role_selfie 模板自带）→ 幂等不追加
    out = _ensure_selfie_pov("她像在给恋人发自拍，桌面有数位板。", "role_selfie")
    assert "绝无他人拍摄" not in out


# ── P2：活动话题中文翻译 + 模板映射 ─────────────────────────
def test_visual_topic_zh_translation_covers_all_activity_topics():
    """world_simulation._ACTIVITY_TOPIC_PREFIXES 的全部话题都能译出中文，无英文残留。"""
    from core.world_simulation import _ACTIVITY_TOPIC_PREFIXES

    topics = {t for prefixes in _ACTIVITY_TOPIC_PREFIXES.values() for t in prefixes}
    assert topics, "activity topic prefixes should not be empty"
    for topic in topics:
        zh = _visual_topic_zh(topic)
        assert zh != topic, f"topic {topic} must have a Chinese translation"
        assert any(ord(c) > 127 for c in zh), f"topic {topic} translation must contain CJK chars: {zh!r}"


def test_visual_topic_zh_reading_time():
    assert "翻书" in _visual_topic_zh("reading_time")


def test_visual_topic_zh_object_legacy_id():
    # 旧英文物件 id → 中文描述（走 _HER_HOME_OBJECTS_ZH）
    assert "沙发" in _visual_topic_zh("object_gray_sofa") or "沙发" in _visual_topic_zh("gray_sofa")


def test_visual_topic_zh_unknown_returns_raw():
    assert _visual_topic_zh("some_unknown_topic") == "some_unknown_topic"


def test_prompt_key_mapping_activity_to_role_in_scene():
    assert _prompt_key_for_visual_topic("reading_time") == "role_in_scene"
    assert _prompt_key_for_visual_topic("coffee_break") == "role_in_scene"


def test_prompt_key_mapping_object_to_environment():
    assert _prompt_key_for_visual_topic("object_gray_sofa") == "environment_object"
    assert _prompt_key_for_visual_topic("gray_sofa") == "environment_object"


def test_prompt_key_mapping_unknown_falls_back():
    assert _prompt_key_for_visual_topic("some_unknown") == "environment_object"
    assert _prompt_key_for_visual_topic("") == "environment_object"


def test_role_in_scene_prompt_uses_topic_zh():
    """role_in_scene 分支 topic 参数化：候选带 reading_time → 提示词含话题中文。"""
    from core.companion import Companion

    comp = Companion.__new__(Companion)
    prompt = comp._compose_base_image_prompt(
        "role_in_scene",
        {"reason_code": "world_visual:reading_time", "scene": "life_share"},
    )
    assert "翻书" in prompt
    assert "手持" in prompt or "自拍" in prompt


def test_role_in_scene_prompt_fallback_without_topic():
    """role_in_scene 无 topic → 回退默认自拍场景，且含 POV 约束。"""
    from core.companion import Companion

    comp = Companion.__new__(Companion)
    prompt = comp._compose_base_image_prompt(
        "role_in_scene",
        {"scene": "life_share"},
    )
    assert "前置摄像头" in prompt
    assert "绝无他人拍摄" in prompt


def test_world_context_text_topics_translated():
    """_world_context_text 输出的可拍主题无可拍主题英文 token 残留。"""
    from core.companion import Companion

    comp = Companion.__new__(Companion)
    text = comp._world_context_text({
        "prompt_key": "environment_object",
        "time_of_day": "evening",
        "clock": "18:00",
        "visual_topics": ["reading_time", "object_gray_sofa"],
        "nearby_objects": ["gray_sofa"],
    })
    assert "reading_time" not in text
    assert "gray_sofa" not in text
    assert "翻书" in text


# ── P3：发图自我认知——图片事件描述与 EVENT 记忆落账 ─────────
def test_image_event_desc_visual_topic():
    # world_visual:reading_time → 话题中文描述（P3 发图后"知道图里是什么"）
    desc = _image_event_desc({"reason_code": "world_visual:reading_time"})
    assert "翻书" in desc


def test_image_event_desc_prompt_key_fallback():
    # 无视觉话题时按 prompt_key 兜底描述
    desc = _image_event_desc({"prompt_key": "role_selfie"})
    assert "自拍" in desc


def test_image_event_desc_generic_fallback():
    assert _image_event_desc({}) == "她发来的一张照片"


class _LayeredStub:
    """记录 store 调用参数的 LayeredMemory 桩。"""

    def __init__(self) -> None:
        self.stores: list[dict] = []

    async def store(self, **kwargs) -> str:
        self.stores.append(kwargs)
        return "mem-1"


def test_persist_image_event_long_term_with_occurred_at():
    """图片事件必须落 long_term（importance≥7.0）且 metadata 带 occurred_at，
    否则 _recall_event_memories（只查 long_term + 按 occurred_at 排序）召回不到。"""
    from core.companion import Companion
    from memory.layers.base import MemoryType

    stub = _LayeredStub()
    comp = Companion.__new__(Companion)
    comp._layered_memory = stub

    async def run():
        await comp._persist_image_event(123, "她窝在沙发里翻书", "qq", "uploads/abc.png")

    import asyncio
    asyncio.run(run())

    assert len(stub.stores) == 1
    call = stub.stores[0]
    assert call["memory_type"] == MemoryType.EVENT
    assert call["importance"] >= 7.0
    meta = call["metadata"]
    assert meta.get("occurred_at"), "occurred_at 必须写入（召回排序依赖）"
    assert meta.get("channel") == "qq"
    assert "http://" not in call["content"], "记忆 content 不应含完整 URL（防泄漏）"


def test_persist_image_event_skips_empty_desc():
    from core.companion import Companion

    stub = _LayeredStub()
    comp = Companion.__new__(Companion)
    comp._layered_memory = stub

    async def run():
        await comp._persist_image_event(123, "   ", "qq")

    import asyncio
    asyncio.run(run())
    assert stub.stores == []

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
    _finalize_image_prompt,
    _image_event_desc,
    _image_orientation_for_size,
    _is_friendly_shot_exception,
    _local_light_phrase,
    _normalize_spec_value,
    _PHOTO_OUTFIT_TABLE,
    _PHOTO_POSE_PHRASE,
    _PHOTO_STYLE_PHRASE,
    _photo_shot_fallback,
    _photo_shot_phrase,
    _reference_assets_for_spec,
    _with_default_shot,
    _PHOTO_FOCUS_DETAIL_TABLE,
    _PHOTO_FOCUS_TABLE,
    _PHOTO_ORIENTATION_TABLE,
    _PHOTO_ORIENTATION_SIZE,
    _PHOTO_POSE_TABLE,
    _PHOTO_SHOT_TABLE,
    _prompt_key_for_visual_topic,
    _visual_topic_zh,
)
from core.image_size import (
    IMAGE_SIZE_LANDSCAPE as _IMAGE_SIZE_LANDSCAPE,
    IMAGE_SIZE_PORTRAIT as _IMAGE_SIZE_PORTRAIT,
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
    # 机位措辞无设备化（POV 约束）：解析仍命中"仰视低角度"，但输出不再是
    # 第三方"从下往上拍她"，也不含任何入镜设备，而是"低机位仰拍，从低处往上取景"。
    assert "低机位仰拍，从低处往上取景" in out


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
    assert "画面重点聚焦在大腿" in out
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
    # 背影机位无设备化：默认角度从"从后面"改为"机位在她身后，从背后取景"。
    assert "拍摄机位：机位在她身后，从背后取景，约 50mm" in out
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
    # 机位措辞无设备化（POV 约束）："特写"输出为"近距离特写机位，约 85mm 定焦"。
    assert "拍摄机位：近距离特写机位，约 85mm 定焦" in out


# ── POV 约束：第一人称自拍视角出口兜底 + 设备不入镜 ─────────
def test_ensure_selfie_pov_appends_when_missing():
    # 人物类提示词无 POV 约束 → 自动追加 _SELFIE_POV_PHRASE
    out = _ensure_selfie_pov("一张写实生活照，人物是伊塔。", "role_selfie")
    assert "第一人称自拍视角" in out
    assert "不出现手机" in out


def test_ensure_selfie_pov_idempotent_when_present():
    # 已含 POV 关键词（如组合器/base 已注入"第一人称自拍视角"）→ 不重复追加，幂等
    out = _ensure_selfie_pov("她以第一人称自拍视角对着镜头，人物是伊塔。", "role_in_scene")
    assert out.count("这张照片是她本人的第一人称自拍视角") == 0
    assert out.count("第一人称自拍视角") == 1


def test_ensure_selfie_pov_skips_environment_object():
    # 环境照不强制带人物，第一人称由模板保证，跳过追加
    out = _ensure_selfie_pov("一张写实照片，第一人称视角。", "environment_object")
    assert "这张照片是她本人的第一人称自拍视角" not in out


def test_ensure_selfie_pov_accepts_selfie_phrase():
    # 仅含"自拍"字样（不含 POV 关键词）→ 仍需追加设备不入镜的 POV 前提
    out = _ensure_selfie_pov("她像在给恋人发自拍，桌面有数位板。", "role_selfie")
    assert "不出现手机" in out


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
    """role_in_scene 无 topic → 回退默认自拍场景，且含 POV 约束（设备不入镜）。"""
    from core.companion import Companion

    comp = Companion.__new__(Companion)
    prompt = comp._compose_base_image_prompt(
        "role_in_scene",
        {"scene": "life_share"},
    )
    assert "第一人称自拍视角" in prompt
    assert "不出现手机" in prompt


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


# ── 方向2：orientation 横竖方（关键词提取 + 归一化 + 尺寸档映射） ─────────
def test_extract_orientation_keyword_landscape():
    # "横着/横构图" → orientation=横
    assert _extract_photo_spec("横着拍一张")["orientation"] == "横"


def test_extract_orientation_keyword_square():
    assert _extract_photo_spec("方构图来一张")["orientation"] == "方"


def test_extract_orientation_default_portrait_empty():
    # 未明确方向 → 空串（由 base 按意图默认竖）
    assert _extract_photo_spec("拍一张")["orientation"] == ""


def test_normalize_orientation_approximation():
    # LLM 近似表述（如"横构图"）→ 归一化到"横"
    assert _normalize_spec_value("横构图", _PHOTO_ORIENTATION_TABLE) == "横"
    assert _normalize_spec_value("竖向", _PHOTO_ORIENTATION_TABLE) == "竖"


def test_orientation_to_size_mapping():
    from core.companion import _image_orientation_for_size

    assert _image_orientation_for_size("横") == _IMAGE_SIZE_LANDSCAPE
    assert _image_orientation_for_size("方") == "1024x1024"
    assert _image_orientation_for_size("竖") == _IMAGE_SIZE_PORTRAIT
    assert _image_orientation_for_size("未定义", fallback=_IMAGE_SIZE_PORTRAIT) == _IMAGE_SIZE_PORTRAIT


# ── 关键词误命中（登记制守卫）：普通闲聊不能被切成"部位特写" ────────────
# 实测背景（2026-09-28 主动消息配图）：整句闲聊被当作"用户要图指令"解析，
#   ① "一抬**头发**现在步行街站了半小时" → 含「头发」→ 整张图变头发特写（85mm 特写）；
#   ② "找个地**方**坐坐" → 含「方」→ 判成方图，且出口把方图谎报成"横构图 16:9"。


def test_plain_chatter_is_not_parsed_as_closeup():
    """普通闲聊：不产生 focus / orientation / shot（本次事故的原始句子）。"""
    spec = _extract_photo_spec(
        "一抬头发现自己在步行街站了半小时 你说我是不是该找个地方坐坐 不对 我是想问你有空了吗"
    )
    assert spec["focus"] == ""
    assert spec["orientation"] == ""
    assert spec["shot"] == ""


def test_cross_word_substring_does_not_match_focus():
    """跨词误命中：「抬头发现」「低头发现」里的"头发"不算；真说头发才算。"""
    assert _extract_photo_spec("低下头发现鞋带开了")["focus"] == ""
    assert _extract_photo_spec("你的头发乱了")["focus"] == "头发"


def test_direction_word_in_prose_does_not_set_orientation():
    """「方法」里的"方"不算方向；真说方向才算。"""
    assert _extract_photo_spec("找个地方坐坐")["orientation"] == ""
    assert _extract_photo_spec("方构图来一张")["orientation"] == "方"


def test_bare_part_word_needs_verb_or_whole_utterance():
    """裸单字部位词：紧邻拍照动作/整句就是它才算；正文里的不算。"""
    assert _extract_photo_spec("腿")["focus"] == "双腿"
    assert _extract_photo_spec("拍腿")["focus"] == "双腿"
    assert _extract_photo_spec("在床上躺着，仰视低角度拍腿，要诱惑感")["focus"] == "双腿"
    # 正文描述身体状态 → 不是要图指令，不该变成部位特写
    assert _extract_photo_spec("我看到她腿上有个包")["focus"] == ""
    assert _extract_photo_spec("腿上青了一块")["focus"] == ""


def test_square_size_phrase_is_not_reported_as_landscape():
    """方图必须说方构图：原先 width>=height 把 1024x1024 说成"横构图 16:9"。"""
    from core.image_size import orientation_phrase

    assert "方构图" in orientation_phrase("1024x1024")
    assert "横" not in orientation_phrase("1024x1024")
    assert "横构图" in orientation_phrase("1344x768")
    assert "竖构图" in orientation_phrase("768x1344")


# ── 三档尺寸的"场景自决"：候选漏填 size 时由 prompt_key 决定 ──
def _prompt_stub():
    """最小 Companion 桩：只喂 _image_prompt_for_impl 需要的外部依赖。"""
    from unittest.mock import AsyncMock, MagicMock

    from core.companion import Companion

    comp = Companion.__new__(Companion)
    comp._semantic_photo_spec = AsyncMock(return_value={})
    comp._is_persona_image = MagicMock(return_value=False)
    comp._life_recording_enabled = MagicMock(return_value=False)
    comp._compose_base_image_prompt = MagicMock(return_value="base")
    comp._image_world_context = MagicMock(return_value={})
    return comp


def test_prompt_layer_fills_scene_size_when_candidate_omits_it():
    """候选没带 size 时按场景决断尺寸，不再一路掉到上游默认的 1:1。

    主动配图 _maybe_attach_companion_image 此前就不带 size，于是
    「按场景决断的横/竖构图」在它这条路上永远出不来（2026-09-28 症状⑧）。
    """
    import asyncio

    comp = _prompt_stub()

    portrait = {"prompt_key": "role_in_scene", "scene": "local_send", "user_raw": "早安"}
    asyncio.run(comp._image_prompt_for_impl("role_in_scene", portrait))
    assert portrait["size"] == _IMAGE_SIZE_PORTRAIT

    landscape = {"prompt_key": "environment_object", "scene": "local_send", "user_raw": "窗边"}
    asyncio.run(comp._image_prompt_for_impl("environment_object", landscape))
    assert landscape["size"] == _IMAGE_SIZE_LANDSCAPE


def test_prompt_layer_keeps_explicit_size_and_lets_orientation_override():
    """显式 size 不被覆盖；语义方向（方）优先级最高，三档都能落地。"""
    import asyncio

    from unittest.mock import AsyncMock

    comp = _prompt_stub()
    comp._semantic_photo_spec = AsyncMock(return_value={"orientation": "方"})

    explicit = {
        "prompt_key": "role_in_scene",
        "scene": "local_send",
        "user_raw": "横着拍一张",
        "size": _IMAGE_SIZE_LANDSCAPE,
    }
    asyncio.run(comp._image_prompt_for_impl("role_in_scene", explicit))
    # 语义给了方向 → 以语义为准（这里是"方"），不是"谁先谁后"的含糊地带
    assert explicit["size"] == "1024x1024"

    no_spec = {
        "prompt_key": "role_selfie",
        "scene": "local_send",
        "user_raw": "拍一张",
        "size": _IMAGE_SIZE_LANDSCAPE,
    }
    comp._semantic_photo_spec = AsyncMock(return_value={})
    asyncio.run(comp._image_prompt_for_impl("role_selfie", no_spec))
    assert no_spec["size"] == _IMAGE_SIZE_LANDSCAPE, "调用方显式给的尺寸不该被默认值顶掉"


# ── 方案A 细分子部位（父部位 → 子部位回退） ──────────────────
def test_focus_detail_prefers_child_over_parent():
    # 细表优先：提到"脚踝" → 子标签"脚踝"，而非父"双脚"
    assert _extract_photo_spec("看看你的脚踝")["focus"] == "脚踝"
    assert _extract_photo_spec("看看你的大腿")["focus"] == "大腿"


def test_focus_detail_falls_back_to_parent():
    # 未提子部位、只给父类"看看腿" → 回退"双腿"
    assert _extract_photo_spec("看看腿")["focus"] == "双腿"


def test_focus_child_is_in_closeup_set():
    from core.companion import _CLOSEUP_FOCUS_SET

    assert "大腿" in _CLOSEUP_FOCUS_SET
    assert "脚踝" in _CLOSEUP_FOCUS_SET


# ── 补充一：景别(shot) 提取 + 归一化 + 镜头短语 + 特写联动 ─────────
def test_extract_shot_keyword_near():
    assert _extract_photo_spec("近景拍一张")["shot"] == "近景"


def test_extract_shot_keyword_closeup():
    assert _extract_photo_spec("怼脸特写拍脚")["shot"] == "特写"


def test_extract_shot_default_empty():
    # 未明确景别 → 空串（由 _photo_shot_fallback 视 focus 联动补）
    assert _extract_photo_spec("拍一张")["shot"] == ""


def test_normalize_shot_approximation():
    assert _normalize_spec_value("大特写", _PHOTO_SHOT_TABLE) == "大特写"
    assert _normalize_spec_value("全身入画", _PHOTO_SHOT_TABLE) == "远景"


def test_shot_phrase_lookup():
    # 特写/大特写只给镜头与景深语言（"虚化"由 focus 模块表达，不重复说）
    assert "浅景深" in (_photo_shot_phrase("特写") or "")
    assert "虚化" not in (_photo_shot_phrase("特写") or "")
    assert "机位拉远" in (_photo_shot_phrase("远景") or "")


def test_shot_fallback_focus_closeup():
    # focus 局部特写且未给景别 → 自动默认"特写"（景别使用率最高的兜底）
    spec = _photo_shot_fallback({"focus": "脚踝"})
    assert spec["shot"] == "特写"


def test_shot_fallback_focus_fullbody():
    assert _photo_shot_fallback({"focus": "全身"})["shot"] == "中景"


def test_shot_fallback_keeps_explicit():
    assert _photo_shot_fallback({"shot": "远景"})["shot"] == "远景"


def test_compose_injects_shot_phrase():
    # user 指令命中景别 → 组合器注入镜头语言
    out = _compose_modular_prompt("base", _spec("近景拍脚"))
    assert "镜头贴近" in out


# ── 补充一：外出/合影 POV 例外（护栏，慎用） ─────────────
def test_is_friendly_shot_exception_outdoor():
    assert _is_friendly_shot_exception("在游乐园拍一张合影") is True
    assert _is_friendly_shot_exception("在公园散步时拍的照片") is True


def test_is_friendly_shot_exception_room_negative():
    # 房间/常见场景不算例外，仍走第一人称自拍护栏
    assert _is_friendly_shot_exception("在床上躺着拍一张") is False


def test_ensure_selfie_pov_outdoor_exception():
    # 出游/合影场景 → 不再追加"第一人称自拍"，追加同行者叙事（同样无设备入镜）
    out = _ensure_selfie_pov("在游乐园拍一张合影", "role_in_scene")
    assert "这张照片是她本人的第一人称自拍视角" not in out
    assert "同行的人" in out
    assert "不出现手机" in out


def test_ensure_selfie_pov_home_premise_kept():
    # 房间内普通请求 → 仍追加第一人称自拍前提（防第三方拍摄误读 + 设备不入镜）
    out = _ensure_selfie_pov("躺在床上拍一张", "role_selfie")
    assert "这张照片是她本人的第一人称自拍视角" in out


# ── 模块化补充：部位细节 / 服装 / 景别镜头语言 ─────────────────
def test_focus_detail_phrase_injected():
    """focus 命中时不仅写"聚焦在X"，还要给出该部位的画面语言。"""
    out = _compose_modular_prompt("base", _spec("看看腿"))
    assert "画面重点聚焦在双腿，其余虚化" in out
    assert "腿部皮肤通透" in out


def test_focus_detail_covers_every_closeup_label():
    """_PHOTO_FOCUS_PHRASE 覆盖全部局部特写标签，避免出现无措辞的空模块。"""
    from core.companion import _CLOSEUP_FOCUS_SET, _PHOTO_FOCUS_PHRASE

    assert _CLOSEUP_FOCUS_SET <= set(_PHOTO_FOCUS_PHRASE)


def test_extract_outfit_keyword():
    assert _extract_photo_spec("穿睡衣拍一张")["outfit"] == "睡衣"
    assert _extract_photo_spec("裹浴巾拍一张")["outfit"] == "浴巾"
    assert _extract_photo_spec("拍一张")["outfit"] == ""


def test_normalize_outfit_approximation():
    assert _normalize_spec_value("睡衣", _PHOTO_OUTFIT_TABLE) == "睡衣"
    assert _normalize_spec_value("连衣裙", _PHOTO_OUTFIT_TABLE) == "连衣裙"


def test_compose_injects_outfit_module():
    out = _compose_modular_prompt("base", _spec("穿睡衣在床上拍一张"))
    assert "穿着宽松家居睡衣" in out


def test_shot_phrase_carries_lens_language():
    """景别模块带镜头/焦段语言，而不是只有一句"贴近/拉远"。"""
    assert "85mm" in (_photo_shot_phrase("特写") or "")
    assert "35mm" in (_photo_shot_phrase("远景") or "")


def test_default_shot_by_prompt_key():
    """既无景别也无 focus 时，按画面类型补默认景别（自拍近景 / 生活场景中景）。"""
    assert _with_default_shot({}, "role_selfie")["shot"] == "近景"
    assert _with_default_shot({}, "role_in_scene")["shot"] == "中景"
    assert _with_default_shot({}, "unknown_key") == {}


def test_default_shot_respects_explicit_or_focus():
    assert _with_default_shot({"shot": "远景"}, "role_selfie")["shot"] == "远景"
    # 已有 focus（可推导景别）时不覆盖，交给 _photo_shot_fallback
    assert "shot" not in _with_default_shot({"focus": "双腿"}, "role_selfie")


# ── 图生图参考视角模块：分部位/姿态 → three_view 视角 ─────────────
def test_reference_view_back_for_back_focus():
    assert _reference_assets_for_spec({"focus": "背影"}) == [
        "three_view:back",
        "three_view:front",
    ]


def test_reference_view_side_for_side_pose():
    assert _reference_assets_for_spec({"pose": "侧躺"}) == [
        "three_view:side",
        "three_view:front",
    ]


def test_reference_view_defaults_to_front_without_fallback():
    assert _reference_assets_for_spec({"focus": "脸庞"}) == ["three_view:front"]
    assert _reference_assets_for_spec(None) == ["three_view:front"]


# ── 出口模块：真实感 + 负面约束（幂等、景物另用一套） ─────────────
def test_finalize_adds_realism_and_negative_for_person():
    out = _finalize_image_prompt("一张写实生活照。", "role_selfie")
    assert "毛孔" in out
    assert "反面约束" in out
    assert "多余或残缺的手指" in out


def test_finalize_is_idempotent():
    once = _finalize_image_prompt("一张写实生活照。", "role_selfie")
    twice = _finalize_image_prompt(once, "role_selfie")
    assert twice == once


def test_finalize_environment_uses_env_realism_and_negative():
    """景物图用景物那套：材质/光影真实，但不塞人物专属的毛孔/手指约束。"""
    out = _finalize_image_prompt("一张写实照片，第一人称视角。", "environment_object")
    assert "真实摄影质感" in out
    assert "反面约束" in out
    assert "毛孔" not in out
    assert "多余或残缺的手指" not in out


# ── 光线模块：world 优先、本地时刻兜底、幂等 ───────────────────
def test_finalize_injects_light():
    out = _finalize_image_prompt(
        "一张写实生活照。", "role_selfie", light="傍晚，黄昏的暖色调光线"
    )
    assert "光线：傍晚，黄昏的暖色调光线" in out


def test_finalize_light_is_idempotent():
    """世界上下文兜底可能已注入同一段光线 → 出口不得重复写第二遍。"""
    once = _finalize_image_prompt(
        "一张写实生活照。", "role_selfie", light="傍晚，黄昏的暖色调光线"
    )
    twice = _finalize_image_prompt(once, "role_selfie", light="傍晚，黄昏的暖色调光线")
    assert twice == once
    assert twice.count("黄昏的暖色调光线") == 1


def test_finalize_skips_light_when_already_in_world_text():
    """光线已由「画面氛围：…」注入时（world 兜底路径），出口不再追加。"""
    base = "一张写实生活照。画面氛围：傍晚，黄昏的暖色调光线。"
    out = _finalize_image_prompt(base, "role_selfie", light="傍晚，黄昏的暖色调光线")
    assert out.count("黄昏的暖色调光线") == 1


def test_finalize_without_light_never_empty():
    """取不到光线（空串）时跳过模块，不产出空段、不影响其余约束。"""
    out = _finalize_image_prompt("一张写实生活照。", "role_selfie", light="")
    assert "光线：" not in out
    assert "反面约束" in out


# ── 拍摄手法模块（b2）：按类型配套 + 设备不入镜 + 状态同步 ─────────
def test_finalize_appends_shooting_phrase():
    out = _finalize_image_prompt("一张写实生活照。", "role_selfie", shooting="拍摄手法：iPhone 前置摄像头，约 50mm。")
    assert "拍摄手法：iPhone 前置摄像头" in out


def test_finalize_shooting_is_idempotent():
    once = _finalize_image_prompt("一张写实生活照。", "role_selfie", shooting="拍摄手法：iPhone 前置摄像头，约 50mm。")
    twice = _finalize_image_prompt(once, "role_selfie", shooting="拍摄手法：iPhone 前置摄像头，约 50mm。")
    assert twice == once
    assert twice.count("拍摄手法：") == 1


def test_negative_carries_device_exclusion():
    """人物类负面约束必须排除拍摄设备本体（手机/相机/三脚架/自拍杆）。"""
    from core.companion import _IMAGE_NEGATIVE_PHRASE

    assert "手机" in _IMAGE_NEGATIVE_PHRASE
    assert "自拍杆" in _IMAGE_NEGATIVE_PHRASE


def test_shooting_phrase_matches_type():
    """拍摄手法按类型配套：惬意的慵懒用柔和机位，远景改用带环境的广角。"""
    from core.image_shooting import shooting_phrase

    cozy = shooting_phrase(style="慵懒", prompt_key="role_selfie")
    far = shooting_phrase(prompt_key="role_in_scene", shot="远景")
    assert "眼平略低的机位" in cozy
    assert "35mm" in far
    assert cozy != far


def test_shooting_phrase_syncs_low_energy_and_night():
    """状态同步：低精力 → 更松弛的柔和手法；夜间 → 补弱光颗粒。"""
    from core.image_shooting import shooting_phrase

    tired = shooting_phrase(prompt_key="role_selfie", energy=0.2)
    night = shooting_phrase(prompt_key="role_selfie", phase="night")
    assert "姿态松弛" in tired
    assert "噪点" in night


def test_shooting_phrase_skips_environment_object():
    """环境照是物件视角，不套人物拍摄手法（缺值即停）。"""
    from core.image_shooting import shooting_phrase

    assert shooting_phrase(prompt_key="environment_object") == ""


def test_strip_device_props_is_idempotent_and_protects_clauses():
    """设备清洗幂等，且不误伤"排除设备"的自身约束（负面/POV 措辞）。"""
    from core.companion import _IMAGE_NEGATIVE_PHRASE, _SELFIE_POV_PHRASE
    from core.image_shooting import strip_device_props

    text = f"她手持手机自拍。{_SELFIE_POV_PHRASE}{_IMAGE_NEGATIVE_PHRASE}"
    once = strip_device_props(text)
    twice = strip_device_props(once)
    assert once == twice
    assert "手持手机" not in once
    assert _SELFIE_POV_PHRASE in once
    assert _IMAGE_NEGATIVE_PHRASE in once


def test_local_light_phrase_covers_every_phase():
    """本地光线兜底必须对每个时段都给得出文案（单一真源 world_phase），无英文/空值。"""
    from datetime import datetime

    from core.world_phase import TIME_OF_DAY_LIGHT_CN

    for hour in (6, 9, 13, 16, 19, 22, 2):
        text = _local_light_phrase(datetime(2026, 9, 21, hour, 0))
        assert text and text in TIME_OF_DAY_LIGHT_CN.values()


# ── 模块去重：横切约束只由出口说一次 ────────────────────────
def test_cross_cutting_constraints_are_not_duplicated():
    """base 与出口模块不得重复同一条横切约束。

    真实感/反动漫/负面约束由出口统一负责；base 若再写一遍，同一条约束会出现
    两三次，模型对单条约束的权重被摊薄（历史现象：一段提示词里"真实摄影质感"
    和"不要动漫风"各出现两遍，"水印"出现三遍）。
    """
    from unittest.mock import patch

    from core.companion import Companion

    comp = Companion.__new__(Companion)
    with patch("config.persona_loader.load_persona", return_value={}):
        base = comp._compose_base_image_prompt(
            "role_selfie",
            {"scene": "local_send", "user_raw": "拍一张", "size": "768x1344"},
        )
    out = _finalize_image_prompt(base, "role_selfie")
    assert out.count("真实摄影质感") == 1
    assert out.count("不要动漫风") == 1
    assert out.count("反面约束") == 1


def test_environment_cross_cutting_constraints_not_duplicated():
    from unittest.mock import patch

    from core.companion import Companion

    comp = Companion.__new__(Companion)
    with patch("config.persona_loader.load_persona", return_value={}):
        base = comp._compose_base_image_prompt(
            "environment_object", {"reason_code": "world_visual:object_gray_sofa"}
        )
    out = _finalize_image_prompt(base, "environment_object")
    assert out.count("真实摄影质感") == 1
    assert out.count("不要动漫风") == 1
    assert out.count("反面约束") == 1


# ── base 模板：不抢光线模块的职责、名词完整 ─────────────────
def _base_with_persona(prompt_key: str, candidate: dict, persona: dict) -> str:
    from unittest.mock import patch

    from core.companion import Companion

    comp = Companion.__new__(Companion)
    with patch("config.persona_loader.load_persona", return_value=persona):
        return comp._compose_base_image_prompt(prompt_key, candidate)


def test_base_prompt_does_not_claim_lighting():
    """光线由光线模块单独表达；base 若写死"自然光"，深夜/雨天的画面就会自相矛盾。"""
    person = _base_with_persona(
        "role_selfie", {"scene": "local_send", "user_raw": "拍一张"}, {}
    )
    env = _base_with_persona(
        "environment_object", {"reason_code": "world_visual:object_gray_sofa"}, {}
    )
    assert "自然光" not in person
    assert "自然光" not in env


def test_base_prompt_prefixes_eye_noun_when_missing():
    """persona eyes 只有描述（"深灰蓝色，目光沉静"）时补"眼睛"名词。"""
    persona = {"persona": {"appearance": {"eyes": "深灰蓝色，目光沉静"}, "profile": {}}}
    out = _base_with_persona(
        "role_selfie", {"scene": "local_send", "user_raw": "拍一张"}, persona
    )
    assert "眼睛深灰蓝色" in out
    assert "眼睛眼睛" not in out


def test_base_prompt_keeps_eye_noun_when_present():
    persona = {"persona": {"appearance": {"eyes": "深灰蓝色眼睛"}, "profile": {}}}
    out = _base_with_persona(
        "role_selfie", {"scene": "local_send", "user_raw": "拍一张"}, persona
    )
    assert out.count("眼睛") == 1


# ── 氛围模块：带神态/视线，而不是只写"整体氛围X" ──────────────
def test_style_phrase_covers_every_label():
    from core.companion import _PHOTO_STYLE_TABLE

    assert {label for label, _ in _PHOTO_STYLE_TABLE} == set(_PHOTO_STYLE_PHRASE)


def test_compose_injects_style_mood():
    out = _compose_modular_prompt("base", _spec("要慵懒的感觉"))
    assert "整体氛围慵懒" in out
    assert _PHOTO_STYLE_PHRASE["慵懒"] in out


# ── 姿态模块：措辞不夹带场景词（场景由 scene 模块独立表达） ──────
def test_pose_phrase_has_no_scene_word():
    assert "床" not in _PHOTO_POSE_PHRASE["侧躺"]


def test_side_lying_on_sofa_does_not_say_bed():
    """用户说"沙发上侧躺" → 画面里不能出现"躺在床上"这种自相矛盾。"""
    out = _compose_modular_prompt("base", _spec("在沙发上侧躺拍一张"))
    assert "场景是沙发" in out
    assert "床上" not in out

"""§十 配图场景与世界地点一致性 —— companion 侧接线测试。

覆盖计划 §10.6 的验收项：
  1/7. world 说室外 → 选到 outdoor 组场景（且兜底提示词点明地点）
  2.   world 说室内 → 不受室外影响
  5.   无 world 快照 → outdoor=None（不约束，不回归）
  6.   轻量 LLM 接力不可用时，确定性兜底仍能表达"她在室外"
  + 接力 system prompt 里"地点优先级高于场景描述"的授权确实存在
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core import image_scene_pool as pool
from core.companion import Companion


def _outdoor_names() -> set[str]:
    return {s["name"] for s in pool.list_scenes_unfiltered() if s["group"] == "outdoor"}


# ── 5 · 无 world 快照：outdoor=None（不约束） ───────────────────────────


def test_no_world_snapshot_yields_none_outdoor():
    """world 不可用时 outdoor 必须是 None，而不是 False。

    给 False 会被场景池当成"她此刻在家"，把"world 关掉"误伤成"硬过滤到室内"。
    """
    comp = Companion.__new__(Companion)
    comp._world_snapshot_for_context = lambda: None

    ctx = comp._image_world_context({})

    assert ctx["has_world"] is False
    assert ctx["outdoor"] is None


def test_indoor_snapshot_reports_false():
    """world 明确说在家 → outdoor=False（此时应当被约束到室内组）。"""
    comp = Companion.__new__(Companion)
    comp._world_snapshot_for_context = lambda: {
        "phase": "afternoon",
        "iso_time": "2026-09-28T15:55:00+08:00",
        "outdoor": False,
        "location": "home",
    }

    ctx = comp._image_world_context({})

    assert ctx["has_world"] is True
    assert ctx["outdoor"] is False


def test_outdoor_snapshot_reports_place():
    """world 说在步行街 → outdoor=True + outdoor_place。"""
    comp = Companion.__new__(Companion)
    comp._world_snapshot_for_context = lambda: {
        "phase": "afternoon",
        "iso_time": "2026-09-28T15:55:00+08:00",
        "outdoor": True,
        "outdoor_place": "步行街",
        "city": "重庆",
    }

    ctx = comp._image_world_context({})

    assert ctx["outdoor"] is True
    assert ctx["outdoor_place"] == "步行街"


# ── 1/7 · 世界地点决定场景分组（端到端） ────────────────────────────────


@pytest.mark.asyncio
async def test_outdoor_world_forces_outdoor_scene():
    """world 说在步行街 + 主动配图 → 选到 outdoor 组场景，不再是 55% 的室内。"""
    captured: dict = {}
    comp = Companion.__new__(Companion)
    comp._world_snapshot_for_context = lambda: {
        "phase": "afternoon",
        "iso_time": "2026-09-28T15:55:00+08:00",
        "outdoor": True,
        "outdoor_place": "步行街",
        "city": "重庆",
        "location": "outdoor",
    }
    comp._semantic_photo_spec = AsyncMock(return_value={})
    comp._is_persona_image = lambda key: True
    comp._life_recording_enabled = lambda: True

    def _base(key, cand=None, spec=None):
        captured["spec"] = dict(spec or {})
        return "一张写实生活照，人物是一位28岁的中国女性。"

    comp._compose_base_image_prompt = _base
    comp._light_relay_refine_prompt = AsyncMock(return_value=None)  # 接力不可用 → 走兜底

    candidate = {
        "prompt_key": "role_selfie",
        "user_raw": "一抬头发现自己在步行街站了半小时",
    }
    prompt = await comp._image_prompt_for_impl("role_selfie", candidate)

    assert candidate["scene_meta"]["group"] == "outdoor"
    assert candidate["scene_meta"]["constrained_by_world"] is True
    assert captured["spec"]["scene"] in _outdoor_names()
    # 兜底注入：轻量 LLM 不可用时也必须点明"她在外面"
    assert "她此刻在步行街" in prompt


@pytest.mark.asyncio
async def test_indoor_world_forces_indoor_scene():
    """反向：world 说在家 → 场景不会跑到江边/街头。"""
    captured: dict = {}
    comp = Companion.__new__(Companion)
    comp._world_snapshot_for_context = lambda: {
        "phase": "night",
        "iso_time": "2026-09-28T22:10:00+08:00",
        "outdoor": False,
        "location": "home",
    }
    comp._semantic_photo_spec = AsyncMock(return_value={})
    comp._is_persona_image = lambda key: True
    comp._life_recording_enabled = lambda: True

    def _base(key, cand=None, spec=None):
        captured["spec"] = dict(spec or {})
        return "一张写实生活照，人物是一位28岁的中国女性。"

    comp._compose_base_image_prompt = _base
    comp._light_relay_refine_prompt = AsyncMock(return_value=None)

    candidate = {"prompt_key": "role_selfie", "user_raw": "我到家了"}
    await comp._image_prompt_for_impl("role_selfie", candidate)

    indoor_names = {s["name"] for s in pool.list_scenes_unfiltered() if s["group"] == "indoor"}
    assert candidate["scene_meta"]["group"] == "indoor"
    assert captured["spec"]["scene"] in indoor_names


# ── 6 · 确定性兜底补 location ─────────────────────────────────────────


def test_fallback_injects_outdoor_place():
    """室外 → 兜底提示词点明"她此刻在{地点}"。"""
    comp = Companion.__new__(Companion)
    candidate = {"prompt_key": "role_selfie"}

    out = comp._inject_world_context_fallback(
        "基础提示词。",
        {"prompt_key": "role_selfie", "outdoor": True, "outdoor_place": "步行街",
         "time_of_day_light": "午后"},
        candidate,
    )

    assert "她此刻在步行街" in out


def test_fallback_skips_place_when_indoor():
    """室内 → 不注入地点句（房间描述已由 base 覆盖）。"""
    comp = Companion.__new__(Companion)
    candidate = {"prompt_key": "role_selfie"}

    out = comp._inject_world_context_fallback(
        "基础提示词。",
        {"prompt_key": "role_selfie", "outdoor": False, "time_of_day_light": "午后"},
        candidate,
    )

    assert "她此刻在" not in out


def test_fallback_skips_place_when_world_missing():
    """无 world（outdoor=None）→ 不注入地点，与改动前一致。"""
    comp = Companion.__new__(Companion)
    candidate = {"prompt_key": "role_selfie"}

    out = comp._inject_world_context_fallback(
        "基础提示词。",
        {"prompt_key": "role_selfie", "outdoor": None, "time_of_day_light": "午后"},
        candidate,
    )

    assert "她此刻在" not in out


# ── 步骤5 · 接力指令给地点一票否决权 ──────────────────────────────────


class _CapturingBrain:
    """只记录 messages 的假 brain：用来检查接力 system prompt 的内容。"""

    def __init__(self) -> None:
        self.messages: list[dict] | None = None

    async def chat(self, messages, **kwargs):
        self.messages = messages

        class _Resp:
            text = "一张写实生活照，她站在步行街上，手机前置自拍，傍晚的光落在肩上。"

        return _Resp()


@pytest.mark.asyncio
async def test_relay_prompt_gives_location_priority(monkeypatch):
    """接力 system prompt 必须写明"地点优先级高于基础提示词的场景描述"。"""
    comp = Companion.__new__(Companion)
    comp.brain = _CapturingBrain()
    monkeypatch.setattr("core.companion._image_light_preference", lambda: (None, None))

    context = {
        "prompt_key": "role_selfie",
        "time_of_day_light": "午后",
        "outdoor": True,
        "outdoor_place": "步行街",
        "city": "重庆",
    }
    refined = await comp._light_relay_refine_prompt("基础提示词。", context, {"prompt_key": "role_selfie"})

    assert refined is not None
    assert comp.brain.messages is not None
    system_msg = str(comp.brain.messages[0]["content"])
    assert "地点优先级高于场景描述" in system_msg
    # 世界数据确实被喂给了接力（否则"以 world 为准"无从谈起）
    user_msg = str(comp.brain.messages[1]["content"])
    assert "她此刻在室外（步行街）" in user_msg

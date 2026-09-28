"""§八 生图模型分级路由测试。

覆盖计划 §8.7 的验收点：
  1. "发张你的自拍" → T2（Flash）
  2. "拍一下桌上的西瓜"（环境/物件）→ T1
  3. "让我看看你的手" → T4（Lite）
  4. "帮我做一张海报" → T1 且 4K
  5. 指定模型失败 → 降级到下一档，用户最终拿到图
  6. 每张图的 tier/model 可审计（metadata 透传）
  + 档位表 / 特写集合与配置不漂移；总开关关闭回落旧行为
"""

from __future__ import annotations

import pytest

from core import image_tiering
from core.companion import _CLOSEUP_FOCUS_SET
from core.image_service import JimengCanvasImageGenerationProvider
from core.world_image_candidates import PERSONA_IMAGE_PROMPT_KEYS, _image_tier_hint


# ── 档位判定（优先级） ─────────────────────────────────────────────────


def test_poster_keyword_wins_over_everything():
    """"帮我做一张海报" → T1 且 4K（用户意图压倒一切，即便同时命中特写）。"""
    decided = image_tiering.decide(
        prompt_key="role_selfie",
        user_raw="帮我做一张海报，用我手部的特写",
        spec={"focus": "手"},
        closeup_focus=_CLOSEUP_FOCUS_SET,
    )
    assert decided.key == "t1_poster"
    assert decided.resolution == "4K"


def test_closeup_focus_goes_to_detail_tier():
    """"让我看看你的手" → T4（低信息量·小部件）。"""
    decided = image_tiering.decide(
        prompt_key="role_selfie",
        spec={"focus": "手"},
        closeup_focus=_CLOSEUP_FOCUS_SET,
    )
    assert decided.key == "t4_detail"


def test_environment_prompt_key_goes_to_high_tier():
    """环境/物件类 → T1（信息量高）。"""
    assert image_tiering.decide(prompt_key="environment_object").key == "t1_high"


def test_far_shot_goes_to_high_tier():
    """远景 = 大场景 → T1。"""
    assert image_tiering.decide(prompt_key="role_in_scene", spec={"shot": "远景"}).key == "t1_high"


def test_non_persona_closeup_shot_goes_to_detail_tier():
    """无人物的小物件 + 特写 → T4。"""
    decided = image_tiering.decide(prompt_key="environment_object", spec={"shot": "大特写"})
    assert decided.key == "t4_detail"


def test_artistic_style_promotes_portrait_to_artistic_tier():
    """人像 + 写真感风格（氛围感/诱惑感/慵懒）→ T3。"""
    for style in ("氛围感", "诱惑感", "慵懒"):
        assert image_tiering.decide(
            prompt_key="role_selfie", spec={"style": style},
        ).key == "t3_artistic"


def test_plain_portrait_is_daily_tier():
    """"发张你的自拍"（无风格/无特写）→ T2。"""
    assert image_tiering.decide(prompt_key="role_selfie").key == "t2_portrait"


def test_unknown_prompt_key_falls_back_to_daily_tier():
    """兜底 = T2（最常用、最便宜、质量够日常）。"""
    assert image_tiering.decide(prompt_key="something_new").key == "t2_portrait"


def test_tier_carries_model_resolution_provider_and_credits():
    """每档都带齐模型/分辨率/通道/参考报价，供 metadata 透传与审计。"""
    decided = image_tiering.tier("t2_portrait")
    assert decided.model == "high_aes_general_v50_flash"
    assert decided.resolution == "2K"
    assert decided.provider == "jimeng"
    assert decided.credits == 3


# ── 配置与代码不漂移 ───────────────────────────────────────────────────


def test_config_persona_keys_match_world_candidates():
    """yaml 里的人像 prompt_key 必须与 PERSONA_IMAGE_PROMPT_KEYS 一致，防两处漂移。"""
    config = image_tiering._load_config()
    assert set(config["persona_prompt_keys"]) == set(PERSONA_IMAGE_PROMPT_KEYS)


def test_tiering_is_enabled_by_default():
    assert image_tiering.enabled() is True


def test_closeup_focus_set_is_non_trivial():
    """特写集合来自 companion，非空且不含"全身"（全身是完整人设，不是小部件）。"""
    assert "手" in _CLOSEUP_FOCUS_SET
    assert "全身" not in _CLOSEUP_FOCUS_SET


# ── 降级链 ─────────────────────────────────────────────────────────────


def test_fallback_target_moves_one_step():
    """最多走一档：T3 → T2；T2 → T1；T1 → T2。"""
    assert image_tiering.fallback_target(image_tiering.tier("t3_artistic")).key == "t2_portrait"
    assert image_tiering.fallback_target(image_tiering.tier("t2_portrait")).key == "t1_high"
    assert image_tiering.fallback_target(image_tiering.tier("t1_high")).key == "t2_portrait"


def test_fallback_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(image_tiering, "enabled", lambda: False)
    assert image_tiering.fallback_target(image_tiering.tier("t3_artistic")) is None


def test_fallback_chain_excludes_relay_sentinel():
    """降级链里的 ``relay`` 是"转中转"的哨兵，不是即梦档位，不出现在 ImageTier 列表里。"""
    chain = image_tiering.fallback_chain(image_tiering.tier("t3_artistic"))
    assert [t.key for t in chain] == ["t2_portrait"]


# ── 候选 → 通道路由 ───────────────────────────────────────────────────


def test_persona_candidate_routes_to_jimeng_with_tier_model():
    """人像候选带档位 → 走即梦，并带上档位模型/分辨率（§8.4 接线）。"""
    hint = _image_tier_hint({
        "prompt_key": "role_selfie",
        "scene": "local_send",
        "image_tier": {"tier": "t2_portrait"},
    })
    assert hint["provider"] == "jimeng"
    assert hint["jimeng_model"] == "high_aes_general_v50_flash"
    assert hint["jimeng_resolution"] == "2K"
    assert hint["jimeng_tier"] == "t2_portrait"


def test_environment_candidate_routes_to_jimeng_pro():
    """"拍一下桌上的西瓜"（环境/物件）→ T1 Pro（走即梦，能出 9:16 竖构图）。"""
    hint = _image_tier_hint({"prompt_key": "environment_object"})
    assert hint["provider"] == "jimeng"
    assert hint["jimeng_model"] == "seedream_5.0_pro"


def test_disabled_tiering_keeps_legacy_provider_hint(monkeypatch):
    """总开关关闭 → 回落旧口径：只有人物类走即梦，模型交给 provider 默认。"""
    monkeypatch.setattr(image_tiering, "enabled", lambda: False)
    persona = _image_tier_hint({"prompt_key": "role_selfie"})
    env = _image_tier_hint({"prompt_key": "environment_object"})
    assert persona == {"provider": "jimeng"}
    assert "jimeng_model" not in persona
    assert env == {"provider": ""}


# ── provider 侧：读取覆盖值 + 档位降级 ─────────────────────────────────


def _stub_jimeng(monkeypatch, results: list[dict]):
    """替换 jimeng_canvas 全部门面函数，并记录每次 generate_image 的入参。"""
    from core import image_service as svc

    calls: list[dict] = []
    queue = list(results)

    class _Stub:
        @staticmethod
        def available() -> bool:
            return True

        @staticmethod
        def load_project_id() -> str:
            return "proj"

        @staticmethod
        def ensure_canvas(project_id: str) -> dict:
            return {"ok": True}

        @staticmethod
        def i2i_usable() -> bool:
            return False

        @staticmethod
        def persona_reference(persona_id: str) -> dict:
            return {}

        @staticmethod
        def credit_ceiling() -> int:
            return 16

        @staticmethod
        def default_model() -> str:
            return "provider_default_model"

        @staticmethod
        def default_resolution() -> str:
            return ""

        @staticmethod
        def note_i2i_blocked(error_code: str) -> None:
            return None

        @staticmethod
        def download_resource(resource_id: str, project_id: str = "", output: str = "") -> dict:
            return {"status": "ok", "image_bytes": b"png-bytes"}

        @staticmethod
        def generate_image(**kwargs) -> dict:
            calls.append(kwargs)
            return queue.pop(0) if queue else {"status": "failed", "error_code": "boom"}

    monkeypatch.setattr(svc, "jimeng_canvas", _Stub)
    return calls


def test_provider_uses_tier_model_and_resolution(monkeypatch):
    """provider 从 metadata 读档位覆盖值（此前这里是唯一真源 = 全局单模型）。"""
    calls = _stub_jimeng(monkeypatch, [{"status": "ok", "resource_id": "r1", "node_id": "n1"}])
    provider = JimengCanvasImageGenerationProvider(model="legacy_default")

    result = provider.generate(
        prompt="一张写实照片",
        request_id="req1",
        owner_id="master",
        metadata={"jimeng_model": "high_aes_general_v50_flash", "jimeng_resolution": "2K"},
    )

    assert result.status == "ok"
    assert calls[0]["model"] == "high_aes_general_v50_flash"
    assert calls[0]["resolution"] == "2K"
    assert result.model == "high_aes_general_v50_flash"
    assert result.metadata["resolution"] == "2K"


def test_provider_without_tier_keeps_its_own_default(monkeypatch):
    """没带档位（直调）→ 用 provider 自己的模型，行为与改动前一致。"""
    calls = _stub_jimeng(monkeypatch, [{"status": "ok", "resource_id": "r1", "node_id": "n1"}])
    provider = JimengCanvasImageGenerationProvider(model="legacy_default")

    provider.generate(prompt="p", request_id="req", owner_id="master", metadata={})

    assert calls[0]["model"] == "legacy_default"


def test_provider_falls_back_to_next_tier_on_failure(monkeypatch):
    """指定档失败 → 降级到下一档重试一次，用户最终拿到图（§8.7 验收 5）。"""
    calls = _stub_jimeng(monkeypatch, [
        {"status": "failed", "error_code": "service.7"},
        {"status": "ok", "resource_id": "r2", "node_id": "n2"},
    ])
    provider = JimengCanvasImageGenerationProvider()

    result = provider.generate(
        prompt="p",
        request_id="req",
        owner_id="master",
        metadata={"jimeng_model": "jm_image_model_yc_mj82", "jimeng_resolution": "2K",
                  "jimeng_tier": "t3_artistic"},
    )

    assert result.status == "ok"
    assert [c["model"] for c in calls] == ["jm_image_model_yc_mj82", "high_aes_general_v50_flash"]
    assert [c["resolution"] for c in calls] == ["2K", "2K"]


def test_provider_does_not_retry_when_credit_not_authorized(monkeypatch):
    """额度未授权（credit_exceeded）不降级：降级同样过不了闸门，重试只是白跑。"""
    calls = _stub_jimeng(monkeypatch, [{"status": "credit_exceeded", "error_code": "credit_exceeded"}])
    provider = JimengCanvasImageGenerationProvider()

    result = provider.generate(
        prompt="p",
        request_id="req",
        owner_id="master",
        metadata={"jimeng_tier": "t3_artistic"},
    )

    assert result.status == "credit_exceeded"
    assert len(calls) == 1

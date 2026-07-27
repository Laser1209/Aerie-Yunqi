"""P1-A.5 — 角色配置版本化 PersonaConfig 契约测试。

验证六类输入合并、revision 版本化、旧 revision 失效、持久化与
P0 VisualIntentRouter 接口兼容。

依赖：P0 Task 3.4 VisualIntentRouter（core.image_service）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.persona_config import PersonaConfig, VisualIdentity
from core.image_service import VisualIntentRouter


# ── 六类输入结构 ────────────────────────────────────────


def test_persona_config_contains_six_input_categories():
    """PersonaConfig SHALL expose the six merged input categories."""
    cfg = PersonaConfig(id="persona_5872")

    for attr in (
        "identity_facts",
        "visual_identity",
        "background",
        "speaking_style",
        "active_rules",
        "current_state",
    ):
        assert hasattr(cfg, attr), f"PersonaConfig 缺少六类输入字段: {attr}"

    assert isinstance(cfg.visual_identity, VisualIdentity)


# ── revision 版本化 ────────────────────────────────────


def test_save_records_revision_first_save_is_one(tmp_path: Path):
    """首次保存 SHALL 记录 revision=1。"""
    cfg = PersonaConfig(id="persona_5872")
    assert cfg.revision == 0  # 保存前 revision 为 0

    revision = cfg.save(persist_path=tmp_path / "persona_5872.json")

    assert revision == 1
    assert cfg.revision == 1


def test_update_any_field_increments_revision(tmp_path: Path):
    """更新任意字段后保存，revision SHALL 递增。"""
    cfg = PersonaConfig(id="persona_5872")
    rev1 = cfg.save(persist_path=tmp_path / "persona_5872.json")
    assert rev1 == 1

    cfg.background = {"location": "临海城市", "hobbies": ["夜跑"]}
    rev2 = cfg.save()

    assert rev2 == rev1 + 1
    assert cfg.revision == 2


def test_old_revision_invalidated_after_new_save(tmp_path: Path):
    """新 revision 保存后，旧 revision 引用 SHALL 标记为失效。"""
    cfg = PersonaConfig(id="persona_5872")
    rev1 = cfg.save(persist_path=tmp_path / "persona_5872.json")
    assert cfg.is_revision_valid(rev1) is True

    cfg.speaking_style = {"tone": "直球"}
    rev2 = cfg.save()

    assert rev2 > rev1
    # 旧 revision 在新 revision 保存后失效
    assert cfg.is_revision_valid(rev1) is False
    # 当前 revision 仍然有效
    assert cfg.is_revision_valid(rev2) is True


def test_is_revision_valid_returns_false_for_stale_and_true_for_current(tmp_path: Path):
    """revision 变化 SHALL 使旧生成候选失效。"""
    cfg = PersonaConfig(id="persona_5872")
    rev1 = cfg.save(persist_path=tmp_path / "persona_5872.json")

    cfg.active_rules = {"forbidden_topics": ["政治"]}
    rev2 = cfg.save()

    # 模拟旧生成候选持有的 revision
    stale_candidate_revision = rev1
    assert cfg.is_revision_valid(stale_candidate_revision) is False
    assert cfg.is_revision_valid(rev2) is True
    # 从未保存过的 revision 无效
    assert cfg.is_revision_valid(999) is False


# ── visual_identity 子结构（P0 兼容）──────────────────


def test_visual_identity_substructure_contains_required_fields():
    """visual_identity 子结构 SHALL 包含 visual_identity_revision 与
    selfie_reference_asset_id，与 P0 VisualIntentRouter 兼容。"""
    vi = VisualIdentity(
        visual_identity_revision=3,
        selfie_reference_asset_id="asset_selfie",
        couple_reference_asset_id="asset_couple",
    )
    metadata = vi.to_metadata_dict()

    assert metadata["visual_identity_revision"] == 3
    assert metadata["selfie_reference_asset_id"] == "asset_selfie"
    assert metadata["couple_reference_asset_id"] == "asset_couple"


def test_to_metadata_dict_compatible_with_visual_intent_router(tmp_path: Path):
    """PersonaConfig.to_metadata_dict() SHALL 产出 P0 VisualIntentRouter
    可消费的 persona_config 字典。"""
    cfg = PersonaConfig(id="persona_5872")
    cfg.visual_identity.visual_identity_revision = 3
    cfg.visual_identity.selfie_reference_asset_id = "asset_selfie"
    cfg.save(persist_path=tmp_path / "persona_5872.json")

    router = VisualIntentRouter()
    result = router.route(
        prompt="发张你的自拍",
        metadata={"persona_config": cfg.to_metadata_dict()},
    )

    assert result["status"] == "ok"
    assert result["visual_intent"] == "role_selfie"
    assert result["persona_id"] == "persona_5872"
    assert result["identity_revision"] == 3
    assert result["reference_assets"] == ["asset_selfie"]
    assert "face_identity" in result["must_preserve"]


# ── 持久化 ─────────────────────────────────────────────


def test_persist_and_reload_preserves_revision_and_fields(tmp_path: Path):
    """保存后重新加载，revision 与所有字段 SHALL 一致。"""
    path = tmp_path / "persona_5872.json"
    cfg = PersonaConfig(
        id="persona_5872",
        identity_facts={"name": "伊塔", "english_name": "Ita"},
        background={"location": "临海城市"},
        speaking_style={"tone": "直球"},
        active_rules={"forbidden_topics": ["政治"]},
        current_state={"mood": "Neutral"},
    )
    cfg.visual_identity.visual_identity_revision = 3
    cfg.visual_identity.selfie_reference_asset_id = "asset_selfie"
    cfg.visual_identity.couple_reference_asset_id = "asset_couple"
    cfg.save(persist_path=path)

    loaded = PersonaConfig.load(path)

    assert loaded.id == cfg.id
    assert loaded.revision == cfg.revision
    assert loaded.identity_facts == cfg.identity_facts
    assert loaded.background == cfg.background
    assert loaded.speaking_style == cfg.speaking_style
    assert loaded.active_rules == cfg.active_rules
    assert loaded.current_state == cfg.current_state
    assert loaded.visual_identity.visual_identity_revision == 3
    assert loaded.visual_identity.selfie_reference_asset_id == "asset_selfie"
    assert loaded.visual_identity.couple_reference_asset_id == "asset_couple"


def test_reload_after_update_keeps_latest_revision(tmp_path: Path):
    """更新后保存再加载，revision SHALL 反映最新值。"""
    path = tmp_path / "persona_5872.json"
    cfg = PersonaConfig(id="persona_5872")
    cfg.save(persist_path=path)
    cfg.background = {"location": "临海城市"}
    cfg.save()

    loaded = PersonaConfig.load(path)

    assert loaded.revision == 2
    assert loaded.background == {"location": "临海城市"}


# ── 六类输入按顺序注入 ─────────────────────────────────


def test_to_prompt_sequence_returns_six_categories_in_order():
    """to_prompt_sequence SHALL 按固定顺序输出六类输入：
    identity_facts → visual_identity → background → speaking_style →
    active_rules → current_state。"""
    cfg = PersonaConfig(
        id="persona_5872",
        identity_facts={"name": "伊塔"},
        background={"location": "临海城市"},
        speaking_style={"tone": "直球"},
        active_rules={"forbidden_topics": ["政治"]},
        current_state={"mood": "Neutral"},
    )

    sequence = cfg.to_prompt_sequence()
    keys = [name for name, _ in sequence]

    assert keys == [
        "identity_facts",
        "visual_identity",
        "background",
        "speaking_style",
        "active_rules",
        "current_state",
    ]
    # 每个元素是 (类别名, 内容) 二元组
    for name, content in sequence:
        assert isinstance(name, str)
        assert content is not None

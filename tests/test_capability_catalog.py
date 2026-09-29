"""能力目录（core/capability_catalog.py）契约测试。

目录是「模型/用户现在能用什么、缺什么、去哪儿配」的唯一事实来源，
所以这里重点守三件事：

1. **不可用项必须带「去哪儿配」**（而不是只甩一句 reason）；
2. **反查不到就留空** —— 绝不瞎指路；
3. **绝不携带密钥明文**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import capability_catalog as cc


@pytest.fixture(autouse=True)
def _isolate_ambient_segments(monkeypatch):
    """单元用例只关心 skill 段：把 plugin / mcp 两段钉空，避免受本机配置影响。"""
    monkeypatch.setattr(cc, "_plugin_entries", lambda: [])
    monkeypatch.setattr(cc, "_mcp_entries", lambda: [])


class _FakeLoader:
    """只需要 `discovered` 这个属性（与 SkillLoader 的结构契约一致）。"""

    def __init__(self, discovered: dict) -> None:
        self.discovered = discovered


def _loader_with(*records: tuple[str, dict]) -> _FakeLoader:
    return _FakeLoader({name: meta for name, meta in records})


def _entry(result: dict, name: str) -> dict:
    return next(e for e in result["unavailable"] if e["name"] == name)


def test_ready_skill_has_no_where_and_no_fix():
    loader = _loader_with(("doc-page", {
        "desc": "可打印文档页",
        "available": True,
        "unavailable_reason": "",
        "setup_hint": "",
    }))

    result = cc.snapshot(loader)

    assert result["total"] == 1
    assert result["ready_count"] == 1
    assert result["unavailable"] == []


def test_missing_env_maps_to_platform_credentials_page():
    """缺环境变量 → 反查平台凭证目录，给出「设置页 → 平台凭证 → 哪一块」。"""
    loader = _loader_with(("byted-seedream", {
        "desc": "Seedream 文生图",
        "available": False,
        "unavailable_reason": "missing env: SEEDREAM_KEY",
        "setup_hint": "",
    }))

    entry = _entry(cc.snapshot(loader), "byted-seedream")

    assert entry["fix_kind"] == "env"
    assert entry["missing"] == ["SEEDREAM_KEY"]
    assert "设置页" in entry["where"]
    assert "平台凭证" in entry["where"]


def test_missing_cli_uses_skill_declared_setup_hint():
    loader = _loader_with(("byted-mediakit", {
        "desc": "AI MediaKit",
        "available": False,
        "unavailable_reason": "missing cli: mediakit-cli",
        "setup_hint": "本机执行：npm install -g @volcengine/mediakit-cli",
    }))

    entry = _entry(cc.snapshot(loader), "byted-mediakit")

    assert entry["fix_kind"] == "cli"
    assert entry["missing"] == ["mediakit-cli"]
    assert entry["where"] == "本机执行：npm install -g @volcengine/mediakit-cli"


def test_not_implemented_carries_reason_text_as_where():
    loader = _loader_with(("alipay-payment", {
        "desc": "支付宝",
        "available": False,
        "unavailable_reason": "not implemented (scaffold stub): 本轮不做，涉及真实资金",
        "setup_hint": "",
    }))

    entry = _entry(cc.snapshot(loader), "alipay-payment")

    assert entry["fix_kind"] == "not_implemented"
    assert entry["where"] == "本轮不做，涉及真实资金"


def test_unknown_reason_leaves_where_empty_instead_of_guessing():
    """反查不到标识 → where 留空（不瞎指路）。"""
    loader = _loader_with(("weird", {
        "desc": "x",
        "available": False,
        "unavailable_reason": "some brand new gate",
        "setup_hint": "不该被用到",
    }))

    entry = _entry(cc.snapshot(loader), "weird")

    assert entry["fix_kind"] == ""
    assert entry["where"] == ""


def test_snapshot_limit_truncates_and_counts():
    loader = _loader_with(*[
        (f"skill-{i}", {
            "desc": "x",
            "available": False,
            "unavailable_reason": "missing module: mod_x",
            "setup_hint": "装 mod_x",
        })
        for i in range(5)
    ])

    result = cc.snapshot(loader, limit=2)

    assert result["unavailable_count"] == 5
    assert len(result["unavailable"]) == 2
    assert result["truncated"] == 3


def test_catalog_never_carries_secret_values():
    """目录只读"是否已配置"，绝不带值 —— 这条用真实仓库数据一起验。"""
    from core.skill_loader import SkillLoader

    loader = SkillLoader(None, None)
    loader.discover()
    result = cc.snapshot(loader)

    blob = json.dumps(result, ensure_ascii=False)
    for marker in ("sk-", "ntn_", "Bearer "):
        assert marker not in blob


def test_lookup_unknown_name_returns_none():
    loader = _loader_with(("doc-page", {
        "desc": "x", "available": True, "unavailable_reason": "", "setup_hint": "",
    }))

    assert cc.lookup("doc-page", loader) is not None
    assert cc.lookup("no-such-capability", loader) is None
    assert cc.lookup("", loader) is None


def test_real_repo_catalog_points_seedream_to_settings():
    """真实仓库端到端：未设 SEEDREAM_KEY 时，目录应指出去哪一页配。"""
    from core.skill_loader import SkillLoader

    loader = SkillLoader(None, None)
    loader.discover()
    entry = cc.lookup("byted-seedream", loader)

    assert entry is not None
    if entry.ready:
        return  # 本机已配了密钥：就绪态天然没有 where
    assert entry.fix_kind == "env"
    assert "SEEDREAM_KEY" in entry.missing
    assert "平台凭证" in entry.where


def test_real_repo_catalog_reports_cli_gated_skills():
    from core.skill_loader import SkillLoader

    loader = SkillLoader(None, None)
    loader.discover()
    entry = cc.lookup("byted-mediakit", loader)

    assert entry is not None
    if entry.ready:
        return
    assert entry.fix_kind == "cli"
    assert "mediakit-cli" in entry.missing
    assert "npm install" in entry.where

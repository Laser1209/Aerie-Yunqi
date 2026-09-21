"""A 部分：SkillLoader 目录发现测试。

覆盖：skills/cloud 能被发现并注册、缺失的 skill 根目录不报错、同名优先级。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import skill_loader as skill_loader_module
from core.skill_loader import SkillLoader
from core.skill_router import SkillRouter
from core.tool_registry import ToolRegistry


def _loader(registry: ToolRegistry | None = None) -> SkillLoader:
    return SkillLoader(registry or ToolRegistry(), SkillRouter({}))


def test_cloud_skills_are_discovered():
    loader = _loader()
    count = loader.discover()
    assert count >= 77

    cloud = {
        name: meta
        for name, meta in loader.discovered.items()
        if meta["kind"] == "cloud"
    }
    assert len(cloud) >= 59
    assert "mcp-builder" in cloud
    assert "defuddle" in cloud
    # api_server 的 /api/skills/{name} 依赖 path/SKILL.md 存在
    for meta in cloud.values():
        assert meta["path"].is_dir()
        assert (meta["path"] / "SKILL.md").exists()


def test_data_and_local_skills_are_still_discovered():
    """skills/data 与 skills/local 的既有发现行为不能回归。"""
    loader = _loader()
    loader.discover()
    assert loader.discovered["figma"]["kind"] == "data"
    assert loader.discovered["tts"]["kind"] == "local"


def test_cloud_skills_register_into_tool_registry():
    registry = ToolRegistry()
    loader = _loader(registry)
    discovered = loader.discover()
    registered = loader.register_all()

    assert discovered >= 77  # 59 cloud + 13 local + 5 data
    assert registered == discovered
    for name in ("mcp-builder", "defuddle"):
        entry = registry.get(name)
        assert entry is not None
        assert callable(entry["func"])
        assert entry["schema"]["function"]["name"] == name


def test_missing_skill_roots_are_tolerated(tmp_path, monkeypatch):
    """根目录不存在时 discover() 不抛异常，也不影响存在的根。"""
    cloud_dir = tmp_path / "cloud"
    (cloud_dir / "only-one").mkdir(parents=True)
    (cloud_dir / "only-one" / "SKILL.md").write_text(
        "---\nname: only-one\ndescription: demo\n---\n", encoding="utf-8"
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", (
        (tmp_path / "does-not-exist", "local"),
        (cloud_dir, "cloud"),
        (tmp_path / "also-missing", "data"),
    ))

    loader = _loader()
    assert loader.discover() == 1
    assert loader.discovered["only-one"]["kind"] == "cloud"


def _write_skill(root: Path, dir_name: str, name: str, marker: str) -> Path:
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {marker}\n---\n", encoding="utf-8"
    )
    (skill_dir / "run.py").write_text(
        f"def run(args=None):\n    return {{'marker': {marker!r}}}\n", encoding="utf-8"
    )
    return skill_dir


def test_local_shadows_cloud_on_same_name(tmp_path, monkeypatch):
    """同名优先级：local > cloud > data（先扫到的胜出）。"""
    local_dir = tmp_path / "local"
    cloud_dir = tmp_path / "cloud"
    data_dir = tmp_path / "data"
    local_path = _write_skill(local_dir, "demo-dir", "demo", "from-local")
    _write_skill(cloud_dir, "demo-dir", "demo", "from-cloud")
    _write_skill(data_dir, "demo-dir", "demo", "from-data")

    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", (
        (local_dir, "local"),
        (cloud_dir, "cloud"),
        (data_dir, "data"),
    ))
    monkeypatch.setattr(
        skill_loader_module,
        "_ALLOWED_BASES",
        (local_dir.resolve(), cloud_dir.resolve(), data_dir.resolve()),
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    assert loader.discover() == 1  # 只保留一条
    assert loader.discovered["demo"]["kind"] == "local"
    assert loader.discovered["demo"]["path"] == local_path

    assert loader.register_all() == 1
    assert registry.get("demo")["func"]({}) == {"marker": "from-local"}


def test_cloud_shadows_data_on_same_name(tmp_path, monkeypatch):
    cloud_dir = tmp_path / "cloud"
    data_dir = tmp_path / "data"
    cloud_path = _write_skill(cloud_dir, "demo-dir", "demo", "from-cloud")
    _write_skill(data_dir, "demo-dir", "demo", "from-data")

    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", (
        (tmp_path / "missing-local", "local"),
        (cloud_dir, "cloud"),
        (data_dir, "data"),
    ))

    loader = _loader()
    assert loader.discover() == 1
    assert loader.discovered["demo"]["kind"] == "cloud"
    assert loader.discovered["demo"]["path"] == cloud_path


def test_read_only_defaults_by_root(tmp_path, monkeypatch):
    """read_only 缺省语义保持原样：data 默认只读，local/cloud 默认可写；显式声明优先。"""
    local_dir = tmp_path / "local"
    cloud_dir = tmp_path / "cloud"
    data_dir = tmp_path / "data"
    _write_skill(local_dir, "a", "skill-a", "a")
    _write_skill(cloud_dir, "b", "skill-b", "b")
    _write_skill(data_dir, "c", "skill-c", "c")

    declared = cloud_dir / "d"
    declared.mkdir(parents=True)
    (declared / "SKILL.md").write_text(
        "---\nname: skill-d\ndescription: d\nread_only: true\n---\n", encoding="utf-8"
    )

    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", (
        (local_dir, "local"),
        (cloud_dir, "cloud"),
        (data_dir, "data"),
    ))

    loader = _loader()
    loader.discover()
    assert loader.discovered["skill-a"]["read_only"] is False
    assert loader.discovered["skill-b"]["read_only"] is False
    assert loader.discovered["skill-c"]["read_only"] is True
    assert loader.discovered["skill-d"]["read_only"] is True  # 显式声明优先

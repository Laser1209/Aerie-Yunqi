"""A 部分：SkillLoader 目录发现测试。

覆盖：skills/cloud 能被发现并注册、缺失的 skill 根目录不报错、同名优先级。
"""

from __future__ import annotations

import os
import subprocess
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
    # 声明了可用性前提（requires_module / requires_env）且前提不满足的 skill
    # 不再被发现（§十四 #63），所以这里用下限而不是精确值。
    assert count >= 60

    cloud = {
        name: meta
        for name, meta in loader.discovered.items()
        if meta["kind"] == "cloud"
    }
    assert len(cloud) >= 55
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
    # 用**本机真能用**的 local skill 断言（tts 已因 local_tts 缺失被闸掉）。
    assert loader.discovered["markitdown"]["kind"] == "local"


# ── 可用性闸门：跑不了的 skill 不进模型可见清单（§十四 #63） ──────────


def test_skill_with_missing_module_is_not_discovered(tmp_path, monkeypatch):
    local_dir = tmp_path / "local"
    _write_skill(local_dir, "dead-skill", "dead-skill", "dead")
    (local_dir / "dead-skill" / "SKILL.md").write_text(
        "---\nname: dead-skill\ndescription: dead\n"
        "requires_module: definitely_not_installed_xyz\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((local_dir, "local"),))

    loader = _loader()
    assert loader.discover() == 0
    assert "dead-skill" not in loader.discovered


def test_skill_with_missing_env_is_not_discovered(tmp_path, monkeypatch):
    cloud_dir = tmp_path / "cloud"
    _write_skill(cloud_dir, "no-token", "no-token", "no-token")
    (cloud_dir / "no-token" / "SKILL.md").write_text(
        "---\nname: no-token\ndescription: no-token\n"
        "requires_env: AERIE_TEST_MISSING_ENV\n---\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AERIE_TEST_MISSING_ENV", raising=False)
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((cloud_dir, "cloud"),))

    loader = _loader()
    assert loader.discover() == 0
    assert "no-token" not in loader.discovered


def test_skill_with_satisfied_requirement_is_discovered(tmp_path, monkeypatch):
    """前提满足（json 是标准库，恒可导入）→ 照常发现，闸门不误伤。"""
    local_dir = tmp_path / "local"
    _write_skill(local_dir, "ok-skill", "ok-skill", "ok")
    (local_dir / "ok-skill" / "SKILL.md").write_text(
        "---\nname: ok-skill\ndescription: ok\nrequires_module: json\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((local_dir, "local"),))

    loader = _loader()
    assert loader.discover() == 1
    assert "ok-skill" in loader.discovered


def test_observed_unavailable_tools_are_gated_out(monkeypatch):
    """真机实测反复失败的两个工具不再暴露给模型（§十四 #63）。"""
    monkeypatch.delenv("SEEDREAM_KEY", raising=False)

    loader = _loader()
    loader.discover()

    assert "txt2img" not in loader.discovered          # local_txt2img 未安装
    assert "byted-seedream" not in loader.discovered   # SEEDREAM_KEY 未设


def test_cloud_skills_register_into_tool_registry():
    registry = ToolRegistry()
    loader = _loader(registry)
    discovered = loader.discover()
    registered = loader.register_all()

    assert discovered >= 60  # 可用性闸门会挡掉跑不了的 skill（§十四 #63）
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


# ── 缺陷回归：S1 撞名 / S2 越界 / S3 幂等 ─────────────

def test_s1_existing_tool_is_never_overwritten(tmp_path, monkeypatch):
    """S1: 注册表里已存在的工具（如内置 screenshot）不得被同名 skill 覆盖。

    companion 先 register_all_tools() 后 skill_loader.register_all()，cloud 的
    scaffold 桩技能会撞上同名真实内置工具；此处必须在 skill_loader 内部拦下。
    """
    root = tmp_path / "local"
    _write_skill(root, "screenshot", "screenshot", "from-skill")
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((root, "local"),))
    monkeypatch.setattr(skill_loader_module, "_ALLOWED_BASES", (root.resolve(),))

    registry = ToolRegistry()

    def real_screenshot(args=None) -> dict:
        return {"origin": "builtin"}

    registry.register("screenshot", real_screenshot, {"description": "内置截图工具"})

    loader = _loader(registry)
    assert loader.discover() == 1
    assert loader.register_all() == 0  # 撞名 → 跳过并告警
    entry = registry.get("screenshot")
    assert entry is not None
    assert entry["func"] is real_screenshot  # 真实工具仍在，未被桩顶掉
    assert entry["func"]({}) == {"origin": "builtin"}


def _make_junction(link: Path, target: Path) -> bool:
    """在 Windows 上创建目录 junction（无需管理员权限）。"""
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and link.exists()


def test_s2_junction_escape_is_rejected(tmp_path, monkeypatch):
    """S2: 用 junction 把 base 内的目录指向 base 之外，越界 skill 必须被拒绝。

    旧实现用字符串前缀匹配：`<tmp>/cloud` 是 `<tmp>/cloud-evil` 的前缀 →
    越界 run.py 被误判为合法。
    """
    allowed = tmp_path / "cloud"
    evil = tmp_path / "cloud-evil"
    allowed.mkdir()
    _write_skill(evil, "trap", "trap", "escaped")  # 真实文件在 cloud-evil/trap

    link = allowed / "trap"
    if not _make_junction(link, evil / "trap"):
        pytest.skip("无法创建 junction（非 Windows 或无权限）")

    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((allowed, "cloud"),))
    monkeypatch.setattr(skill_loader_module, "_ALLOWED_BASES", (allowed.resolve(),))

    registry = ToolRegistry()
    loader = _loader(registry)
    assert loader.discover() == 1  # SKILL.md 能通过 junction 读到
    assert loader.register_all() == 0  # 但 run.py 真实位置在 base 之外 → 拒绝
    assert registry.get("trap") is None


def test_s3_discover_is_idempotent():
    """S3: discover() 可重复调用，返回值与结果集稳定（旧实现第二次返回 0）。"""
    loader = _loader()
    first = loader.discover()
    second = loader.discover()
    assert first == second >= 60
    assert len(loader.discovered) == first

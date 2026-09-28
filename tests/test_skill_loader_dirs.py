"""A 部分：SkillLoader 目录发现测试。

覆盖：skills/cloud 能被发现并注册、缺失的 skill 根目录不报错、同名优先级。
"""

from __future__ import annotations

import asyncio
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
    # 发现层不过滤可用性（panel 要能看到 SKILL.md），所以仍是全量 77。
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
    assert loader.discovered["markitdown"]["kind"] == "local"


# ── 可用性闸门：跑不了的 skill 不进**模型可见**清单（§十四 #63 / #74） ──
#
# 口径（R11 修正）：`discover()` 发现全部并标注 `available`；`register_all()`
# 只注册 available 的。此前把闸门放在 discover 层，会让 /api/skills/list 与
# /api/skills/{name} 把这类 skill 从面板上抹掉 —— 那是"让面板失明"，不是治理。


def test_skill_with_missing_module_is_discovered_but_not_registered(
    tmp_path, monkeypatch
):
    local_dir = tmp_path / "local"
    _write_skill(local_dir, "dead-skill", "dead-skill", "dead")
    (local_dir / "dead-skill" / "SKILL.md").write_text(
        "---\nname: dead-skill\ndescription: dead\n"
        "requires_module: definitely_not_installed_xyz\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((local_dir, "local"),))
    monkeypatch.setattr(
        skill_loader_module, "_ALLOWED_BASES", (local_dir.resolve(),)
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    assert loader.discover() == 1
    meta = loader.discovered["dead-skill"]
    assert meta["available"] is False
    assert "definitely_not_installed_xyz" in meta["unavailable_reason"]

    assert loader.register_all() == 0
    assert registry.get("dead-skill") is None


def test_skill_with_missing_env_is_discovered_but_not_registered(
    tmp_path, monkeypatch
):
    cloud_dir = tmp_path / "cloud"
    _write_skill(cloud_dir, "no-token", "no-token", "no-token")
    (cloud_dir / "no-token" / "SKILL.md").write_text(
        "---\nname: no-token\ndescription: no-token\n"
        "requires_env: AERIE_TEST_MISSING_ENV\n---\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AERIE_TEST_MISSING_ENV", raising=False)
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((cloud_dir, "cloud"),))
    monkeypatch.setattr(
        skill_loader_module, "_ALLOWED_BASES", (cloud_dir.resolve(),)
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    assert loader.discover() == 1
    assert loader.discovered["no-token"]["available"] is False
    assert loader.register_all() == 0
    assert registry.get("no-token") is None


def test_scaffold_stub_is_not_registered(tmp_path, monkeypatch):
    """`implemented: false` 的 scaffold 桩不注册（§十四 #74）。

    真机实录：`canvas-design` 被模型调用并恒返 `cloud_call_not_implemented`。
    它既不缺模块也不缺凭证，光靠 requires_* 挡不住，必须显式声明"还没实现"。
    """
    cloud_dir = tmp_path / "cloud"
    _write_skill(cloud_dir, "stub-skill", "stub-skill", "stub")
    (cloud_dir / "stub-skill" / "SKILL.md").write_text(
        "---\nname: stub-skill\ndescription: stub\nimplemented: false\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((cloud_dir, "cloud"),))
    monkeypatch.setattr(
        skill_loader_module, "_ALLOWED_BASES", (cloud_dir.resolve(),)
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    loader.discover()
    assert loader.discovered["stub-skill"]["available"] is False
    assert loader.register_all() == 0
    assert registry.get("stub-skill") is None


def test_skill_with_satisfied_requirement_is_registered(tmp_path, monkeypatch):
    """前提满足（json 是标准库，恒可导入）→ 照常注册，闸门不误伤。"""
    local_dir = tmp_path / "local"
    _write_skill(local_dir, "ok-skill", "ok-skill", "ok")
    (local_dir / "ok-skill" / "SKILL.md").write_text(
        "---\nname: ok-skill\ndescription: ok\nrequires_module: json\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((local_dir, "local"),))
    monkeypatch.setattr(
        skill_loader_module, "_ALLOWED_BASES", (local_dir.resolve(),)
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    assert loader.discover() == 1
    assert loader.discovered["ok-skill"]["available"] is True
    assert loader.register_all() == 1
    assert registry.get("ok-skill") is not None


def test_observed_unavailable_tools_do_not_reach_the_model(monkeypatch):
    """真机实测反复失败的工具不再注册给模型（§十四 #63 / #74）。"""
    monkeypatch.delenv("SEEDREAM_KEY", raising=False)

    registry = ToolRegistry()
    loader = _loader(registry)
    loader.discover()
    loader.register_all()

    for name in ("txt2img", "byted-seedream", "canvas-design"):
        # 仍被发现（面板能读 SKILL.md），但模型看不到
        assert name in loader.discovered
        assert loader.discovered[name]["available"] is False
        assert registry.get(name) is None


def test_unavailable_skill_does_not_shadow_an_available_one(tmp_path, monkeypatch):
    """跑不了的 skill 不得挡住同名的可用 skill（否则一个死掉的 local 会永久遮蔽）。"""
    local_dir = tmp_path / "local"
    cloud_dir = tmp_path / "cloud"
    _write_skill(local_dir, "dup", "dup", "from-local")
    (local_dir / "dup" / "SKILL.md").write_text(
        "---\nname: dup\ndescription: dup\n"
        "requires_module: definitely_not_installed_xyz\n---\n",
        encoding="utf-8",
    )
    cloud_path = _write_skill(cloud_dir, "dup-dir", "dup", "from-cloud")

    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", (
        (local_dir, "local"),
        (cloud_dir, "cloud"),
    ))
    monkeypatch.setattr(
        skill_loader_module,
        "_ALLOWED_BASES",
        (local_dir.resolve(), cloud_dir.resolve()),
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    loader.discover()
    meta = loader.discovered["dup"]
    assert meta["kind"] == "cloud"
    assert meta["path"] == cloud_path

    assert loader.register_all() == 1
    assert registry.get("dup") is not None


def test_cloud_skills_register_into_tool_registry():
    """注册的是**可用**子集；未注册的那些必须都标了 available=False。"""
    registry = ToolRegistry()
    loader = _loader(registry)
    discovered = loader.discover()
    registered = loader.register_all()

    assert discovered >= 77
    assert registered < discovered  # 本体有大量不可用 skill（见下条）
    assert registered == sum(
        1 for meta in loader.discovered.values() if meta["available"]
    )
    for name, meta in loader.discovered.items():
        if meta["available"]:
            assert registry.get(name) is not None
        else:
            assert registry.get(name) is None


def test_available_skill_is_registered_with_working_signature(tmp_path, monkeypatch):
    """注册进去的 skill 必须真的能被 registry 调用（§十四 #73 契约对齐）。"""
    local_dir = tmp_path / "local"
    _write_skill(local_dir, "echo", "echo", "echoed")
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((local_dir, "local"),))
    monkeypatch.setattr(
        skill_loader_module, "_ALLOWED_BASES", (local_dir.resolve(),)
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    loader.discover()
    loader.register_all()

    entry = registry.get("echo")
    assert entry is not None
    assert entry["func"]({}) == {"marker": "echoed"}


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
    assert first == second >= 77
    assert len(loader.discovered) == first


# ── #73 调用契约：run(args) ↔ registry 的 func(**kwargs) ─────────────


def test_entry_adapter_accepts_both_call_shapes():
    """注册后的工具既能收 `args={...}` 也能收平铺 kwargs（§十四 #73）。

    真机实录：模型平铺参数调 skill → ``unexpected keyword argument``；
    不带参数调 → ``missing 1 required positional argument: 'args'``。
    两种形状都必须是"到达 run()"，而不是崩在签名上。
    """
    from core.skill_loader import _adapt_skill_entry

    seen: list[dict] = []

    def run(args: dict) -> dict:
        seen.append(dict(args))
        return {"ok": True}

    wrapped = _adapt_skill_entry(run)

    wrapped({"image_path": "a.png"})            # 内层 args
    wrapped(image_path="b.png")                 # 平铺 kwarg
    wrapped({"image_path": "c.png"}, question="这是什么")  # 混合，平铺优先
    wrapped()                                   # 无参数 → 交给 run 自己报 missing

    assert seen == [
        {"image_path": "a.png"},
        {"image_path": "b.png"},
        {"image_path": "c.png", "question": "这是什么"},
        {},
    ]


def test_entry_adapter_works_through_registry(tmp_path, monkeypatch):
    """端到端：注册后的 skill 用平铺参数经 registry.execute 调用不再崩。"""
    local_dir = tmp_path / "local"
    _write_skill(local_dir, "echo-flat", "echo-flat", "flat")
    (local_dir / "echo-flat" / "run.py").write_text(
        "def run(args):\n    return {'got': dict(args)}\n", encoding="utf-8"
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((local_dir, "local"),))
    monkeypatch.setattr(
        skill_loader_module, "_ALLOWED_BASES", (local_dir.resolve(),)
    )

    registry = ToolRegistry()
    loader = _loader(registry)
    loader.discover()
    loader.register_all()

    assert asyncio.run(registry.execute("echo-flat", {"args": {"k": 1}})) == {
        "got": {"k": 1}
    }
    assert asyncio.run(registry.execute("echo-flat", {"k": 2})) == {"got": {"k": 2}}
    assert asyncio.run(registry.execute("echo-flat", {})) == {"got": {}}

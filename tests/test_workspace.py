"""工作区管理器 + 路径提取的单元测试。

纯 mock / 临时目录,不触碰真实 D 盘目录、不调真实 LLM、不触发 os.startfile。
"""

from __future__ import annotations

import pytest

from core.computer_control import (
    AccessPolicy,
    ControlAction,
    ControlMode,
    PolicyEntryType,
)
from core.pipeline import _extract_paths
from core.workspace import WorkspaceManager, _ROOTS_STATE_FILE


@pytest.fixture
def ws(tmp_path, monkeypatch):
    # 隔离持久化文件,避免测试污染真实 data/workspace_roots.json
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "workspace_roots.json")
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir(parents=True, exist_ok=True)   # 默认根只播种真实存在的目录
    root_b.mkdir(parents=True, exist_ok=True)
    # L4：add_root 要求目录真实存在，测试统一预建常用根
    (tmp_path / "temp_x").mkdir(parents=True, exist_ok=True)
    return WorkspaceManager(default_roots=[str(root_a), str(root_b)])


@pytest.fixture
def root_a(tmp_path):
    d = tmp_path / "root_a"
    d.mkdir(parents=True, exist_ok=True)
    (d / "doc.pdf").write_bytes(b"pdf-bytes")
    from PIL import Image

    img = Image.new("RGB", (64, 64), (200, 120, 80))
    img.save(d / "pic.png", format="PNG")
    (d / "sub").mkdir(exist_ok=True)
    (d / "sub" / "inner.txt").write_text("hello")
    return d


# --------------------------------------------------------------------- 路径提取


@pytest.mark.parametrize(
    "text,expected",
    [
        ("帮我整理 D:\\T08171634 文件夹", ["D:\\T08171634"]),
        ("把 E:\\Downloads 里的文件归类", ["E:\\Downloads"]),
        ("整理 D:\\T08171634,顺便删重复", ["D:\\T08171634"]),
        ("今天好累呀", []),
        ("", []),
        ("把 D:\\A 和 E:\\B 都整理一下", ["D:\\A", "E:\\B"]),
    ],
)
def test_extract_paths(text, expected):
    assert _extract_paths(text) == expected


def test_extract_paths_dedup():
    assert _extract_paths("整理 D:\\X 再整理 D:\\X") == ["D:\\X"]


# --------------------------------------------------------------------- 工作区根目录


def test_roots_seeded_from_defaults(ws, tmp_path):
    roots = ws.roots()
    assert len(roots) == 2
    assert str(tmp_path / "root_a") in roots


def test_seed_skips_nonexistent_default_dirs(tmp_path, monkeypatch):
    """默认根里不存在的目录不播种——进白名单毫无意义。"""
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "ws.json")
    real = tmp_path / "real"
    real.mkdir()
    manager = WorkspaceManager(default_roots=[str(real), str(tmp_path / "ghost")])
    assert manager.roots() == [str(real)]


def test_add_root(ws, tmp_path):
    assert ws.add_root(str(tmp_path / "temp_x")) is True
    assert ws.add_root(str(tmp_path / "temp_x")) is False  # 去重
    assert str(tmp_path / "temp_x") in ws.roots()


def test_remove_root_allows_any_root(ws, tmp_path):
    """任何根都可移除（用户要求不锁死），包括默认播种的那个。"""
    ws.add_root(str(tmp_path / "temp_x"))
    assert ws.remove_root(str(tmp_path / "temp_x")) is True
    assert str(tmp_path / "temp_x") not in ws.roots()
    assert ws.remove_root(str(tmp_path / "root_a")) is True
    assert str(tmp_path / "root_a") not in ws.roots()
    # 未注册的目录移除返回 False
    assert ws.remove_root(str(tmp_path / "nope")) is False


def test_removed_default_is_not_reseeded_on_restart(tmp_path, monkeypatch):
    """默认根被移除后重启不得自动加回，否则「想移除哪个就移除哪个」是空话。"""
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "ws.json")
    root_a = tmp_path / "root_a"
    root_a.mkdir()
    ws1 = WorkspaceManager(default_roots=[str(root_a)])
    assert ws1.remove_root(str(root_a)) is True

    ws2 = WorkspaceManager(default_roots=[str(root_a)])
    assert ws2.roots() == []


def test_removing_active_root_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "ws.json")
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    manager = WorkspaceManager(default_roots=[str(root_a), str(root_b)])
    manager.set_active_root(str(root_b))
    manager.remove_root(str(root_b))
    assert manager.active_root() == str(root_a)


def test_roots_persist_across_reload(tmp_path, monkeypatch):
    """增删都持久化:重建实例后与文件一致。"""
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "ws.json")
    (tmp_path / "temp_x").mkdir(parents=True, exist_ok=True)
    ws1 = WorkspaceManager(default_roots=[])
    ws1.add_root(str(tmp_path / "temp_x"))

    ws2 = WorkspaceManager(default_roots=[])
    assert str(tmp_path / "temp_x") in ws2.roots()  # 新增重启后保留
    assert len(ws2.roots()) == 1

    ws2.remove_root(str(tmp_path / "temp_x"))
    ws3 = WorkspaceManager(default_roots=[])
    assert ws3.roots() == []  # 移除也持久化


def test_add_root_rejects_missing_dir(ws, tmp_path):
    """L4：不存在的目录不能注册为授权根。"""
    ghost = tmp_path / "does_not_exist"
    assert ghost.exists() is False
    assert ws.add_root(str(ghost)) is False
    assert str(ghost) not in ws.roots()


def test_add_root_from_file_registers_parent_dir(ws, tmp_path):
    """P1-1：给一个文件路径 → 注册其父目录（而非拒绝）。

    "把 D:\\a\\b.pptx 发给我" 是用户最自然的表达；旧实现要求 is_dir()，
    这条路直接是死路。
    """
    nested = tmp_path / "granted_parent"
    nested.mkdir()
    file_path = nested / "a_file.txt"
    file_path.write_text("x")
    assert ws.add_root(str(file_path)) is True
    assert str(nested) in ws.roots()


def test_add_root_from_file_is_deduped_by_parent(ws, tmp_path):
    """同一目录下的两个文件 → 只注册一次父目录。"""
    nested = tmp_path / "granted_parent"
    nested.mkdir()
    (nested / "one.txt").write_text("1")
    (nested / "two.txt").write_text("2")
    assert ws.add_root(str(nested / "one.txt")) is True
    assert ws.add_root(str(nested / "two.txt")) is False
    assert ws.roots().count(str(nested)) == 1


def test_get_workspace_manager_seeds_office_dir(tmp_path, monkeypatch):
    """P1-1：office.dir 也是工作区的默认成员，两套"根"口径统一。

    办公目录本就无条件可写，却不出现在工作区面板里；不登记它，用户看到的
    授权范围和实际许可范围就是两码事。
    """
    ws_root = tmp_path / "ws_root"
    office = tmp_path / "office"
    ws_root.mkdir()
    office.mkdir()
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "ws.json")
    monkeypatch.setattr("core.workspace._workspace_manager", None)
    monkeypatch.setattr(
        "config.persona_loader.load_settings",
        lambda: {
            "agent": {"workspace_default_roots": [str(ws_root)]},
            "office": {"dir": str(office)},
        },
    )
    from core.workspace import get_workspace_manager

    roots = get_workspace_manager().roots()
    assert str(ws_root) in roots
    assert str(office) in roots


# --------------------------------------------------------------------- 激活工作区


def test_active_root_defaults_to_first(ws, tmp_path):
    assert ws.active_root() == str(tmp_path / "root_a")


def test_set_active_root(ws, tmp_path):
    ws.add_root(str(tmp_path / "temp_x"))
    assert ws.set_active_root(str(tmp_path / "temp_x")) == str(tmp_path / "temp_x")
    assert ws.active_root() == str(tmp_path / "temp_x")


def test_set_active_root_rejects_unregistered(ws, tmp_path):
    before = ws.active_root()
    ws.set_active_root(str(tmp_path / "not_registered"))
    assert ws.active_root() == before  # 拒绝后保持原值


def test_active_root_falls_back_when_removed(ws, tmp_path):
    ws.add_root(str(tmp_path / "temp_x"))
    ws.set_active_root(str(tmp_path / "temp_x"))
    ws.remove_root(str(tmp_path / "temp_x"))
    assert ws.active_root() == str(tmp_path / "root_a")  # 回退首个根


def test_active_root_persists_across_reload(tmp_path, monkeypatch):
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "ws.json")
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    ws1 = WorkspaceManager(default_roots=[str(root_a), str(root_b)])
    ws1.set_active_root(str(root_b))

    ws2 = WorkspaceManager(default_roots=[str(root_a), str(root_b)])
    assert ws2.active_root() == str(root_b)  # 重启后保留激活状态


def test_resolve_within(root_a, ws, tmp_path):
    # 绝对路径在工作区内 → 放行
    resolved = ws.resolve_within(str(root_a / "doc.pdf"))
    assert resolved is not None and resolved.name == "doc.pdf"
    # 工作区外的绝对路径 → 拒绝
    outside = tmp_path / "outside" / "evil.txt"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("x")
    assert ws.resolve_within(str(outside)) is None
    # 根目录本身放行
    assert ws.resolve_within(str(root_a)) is not None


def test_resolve_within_rejects_parent_traversal(root_a, ws):
    """C6：相对路径携带 ..\\.. 逃出工作区必须拒绝（无论目标是否存在）。"""
    escape = ws.resolve_within(r"..\..\..\Windows\System32\evil.dll")
    assert escape is None


def test_resolve_within_relative_nonexistent_inside(root_a, ws):
    """C6：根内不存在的相对路径仍可解析（写入场景），但必须落在根内。"""
    target = ws.resolve_within(r"sub\new_file.txt")
    assert target is not None
    assert target == (root_a / "sub" / "new_file.txt").resolve()


def test_resolve_within_no_roots(tmp_path, monkeypatch):
    monkeypatch.setattr("core.workspace._ROOTS_STATE_FILE", tmp_path / "empty.json")
    empty_ws = WorkspaceManager(default_roots=[])
    assert empty_ws.resolve_within("anything.txt") is None


# --------------------------------------------------------------------- 文件树


def test_tree(root_a, ws):
    tree = ws.tree(str(root_a))
    names = {e["name"] for e in tree["entries"]}
    assert "doc.pdf" in names
    assert "pic.png" in names
    assert "sub" in names
    sub = next(e for e in tree["entries"] if e["name"] == "sub")
    assert sub["is_dir"] is True
    pdf = next(e for e in tree["entries"] if e["name"] == "doc.pdf")
    assert pdf["is_image"] is False
    png = next(e for e in tree["entries"] if e["name"] == "pic.png")
    assert png["is_image"] is True


def test_tree_outside_rejected(ws, tmp_path):
    with pytest.raises(ValueError):
        ws.tree(str(tmp_path))  # tmp_path 不在 root_a/root_b 内


# --------------------------------------------------------------------- 缩略图


def test_thumbnail_png(root_a, ws):
    data = ws.thumbnail(str(root_a / "pic.png"), size=64)
    assert data is not None
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_thumbnail_non_image(root_a, ws):
    assert ws.thumbnail(str(root_a / "doc.pdf")) is None
    assert ws.thumbnail(str(root_a / "missing.png")) is None


# --------------------------------------------------------------------- 打开


def test_open_rejects_outside(ws, tmp_path):
    outside = tmp_path / "outside"
    ok, _ = ws.open_path(str(outside))
    assert ok is False  # 越界拒绝,不触发 os.startfile


# --------------------------------------------------------------------- 操作日志


def test_activities_order(ws):
    ws.add_activity(kind="scan", detail="扫描完成")
    ws.add_activity(kind="execute", detail="移动 3 个文件")
    rows = ws.activities()
    assert len(rows) == 2
    assert rows[0]["detail"] == "移动 3 个文件"  # 倒序:最新在前


def test_activities_clear(ws):
    ws.add_activity(kind="scan", detail="x")
    ws.clear_activities()
    assert ws.activities() == []


# --------------------------------------------------------------------- 权限联动(v0.4.2)
# decide_write 与电脑操控共用同一 AccessPolicy(四级模式 + 黑白名单),仅拦写操作


def _policy(mode: ControlMode = ControlMode.MANUAL) -> AccessPolicy:
    """构造不落盘的 AccessPolicy(persist=False,避免污染 settings.yaml)。"""
    return AccessPolicy(mode=mode, persist=False)


def test_decide_write_no_policy_defaults_allow(ws):
    # 未注入 policy → 兼容旧行为,默认放行
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_manual_approves(ws):
    ws.bind_access_policy(_policy(ControlMode.MANUAL))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "approve"


def test_decide_write_auto_approves_medium_risk(ws):
    # FILE_WRITE 映射 MEDIUM → AUTO 模式需审批
    ws.bind_access_policy(_policy(ControlMode.AUTO))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "approve"


def test_decide_write_full_allows(ws):
    ws.bind_access_policy(_policy(ControlMode.FULL))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_custom_default_intercepts(ws):
    # CUSTOM 无规则:默认拦截(走审批弹窗)
    ws.bind_access_policy(_policy(ControlMode.CUSTOM))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "approve"


def test_decide_write_custom_block_rule(ws):
    p = _policy(ControlMode.CUSTOM)
    p.set_custom_rule(ControlAction.FILE_WRITE.value, "block")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "block"


def test_decide_write_custom_allow_rule(ws):
    p = _policy(ControlMode.CUSTOM)
    p.set_custom_rule(ControlAction.FILE_WRITE.value, "allow")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_whitelist_overrides_mode(ws):
    # 白名单命中直接放行,MANUAL 也放行
    p = _policy(ControlMode.MANUAL)
    p.add_whitelist(PolicyEntryType.ACTION.value, ControlAction.FILE_WRITE.value, "工作区写操作")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_blacklist_blocks_even_full(ws):
    # 黑名单硬闸:FULL 模式下仍拦截
    p = _policy(ControlMode.FULL)
    p.add_blacklist(PolicyEntryType.ACTION.value, ControlAction.FILE_WRITE.value, "禁止文件写操作")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "block"

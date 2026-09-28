"""office_tools 安全修复测试（2026-09-25 审计批B）。

覆盖：
- C2 写工具统一守卫：越界拒绝、MANUAL 策略拒绝并写审计；
- C6 路径逃逸（..\\.. / 改名携带分隔符）；
- M3 app_open 拒绝 cmd/powershell/UNC/带参数/危险解释器；
- M4 web_fetch 协议白名单与本机地址阻断。

全部在 tmp_path 内操作，不启动真实程序、不发起真实网络请求。
"""

from __future__ import annotations

from enum import Enum

import pytest

from core import office_tools
from core.computer_control import ControlAction, Decision


# ────────────────────────────────────────────── fixtures / fakes


class _FakePermission:
    def __init__(self, decision: Decision, reason: str = "fake"):
        self._decision = decision
        self._reason = reason
        self.calls: list[tuple] = []

    def decide(self, action, params):
        self.calls.append((action, dict(params)))
        return self._decision, self._reason


class _FakeController:
    def __init__(self, decision: Decision = Decision.ALLOW):
        self.permission = _FakePermission(decision)
        self.audit_calls: list[tuple] = []

    def _audit(self, action, params, result):
        self.audit_calls.append((action, dict(params), result))


@pytest.fixture
def office_dir(tmp_path, monkeypatch):
    """把办公目录隔离到 tmp（守卫天然把它当授权根）。"""
    d = tmp_path / "AerieOffice"
    d.mkdir()
    # get_office_dir() 每次从 settings 重读，必须 patch 函数本身
    monkeypatch.setattr(office_tools, "get_office_dir", lambda: d)
    return d


@pytest.fixture
def fake_controller(monkeypatch):
    controller = _FakeController()
    monkeypatch.setattr(office_tools, "_get_controller", lambda: controller)
    return controller


@pytest.fixture
def no_controller(monkeypatch):
    monkeypatch.setattr(office_tools, "_get_controller", lambda: None)


# ────────────────────────────────────────────── C6/C2：路径守卫


def test_guard_rejects_outside_root(office_dir, no_controller, tmp_path):
    """目标在办公目录与所有工作区之外 → 拒绝。"""
    blocked = office_tools.guard_write_paths(
        destination=str(tmp_path / "outside" / "x.txt")
    )
    assert blocked is not None
    assert blocked["success"] is False
    assert blocked["reason"] == "outside_workspace_roots"


def test_guard_rejects_parent_traversal(office_dir, no_controller):
    blocked = office_tools.guard_write_paths(
        destination=str(office_dir / ".." / ".." / "evil.txt")
    )
    assert blocked is not None and blocked["success"] is False


def test_guard_allows_inside_office_dir(office_dir, no_controller):
    assert office_tools.guard_write_paths(
        destination=str(office_dir / "out" / "x.txt")
    ) is None


def test_guard_manual_mode_blocks_and_audits(office_dir, fake_controller):
    fake_controller.permission._decision = Decision.APPROVE
    result = office_tools.guard_write_paths(destination=str(office_dir / "x.txt"))
    assert result is not None
    assert result["success"] is False
    assert result["needs_approval"] is True
    # 拦截也要留审计
    assert fake_controller.audit_calls
    assert fake_controller.audit_calls[0][2] == "needs_approval"


def test_guard_full_mode_allows_and_audits(office_dir, fake_controller):
    result = office_tools.guard_write_paths(destination=str(office_dir / "x.txt"))
    assert result is None
    assert fake_controller.audit_calls[0][2] == "allowed"
    assert fake_controller.permission.calls[0][0] == ControlAction.FILE_WRITE


# ────────────────────────────────────────────── 写工具端到端（不落盘越界）


def test_file_copy_outside_rejected(office_dir, no_controller, tmp_path):
    src = office_dir / "a.txt"
    src.write_text("hello")
    out_dir = tmp_path / "outside"
    out_dir.mkdir()
    result = office_tools.tool_file_copy(
        source=str(src), destination=str(out_dir / "b.txt")
    )
    assert result["success"] is False
    assert not (out_dir / "b.txt").exists()


def test_file_copy_inside_allowed(office_dir, no_controller):
    src = office_dir / "a.txt"
    src.write_text("hello")
    dst = office_dir / "b.txt"
    result = office_tools.tool_file_copy(source=str(src), destination=str(dst))
    assert result["success"] is True
    assert dst.read_text() == "hello"


def test_directory_create_outside_rejected(no_controller, tmp_path):
    result = office_tools.tool_directory_create(
        directory=str(tmp_path / "outside" / "new_dir")
    )
    assert result["success"] is False


def test_directory_create_inside_allowed(office_dir, no_controller):
    target = office_dir / "new_dir"
    result = office_tools.tool_directory_create(directory=str(target))
    assert result["success"] is True
    assert target.is_dir()


def test_file_rename_traversal_rejected(office_dir, no_controller):
    f = office_dir / "a.txt"
    f.write_text("x")
    result = office_tools.tool_file_rename(
        filepath=str(f), new_name=r"..\..\evil.txt"
    )
    assert result["success"] is False
    assert f.exists()


# ────────────────────────────────────────────── M3：app_open


@pytest.mark.parametrize(
    "app_name",
    ["cmd", "cmd.exe", "powershell", "powershell.exe", "wscript", "mshta"],
)
def test_app_open_rejects_shells(app_name, office_dir, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("绝不能真的启动进程")

    monkeypatch.setattr("subprocess.Popen", _boom)
    result = office_tools.tool_app_open(app_name)
    assert result["success"] is False


def test_app_open_rejects_unc(office_dir):
    result = office_tools.tool_app_open(r"\\evil\share\backdoor.exe")
    assert result["success"] is False


def test_app_open_rejects_arguments(office_dir):
    result = office_tools.tool_app_open("notepad.exe c:\\secret.txt")
    assert result["success"] is False


def test_app_open_rejects_script_extension_absolute(office_dir):
    result = office_tools.tool_app_open(str(office_dir / "payload.bat"))
    assert result["success"] is False
    result = office_tools.tool_app_open(str(office_dir / "payload.vbs"))
    assert result["success"] is False


def test_app_open_whitelisted_starts_directly(office_dir, monkeypatch):
    from core.computer_control import ComputerController, ControlMode, ControlResult
    from unittest.mock import Mock

    controller = ComputerController(mode=ControlMode.AUTO, persist=False, audit_log_dir=str(office_dir / "audit"))
    launch = Mock(return_value=ControlResult(True, "app_launch"))
    monkeypatch.setattr(controller, "_launch_app", launch)
    monkeypatch.setattr(office_tools, "_get_controller", lambda: controller)
    result = office_tools.tool_app_open("notepad")
    assert result["success"] is True
    launch.assert_called_once_with(exe="notepad.exe", args=[])
    assert controller.get_audit_logs()[-1]["action"] == "app_launch"


# ────────────────────────────────────────────── M4：web_fetch


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/win.ini",
        "ftp://example.com/x",
        "gopher://example.com/",
    ],
)
def test_web_fetch_rejects_non_http_schemes(url):
    result = office_tools.tool_web_fetch(url)
    assert result["success"] is False
    assert "协议" in result["error"]


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "::1", "169.254.169.254"],
)
def test_web_fetch_rejects_local_hosts(host):
    result = office_tools.tool_web_fetch(f"http://{host}/secret")
    assert result["success"] is False


def test_is_blocked_fetch_host_helper():
    assert office_tools._is_blocked_fetch_host("127.0.0.1") is True
    assert office_tools._is_blocked_fetch_host("localhost") is True
    assert office_tools._is_blocked_fetch_host("169.254.169.254") is True
    assert office_tools._is_blocked_fetch_host("example.com") is False
    assert office_tools._is_blocked_fetch_host("8.8.8.8") is False


# ────────────────────────────────────────────── document_read 前缀绕过


def test_document_read_prefix_sibling_dir_rejected(office_dir, monkeypatch, tmp_path):
    """Desktop 与 Desktop2 是同级不同目录，startswith 判定会误放行。"""
    user_home = tmp_path / "home"
    desktop = user_home / "Desktop"
    desktop2 = user_home / "Desktop2"
    desktop.mkdir(parents=True)
    desktop2.mkdir(parents=True)
    secret = desktop2 / "secret.txt"
    secret.write_text("secret")
    monkeypatch.setattr(
        office_tools.os.path, "expanduser",
        lambda p: str(user_home / p.replace("~/", "").replace("~\\", "")),
    )
    result = office_tools.tool_document_read(filepath=str(secret))
    assert result["success"] is False


# ────────────────────────── #68 授权白名单单一真源（读/搜/写同一份名单）


@pytest.fixture
def ws_root(tmp_path, monkeypatch):
    """把工作区管理器隔离到 tmp，并注册一个授权根。

    修复前 document_read / file_search 各自硬编码"桌面/文档/下载/AerieOffice"，
    完全无视用户在工作区里加的目录，于是出现过「E:\\ 在授权根里却读不了」。
    """
    import core.workspace as workspace

    monkeypatch.setattr(workspace, "_ROOTS_STATE_FILE", tmp_path / "ws.json")
    root = tmp_path / "authorized"
    root.mkdir()
    manager = workspace.WorkspaceManager(default_roots=[str(root)])
    monkeypatch.setattr(workspace, "_workspace_manager", manager)
    return root


def test_document_read_allows_registered_workspace_root(office_dir, ws_root):
    """工作区里授权过的目录，读取必须放行（§十四 #68 的核心症状）。"""
    note = ws_root / "note.txt"
    note.write_text("hello", encoding="utf-8")

    result = office_tools.tool_document_read(filepath=str(note))

    assert result["success"] is True
    assert result["content"] == "hello"


def test_document_read_rejects_unregistered_dir(office_dir, ws_root):
    """既不在工作区、也不在办公目录/常用文档目录 → 仍拒绝，且给出可操作原因。"""
    outside = ws_root.parent / "elsewhere"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    result = office_tools.tool_document_read(filepath=str(secret))

    assert result["success"] is False
    assert result["reason"] == "outside_workspace_roots"


def test_file_search_covers_registered_workspace_root(office_dir, ws_root):
    """默认搜索范围必须覆盖工作区授权根，否则"搜我 E 盘的文件"同样会落空。"""
    (ws_root / "target_note.md").write_text("x", encoding="utf-8")

    result = office_tools.tool_file_search(keyword="target_note")

    assert result["success"] is True
    assert any(item["name"] == "target_note.md" for item in result["files"])


def test_file_search_rejects_explicit_dir_outside_roots(office_dir, ws_root):
    """显式目录同样过白名单，不能成为绕开授权的后门。"""
    outside = ws_root.parent / "elsewhere_search"
    outside.mkdir()

    result = office_tools.tool_file_search(keyword="x", directory=str(outside))

    assert result["success"] is False
    assert result["reason"] == "outside_workspace_roots"


def test_read_write_share_one_authorization_source(office_dir, ws_root, no_controller):
    """同一目录：读放行则写也放行，两者不得再各持一份名单。"""
    note = ws_root / "note.txt"
    note.write_text("hello", encoding="utf-8")
    target = ws_root / "shared" / "out.txt"

    assert office_tools.tool_document_read(filepath=str(note))["success"] is True
    assert office_tools.guard_write_paths(destination=str(target)) is None

"""受控 QQ 运行时（core.napcat_installer）与 launcher 的 QQ 来源解析。

背景：NapCat 的 ``napimain.exe`` 需要外部 QQ.exe 作注入宿主，旧实现从注册表取
系统 QQ —— 用户机器上是 QQ **Beta 通道**且自动升级，注入后触发账号风控、频繁
要求重新登录。本组测试钉住新的来源优先级（配置 → 受控目录 → 注册表兜底）与
"缺 NapCat 本体" / "缺 QQ 宿主" 两种错误的区分。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import napcat_installer as installer_module
from core import napcat_launcher as launcher_module
from core.napcat_installer import NapcatInstaller
from core.napcat_launcher import NapcatLauncher


def _make_qq_runtime(root: Path) -> Path:
    """造一个受控运行时目录，QQ.exe 放在版本子目录里（贴近真实安装产物）。"""
    qq_dir = root / "QQ" / "versions" / "9.9.26-44498"
    qq_dir.mkdir(parents=True, exist_ok=True)
    qq_exe = qq_dir / "QQ.exe"
    qq_exe.write_bytes(b"MZ")
    return qq_exe


def _make_napcat_dir(root: Path) -> Path:
    """造一个含 Framework v4.18 三件套的 NapCat 目录。"""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("napimain.exe", "napiloader.dll", "nativeLoader.cjs"):
        (root / name).write_bytes(b"x")
    return root


# ── 受控目录解析 ─────────────────────────────────────────────
def test_runtime_root_env_overrides_settings(monkeypatch, tmp_path):
    """与 _resolve_napcat_dir 同约定：环境变量 > settings > data 默认。"""
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "from_env"))
    settings = {"napcat": {"runtime_dir": str(tmp_path / "from_cfg")}}
    assert installer_module.runtime_root(settings) == tmp_path / "from_env"

    monkeypatch.delenv("AERIE_NAPCAT_RUNTIME_DIR")
    assert installer_module.runtime_root(settings) == tmp_path / "from_cfg"


def test_resolve_qq_exe_finds_nested_install(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path))
    assert installer_module.resolve_qq_exe({}) is None
    expected = _make_qq_runtime(tmp_path)
    assert installer_module.resolve_qq_exe({}) == expected


def test_installer_status_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path))
    status = NapcatInstaller({}).status()
    assert status["state"] == "idle"
    assert status["installed"] is False
    assert status["runtime_dir"] == str(tmp_path)
    assert isinstance(status["installer_embedded"], bool)


def test_bundled_installer_is_committed_with_repo():
    """内置引导器必须随仓库落地（打包后由 extraResources 一并拷贝）。"""
    path = installer_module.bundled_installer_path()
    assert path is not None and path.exists()
    boot = installer_module.bundled_boot_exe()
    assert boot is not None and boot.exists()
    assert installer_module.QQ_INSTALLER_URL.startswith("https://dldir1.qq.com/")


# ── launcher：QQ 来源优先级 ───────────────────────────────────
def test_resolve_qq_exe_prefers_explicit_config(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "runtime"))
    explicit = tmp_path / "custom" / "QQ.exe"
    explicit.parent.mkdir(parents=True, exist_ok=True)
    explicit.write_bytes(b"MZ")
    monkeypatch.setattr(launcher_module, "_find_registry_qq_exe", lambda: None)

    path, source = launcher_module.resolve_qq_exe({"napcat": {"qq_exe": str(explicit)}})

    assert (path, source) == (explicit, "config")


def test_resolve_qq_exe_prefers_controlled_over_registry(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(runtime))
    controlled = _make_qq_runtime(runtime)
    registry_qq = tmp_path / "system" / "QQ.exe"
    registry_qq.parent.mkdir(parents=True, exist_ok=True)
    registry_qq.write_bytes(b"MZ")
    monkeypatch.setattr(launcher_module, "_find_registry_qq_exe", lambda: registry_qq)

    path, source = launcher_module.resolve_qq_exe({})

    assert (path, source) == (controlled, "controlled")


def test_resolve_qq_exe_falls_back_to_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "runtime"))
    registry_qq = tmp_path / "system" / "QQ.exe"
    registry_qq.parent.mkdir(parents=True, exist_ok=True)
    registry_qq.write_bytes(b"MZ")
    monkeypatch.setattr(launcher_module, "_find_registry_qq_exe", lambda: registry_qq)

    path, source = launcher_module.resolve_qq_exe({})

    assert (path, source) == (registry_qq, "system_registry")


def test_resolve_qq_exe_reports_empty_when_nothing_available(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(launcher_module, "_find_registry_qq_exe", lambda: None)

    assert launcher_module.resolve_qq_exe({}) == (None, "")


def test_launch_command_carries_resolved_qq(monkeypatch, tmp_path):
    napcat_dir = _make_napcat_dir(tmp_path / "shell")
    qq_exe = tmp_path / "runtime" / "QQ" / "QQ.exe"
    qq_exe.parent.mkdir(parents=True, exist_ok=True)
    qq_exe.write_bytes(b"MZ")

    command = launcher_module._build_launch_command(napcat_dir, qq_exe)

    assert command is not None
    assert command[1] == str(qq_exe)
    assert launcher_module._build_launch_command(napcat_dir, None) is None


# ── launcher：错误码区分 + 状态可观测 ─────────────────────────
def test_setup_error_code_distinguishes_missing_qq_from_missing_shell(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(launcher_module, "_find_registry_qq_exe", lambda: None)
    launcher = NapcatLauncher()
    launcher.napcat_dir = tmp_path / "absent"
    assert launcher._setup_error_code() == "launcher_not_found"

    launcher.napcat_dir = _make_napcat_dir(tmp_path / "shell")
    launcher._qq_exe = None
    assert launcher._setup_error_code() == "qq_not_found"


@pytest.mark.asyncio
async def test_start_reports_qq_not_found_without_installing(monkeypatch, tmp_path):
    """缺 QQ 宿主时给出可操作的错误码，而不是笼统的 launcher_not_found。"""
    monkeypatch.setattr(launcher_module, "_port_is_open", lambda **_kwargs: False)
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(launcher_module, "_find_registry_qq_exe", lambda: None)
    # start() 开头会 _refresh_paths() 重新解析目录，因此把解析结果固定到含三件套的目录，
    # 否则测试会隐式依赖运行环境里 data_dir() 指向哪（有无下载标记）。
    shell = _make_napcat_dir(tmp_path / "shell")
    monkeypatch.setattr(launcher_module, "_resolve_napcat_dir", lambda _settings: shell)
    launcher = NapcatLauncher()

    result = await launcher.start()

    assert result["ok"] is False
    assert result["error_code"] == "qq_not_found"
    assert "Agent_reply" not in result["message"]


def test_status_exposes_qq_source(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher_module, "_port_is_open", lambda **_kwargs: False)
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(launcher_module, "_find_registry_qq_exe", lambda: None)
    launcher = NapcatLauncher()
    launcher.qrcode_path = tmp_path / "absent.png"

    status = launcher.get_status()

    assert status["qq_source"] == ""
    assert status["qq_ready"] is False

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
    """造一个含 Framework v4.18 三件套的 NapCat 目录（有头形态）。"""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("napimain.exe", "napiloader.dll", "nativeLoader.cjs"):
        (root / name).write_bytes(b"x")
    return root


def _make_headless_dir(root: Path) -> Path:
    """造一个含无头素材的 NapCat 目录（NapCat.Shell 形态）。

    注意不预置 ``loadNapCat.js``：它是运行时生成物，不应作为素材判据。
    """
    root.mkdir(parents=True, exist_ok=True)
    for name in ("NapCatWinBootMain.exe", "NapCatWinBootHook.dll", "napcat.mjs", "qqnt.json"):
        (root / name).write_bytes(b"x")
    return root


# ── 无头 / 有头形态识别 ───────────────────────────────────────
def test_boot_mode_detects_headless_and_framework(tmp_path):
    assert launcher_module.boot_mode_of(_make_headless_dir(tmp_path / "hl")) == "headless"
    assert launcher_module.boot_mode_of(_make_napcat_dir(tmp_path / "fw")) == "framework"
    assert launcher_module.boot_mode_of(tmp_path / "absent") == ""


def test_repo_bundled_shell_is_headless():
    """仓库自带的 NapCat.Shell 必须是完整的无头部署（不弹 QQ 窗口的前提）。"""
    bundled = launcher_module._DEFAULT_NAPCAT_DIR
    assert launcher_module.boot_mode_of(bundled) == "headless"


def test_build_launch_command_prefers_headless(monkeypatch, tmp_path):
    """同一目录同时具备两套素材时，必须选无头（用户要求不弹 QQ 窗口）。"""
    napcat_dir = _make_headless_dir(tmp_path / "both")
    for name in ("napimain.exe", "napiloader.dll", "nativeLoader.cjs"):
        (napcat_dir / name).write_bytes(b"x")
    qq_exe = tmp_path / "QQ.exe"
    qq_exe.write_bytes(b"MZ")

    command = launcher_module._build_launch_command(napcat_dir, qq_exe)

    assert command is not None
    assert command[0].endswith("NapCatWinBootMain.exe")
    assert command[1] == str(qq_exe)
    assert command[2].endswith("NapCatWinBootHook.dll")


def test_build_launch_command_none_without_qq(monkeypatch, tmp_path):
    """无头形态同样需要 QQ 宿主；缺 QQ 时不得返回命令。"""
    napcat_dir = _make_headless_dir(tmp_path / "hl")
    assert launcher_module._build_launch_command(napcat_dir, None) is None


def test_headless_env_carries_napcat_paths(tmp_path):
    napcat_dir = _make_headless_dir(tmp_path / "hl")
    env = launcher_module._napcat_env(napcat_dir)

    assert env["NAPCAT_INJECT_PATH"].endswith("NapCatWinBootHook.dll")
    assert env["NAPCAT_MAIN_PATH"].endswith("napcat.mjs")
    assert env["NAPCAT_PATCH_PACKAGE"].endswith("qqnt.json")
    assert env["NAPCAT_LOAD_PATH"].endswith("loadNapCat.js")


def test_prepare_headless_loader_points_at_payload(tmp_path):
    napcat_dir = _make_headless_dir(tmp_path / "hl")
    launcher_module._prepare_headless_loader(napcat_dir)

    text = (napcat_dir / "loadNapCat.js").read_text(encoding="utf-8")

    assert "import(" in text
    assert "napcat.mjs" in text
    # 与 launcher-user.bat 一致：必须是 file:/// + 正斜杠，Windows 反斜杠会 import 失败
    assert "file:///" in text
    assert "\\" not in text


def test_resolve_napcat_dir_prefers_headless_over_download_marker(monkeypatch, tmp_path):
    """下载标记指向有头部署时，仍应优先自带的无头部署（否则 QQ 窗口会冒出来）。"""
    framework = _make_napcat_dir(tmp_path / "fw")
    monkeypatch.setattr(launcher_module, "_read_download_marker", lambda: framework)

    resolved = launcher_module._resolve_napcat_dir({})

    assert launcher_module.boot_mode_of(resolved) == "headless"


def test_resolve_napcat_dir_respects_explicit_config(monkeypatch, tmp_path):
    """显式指定目录一律尊重，不被无头偏好覆盖。"""
    framework = _make_napcat_dir(tmp_path / "explicit")

    resolved = launcher_module._resolve_napcat_dir({"napcat": {"dir": str(framework)}})

    assert resolved == framework


def test_headless_can_be_disabled_by_config(monkeypatch, tmp_path):
    framework = _make_napcat_dir(tmp_path / "fw")
    monkeypatch.setattr(launcher_module, "_read_download_marker", lambda: framework)

    resolved = launcher_module._resolve_napcat_dir({"napcat": {"headless": False}})

    assert resolved == framework


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
    assert status["installer_drop_dir"] == str(tmp_path / "installer")
    assert status["local_installer"] == ""


def test_bundled_installer_is_committed_with_repo():
    """内置引导器必须随仓库落地（打包后由 extraResources 一并拷贝）。"""
    path = installer_module.bundled_installer_path()
    assert path is not None and path.exists()
    boot = installer_module.bundled_boot_exe()
    assert boot is not None and boot.exists()
    assert installer_module.QQ_INSTALLER_URL.startswith("https://")


def test_local_installer_preferred_over_download(monkeypatch, tmp_path):
    """本地投放的安装包优先于远程下载（腾讯 CDN 直连实测 403）。"""
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path))
    assert installer_module.find_local_installer({}) is None

    drop = installer_module.installer_drop_dir({})
    drop.mkdir(parents=True, exist_ok=True)
    local = drop / "QQ_9.9.36_260924_x86_01.exe"
    local.write_bytes(b"MZ")

    assert installer_module.find_local_installer({}) == local


def test_local_installer_explicit_config_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path / "runtime"))
    explicit = tmp_path / "elsewhere" / "QQ_setup.exe"
    explicit.parent.mkdir(parents=True, exist_ok=True)
    explicit.write_bytes(b"MZ")

    found = installer_module.find_local_installer({"napcat": {"qq_installer": str(explicit)}})

    assert found == explicit


def test_install_reports_local_installer_progress(monkeypatch, tmp_path):
    """走本地安装包时不应尝试联网下载。"""
    monkeypatch.setenv("AERIE_NAPCAT_RUNTIME_DIR", str(tmp_path))
    drop = installer_module.installer_drop_dir({})
    drop.mkdir(parents=True, exist_ok=True)
    (drop / "QQ_setup.exe").write_bytes(b"MZ")

    def _no_download(*_args, **_kwargs):
        raise AssertionError("local installer present; must not download")

    monkeypatch.setattr(NapcatInstaller, "_download", _no_download)
    monkeypatch.setattr(NapcatInstaller, "_silent_install", lambda self, p: False)
    monkeypatch.setattr(NapcatInstaller, "_seven_zip_extract", lambda self, p, t: None)

    result = NapcatInstaller({}).install_qq_runtime()

    # 安装器不可用时如实报错，但绝没有走下载分支
    assert result["ok"] is False
    assert result["error_code"] == "qq_exe_not_found"


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


# ── 回归：tasklist stdout 为 None 不得打断启动 ────────────────
def test_list_qq_pids_tolerates_none_stdout(monkeypatch):
    """Electron 以 stdio=["ignore","pipe","pipe"] 启动后端时，tasklist 的
    stdout 可能是 None。旧实现直接 .splitlines() 抛 AttributeError，导致
    NapCat 永远起不来（实测：napcat_start_failed + NapCat start error）。
    """
    from types import SimpleNamespace

    monkeypatch.setattr(launcher_module.sys, "platform", "win32")
    monkeypatch.setattr(
        launcher_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=None, stderr=None),
    )

    assert launcher_module._list_qq_pids() == set()


def test_list_qq_pids_parses_normal_output(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(launcher_module.sys, "platform", "win32")
    csv = '"QQ.exe","4242","Console","1","100,000 K"\n'
    monkeypatch.setattr(
        launcher_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=csv, stderr=""),
    )

    assert launcher_module._list_qq_pids() == {4242}


def test_list_qq_pids_passes_devnull_stdin(monkeypatch):
    """必须显式接 DEVNULL stdin，否则父进程 stdin 无效会污染子进程。"""
    seen: dict = {}

    def _capture(*_args, **kwargs):
        seen.update(kwargs)
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()

    monkeypatch.setattr(launcher_module.sys, "platform", "win32")
    monkeypatch.setattr(launcher_module.subprocess, "run", _capture)

    launcher_module._list_qq_pids()

    assert seen.get("stdin") == launcher_module.subprocess.DEVNULL

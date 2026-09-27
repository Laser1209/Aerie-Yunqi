from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import napcat_launcher as launcher_module
from core.napcat_launcher import NapcatLauncher


def test_status_ignores_stale_qrcode_file_without_live_webui(monkeypatch):
    # A qrcode.png left on disk from a previous run must never be offered as a
    # scannable code: without a live WebUI session the file is always stale.
    monkeypatch.setattr(launcher_module, "_port_is_open", lambda **_kwargs: False)
    launcher = NapcatLauncher()
    launcher.qrcode_path = SimpleNamespace(exists=lambda: True)

    status = launcher.get_status()

    assert status["phase"] == "idle"
    assert status["qrcode_available"] is False
    assert "qrcode_path" not in status


@pytest.mark.asyncio
async def test_stop_terminates_owned_process_tree_and_clears_ownership(monkeypatch):
    port_states = iter([True, False])
    monkeypatch.setattr(
        launcher_module,
        "_port_is_open",
        lambda **_kwargs: next(port_states, False),
    )
    terminate_tree = Mock()
    monkeypatch.setattr(launcher_module, "_terminate_process_tree", terminate_tree)
    launcher = NapcatLauncher()
    proc = SimpleNamespace(pid=1234, poll=lambda: None)
    launcher._proc = proc
    launcher._owns_process = True

    result = await launcher.stop()

    terminate_tree.assert_called_once_with(proc)
    assert result["ok"] is True
    assert launcher._proc is None
    assert launcher._owns_process is False


@pytest.mark.asyncio
async def test_stop_does_not_kill_unowned_existing_napcat(monkeypatch):
    monkeypatch.setattr(launcher_module, "_port_is_open", lambda **_kwargs: True)
    terminate_tree = Mock(side_effect=AssertionError("unowned process killed"))
    monkeypatch.setattr(launcher_module, "_terminate_process_tree", terminate_tree)
    launcher = NapcatLauncher()

    assert launcher.get_status()["phase"] == "connected"
    result = await launcher.stop()

    assert result == {
        "ok": True,
        "message": "NapCat was already running outside Aerie",
        "owned": False,
    }
    terminate_tree.assert_not_called()


@pytest.mark.asyncio
async def test_missing_launcher_error_does_not_leak_absolute_path(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher_module, "_port_is_open", lambda **_kwargs: False)
    # 目录解析指向一个没有 launcher-user.bat 的临时目录，模拟未安装 NapCat
    monkeypatch.setattr(
        launcher_module,
        "_resolve_napcat_dir",
        lambda _settings: tmp_path,
    )
    launcher = NapcatLauncher()

    result = await launcher.start()

    assert result["ok"] is False
    assert result["error_code"] == "launcher_not_found"
    assert "Agent_reply" not in result["message"]

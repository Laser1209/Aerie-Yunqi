from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import napcat_launcher as launcher_module
from core.napcat_launcher import NapcatLauncher


def test_status_does_not_expose_local_qrcode_path(monkeypatch):
    monkeypatch.setattr(launcher_module, "_port_is_open", lambda **_kwargs: False)
    monkeypatch.setattr(
        launcher_module,
        "_QRCODE_PATH",
        SimpleNamespace(exists=lambda: True),
    )
    launcher = NapcatLauncher()

    status = launcher.get_status()

    assert status["qrcode_available"] is True
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
async def test_missing_launcher_error_does_not_leak_absolute_path(monkeypatch):
    monkeypatch.setattr(launcher_module, "_port_is_open", lambda **_kwargs: False)
    monkeypatch.setattr(
        launcher_module,
        "_LAUNCHER_BAT",
        SimpleNamespace(exists=lambda: False),
    )
    launcher = NapcatLauncher()

    result = await launcher.start()

    assert result["ok"] is False
    assert result["error_code"] == "launcher_not_found"
    assert "Agent_reply" not in result["message"]

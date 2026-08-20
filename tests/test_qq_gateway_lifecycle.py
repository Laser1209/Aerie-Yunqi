from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import qq_gateway as gateway_module
from core.qq_gateway import QQEngineGateway


def test_status_does_not_expose_local_qrcode_path(monkeypatch):
    monkeypatch.setattr(gateway_module, "_port_is_open", lambda **_kwargs: False)
    gateway = QQEngineGateway()
    gateway.qrcode_path = SimpleNamespace(exists=lambda: True)

    status = gateway.get_status()

    assert status["qrcode_available"] is True
    assert "qrcode_path" not in status


def test_api_server_does_not_expose_engine_download_routes():
    source = gateway_module._PROJECT_ROOT.joinpath("core", "api_server.py").read_text(encoding="utf-8")

    assert "/api/qq/gateway/download" not in source
    assert "/api/qq/gateway/download/status" not in source
    assert "/api/qq/gateway/update/check" not in source
    assert "core.qq_gateway_downloader" not in source


@pytest.mark.asyncio
async def test_stop_terminates_owned_process_tree_and_clears_ownership(monkeypatch):
    port_states = iter([True, False])
    monkeypatch.setattr(
        gateway_module,
        "_port_is_open",
        lambda **_kwargs: next(port_states, False),
    )
    terminate_tree = Mock()
    monkeypatch.setattr(gateway_module, "_terminate_process_tree", terminate_tree)
    gateway = QQEngineGateway()
    proc = SimpleNamespace(pid=1234, poll=lambda: None)
    gateway._proc = proc
    gateway._owns_process = True

    result = await gateway.stop()

    terminate_tree.assert_called_once_with(proc)
    assert result["ok"] is True
    assert gateway._proc is None
    assert gateway._owns_process is False


@pytest.mark.asyncio
async def test_stop_does_not_kill_unowned_existing_engine(monkeypatch):
    monkeypatch.setattr(gateway_module, "_port_is_open", lambda **_kwargs: True)
    terminate_tree = Mock(side_effect=AssertionError("unowned process killed"))
    monkeypatch.setattr(gateway_module, "_terminate_process_tree", terminate_tree)
    gateway = QQEngineGateway()

    assert gateway.get_status()["phase"] == "connected"
    result = await gateway.stop()

    assert result == {
        "ok": True,
        "message": "QQ engine was already running outside Aerie",
        "owned": False,
    }
    terminate_tree.assert_not_called()


@pytest.mark.asyncio
async def test_missing_launcher_error_does_not_leak_absolute_path(monkeypatch, tmp_path):
    monkeypatch.setattr(gateway_module, "_port_is_open", lambda **_kwargs: False)
    # 目录解析指向一个没有 launcher-user.bat 的临时目录，模拟未安装引擎
    monkeypatch.setattr(
        gateway_module,
        "_resolve_engine_dir",
        lambda _settings: tmp_path,
    )
    gateway = QQEngineGateway()

    result = await gateway.start()

    assert result["ok"] is False
    assert result["error_code"] == "launcher_not_found"
    assert "Agent_reply" not in result["message"]

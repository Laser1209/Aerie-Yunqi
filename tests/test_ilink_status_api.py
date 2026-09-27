from unittest.mock import AsyncMock, Mock

import pytest

from core import api_server


@pytest.mark.asyncio
async def test_ilink_status_is_mock_safe_without_running_companion(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: None)

    result = await api_server.ilink_status()

    assert result == {
        "phase": "disabled",
        "configured": False,
        "connected": False,
        "error_code": "backend_not_ready",
    }


@pytest.mark.asyncio
async def test_ilink_status_returns_gateway_public_state(monkeypatch):
    gateway = Mock()
    gateway.get_status.return_value = {
        "phase": "connected",
        "configured": True,
        "connected": True,
    }
    companion = Mock(ilink_gateway=gateway, ilink_auth_flow=None)
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    result = await api_server.ilink_status()

    assert result["phase"] == "connected"
    assert result["connected"] is True


@pytest.mark.asyncio
async def test_ilink_start_and_stop_delegate_to_gateway(monkeypatch):
    gateway = Mock()
    gateway.start = AsyncMock()
    gateway.stop = AsyncMock()
    gateway.get_status.return_value = {
        "phase": "connected",
        "configured": True,
        "connected": True,
    }
    companion = Mock(ilink_gateway=gateway)
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    started = await api_server.ilink_start()
    stopped = await api_server.ilink_stop()

    gateway.start.assert_awaited_once()
    gateway.stop.assert_awaited_once()
    assert started["phase"] == "connected"
    assert stopped["phase"] == "connected"


@pytest.mark.asyncio
async def test_ilink_pairing_code_returns_404_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: Mock(ilink_gateway=Mock()))
    monkeypatch.setattr(api_server, "_ilink_pairing_enabled", lambda: False)

    response = await api_server.ilink_pairing_code()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ilink_pairing_code_returns_503_without_backend(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: None)
    monkeypatch.setattr(api_server, "_ilink_pairing_enabled", lambda: True)

    response = await api_server.ilink_pairing_code()

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ilink_pairing_code_delegates_to_gateway(monkeypatch):
    gateway = Mock()
    gateway.create_pairing_code.return_value = {
        "code": "12345678",
        "bot_id": "bot-1",
        "expires_at": "2026-09-27T00:00:00+00:00",
    }
    monkeypatch.setattr(api_server, "get_companion", lambda: Mock(ilink_gateway=gateway))
    monkeypatch.setattr(api_server, "_ilink_pairing_enabled", lambda: True)

    result = await api_server.ilink_pairing_code()

    assert result["code"] == "12345678"
    gateway.create_pairing_code.assert_called_once()


@pytest.mark.asyncio
async def test_ilink_pairing_code_returns_409_on_missing_credentials(monkeypatch):
    gateway = Mock()
    gateway.create_pairing_code.side_effect = RuntimeError("iLink credentials are required")
    monkeypatch.setattr(api_server, "get_companion", lambda: Mock(ilink_gateway=gateway))
    monkeypatch.setattr(api_server, "_ilink_pairing_enabled", lambda: True)

    response = await api_server.ilink_pairing_code()

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_ilink_status_drops_pairing_block_when_flag_disabled(monkeypatch):
    gateway = Mock()
    gateway.get_status.return_value = {
        "phase": "connected",
        "configured": True,
        "connected": True,
        "pairing": {"required": True, "bound": False, "expires_at": None, "attempts": 0},
    }
    companion = Mock(ilink_gateway=gateway, ilink_auth_flow=None)
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    monkeypatch.setattr(api_server, "_ilink_pairing_enabled", lambda: False)

    result = await api_server.ilink_status()

    assert "pairing" not in result

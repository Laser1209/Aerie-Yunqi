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
    companion = Mock(ilink_gateway=gateway)
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

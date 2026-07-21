"""Phase 1 contract tests for the isolated Android mobile gateway."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from core.mobile_gateway import (
    MobileGatewayConfig,
    get_mobile_gateway_config,
    is_mobile_gateway_enabled,
    mobile_app,
    start_mobile_gateway,
)


client = TestClient(mobile_app)


def test_mobile_gateway_exposes_only_the_public_health_route():
    paths = {route.path for route in mobile_app.routes}

    assert paths == {"/api/mobile/v1/health"}
    assert mobile_app.docs_url is None
    assert mobile_app.redoc_url is None
    assert mobile_app.openapi_url is None
    assert not any(
        middleware.cls is CORSMiddleware
        for middleware in mobile_app.user_middleware
    )


def test_mobile_gateway_health_is_minimal_and_public():
    response = client.get("/api/mobile/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "apiVersion": "v1"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/system/restart",
        "/api/brain/shell",
        "/api/env/providers",
        "/api/config/yaml",
        "/api/computer_control/level",
        "/api/chat/send",
        "/docs",
        "/openapi.json",
    ],
)
def test_mobile_gateway_does_not_expose_management_routes(path: str):
    response = client.get(path)

    assert response.status_code == 404


def test_mobile_gateway_uses_loopback_and_the_reserved_port_by_default(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("AERIE_MOBILE_GATEWAY_HOST", raising=False)
    monkeypatch.delenv("AERIE_MOBILE_GATEWAY_PORT", raising=False)

    config = get_mobile_gateway_config()

    assert config.host == "127.0.0.1"
    assert config.port == 7891


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::"])
def test_mobile_gateway_rejects_non_loopback_bind_addresses(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
):
    monkeypatch.setenv("AERIE_MOBILE_GATEWAY_HOST", host)

    with pytest.raises(ValueError, match="127.0.0.1"):
        get_mobile_gateway_config()


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_mobile_gateway_rejects_invalid_ports(
    monkeypatch: pytest.MonkeyPatch,
    port: str,
):
    monkeypatch.setenv("AERIE_MOBILE_GATEWAY_PORT", port)

    with pytest.raises(ValueError, match="port"):
        get_mobile_gateway_config()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("false", False)],
)
def test_mobile_gateway_explicit_environment_flag_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,
):
    monkeypatch.setenv("AERIE_MOBILE_GATEWAY_ENABLED", value)

    assert is_mobile_gateway_enabled() is expected


def test_mobile_gateway_feature_flag_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("AERIE_MOBILE_GATEWAY_ENABLED", raising=False)
    monkeypatch.delenv("AERIE_FEATURE_MOBILE_GATEWAY_V1", raising=False)

    assert is_mobile_gateway_enabled() is False


def test_mobile_gateway_rejects_invalid_environment_flag(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AERIE_MOBILE_GATEWAY_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="boolean"):
        is_mobile_gateway_enabled()


@pytest.mark.asyncio
async def test_mobile_gateway_starts_on_loopback_and_shuts_down_cleanly():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    runner = await start_mobile_gateway(MobileGatewayConfig("127.0.0.1", port))
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"http://127.0.0.1:{port}/api/mobile/v1/health"
            )
        assert response.status_code == 200
        assert response.json()["apiVersion"] == "v1"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_main_starts_mobile_gateway_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    import core.mobile_gateway as mobile_gateway
    import main

    logger = Mock()
    expected_runner = SimpleNamespace()
    starter = AsyncMock(return_value=expected_runner)
    monkeypatch.setattr(mobile_gateway, "is_mobile_gateway_enabled", lambda: True)
    monkeypatch.setattr(mobile_gateway, "start_mobile_gateway", starter)

    result = await main._start_optional_mobile_gateway(logger)

    assert result is expected_runner
    starter.assert_awaited_once_with()
    logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_main_keeps_desktop_backend_available_when_mobile_start_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    import core.mobile_gateway as mobile_gateway
    import main

    logger = Mock()
    monkeypatch.setattr(mobile_gateway, "is_mobile_gateway_enabled", lambda: True)
    monkeypatch.setattr(
        mobile_gateway,
        "start_mobile_gateway",
        AsyncMock(side_effect=RuntimeError("port is occupied")),
    )

    result = await main._start_optional_mobile_gateway(logger)

    assert result is None
    logger.exception.assert_called_once()

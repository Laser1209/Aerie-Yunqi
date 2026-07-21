"""Isolated HTTP boundary for the future Android companion app.

This module deliberately owns a separate FastAPI application.  It must never
mount or proxy the broad local management API from :mod:`core.api_server`.
Phase 1 exposes only a public, non-sensitive health response; authenticated
mobile capabilities are added in later phases.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.feature_flags import FeatureFlags


logger = logging.getLogger(__name__)

MOBILE_GATEWAY_HOST = "127.0.0.1"
MOBILE_GATEWAY_PORT = 7891
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class MobileGatewayConfig:
    """Network configuration for the intentionally local-only gateway."""

    host: str
    port: int


def _read_enabled_override() -> bool | None:
    raw_value = os.getenv("AERIE_MOBILE_GATEWAY_ENABLED")
    if raw_value is None:
        return None
    normalized = raw_value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError("AERIE_MOBILE_GATEWAY_ENABLED must be a boolean value")


def is_mobile_gateway_enabled() -> bool:
    """Return the startup flag, with an explicit environment override."""

    override = _read_enabled_override()
    if override is not None:
        return override
    return FeatureFlags().is_enabled("mobile_gateway_v1")


def get_mobile_gateway_config() -> MobileGatewayConfig:
    """Read and validate the local-only bind address and reserved port."""

    host = os.getenv("AERIE_MOBILE_GATEWAY_HOST", MOBILE_GATEWAY_HOST).strip()
    if host != MOBILE_GATEWAY_HOST:
        raise ValueError(
            "mobile gateway must bind to 127.0.0.1; use Cloudflare Tunnel "
            "instead of exposing it directly"
        )

    raw_port = os.getenv("AERIE_MOBILE_GATEWAY_PORT", str(MOBILE_GATEWAY_PORT))
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("mobile gateway port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("mobile gateway port must be between 1 and 65535")

    return MobileGatewayConfig(host=host, port=port)


mobile_app = FastAPI(
    title="Aerie Mobile Gateway",
    version="v1",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@mobile_app.get("/api/mobile/v1/health", include_in_schema=False)
async def mobile_health() -> JSONResponse:
    """Return a deliberately minimal public response for connection checks."""

    return JSONResponse(
        {"status": "ok", "apiVersion": "v1"},
        headers={"Cache-Control": "no-store"},
    )


class MobileGatewayRunner:
    """Owns the uvicorn task so the main process can shut it down cleanly."""

    def __init__(self, server: uvicorn.Server, task: asyncio.Task[Any]) -> None:
        self._server = server
        self._task = task

    async def cleanup(self) -> None:
        self._server.should_exit = True
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


async def start_mobile_gateway(
    config: MobileGatewayConfig | None = None,
) -> MobileGatewayRunner:
    """Start the isolated gateway and fail explicitly if it does not bind."""

    bind_config = config or get_mobile_gateway_config()
    uvicorn_config = uvicorn.Config(
        mobile_app,
        host=bind_config.host,
        port=bind_config.port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)
    task = asyncio.create_task(
        server.serve(),
        name="aerie-mobile-gateway",
    )
    runner = MobileGatewayRunner(server, task)

    for _ in range(20):
        await asyncio.sleep(0.05)
        if server.started:
            logger.info(
                "mobile gateway listening at http://%s:%d",
                bind_config.host,
                bind_config.port,
            )
            return runner
        if task.done():
            try:
                task.result()
            except BaseException as exc:
                raise RuntimeError("mobile gateway failed to start") from exc
            raise RuntimeError("mobile gateway stopped before it started")

    await runner.cleanup()
    raise RuntimeError("mobile gateway did not bind within one second")

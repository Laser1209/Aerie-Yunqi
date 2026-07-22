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
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from core.feature_flags import FeatureFlags
from core.mobile_chat import MobileChatError, MobileChatService
from core.mobile_identity import (
    MobileAuthError,
    MobileIdentityStore,
    MobilePrincipal,
    TokenPair,
)


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


class _MobileModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class LoginRequest(_MobileModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=12, max_length=1024)
    device_name: str = Field(alias="deviceName", min_length=1, max_length=100)
    pairing_code: str = Field(alias="pairingCode", pattern=r"^\d{8}$")
    public_key: str | None = Field(default=None, alias="publicKey", max_length=8192)


class RefreshRequest(_MobileModel):
    refresh_token: str = Field(alias="refreshToken", min_length=20, max_length=512)


class SubmitRequest(_MobileModel):
    client_request_id: str = Field(alias="clientRequestId", min_length=36, max_length=36)
    text: str = Field(default="", max_length=20_002)
    file_ids: list[str] = Field(default_factory=list, alias="fileIds", max_length=20)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", f"req_{secrets.token_hex(12)}")


def _error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "requestId": _request_id(request),
            }
        },
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _token_response(tokens: TokenPair) -> dict[str, Any]:
    return {
        "accessToken": tokens.access_token,
        "refreshToken": tokens.refresh_token,
        "accessExpiresIn": tokens.access_expires_in,
        "refreshExpiresIn": tokens.refresh_expires_in,
        "account": {
            "accountId": tokens.principal.account_id,
            "username": tokens.principal.username,
            "role": tokens.principal.role,
            "actorId": tokens.principal.actor_id,
            "userId": str(tokens.principal.user_id),
            "deviceId": tokens.principal.device_id,
        },
    }


def _default_identity_store() -> MobileIdentityStore:
    pepper = os.getenv("AERIE_MOBILE_TOKEN_PEPPER", "")
    if not pepper:
        raise MobileAuthError("service_unavailable", status_code=503)
    path = Path(os.getenv("AERIE_MOBILE_AUTH_DB", "data/mobile_gateway.db"))
    return MobileIdentityStore(path, pepper=pepper)


def _default_chat_service(identity_store: MobileIdentityStore) -> MobileChatService:
    flags = FeatureFlags()
    required = (
        "migration_framework_v1",
        "conversation_model_v1",
        "chat_request_queue_v1",
    )
    if not all(flags.is_enabled(name) for name in required):
        raise MobileChatError("chat_unavailable", status_code=503)
    from core.database import Database

    return MobileChatService(Database(), identity_store)


def create_mobile_app(
    *,
    identity_store: MobileIdentityStore | None = None,
    chat_service: MobileChatService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Aerie Mobile Gateway",
        version="v1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    if identity_store is not None:
        app.state.identity_store = identity_store
    if chat_service is not None:
        app.state.chat_service = chat_service

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: Any) -> Response:
        request.state.request_id = f"req_{secrets.token_hex(12)}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(MobileAuthError)
    async def mobile_auth_error(
        request: Request,
        exc: MobileAuthError,
    ) -> JSONResponse:
        messages = {
            "invalid_credentials": "用户名、密码或配对码无效",
            "invalid_token": "会话无效或已过期",
            "rate_limited": "尝试次数过多，请稍后再试",
            "forbidden": "没有执行此操作的权限",
            "not_found": "请求的资源不存在",
            "service_unavailable": "移动认证服务尚未配置",
        }
        return _error_response(
            request,
            code=exc.code,
            message=messages.get(exc.code, "请求失败"),
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            code="invalid_request",
            message="请求格式无效",
            status_code=422,
        )

    @app.exception_handler(MobileChatError)
    async def mobile_chat_error(
        request: Request,
        exc: MobileChatError,
    ) -> JSONResponse:
        messages = {
            "chat_unavailable": "持久聊天服务尚未启用",
            "not_found": "请求的资源不存在",
            "invalid_cursor": "分页或事件游标无效",
            "invalid_limit": "分页数量无效",
            "invalid_client_request_id": "clientRequestId 必须是 UUID",
            "text_too_long": "文本超过 20000 字符",
            "empty_request": "文本和文件不能同时为空",
            "files_not_available": "文件功能尚未启用",
            "request_not_retryable": "当前请求不能重试",
        }
        return _error_response(
            request,
            code=exc.code,
            message=messages.get(exc.code, "请求失败"),
            status_code=exc.status_code,
        )

    def store(request: Request) -> MobileIdentityStore:
        existing = getattr(request.app.state, "identity_store", None)
        if existing is None:
            existing = _default_identity_store()
            request.app.state.identity_store = existing
        return existing

    def principal(
        request: Request,
        authorization: str | None = Header(default=None),
        identity: MobileIdentityStore = Depends(store),
    ) -> MobilePrincipal:
        if not authorization or not authorization.startswith("Bearer "):
            raise MobileAuthError("invalid_token")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise MobileAuthError("invalid_token")
        return identity.authenticate_access(token)

    def chat(
        request: Request,
        identity: MobileIdentityStore = Depends(store),
    ) -> MobileChatService:
        existing = getattr(request.app.state, "chat_service", None)
        if existing is None:
            existing = _default_chat_service(identity)
            request.app.state.chat_service = existing
        return existing

    @app.get("/api/mobile/v1/health", include_in_schema=False)
    async def mobile_health() -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "apiVersion": "v1"},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/mobile/v1/auth/login")
    async def login(
        payload: LoginRequest,
        request: Request,
        identity: MobileIdentityStore = Depends(store),
    ) -> dict[str, Any]:
        host = request.client.host if request.client else "unknown"
        tokens = identity.login(
            username=payload.username,
            password=payload.password,
            device_name=payload.device_name,
            pairing_code=payload.pairing_code,
            public_key=payload.public_key,
            ip_address=host,
        )
        return _token_response(tokens)

    @app.post("/api/mobile/v1/auth/refresh")
    async def refresh(
        payload: RefreshRequest,
        identity: MobileIdentityStore = Depends(store),
    ) -> dict[str, Any]:
        return _token_response(identity.refresh(payload.refresh_token))

    @app.post("/api/mobile/v1/auth/logout", status_code=204)
    async def logout(
        current: MobilePrincipal = Depends(principal),
        identity: MobileIdentityStore = Depends(store),
    ) -> Response:
        identity.logout(current)
        return Response(status_code=204)

    @app.get("/api/mobile/v1/me")
    async def me(current: MobilePrincipal = Depends(principal)) -> dict[str, Any]:
        return {
            "accountId": current.account_id,
            "username": current.username,
            "role": current.role,
            "actorId": current.actor_id,
            "userId": str(current.user_id),
            "deviceId": current.device_id,
            "capabilities": {
                "chat": True,
                "files": False,
                "approvals": current.role == "owner",
            },
        }

    @app.get("/api/mobile/v1/devices")
    async def devices(
        current: MobilePrincipal = Depends(principal),
        identity: MobileIdentityStore = Depends(store),
    ) -> dict[str, Any]:
        items = []
        for item in identity.list_devices(current):
            items.append(
                {
                    "deviceId": item["device_id"],
                    "accountId": item["account_id"],
                    "deviceName": item["device_name"],
                    "createdAt": item["created_at"],
                    "lastUsedAt": item["last_used_at"],
                    "revokedAt": item["revoked_at"],
                }
            )
        return {"items": items}

    @app.delete("/api/mobile/v1/devices/{device_id}", status_code=204)
    async def delete_device(
        device_id: str,
        current: MobilePrincipal = Depends(principal),
        identity: MobileIdentityStore = Depends(store),
    ) -> Response:
        identity.revoke_device(current, device_id)
        return Response(status_code=204)

    @app.get("/api/mobile/v1/messages")
    async def messages(
        before_id: str | None = None,
        after_id: str | None = None,
        limit: int = 50,
        current: MobilePrincipal = Depends(principal),
        service: MobileChatService = Depends(chat),
    ) -> dict[str, Any]:
        return service.list_messages(
            current,
            before_id=before_id,
            after_id=after_id,
            limit=limit,
        )

    @app.post("/api/mobile/v1/requests", status_code=202)
    async def submit_request(
        payload: SubmitRequest,
        current: MobilePrincipal = Depends(principal),
        service: MobileChatService = Depends(chat),
    ) -> dict[str, Any]:
        return service.submit_request(
            current,
            client_request_id=payload.client_request_id,
            text=payload.text,
            file_ids=payload.file_ids,
        )

    @app.get("/api/mobile/v1/requests/{request_id}")
    async def get_request(
        request_id: str,
        current: MobilePrincipal = Depends(principal),
        service: MobileChatService = Depends(chat),
    ) -> dict[str, Any]:
        return service.get_request(current, request_id)

    @app.post("/api/mobile/v1/requests/{request_id}/cancel")
    async def cancel_request(
        request_id: str,
        current: MobilePrincipal = Depends(principal),
        service: MobileChatService = Depends(chat),
    ) -> dict[str, Any]:
        return service.cancel_request(current, request_id)

    @app.post("/api/mobile/v1/requests/{request_id}/retry", status_code=202)
    async def retry_request(
        request_id: str,
        current: MobilePrincipal = Depends(principal),
        service: MobileChatService = Depends(chat),
    ) -> dict[str, Any]:
        return service.retry_request(current, request_id)

    @app.get("/api/mobile/v1/events")
    async def events(
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        current: MobilePrincipal = Depends(principal),
        service: MobileChatService = Depends(chat),
    ) -> StreamingResponse:
        service.list_events(current, after_event_id=last_event_id, limit=0)

        async def stream_events():
            cursor = last_event_id
            yield "event: stream.open\ndata: {}\n\n"
            heartbeat = 0
            while not await request.is_disconnected():
                batch = service.list_events(current, after_event_id=cursor)
                for event in batch:
                    cursor = event["id"]
                    payload = JSONResponse(content=event["data"]).body.decode("utf-8")
                    yield (
                        f"id: {event['id']}\n"
                        f"event: {event['type']}\n"
                        f"data: {payload}\n\n"
                    )
                heartbeat += 1
                if heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = 0
                await asyncio.sleep(1)

        return StreamingResponse(
            stream_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return app


mobile_app = create_mobile_app()


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

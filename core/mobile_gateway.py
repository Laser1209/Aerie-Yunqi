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
import socket
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from core.feature_flags import FeatureFlags
from core.mobile_approvals import (
    MobileApprovalError,
    decide_approval as mobile_approval_decide,
    list_pending_approvals as mobile_approval_list,
)
from core.mobile_chat import MobileChatError, MobileChatService
from core.mobile_files import (
    PART_SIZE,
    MobileFileError,
    MobileFileService,
    iter_download,
)
from core.mobile_identity import (
    MobileAuthError,
    MobileIdentityStore,
    MobilePrincipal,
    TokenPair,
)
from core.mobile_readonly import (
    MobileReadonlyError,
    get_brief,
    get_memory,
    get_weather,
    get_world,
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
    # Quote V2: unified quote support — the chat_log.id being replied to.
    reply_to_id: int = Field(default=0, alias="replyToId", ge=0)


class ApprovalDecisionRequest(_MobileModel):
    approved: bool
    whitelist: bool = False
    blacklist: bool = False


class CreateUploadRequest(_MobileModel):
    client_upload_id: str = Field(
        alias="clientUploadId",
        min_length=36,
        max_length=36,
    )
    file_name: str = Field(alias="fileName", min_length=1, max_length=255)
    size: int
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=255)
    directory_grant_id: str | None = Field(
        default=None,
        alias="directoryGrantId",
        max_length=128,
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", f"req_{secrets.token_hex(12)}")


def _error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = {"Cache-Control": "no-store"}
    response_headers.update(headers or {})
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "requestId": _request_id(request),
            }
        },
        status_code=status_code,
        headers=response_headers,
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


def _default_file_service(identity_store: MobileIdentityStore) -> MobileFileService:
    return MobileFileService(
        identity_store.db_path,
        storage_root=Path("data/mobile_files"),
    )


def _default_chat_service(
    identity_store: MobileIdentityStore,
    file_service: MobileFileService,
) -> MobileChatService:
    flags = FeatureFlags()
    required = (
        "migration_framework_v1",
        "conversation_model_v1",
        "chat_request_queue_v1",
    )
    if not all(flags.is_enabled(name) for name in required):
        raise MobileChatError("chat_unavailable", status_code=503)
    from core.database import Database

    return MobileChatService(
        Database(),
        identity_store,
        file_service=file_service,
    )


def create_mobile_app(
    *,
    identity_store: MobileIdentityStore | None = None,
    chat_service: MobileChatService | None = None,
    file_service: MobileFileService | None = None,
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
    if file_service is not None:
        app.state.file_service = file_service

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: Any) -> Response:
        request.state.request_id = f"req_{secrets.token_hex(12)}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    # ── Lightweight in-process rate limiting (§12.2) ──────────────────────
    # Buckets are keyed by (class, identity) with fixed-window counting.  This
    # is intentionally per-process state: the gateway runs a single uvicorn
    # worker on 127.0.0.1, so cross-process coordination is unnecessary.
    _window = 60.0
    _limits: dict[str, int] = {
        # class -> requests per 60s window (per client+token identity)
        "auth": 120,
        "message": 10,
        "sse": 2,
    }
    _buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _classify_rate_path(path: str) -> str | None:
        if path.startswith("/api/mobile/v1/auth/") or path == "/api/mobile/v1/auth/login":
            return "auth"
        if path == "/api/mobile/v1/requests":
            return "message"
        if path == "/api/mobile/v1/events":
            return "sse"
        return None

    def _rate_limit_key(request: Request, cls: str) -> str:
        identity = request.headers.get("authorization", "") or ""
        client = request.client.host if request.client else "unknown"
        return f"{cls}:{client}:{identity}"

    @app.middleware("http")
    async def rate_limit(request: Request, call_next: Any) -> Response:
        cls = _classify_rate_path(request.url.path)
        if cls is not None:
            now = time.monotonic()
            limit = _limits[cls]
            key = _rate_limit_key(request, cls)
            bucket = _buckets[key]
            while bucket and now - bucket[0] > _window:
                bucket.popleft()
            if len(bucket) >= limit:
                return _error_response(
                    request,
                    code="rate_limited",
                    message="请求过于频繁，请稍后再试",
                    status_code=429,
                )
            bucket.append(now)
        return await call_next(request)

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
        is_file_request = request.url.path.startswith("/api/mobile/v1/files")
        return _error_response(
            request,
            code="invalid_file" if is_file_request else "invalid_request",
            message="文件请求无效" if is_file_request else "请求格式无效",
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

    @app.exception_handler(MobileFileError)
    async def mobile_file_error(
        request: Request,
        exc: MobileFileError,
    ) -> JSONResponse:
        messages = {
            "invalid_file": "文件请求无效",
            "file_too_large": "文件超过 50MB 限制",
            "file_type_denied": "文件类型不受支持",
            "file_conflict": "文件状态或内容冲突",
            "file_scan_failed": "文件安全扫描未通过",
            "file_not_found": "文件不存在或不可访问",
            "range_not_satisfiable": "下载范围无效",
            "rate_limited": "活动上传数量已达上限",
        }
        return _error_response(
            request,
            code=exc.code,
            message=messages.get(exc.code, "文件操作失败"),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(MobileApprovalError)
    async def mobile_approval_error(
        request: Request,
        exc: MobileApprovalError,
    ) -> JSONResponse:
        messages = {
            "forbidden": "没有执行此操作的权限",
            "approval_not_found": "审批请求不存在",
            "approvals_unavailable": "审批服务暂不可用",
        }
        return _error_response(
            request,
            code=exc.code,
            message=messages.get(exc.code, "审批操作失败"),
            status_code=exc.status_code,
        )

    @app.exception_handler(MobileReadonlyError)
    async def mobile_readonly_error(
        request: Request,
        exc: MobileReadonlyError,
    ) -> JSONResponse:
        messages = {
            "service_unavailable": "只读服务暂不可用",
            "brief_unavailable": "今日简报暂不可用",
            "world_unavailable": "世界状态暂不可用",
            "memory_unavailable": "记忆档案暂不可用",
            "weather_unavailable": "天气信息暂不可用",
        }
        return _error_response(
            request,
            code=exc.code,
            message=messages.get(exc.code, "只读操作失败"),
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

    def files(
        request: Request,
        identity: MobileIdentityStore = Depends(store),
    ) -> MobileFileService:
        existing = getattr(request.app.state, "file_service", None)
        if existing is None:
            existing = _default_file_service(identity)
            request.app.state.file_service = existing
        return existing

    def chat(
        request: Request,
        identity: MobileIdentityStore = Depends(store),
        file_storage: MobileFileService = Depends(files),
    ) -> MobileChatService:
        existing = getattr(request.app.state, "chat_service", None)
        if existing is None:
            existing = _default_chat_service(identity, file_storage)
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
                "files": True,
                "approvals": current.role == "owner",
            },
        }

    # ── Approvals (owner-only; Phase 6 mobile contract §7.5) ─────────────
    @app.get("/api/mobile/v1/approvals")
    async def approvals(
        current: MobilePrincipal = Depends(principal),
    ) -> dict[str, Any]:
        return mobile_approval_list(current)

    @app.get("/api/mobile/v1/approvals/{approval_id}")
    async def approval_detail(
        approval_id: str,
        current: MobilePrincipal = Depends(principal),
    ) -> dict[str, Any]:
        from core.mobile_approvals import get_approval

        return get_approval(current, approval_id)

    @app.post("/api/mobile/v1/approvals/{approval_id}/decision")
    async def approval_decision(
        approval_id: str,
        payload: ApprovalDecisionRequest,
        current: MobilePrincipal = Depends(principal),
    ) -> dict[str, Any]:
        return mobile_approval_decide(
            current,
            approval_id,
            approved=payload.approved,
            whitelist=payload.whitelist,
            blacklist=payload.blacklist,
        )

    # ── Owner-only audit / guest browsing (§7.5) ─────────────────────────
    @app.get("/api/mobile/v1/owner/guests")
    async def owner_guests(
        current: MobilePrincipal = Depends(principal),
        identity: MobileIdentityStore = Depends(store),
    ) -> dict[str, Any]:
        if current.role != "owner":
            raise MobileAuthError("forbidden", status_code=403)
        return {"items": identity.list_guests()}

    @app.get("/api/mobile/v1/owner/guests/{account_id}/messages")
    async def owner_guest_messages(
        account_id: str,
        limit: int = Query(default=50, ge=1, le=100),
        current: MobilePrincipal = Depends(principal),
        service: MobileChatService = Depends(chat),
    ) -> dict[str, Any]:
        if current.role != "owner":
            raise MobileAuthError("forbidden", status_code=403)
        return service.list_messages_for_actor(account_id, limit=limit)

    @app.get("/api/mobile/v1/owner/audit")
    async def owner_audit(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        account_id: str | None = Query(default=None, alias="accountId"),
        current: MobilePrincipal = Depends(principal),
        identity: MobileIdentityStore = Depends(store),
    ) -> dict[str, Any]:
        if current.role != "owner":
            raise MobileAuthError("forbidden", status_code=403)
        return {
            "items": identity.list_audit_events(
                limit=limit,
                offset=offset,
                account_id=account_id,
            )
        }

    # ── Read-only capability facade (§7.5 / §3.1.2) ──────────────────────
    @app.get("/api/mobile/v1/readonly/brief")
    async def readonly_brief(
        current: MobilePrincipal = Depends(principal),
    ) -> dict[str, Any]:
        return await get_brief()

    @app.get("/api/mobile/v1/readonly/world")
    async def readonly_world(
        current: MobilePrincipal = Depends(principal),
    ) -> dict[str, Any]:
        return await get_world()

    @app.get("/api/mobile/v1/readonly/memory")
    async def readonly_memory(
        current: MobilePrincipal = Depends(principal),
    ) -> dict[str, Any]:
        return await get_memory(current.user_id)

    @app.get("/api/mobile/v1/readonly/weather")
    async def readonly_weather(
        current: MobilePrincipal = Depends(principal),
    ) -> dict[str, Any]:
        return await get_weather()

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

    @app.post("/api/mobile/v1/files/uploads")
    async def create_upload(
        payload: CreateUploadRequest,
        response: Response,
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> dict[str, Any]:
        result, created = service.create_upload(
            current,
            client_upload_id=payload.client_upload_id,
            file_name=payload.file_name,
            size=payload.size,
            sha256=payload.sha256,
            mime_type=payload.mime_type,
            directory_grant_id=payload.directory_grant_id,
        )
        response.status_code = 201 if created else 200
        return result

    @app.get("/api/mobile/v1/files/uploads/{upload_id}")
    async def get_upload(
        upload_id: str,
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> dict[str, Any]:
        return service.get_upload(current, upload_id)

    @app.put(
        "/api/mobile/v1/files/uploads/{upload_id}/parts/{part_number}",
        status_code=204,
    )
    async def put_upload_part(
        upload_id: str,
        part_number: int,
        request: Request,
        x_part_sha256: str | None = Header(
            default=None,
            alias="X-Part-SHA256",
        ),
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> Response:
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > PART_SIZE:
                raise MobileFileError("file_conflict", status_code=409)
            content.extend(chunk)
        service.put_part(
            current,
            upload_id,
            part_number,
            bytes(content),
            x_part_sha256 or "",
        )
        return Response(status_code=204)

    @app.post("/api/mobile/v1/files/uploads/{upload_id}/complete")
    async def complete_upload(
        upload_id: str,
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> dict[str, Any]:
        return service.complete_upload(current, upload_id)

    @app.delete(
        "/api/mobile/v1/files/uploads/{upload_id}",
        status_code=204,
    )
    async def cancel_upload(
        upload_id: str,
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> Response:
        service.cancel_upload(current, upload_id)
        return Response(status_code=204)

    @app.get("/api/mobile/v1/files")
    async def list_files(
        before_id: str | None = Query(default=None, alias="beforeId"),
        limit: int = 50,
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> dict[str, Any]:
        return service.list_files(current, before_id=before_id, limit=limit)

    @app.get("/api/mobile/v1/files/{file_id}")
    async def get_file(
        file_id: str,
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> dict[str, Any]:
        return service.get_file(current, file_id)

    @app.get("/api/mobile/v1/files/{file_id}/content")
    async def download_file(
        file_id: str,
        range_header: str | None = Header(default=None, alias="Range"),
        current: MobilePrincipal = Depends(principal),
        service: MobileFileService = Depends(files),
    ) -> StreamingResponse:
        download = service.prepare_download(current, file_id, range_header)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(download.content_length),
            "Content-Disposition": download.content_disposition,
            "ETag": f'"{download.sha256}"',
        }
        if download.partial:
            headers["Content-Range"] = (
                f"bytes {download.start}-{download.end}/{download.total_size}"
            )
        return StreamingResponse(
            iter_download(download),
            status_code=206 if download.partial else 200,
            media_type=download.mime_type,
            headers=headers,
        )

    @app.get("/api/mobile/v1/messages")
    async def messages(
        before_id: str | None = Query(default=None, alias="beforeId"),
        after_id: str | None = Query(default=None, alias="afterId"),
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
            reply_to_id=payload.reply_to_id,
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
        except (asyncio.TimeoutError, BaseException):
            # Timeout or any escape (SystemExit etc.) — force-cancel.
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, BaseException):
                pass


async def start_mobile_gateway(
    config: MobileGatewayConfig | None = None,
) -> MobileGatewayRunner:
    """Start the isolated gateway and fail explicitly if it does not bind."""

    bind_config = config or get_mobile_gateway_config()

    # Pre-flight port check: uvicorn calls sys.exit(STARTUP_FAILURE) on bind
    # failure, which raises SystemExit (a BaseException, NOT an Exception).
    # SystemExit bypasses normal except-Exception handling and in some
    # asyncio code paths can kill the entire event loop. Probe the port
    # with a TCP connect first so we fail with a clean RuntimeError.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect((bind_config.host, bind_config.port))
            # Connect succeeded — something is already listening.
            raise RuntimeError(
                f"mobile gateway port {bind_config.port} is already in use"
            )
        except (ConnectionRefusedError, socket.timeout):
            # Port is free (connection refused) or filtered (timeout)
            pass

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
    # Safety net: if uvicorn somehow still manages to raise a BaseException
    # (e.g. SystemExit from a different code path), swallow it here so it
    # can never kill the event loop. The for-loop below (or cleanup) will
    # still detect the failure via task.done()/task.result().
    def _swallow_escape(_task: asyncio.Task[Any]) -> None:
        if not _task.done():
            return
        try:
            _task.result()
        except BaseException:
            pass
    task.add_done_callback(_swallow_escape)
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

    try:
        await runner.cleanup()
    except BaseException as exc:
        raise RuntimeError("mobile gateway failed during startup cleanup") from exc
    raise RuntimeError("mobile gateway did not bind within one second")

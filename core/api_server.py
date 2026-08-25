"""Aerie · 云栖 v0.1.0-beta.1 — HTTP API server (FastAPI + uvicorn).

Routes:
  GET  /api/health          — heartbeat + QQ WS status
  POST /api/chat/send       — send message (text + user_id)
  GET  /api/chat/history    — chat history (user_id + limit)
  GET  /api/chat/poll       — incremental poll (user_id + since_id)
  GET  /api/napcat/status   — NapCat status
  POST /api/napcat/start    — start NapCat
  POST /api/napcat/stop     — stop NapCat
  GET  /api/napcat/logs     — NapCat recent logs
  GET  /api/napcat/qrcode   — QR code PNG
  GET  /api/emotion/state   — emotion engine state
  GET  /api/tools/list      — registered tools
  GET  /api/stats/tokens    — token usage stats
  GET  /api/events/stream   — Phase 9: SSE real-time event stream
  GET  /api/cognition/recent   — Phase 9: recent cognition traces
  GET  /api/cognition/{id}     — Phase 9: single trace detail
  GET  /api/cognition/stats    — Phase 9: stats
  GET  /api/emotion/history    — Phase 9: 24h/7d/30d emotion series
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

import uvicorn
import yaml
from fastapi import FastAPI, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, FileResponse, StreamingResponse

from communication.message import IncomingMessage
import main  # R6.6: for PROCESS_START_TIME / GIT_COMMIT (stale-code detection)
from config.persona_loader import (
    load_settings,
    save_settings,
    reset_settings,
    get_persona_summary,
    save_persona,
    save_avatar_bytes,
    load_avatar_bytes,
)
from core.companion import get_companion
from core.database import Database
from core.napcat_launcher import get_launcher
from core.chat_events import emit
from core.chat_request_service import (
    InvalidChatInput,
    QueueUnavailable,
    RequestConflict,
    RequestNotFound,
    RequestStatusView,
)
from core.feature_flags import FeatureFlags
from core.token_tracker import get_token_tracker
from core.cognition import CognitionEngine
from core.event_stream import stream as event_stream_generator
from core.self_evolve_l4 import L4SelfEvolution
from core.self_evolver import SelfEvolver
from core.computer_control import (
    ComputerController,
    ControlMode,
    PolicyEntryType,
)
from core.file_organizer import FileOrganizer
from core.doc_writer import DocWriter, DocType, ExportFormat
from core.calendar_manager import CalendarManager
from core.persona_hub import get_persona_manager
from core.multimodal_input import AudioTranscriber
from knowledge.kb import KnowledgeBase

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(main.PROJECT_ROOT).resolve()

app = FastAPI(title="Aerie · 云栖", version="0.3.1-Beta.1")

# R6.6: enable CORS so the Electron renderer (loaded from file://) can
# call /api/persona/avatar via fetch() and other plain-XHR endpoints.
# This is a local app per project constraints — no network-layer auth
# is required. allow_origins=["*"] covers file://, app://, and any
# custom scheme the renderer might use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

_db = Database()
# 将数据库注入 TokenTracker 单例，否则 llm_caller 的 record() 因 _db 为空而从不落库，
# /api/stats/tokens 的 Token 消耗与 API 调用次数将恒为 0。
get_token_tracker(_db)
_knowledge = KnowledgeBase(_db)
_START_TIME = time.time()

# v13.9: 使用 companion 中的共享 ComputerController 实例，确保权限设置全局生效
# 延迟初始化：第一次访问时从 companion 获取
_computer_controller = None
_file_organizer = FileOrganizer()
_doc_writer = DocWriter()
_calendar = CalendarManager(_db)
_calendar_reminder_task: asyncio.Task | None = None
_persona_mgr = get_persona_manager()
_audio_transcriber = None
_desktop_attachment_service_instance = None
_desktop_attachment_service_key: tuple[int, str] | None = None
_attachment_processing_tasks: set[asyncio.Task] = set()


async def _calendar_reminder_loop() -> None:
    """Scan due calendar reminders and emit them to Electron/SSE clients."""
    while True:
        try:
            reminders = _calendar.collect_due_reminders(lookback_minutes=2)
            for reminder in reminders:
                emit(
                    "calendar_reminder",
                    title=reminder.get("title", "日程提醒"),
                    description=reminder.get("description", ""),
                    event_id=reminder.get("event_id"),
                    instance_id=reminder.get("instance_id"),
                    start_time=reminder.get("start_time"),
                    remind_at=reminder.get("remind_at"),
                    color=reminder.get("color"),
                    event_type=reminder.get("event_type"),
                )
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("calendar reminder loop error")
            await asyncio.sleep(30)


@app.on_event("startup")
async def _start_calendar_reminders() -> None:
    global _calendar_reminder_task
    if _calendar_reminder_task is None or _calendar_reminder_task.done():
        _calendar_reminder_task = asyncio.create_task(_calendar_reminder_loop())


@app.on_event("shutdown")
async def _stop_calendar_reminders() -> None:
    global _calendar_reminder_task
    if _calendar_reminder_task:
        _calendar_reminder_task.cancel()
        try:
            await _calendar_reminder_task
        except asyncio.CancelledError:
            pass
        _calendar_reminder_task = None


def _get_audio_transcriber() -> AudioTranscriber:
    global _audio_transcriber
    if _audio_transcriber is None:
        _audio_transcriber = AudioTranscriber()
    return _audio_transcriber


def _get_computer_controller():
    """获取共享的 ComputerController 实例（优先使用 companion 中的）。"""
    global _computer_controller
    if _computer_controller is None:
        try:
            comp = get_companion()
            if comp and hasattr(comp, "computer_controller") and comp.computer_controller:
                _computer_controller = comp.computer_controller
        except Exception:
            pass
        if _computer_controller is None:
            _computer_controller = ComputerController()
    return _computer_controller


_permission_manager = None


def _get_permission_manager():
    """获取共享的 FineGrainedPermissionManager 实例。"""
    global _permission_manager
    if _permission_manager is None:
        try:
            comp = get_companion()
            if comp and hasattr(comp, "permission_manager") and comp.permission_manager:
                _permission_manager = comp.permission_manager
        except Exception:
            pass
        if _permission_manager is None:
            from core.permission_manager import FineGrainedPermissionManager
            _permission_manager = FineGrainedPermissionManager()
    return _permission_manager


# ── Phase 15: World Dashboard backend contract ─────────────────────────

_WORLD_DASHBOARD_APPROVAL_ACTIONS = {"approve", "reject", "postpone"}

_WORLD_DASHBOARD_EMPTY_SNAPSHOT = {
    "worldSummary": {},
    "relationshipState": {},
    "selfModel": {},
    "actionTimeline": [],
    "imageCandidates": [],
}


def _world_sidecar_enabled(companion: Any | None = None) -> bool:
    """世界是否以任一模式启用（sidecar 或 inprocess）。

    世界既可能运行在 sidecar（world_sidecar_v1）也可能运行在进程内
    （world_inprocess_v1）。之前只查 sidecar flag：当世界以 inprocess
    运行时 dashboard 会被误判 disabled，世界总览/生图候选全部不可见。
    """
    flags = getattr(companion, "feature_flags", None)
    is_enabled = getattr(flags, "is_enabled", None)
    if callable(is_enabled):
        try:
            return (
                is_enabled("world_sidecar_v1") is True
                or is_enabled("world_inprocess_v1") is True
            )
        except Exception:
            logger.warning("shared world feature flag lookup failed", exc_info=True)
    flags_fallback = FeatureFlags()
    return (
        flags_fallback.is_enabled("world_sidecar_v1") is True
        or flags_fallback.is_enabled("world_inprocess_v1") is True
    )


def _world_dashboard_safe_text(value: Any, limit: int = 200) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _sanitize_world_candidate_approval(payload: Any) -> dict[str, str]:
    data = payload if isinstance(payload, dict) else {}
    action = _world_dashboard_safe_text(data.get("action") or "approve").lower()
    if action not in _WORLD_DASHBOARD_APPROVAL_ACTIONS:
        action = "reject"
    candidate_id = _world_dashboard_safe_text(
        data.get("candidate_id") or data.get("candidateId") or ""
    )
    idempotency_key = _world_dashboard_safe_text(
        data.get("idempotency_key")
        or data.get("idempotencyKey")
        or candidate_id
    )
    reason_code = _world_dashboard_safe_text(
        data.get("reason_code") or data.get("reasonCode") or ""
    )
    return {
        "candidate_id": candidate_id,
        "action": action,
        "idempotency_key": idempotency_key,
        "reason_code": reason_code,
    }


def _world_candidate_approval_response(
    *,
    status: str,
    candidate_id: str,
    ack: bool,
    handler_called: bool,
    reason: str = "",
    error_code: str = "",
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "status": _world_dashboard_safe_text(status or "unknown"),
        "candidateId": _world_dashboard_safe_text(candidate_id),
        "ack": bool(ack),
        "sideEffects": {"handler_called": bool(handler_called)},
    }
    if reason:
        response["reason"] = _world_dashboard_safe_text(reason)
    if error_code:
        response["error_code"] = _world_dashboard_safe_text(error_code)
    return response


def _world_dashboard_public_snapshot(
    snapshot: Any,
    *,
    status: str = "",
    handler_called: bool,
) -> dict[str, Any]:
    data = snapshot if isinstance(snapshot, dict) else {}
    public = {
        "status": _world_dashboard_safe_text(status or data.get("status") or "unknown"),
        "worldSummary": _world_dashboard_public_world_summary(data.get("worldSummary") or data.get("world_summary")),
        "relationshipState": _world_dashboard_public_relationship(data.get("relationshipState") or data.get("relationship_state")),
        "selfModel": _world_dashboard_public_self_model(data.get("selfModel") or data.get("self_model")),
        "actionTimeline": _world_dashboard_public_timeline(data.get("actionTimeline") or data.get("action_timeline")),
        "imageCandidates": _world_dashboard_public_candidates(data.get("imageCandidates") or data.get("image_candidates")),
        "sideEffects": {"handler_called": bool(handler_called)},
    }
    updated_at = _world_dashboard_public_scalar(data.get("updatedAt") or data.get("updated_at"))
    if updated_at not in ("", None):
        public["updatedAt"] = updated_at
    error_code = _world_dashboard_safe_text(data.get("error_code") or data.get("errorCode") or "")
    if error_code:
        public["error_code"] = error_code
    return public


def _world_dashboard_public_world_summary(value: Any) -> dict[str, Any]:
    return _world_dashboard_public_map(
        value,
        (
            ("status", "status"),
            ("source", "source"),
            ("instanceId", "instanceId", "instance_id"),
            ("protocol", "protocol"),
            ("protocolVersion", "protocolVersion", "protocol_version"),
            ("phase", "phase"),
            ("location", "location"),
            ("activity", "activity"),
            ("energy", "energy"),
            # 房间级细粒度定位（方向5）：透传楼层/区域/大致位置/周边物件到世界界面。
            ("floor", "floor"),
            ("zone", "zone"),
            ("positionDesc", "position_desc", "positionDesc"),
            ("nearbyObjects", "nearby_objects", "nearbyObjects"),
            # P2: 移动状态透传（status/path/waypoints/progress/reason）。
            ("movement", "movement"),
            ("weather", "weather", "weather_mood"),
            ("weatherMood", "weather_mood", "weather"),
            ("weatherDetail", "weather_detail", "weatherDetail"),
            ("city", "city"),
            ("randomEvents", "random_events", "randomEvents"),
            ("cityEvents", "city_events", "cityEvents"),
            ("sequence", "sequence"),
            ("revision", "revision"),
            ("paused", "paused"),
            ("generatedAt", "generatedAt", "generated_at"),
            ("capabilities", "capabilities"),
        ),
    )


def _world_dashboard_public_relationship(value: Any) -> dict[str, Any]:
    return _world_dashboard_public_map(
        value,
        (
            ("user_id", "user_id", "userId"),
            ("persona_id", "persona_id", "personaId"),
            ("warmth", "warmth"),
            ("trust", "trust"),
            ("affinity", "affinity"),
            ("tension", "tension"),
            ("familiarity", "familiarity"),
            ("conflict", "conflict"),
            ("closeness", "closeness"),
            ("summary", "summary"),
            ("updated_at", "updated_at", "updatedAt"),
        ),
    )


def _world_dashboard_public_self_model(value: Any) -> dict[str, Any]:
    return _world_dashboard_public_map(
        value,
        (
            ("mood", "mood"),
            ("energy", "energy"),
            ("focus", "focus"),
            ("stability", "stability"),
            ("summary", "summary"),
            ("updated_at", "updated_at", "updatedAt"),
        ),
    )


def _world_dashboard_public_timeline(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    return [
        _world_dashboard_public_map(
            row,
            (
                ("eventId", "eventId", "event_id"),
                ("topic", "topic"),
                ("eventType", "eventType", "event_type"),
                ("sequence", "sequence"),
                ("occurredAt", "occurredAt", "occurred_at"),
                ("payloadKeys", "payloadKeys", "payload_keys"),
                ("payloadSha256", "payloadSha256", "payload_sha256"),
            ),
        )
        for row in rows[:25]
        if isinstance(row, dict)
    ]


def _world_dashboard_public_candidates(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    return [
        _world_dashboard_public_map(
            row,
            (
                ("candidateId", "candidateId", "candidate_id"),
                ("idempotencyKey", "idempotencyKey", "idempotency_key"),
                ("scene", "scene"),
                ("ownerId", "ownerId", "owner_id"),
                ("channel", "channel"),
                ("target", "target"),
                ("promptKey", "promptKey", "prompt_key"),
                ("reasonCode", "reasonCode", "reason_code"),
                ("source", "source"),
                ("score", "score"),
                ("expiresAt", "expiresAt", "expires_at"),
                ("createdAt", "createdAt", "created_at"),
                ("sequence", "sequence"),
                ("eventId", "eventId", "event_id"),
                ("payloadKeys", "payloadKeys", "payload_keys"),
                ("sensitiveKeys", "sensitiveKeys", "sensitive_keys"),
                ("sensitiveSha256", "sensitiveSha256", "sensitive_sha256"),
            ),
        )
        for row in rows[:25]
        if isinstance(row, dict)
    ]


def _world_dashboard_public_map(
    value: Any,
    fields: tuple[tuple[str, ...], ...],
) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    public: dict[str, Any] = {}
    for field in fields:
        output_key, *input_keys = field
        raw = _world_dashboard_first(data, input_keys)
        public_value = _world_dashboard_public_scalar(raw)
        if public_value not in ("", None, [], {}):
            public[output_key] = public_value
    return public


def _world_dashboard_first(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _world_dashboard_public_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, list | tuple):
        return [_world_dashboard_safe_text(item, 120) for item in value[:25]]
    if value is None:
        return ""
    return _world_dashboard_safe_text(value)


@app.get("/api/world/dashboard/snapshot")
async def world_dashboard_snapshot(
    user_id: int | None = Query(default=None),
) -> dict[str, Any]:
    """Redacted World Dashboard snapshot contract.

    This endpoint exposes only public dashboard fields. Raw world payloads,
    prompt text, message text, plugin config values, and provider details are
    deliberately dropped by whitelisting instead of recursively echoing handler
    output.
    """
    comp = get_companion()
    if not _world_sidecar_enabled(comp):
        return _world_dashboard_public_snapshot(
            {
                "status": "disabled",
                **_WORLD_DASHBOARD_EMPTY_SNAPSHOT,
            },
            status="disabled",
            handler_called=False,
        )

    if user_id is None:
        user_id = _primary_user_id(comp) if comp is not None else None
        if user_id is None:
            return _world_dashboard_public_snapshot(
                {
                    "status": "unavailable",
                    **_WORLD_DASHBOARD_EMPTY_SNAPSHOT,
                    "error_code": "primary_identity_unconfigured",
                },
                status="unavailable",
                handler_called=False,
            )
    elif user_id <= 0:
        return _world_dashboard_public_snapshot(
            {
                "status": "unavailable",
                **_WORLD_DASHBOARD_EMPTY_SNAPSHOT,
                "error_code": "invalid_user_id",
            },
            status="unavailable",
            handler_called=False,
        )
    handler = getattr(comp, "get_world_dashboard_snapshot", None)
    if not callable(handler):
        return _world_dashboard_public_snapshot(
            {
                "status": "backend_unavailable",
                **_WORLD_DASHBOARD_EMPTY_SNAPSHOT,
                "error_code": "snapshot_handler_missing",
            },
            status="backend_unavailable",
            handler_called=False,
        )

    try:
        try:
            result = handler(user_id=user_id)
        except TypeError:
            result = handler()
        if hasattr(result, "__await__"):
            result = await result
    except Exception:
        logger.warning("world dashboard snapshot handler failed", exc_info=True)
        return _world_dashboard_public_snapshot(
            {
                "status": "failed",
                **_WORLD_DASHBOARD_EMPTY_SNAPSHOT,
                "error_code": "snapshot_handler_failed",
            },
            status="failed",
            handler_called=True,
        )

    return _world_dashboard_public_snapshot(result, handler_called=True)


@app.get("/api/internal/state")
async def internal_state(
    user_id: int | None = Query(default=None),
) -> dict[str, Any]:
    """Read-only internal-state snapshot (needs / fatigue / neuro-like metrics).

    Phase 15 Batch 3 (B3.1). Deterministic and source-tracked; always labelled
    "计算模型，非生物测量" — never a medical measurement. Exposes no write path.
    """
    comp = get_companion()
    handler = getattr(comp, "get_internal_state", None) if comp else None
    if not callable(handler):
        return {"status": "backend_unavailable", "label": "计算模型，非生物测量"}
    try:
        result = handler(user_id=user_id or 0)
        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, dict):
            result = {}
        result.setdefault("status", "ready")
        return result
    except Exception:
        logger.warning("internal state handler failed", exc_info=True)
        return {"status": "failed", "label": "计算模型，非生物测量"}


@app.get("/api/internal/history")
async def internal_history(
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Read-only internal-state trend sequence for the dashboard chart."""
    comp = get_companion()
    handler = getattr(comp, "get_internal_history", None) if comp else None
    if not callable(handler):
        return {"status": "backend_unavailable", "items": []}
    try:
        items = handler(limit=limit)
        if hasattr(items, "__await__"):
            items = await items
        if not isinstance(items, list):
            items = []
        return {"status": "ready", "items": items}
    except Exception:
        logger.warning("internal history handler failed", exc_info=True)
        return {"status": "failed", "items": []}


@app.post("/api/world/candidates/approve")
async def world_candidate_approve(request: Request) -> dict[str, Any]:
    """Dashboard-only candidate approval contract.

    The API layer deliberately remains a thin, redacted adapter.  It accepts
    only the public approval fields, respects ``world_sidecar_v1`` as a hard
    feature gate, and delegates actual world/image side effects to Companion
    when a handler is available.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    approval = _sanitize_world_candidate_approval(payload)

    comp = get_companion()
    if not _world_sidecar_enabled(comp):
        return _world_candidate_approval_response(
            status="disabled",
            candidate_id=approval["candidate_id"],
            ack=False,
            handler_called=False,
        )

    handler = getattr(comp, "approve_world_image_candidate", None)
    if not callable(handler):
        return _world_candidate_approval_response(
            status="backend_unavailable",
            candidate_id=approval["candidate_id"],
            ack=False,
            handler_called=False,
            error_code="approval_handler_missing",
        )

    try:
        result = handler(dict(approval))
        if hasattr(result, "__await__"):
            result = await result
    except Exception:
        logger.warning("world candidate approval handler failed", exc_info=True)
        return _world_candidate_approval_response(
            status="failed",
            candidate_id=approval["candidate_id"],
            ack=False,
            handler_called=True,
            error_code="approval_handler_failed",
        )

    result = result if isinstance(result, dict) else {}
    return _world_candidate_approval_response(
        status=_world_dashboard_safe_text(result.get("status") or "submitted"),
        candidate_id=approval["candidate_id"],
        ack=bool(result.get("ack") or result.get("acked")),
        handler_called=True,
        reason=_world_dashboard_safe_text(result.get("reason") or ""),
        error_code=_world_dashboard_safe_text(result.get("error_code") or ""),
    )


@app.post("/api/world/image-candidates/publish")
async def world_image_candidate_publish(request: Request) -> dict[str, Any]:
    """Publish an AI image decision so the generated image lands in local chat.

    Thin adapter over :meth:`Companion.publish_image_candidate`.  Accepts only
    public candidate fields; the world normalizes + redacts the payload, then
    the Phase 14 consumer runs the image workflow and injects the result into
    the local chat bubble (or QQ) for the given channel.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload = body if isinstance(body, dict) else {}

    comp = get_companion()
    if comp is None:
        return {
            "status": "unavailable",
            "reason": "companion_unavailable",
            "channel": str(payload.get("channel") or "local_chat"),
        }

    publisher = getattr(comp, "publish_image_candidate", None)
    if not callable(publisher):
        return {
            "status": "unavailable",
            "reason": "publisher_unavailable",
            "channel": str(payload.get("channel") or "local_chat"),
        }

    candidate = {
        "candidate_id": _world_dashboard_safe_text(payload.get("candidate_id")),
        "idempotency_key": _world_dashboard_safe_text(payload.get("idempotency_key")),
        "scene": _world_dashboard_safe_text(payload.get("scene")) or "local_send",
        "owner_id": _world_dashboard_safe_text(payload.get("owner_id")) or "master",
        "channel": _world_dashboard_safe_text(payload.get("channel")) or "local_chat",
        "target": _world_dashboard_safe_text(payload.get("target")),
        "prompt_key": _world_dashboard_safe_text(payload.get("prompt_key")),
        "reason_code": _world_dashboard_safe_text(payload.get("reason_code")),
        "source": _world_dashboard_safe_text(payload.get("source")) or "generated",
        "score": float(payload.get("score") or 0.0) if isinstance(payload.get("score"), (int, float)) else 0.0,
    }

    try:
        result = publisher(candidate)
        if hasattr(result, "__await__"):
            result = await result
    except Exception:
        logger.warning("world image candidate publish failed", exc_info=True)
        return {
            "status": "failed",
            "reason": "publish_failed",
            "channel": candidate["channel"],
        }

    result = result if isinstance(result, dict) else {}
    return {
        "status": _world_dashboard_safe_text(result.get("status") or "failed"),
        "reason": _world_dashboard_safe_text(result.get("reason") or ""),
        "candidateId": _world_dashboard_safe_text(result.get("candidate_id")),
        "channel": _world_dashboard_safe_text(result.get("channel")),
        "target": _world_dashboard_safe_text(result.get("target")),
        "sequence": int(result.get("sequence") or 0),
        "consumed": result.get("consumed") if isinstance(result.get("consumed"), list) else [],
    }


# ── Health ──────────────────────────────────────────

# Runtime configuration

def _runtime_config_service():
    companion = get_companion()
    return getattr(companion, "runtime_config_service", None) if companion else None


def _runtime_public_snapshot(service: Any) -> dict[str, Any]:
    snapshot = dict(service.snapshot())
    values = snapshot.get("values") or {}
    snapshot["requiresRestartKeys"] = [
        key
        for key, entry in values.items()
        if isinstance(entry, dict) and entry.get("requiresRestart") is True
    ]
    companion = get_companion()
    selection = (
        companion.get_primary_user_selection()
        if companion and hasattr(companion, "get_primary_user_selection")
        else None
    )
    identity = (
        selection.as_dict()
        if selection is not None and hasattr(selection, "as_dict")
        else {"primaryUserId": None, "source": "unconfigured"}
    )
    snapshot["primaryIdentity"] = identity
    snapshot["primaryUserId"] = identity.get("primaryUserId")
    return snapshot


@app.get("/api/runtime/snapshot")
async def runtime_snapshot() -> Response:
    service = _runtime_config_service()
    if service is None:
        return JSONResponse(
            {"error": "runtime_config_unavailable", "errorCode": "runtime_config_unavailable"},
            status_code=503,
        )
    return JSONResponse(_runtime_public_snapshot(service))


@app.patch("/api/runtime/config")
async def runtime_config_update(request: Request) -> Response:
    service = _runtime_config_service()
    if service is None:
        return JSONResponse(
            {"accepted": False, "error": "runtime_config_unavailable", "errorCode": "runtime_config_unavailable"},
            status_code=503,
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"accepted": False, "error": "invalid_json", "errorCode": "invalid_json"},
            status_code=400,
        )
    if not isinstance(body, dict) or not isinstance(body.get("changes"), dict):
        return JSONResponse(
            {"accepted": False, "error": "invalid_changes", "errorCode": "invalid_changes"},
            status_code=400,
        )
    if "primary_user_id" in body["changes"]:
        primary_value = body["changes"]["primary_user_id"]
        normalized_primary = str(primary_value).strip()
        if (
            isinstance(primary_value, bool)
            or not normalized_primary.isdecimal()
            or int(normalized_primary) <= 0
        ):
            return JSONResponse(
                {
                    "accepted": False,
                    "error": "validation_failed",
                    "errorCode": "validation_failed",
                    "validationErrors": [
                        {"key": "primary_user_id", "code": "invalid_positive_identity"}
                    ],
                },
                status_code=422,
            )
    expected = body.get("expected_revision", body.get("expectedRevision"))
    if isinstance(expected, bool):
        expected = None
    try:
        expected_revision = int(expected)
    except (TypeError, ValueError):
        return JSONResponse(
            {"accepted": False, "error": "invalid_revision", "errorCode": "invalid_revision"},
            status_code=400,
        )

    from core.runtime_config import (
        RuntimeConfigConflict,
        RuntimeConfigError,
        RuntimeConfigValidationError,
    )

    try:
        service.update(body["changes"], expected_revision=expected_revision)
    except RuntimeConfigConflict as exc:
        return JSONResponse(
            {
                "accepted": False,
                "error": exc.code,
                "errorCode": exc.code,
                "expectedRevision": exc.expected,
                "currentRevision": exc.current,
            },
            status_code=409,
        )
    except RuntimeConfigValidationError as exc:
        return JSONResponse(
            {
                "accepted": False,
                "error": exc.code,
                "errorCode": exc.code,
                "validationErrors": exc.errors,
            },
            status_code=422,
        )
    except RuntimeConfigError as exc:
        return JSONResponse(
            {"accepted": False, "error": exc.code, "errorCode": exc.code},
            status_code=409,
        )
    return JSONResponse({"accepted": True, **_runtime_public_snapshot(service)})


def _main_process_request_authorized(request: Request) -> bool:
    import secrets

    expected = os.getenv("AERIE_MAIN_PROCESS_TOKEN", "")
    provided = request.headers.get("X-Aerie-Main-Token", "")
    return bool(expected and provided) and secrets.compare_digest(expected, provided)


def _memory_write_validation_enabled() -> bool:
    """P2 写入校验门开关（§3.7-2），PoC 阶段默认关闭。"""
    try:
        from core.feature_flags import FeatureFlags

        return bool(FeatureFlags().is_enabled("memory_write_validation_v1"))
    except Exception:
        return False


@app.post("/api/world/runtime/bind")
async def world_runtime_bind(request: Request) -> Response:
    if not _main_process_request_authorized(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    companion = get_companion()
    if companion is None:
        return JSONResponse({"error": "backend_not_ready"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    connection = body.get("connection") if isinstance(body, dict) else None
    if connection is None:
        from core.world_port import NullWorldAdapter, InProcessWorldAdapter
        # 世界 supervisor 停止通知只在 sidecar 场景有意义。InProcess 世界由
        # Core 自己驱动，不依赖 sidecar supervisor；Electron 的 world connection
        # monitor 在 sidecar 未启用时每 2s 上报 connection=null，若这里无条件
        # 覆盖，会把正在运行的 InProcess 世界静默替换为 NullWorldAdapter，
        # 导致 publish_image_candidate 全部返回 world_disabled，生图链路瘫痪。
        if isinstance(getattr(companion, "world_port", None), InProcessWorldAdapter):
            return JSONResponse({"accepted": True, "adapter": "in_process_kept"})
        companion.world_port = NullWorldAdapter(reason="supervisor_stopped")
        return JSONResponse({"accepted": True, "adapter": "null"})
    if not isinstance(connection, dict):
        return JSONResponse({"error": "invalid_connection"}, status_code=400)
    endpoint = str(connection.get("endpoint") or "").strip()
    token = str(connection.get("token") or "")
    expected_instance_id = str(connection.get("instanceId") or "").strip()
    if len(endpoint) > 256 or not (16 <= len(token) <= 512):
        return JSONResponse({"error": "invalid_connection"}, status_code=400)
    try:
        from core.world_adapters.remote import HttpWorldSidecarClient, RemoteWorldAdapter

        client = HttpWorldSidecarClient(endpoint, token=token)
        hello = await asyncio.to_thread(client.hello)
    except Exception:
        return JSONResponse({"error": "sidecar_handshake_failed"}, status_code=409)
    instance_id = str(hello.get("instance_id") or "")
    if not instance_id or (
        expected_instance_id and expected_instance_id != instance_id
    ):
        return JSONResponse({"error": "sidecar_instance_mismatch"}, status_code=409)
    companion.world_port = RemoteWorldAdapter(client)
    return JSONResponse(
        {"accepted": True, "adapter": "remote", "instanceId": instance_id}
    )


@app.post("/api/world/control")
async def world_control(request: Request) -> Response:
    """世界控制台 HTTP 控制接口（Phase 15 Batch 2）。

    受 `X-Aerie-Main-Token` 鉴权保护，仅主进程可调。动作转发到
    ``world_port.control``（inprocess / sidecar 任一模均支持）。
    支持 pause / resume / start / stop / restart / enable / disable 等，
    其余动作（如 speed / fastforward / seed / checkpoint / replay）在
    适配器不支持时返回 ``accepted=false`` + ``errorCode=unsupported_action``。
    """
    if not _main_process_request_authorized(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    companion = get_companion()
    if companion is None:
        return JSONResponse({"error": "backend_not_ready"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    action = str((body or {}).get("action") or "").strip()
    if not action:
        return JSONResponse({"error": "missing_action"}, status_code=400)

    world_port = getattr(companion, "world_port", None)
    control = getattr(world_port, "control", None)
    if not callable(control):
        return JSONResponse(
            {"accepted": False, "rejected": True, "errorCode": "world_unavailable"}
        )

    expected_revision = (body or {}).get("expectedRevision", (body or {}).get("expected_revision"))
    idempotency_key = str((body or {}).get("idempotencyKey") or (body or {}).get("idempotency_key") or "")
    try:
        result = control(
            action,
            expected_revision=int(expected_revision) if expected_revision is not None else None,
            idempotency_key=idempotency_key,
        )
        if hasattr(result, "__await__"):
            result = await result
    except Exception:
        logger.warning("world control failed", exc_info=True)
        return JSONResponse(
            {"accepted": False, "rejected": True, "errorCode": "control_failed"}
        )

    if not isinstance(result, dict):
        result = {"accepted": bool(result), "rejected": not bool(result)}
    result.setdefault("action", action)
    return JSONResponse(result)


@app.post("/api/world/reality/refresh")
async def world_reality_refresh(request: Request) -> Response:
    """立即拉取并注入当前世界城市的真实数据（天气/附近地点/实时事件）。

    在仪表盘保存世界位置后调用，让位置改动无需等待后台刷新周期即可生效。
    受主进程 Token 鉴权保护。
    """
    if not _main_process_request_authorized(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    companion = get_companion()
    if companion is None:
        return JSONResponse({"error": "backend_not_ready"}, status_code=503)
    world_port = getattr(companion, "world_port", None)
    setter = getattr(world_port, "set_reality", None)
    if not callable(setter):
        return JSONResponse({"error": "world_unavailable"}, status_code=503)

    try:
        settings = load_settings() or {}
        city = str((settings.get("world") or {}).get("location") or "").strip()
        if not city:
            from core.location_resolver import resolve_location_async
            city = str((await resolve_location_async()).get("city") or "").strip()
        result: dict[str, Any] = {"status": "ok", "city": city, "weather": {}}
        if city:
            from core.world_reality import fetch_reality
            reality = await fetch_reality(city)
            setter(reality)
            result["city"] = city
            result["weather"] = reality.get("weather") or {}
            result["nearby"] = len(reality.get("nearby_places") or [])
            result["events"] = len(reality.get("city_events") or [])
        else:
            result["status"] = "no_city"
        return JSONResponse(result)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("world reality refresh failed: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@app.get("/api/health")
async def health(request: Request) -> dict:
    comp = get_companion()
    uptime = int(time.time() - _START_TIME)
    # R6.6: also report whether the running process is stale (i.e. some
    # source file has been modified after this Python process started).
    stale_info = _check_stale_code()

    # R9.0+: component-level health details
    qq_state = "unknown"
    qq_ws_connected = False
    qq_logged_in = False
    qq_self_id = 0
    push_running = False
    push_paused = False
    push_paused_reason = ""

    if comp:
        qq_state = comp.qq.state
        qq_ws_connected = comp.qq.is_connected
        qq_logged_in = comp.qq.is_logged_in
        qq_self_id = comp.qq.self_id
        push_running = comp.push_scheduler.cron._running
        push_paused = comp.push_scheduler.is_paused
        push_paused_reason = comp.push_scheduler.paused_reason

    # Overall status: healthy / degraded / unhealthy
    if comp and qq_logged_in:
        overall = "healthy"
    elif comp:
        overall = "degraded"
    else:
        overall = "unhealthy"

    return {
        "status": overall,
        "app": "Aerie · 云栖",
        "version": "0.3.1-Beta.1",
        "uptime_seconds": uptime,
        "qq_connected": qq_ws_connected,
        "git_commit": getattr(main, "GIT_COMMIT", "unknown"),
        "process_started_at": getattr(main, "PROCESS_START_ISO", ""),
        "backend_instance_id": getattr(main, "BACKEND_INSTANCE_ID", ""),
        "data_path_id": str(_db.db_path.resolve()).lower(),
        "stale_code": stale_info,
        "startup_progress": _startup_progress_payload(),
        "components": {
            "backend": "healthy" if comp else "unhealthy",
            "qq": {
                "state": qq_state,
                "ws_connected": qq_ws_connected,
                "logged_in": qq_logged_in,
                "self_id": qq_self_id,
            },
            "push_scheduler": {
                "running": push_running,
                "paused": push_paused,
                "paused_reason": push_paused_reason,
            },
            "providers": _provider_health_payload(comp),
        },
    }


def _startup_progress_payload() -> dict:
    """后端启动进度快照(供前端进度条轮询)。"""
    try:
        from core.startup_progress import get_startup_progress

        return get_startup_progress().snapshot()
    except Exception:  # noqa: BLE001
        return {"started_at": 0, "finished": True, "elapsed_ms": 0, "steps": []}


def _provider_health_payload(comp) -> dict:
    """LLM provider 健康/余额摘要（欠费账户会自动被踢出轮询）。"""
    try:
        brain = getattr(comp, "brain", None)
        if brain is None:
            return {"available": False}
        health = getattr(brain, "health_summary", None)
        if not callable(health):
            return {"available": False}
        return {"available": True, **health()}
    except Exception:
        logger.debug("provider health payload failed", exc_info=True)
        return {"available": False}


def _check_stale_code() -> dict:
    """R6.6: detect source files modified AFTER this process started.

    Returns a dict with ``stale`` (bool) and ``modified`` (list of
    relative paths) when any tracked file in core/ config/ or main.py
    has mtime > PROCESS_START_TIME.
    """
    try:
        start = getattr(main, "PROCESS_START_TIME", None)
        if not start:
            return {"stale": False, "modified": [], "reason": "no_start_time"}
        # Allow a 2s skew (filesystem mtime resolution).
        threshold = start - 2.0
        project_root = Path(main.PROJECT_ROOT)
        watch_dirs = [project_root / "core", project_root / "config", project_root / "main.py"]
        modified: list[str] = []
        for path in watch_dirs:
            if path.is_file():
                files = [path]
            elif path.is_dir():
                files = list(path.rglob("*.py"))
            else:
                continue
            for f in files:
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                if mtime > threshold:
                    rel = f.relative_to(project_root).as_posix()
                    modified.append(rel)
        if modified:
            return {
                "stale": True,
                "modified": modified[:20],
                "started_at": main.PROCESS_START_ISO,
                "now": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "hint": "Run tools/restart.bat to pick up the latest code.",
            }
        return {"stale": False, "modified": []}
    except Exception as e:
        return {"stale": False, "modified": [], "error": str(e)}


# ── Diagnostics telemetry ─────────────────────────────────
# Cumulative runtime tracking + package/upload, consumed by the settings page.
# Package/upload work is synchronous and cheap; it is kept out of the event
# loop via asyncio.to_thread so it never blocks the chat path.

async def _diag_read_json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


@app.get("/api/diagnostics/status")
async def diagnostics_status() -> dict[str, Any]:
    from core import telemetry
    return await asyncio.to_thread(telemetry.get_status)


@app.post("/api/diagnostics/export")
async def diagnostics_export(request: Request) -> dict[str, Any]:
    from core import telemetry
    body = await _diag_read_json(request)
    reason = str(body.get("reason") or "manual")
    info = await asyncio.to_thread(telemetry.create_package, reason)
    upload = bool(body.get("upload"))
    if upload:
        result = await asyncio.to_thread(telemetry.upload_package, info["filename"])
        info["upload"] = result
    return info


@app.post("/api/diagnostics/upload")
async def diagnostics_upload(request: Request) -> dict[str, Any]:
    from core import telemetry
    body = await _diag_read_json(request)
    filename = str(body.get("filename") or "")
    if not filename:
        return JSONResponse({"error": "filename_required"}, status_code=400)
    return await asyncio.to_thread(telemetry.upload_package, filename)


@app.get("/api/diagnostics/list")
async def diagnostics_list() -> dict[str, Any]:
    from core import telemetry
    packages = await asyncio.to_thread(telemetry.list_packages)
    return {"packages": packages}


@app.get("/api/diagnostics/download/{filename}")
async def diagnostics_download(filename: str):
    from core import telemetry
    target = telemetry._packages_dir() / filename
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(str(target), filename=filename, media_type="application/zip")


# R6.6: backend self-restart endpoint. Triggers tools/restart_helper.ps1
# in a detached process so the calling HTTP request can return BEFORE
# the backend itself gets killed.
@app.post("/api/system/restart")
async def system_restart() -> dict:
    import subprocess
    project_root = Path(main.PROJECT_ROOT)
    helper = project_root / "tools" / "restart_helper.ps1"
    if not helper.exists():
        return JSONResponse({"error": "helper_missing"}, status_code=500)
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper),
        "-ProjectRoot",
        str(project_root),
        "-TargetPid",
        str(os.getpid()),
        "-PythonExecutable",
        sys.executable,
    ]
    log_path = project_root / "logs" / "restart_helper.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8") as restart_log:
            process = subprocess.Popen(
                command,
                cwd=str(project_root),
                stdin=subprocess.DEVNULL,
                stdout=restart_log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except Exception as e:
        return JSONResponse({"error": "spawn_failed", "detail": str(e)}, status_code=500)
    logging.getLogger(__name__).info(
        "backend restart helper scheduled pid=%s log=%s",
        process.pid,
        log_path,
    )
    return {"status": "scheduled", "hint": "Backend will restart in ~3s"}


@app.post("/api/system/reload-config")
async def system_reload_config() -> dict:
    """Hot-reload config files without restarting the backend.

    Reloads settings.yaml, persona.yaml, persona_behavior.yaml, and
    proactive.yaml from disk, then pushes updates to modules that
    support runtime reconfiguration.

    Returns a dict of which config files were reloaded and which
    modules were updated.
    """
    import logging
    import asyncio
    log = logging.getLogger(__name__)
    results: dict[str, Any] = {"reloaded": [], "updated": []}

    async def _call_reload(obj, method_name, *args, label: str) -> None:
        """Safely call a reload method (sync or async) on an object."""
        if not hasattr(obj, method_name):
            return
        method = getattr(obj, method_name)
        if not callable(method):
            return
        try:
            r = method(*args)
            if asyncio.iscoroutine(r):
                await r
            results["updated"].append(label)
        except Exception as e:
            log.warning("%s reload failed: %s", label, e)

    try:
        from config.persona_loader import (
            load_settings,
            load_behavior_config,
            load_proactive_config,
            load_persona,
        )
        comp = get_companion()
        if comp:
            new_settings = load_settings()
            comp.settings = new_settings
            results["reloaded"].append("settings.yaml")
            results["updated"].append("companion.settings")

            new_behavior = load_behavior_config()
            comp.behavior_cfg = new_behavior
            results["reloaded"].append("persona_behavior.yaml")
            results["updated"].append("companion.behavior_cfg")

            if hasattr(comp, "emotion") and comp.emotion:
                await _call_reload(comp.emotion, "update_behavior_config", new_behavior, label="emotion_engine")

            if hasattr(comp, "threshold_engine") and comp.threshold_engine:
                await _call_reload(comp.threshold_engine, "reload_config", new_behavior, label="threshold_engine")

            if hasattr(comp, "push_scheduler") and comp.push_scheduler:
                new_proactive = load_proactive_config()
                results["reloaded"].append("proactive.yaml")
                await _call_reload(comp.push_scheduler, "reload_config", new_proactive, label="push_scheduler")
                # 重载 proactive.yaml 会用文件默认值重建 PushPolicy，
                # 需重应用 settings.yaml 的覆盖，避免把设置页的选择丢掉。
                reapply = getattr(comp, "_apply_proactive_overlay", None)
                if callable(reapply):
                    reapply()

            if hasattr(comp, "qq") and comp.qq:
                qq_cfg = new_settings.get("qq", {}) if isinstance(new_settings, dict) else {}
                await _call_reload(comp.qq, "update_config", qq_cfg, label="qq_client")

        emit("config_reloaded", **results)
        log.info("config hot-reload complete: %s", results)
    except Exception as e:
        log.exception("config hot-reload failed")
        return JSONResponse({"error": str(e), "results": results}, status_code=500)

    return {"status": "ok", "results": results}


# ── Chat ───────────────────────────────────────────

def _chat_request_queue_requested(comp: Any) -> bool:
    requested = getattr(comp, "chat_request_queue_requested", None)
    if isinstance(requested, bool):
        return requested
    flags = getattr(comp, "feature_flags", None)
    is_enabled = getattr(flags, "is_enabled", None)
    if not callable(is_enabled):
        return False
    try:
        return is_enabled("chat_request_queue_v1") is True
    except Exception:
        return False


def _chat_request_service_or_error(comp: Any):
    if getattr(comp, "chat_request_queue_ready", False) is not True:
        error = getattr(comp, "chat_request_queue_error", None)
        if not isinstance(error, str) or not error:
            error = "queue_dependencies_unavailable"
        return None, JSONResponse({"error": error}, status_code=503)
    service = getattr(comp, "chat_request_service", None)
    if service is None:
        return None, JSONResponse(
            {"error": "queue_dependencies_unavailable"},
            status_code=503,
        )
    return service, None


def _chat_request_view_response(
    view: RequestStatusView,
    *,
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(asdict(view), status_code=status_code)


def _chat_request_error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, RequestNotFound):
        return JSONResponse({"error": exc.error_code}, status_code=404)
    if isinstance(exc, RequestConflict):
        payload = {"error": exc.error_code}
        if exc.status is not None:
            payload["status"] = exc.status
        return JSONResponse(payload, status_code=409)
    if isinstance(exc, QueueUnavailable):
        return JSONResponse({"error": exc.error_code}, status_code=503)
    if isinstance(exc, InvalidChatInput):
        return JSONResponse({"error": exc.error_code}, status_code=400)
    raise exc


def _positive_user_id(value: Any) -> int | None:
    """Accept only a real positive integer or its decimal string form."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdecimal():
            parsed = int(normalized)
            return parsed if parsed > 0 else None
    return None


def _primary_user_id(companion: Any) -> int | None:
    getter = getattr(companion, "get_primary_user_selection", None)
    if not callable(getter):
        return None
    try:
        selection = getter()
    except Exception:
        logger.warning("primary identity selection failed", exc_info=True)
        return None
    return _positive_user_id(getattr(selection, "user_id", None))


def _trusted_chat_attachments(attachments: Any) -> list[dict[str, Any]]:
    trusted_attachments = []
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        attachment_id = attachment.get("attachmentId") or attachment.get("id")
        if attachment_id:
            attachment_id = str(attachment_id)
            trusted_attachments.append(
                {"attachmentId": attachment_id, "id": attachment_id}
            )
        else:
            trusted_attachments.append(dict(attachment))
    return trusted_attachments


async def _process_local_message(companion: Any, msg: IncomingMessage) -> dict | None:
    processor = getattr(companion, "process_local_message_sync", None)
    if callable(processor):
        return await processor(msg)
    pipeline = getattr(companion, "pipeline", None)
    handler = getattr(pipeline, "handle", None)
    if not callable(handler):
        return None
    return await handler(msg, force_full=True)


@app.post("/api/chat/send")
async def chat_send(request: Request):
    body = await request.json()
    raw_text = body.get("text")
    if raw_text is None:
        raw_text = body.get("content")
    text = raw_text if isinstance(raw_text, str) else ""
    attachments = body.get("attachments") or []

    comp = get_companion()
    if not comp:
        return JSONResponse({"error": "backend not ready"}, status_code=503)

    try:
        reply_to_id = int(body.get("reply_to_id", 0) or 0)
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid_message"}, status_code=400)

    if _chat_request_queue_requested(comp):
        service, error = _chat_request_service_or_error(comp)
        if error is not None:
            return error
        try:
            view = service.submit(
                text=text,
                attachments=attachments,
                reply_to_id=reply_to_id,
                user_id=body.get("user_id"),
            )
        except (
            InvalidChatInput,
            QueueUnavailable,
            RequestConflict,
            RequestNotFound,
        ) as exc:
            return _chat_request_error_response(exc)
        return _chat_request_view_response(view, status_code=202)

    text = text.strip()
    if not text:
        return JSONResponse({"error": "empty_message"}, status_code=400)

    user_id = body.get("user_id")
    if user_id is None:
        user_id = _primary_user_id(comp)
        if user_id is None:
            return JSONResponse(
                {"error": "primary_identity_unconfigured"},
                status_code=409,
            )
    else:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "invalid_message"}, status_code=400)
    if user_id <= 0:
        return JSONResponse({"error": "invalid_user_id"}, status_code=400)
    if not getattr(comp, "pipeline", None):
        return JSONResponse({"error": "backend not ready"}, status_code=503)

    # Phase 4: quote + attachments

    # Block-3 R0.3: enrich attachments with extracted markdown (best-effort)
    if attachments:
        attachments = _trusted_chat_attachments(attachments)
        try:
            from core.attachment_handler import extract_markdown
            for att in attachments:
                if not isinstance(att, dict):
                    continue
                if att.get("attachmentId") or att.get("id"):
                    continue
                url = att.get("url") or ""
                fname = url.lstrip("/").split("/")[-1]
                if not fname or "/" in fname or ".." in fname:
                    continue
                # Block-3: path-traversal guard
                from pathlib import Path as _Path
                upload_path = _Path(UPLOAD_DIR) / fname
                if not upload_path.exists() or not upload_path.is_file():
                    continue
                md = extract_markdown(upload_path, upload_base=UPLOAD_DIR)
                if md:
                    att["markdown"] = md
        except Exception as _e:
            logger.debug("attachment md extraction failed: %s", _e)

    msg = IncomingMessage.from_local(
        text, user_id, reply_to_id=reply_to_id, attachments=attachments
    )
    result = await _process_local_message(comp, msg)
    if not result:
        return {"reply": "(已收到)", "status": "ok"}

    response = {
        "reply": result.get("reply", ""),
        "user_msg_id": result.get("user_msg_id", 0),
        "ai_msg_id": result.get("ai_msg_id", 0),
        "reply_to_id": reply_to_id,
        "status": "ok",
        "persisted": result.get("persisted", True),
    }
    if result.get("persist_error"):
        response["persist_error"] = result["persist_error"]
    return response


def _request_endpoint_service():
    comp = get_companion()
    if not comp:
        return None, JSONResponse({"error": "backend not ready"}, status_code=503)
    service, error = _chat_request_service_or_error(comp)
    if error is not None:
        return None, error
    return service, None


@app.get("/api/chat/requests/{request_id}")
async def chat_request_get(
    request_id: str,
    user_id: int | None = Query(default=None),
):
    service, error = _request_endpoint_service()
    if error is not None:
        return error
    try:
        view = service.get(request_id=request_id, user_id=user_id)
    except (
        InvalidChatInput,
        QueueUnavailable,
        RequestConflict,
        RequestNotFound,
    ) as exc:
        return _chat_request_error_response(exc)
    return _chat_request_view_response(view)


@app.post("/api/chat/requests/{request_id}/cancel")
async def chat_request_cancel(
    request_id: str,
    user_id: int | None = Query(default=None),
):
    service, error = _request_endpoint_service()
    if error is not None:
        return error
    try:
        view = await service.cancel(request_id=request_id, user_id=user_id)
    except (
        InvalidChatInput,
        QueueUnavailable,
        RequestConflict,
        RequestNotFound,
    ) as exc:
        return _chat_request_error_response(exc)
    return _chat_request_view_response(view)


@app.post("/api/chat/requests/{request_id}/retry")
async def chat_request_retry(
    request_id: str,
    user_id: int | None = Query(default=None),
):
    service, error = _request_endpoint_service()
    if error is not None:
        return error
    try:
        view = service.retry(request_id=request_id, user_id=user_id)
    except (
        InvalidChatInput,
        QueueUnavailable,
        RequestConflict,
        RequestNotFound,
    ) as exc:
        return _chat_request_error_response(exc)
    return _chat_request_view_response(view, status_code=202)


@app.get("/api/chat/history/page")
async def chat_history_page(
    user_id: int | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=128),
    direction: str = Query(default="older", pattern="^(older|newer)$"),
    limit: int = Query(default=50, ge=1, le=200),
    conversation_id: str | None = Query(default=None, max_length=128),
) -> Response:
    companion = get_companion()
    if companion is None:
        return JSONResponse({"error": "backend_not_ready"}, status_code=503)
    if user_id is None:
        user_id = _primary_user_id(companion)
        if user_id is None:
            return JSONResponse(
                {"error": "primary_identity_unconfigured"},
                status_code=409,
            )
    if user_id <= 0:
        return JSONResponse({"error": "invalid_user_id"}, status_code=400)

    identity = companion.identity_resolver.resolve("desktop", "local")
    try:
        # 角色级隔离：历史分页同样按激活角色过滤（persona_id 未传时
        # history_page 内部退化为不过滤，此处显式传入保持全链一致）
        from core.conversation_repository import active_persona_id

        page_result = companion.conversation_repository.history_page(
            actor_id=identity.actor_id,
            channel="desktop",
            channel_account_id="local",
            user_id=int(user_id),
            conversation_id=conversation_id,
            cursor=cursor,
            direction=direction,
            limit=limit,
            persona_id=active_persona_id(),
        )
    except Exception as exc:
        from core.conversation_repository import InvalidHistoryCursor

        if isinstance(exc, InvalidHistoryCursor):
            return JSONResponse({"error": "invalid_cursor"}, status_code=400)
        logger.exception("chat history page failed")
        return JSONResponse({"error": "history_unavailable"}, status_code=500)
    _hydrate_desktop_attachment_records(page_result.get("items") or [])
    return JSONResponse({"primaryUserId": int(user_id), **page_result})


@app.get("/api/chat/history")
async def chat_history(
    user_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    try:
        if user_id is not None and user_id <= 0:
            return JSONResponse({"error": "invalid_user_id"}, status_code=400)
        where = (
            " WHERE user_id = ? AND deleted_at IS NULL"
            if user_id is not None
            else " WHERE deleted_at IS NULL"
        )
        params = (user_id,) if user_id is not None else ()
        # 角色隔离：active persona 非 None 时只看 persona + NULL 共享行
        from core.conversation_repository import active_persona_id

        persona = active_persona_id()
        if user_id is not None and persona:
            where += " AND (persona_id = ? OR persona_id IS NULL)"
            params += (persona,)
        count = _db.query_one(f"SELECT COUNT(*) AS cnt FROM chat_log{where}", params)
        rows = _db.query(
            f"SELECT * FROM chat_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + (limit, (page - 1) * limit),
        )
        rows.reverse()
        import json as _json
        for row in rows:
            if row.get("attachments"):
                try:
                    row["attachments"] = _json.loads(row["attachments"])
                except Exception:
                    row["attachments"] = []
            else:
                row["attachments"] = []
            if not row.get("ts"):
                row["ts"] = row.get("created_at")
        _hydrate_desktop_attachment_records(rows)
        return {
            "history": rows,
            "total": int(count["cnt"] if count else 0),
            "page": page,
            "limit": limit,
            "user_id": user_id,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/chat/poll")
async def chat_poll(
    user_id: int | None = Query(default=None),
    since_id: int = Query(default=0),
) -> dict:
    if user_id is None:
        companion = get_companion()
        user_id = _primary_user_id(companion) if companion is not None else None
        if user_id is None:
            return JSONResponse(
                {"error": "primary_identity_unconfigured"},
                status_code=409,
            )
    if user_id <= 0:
        return JSONResponse({"error": "invalid_user_id"}, status_code=400)
    try:
        # 角色隔离：active persona 非 None 时只看 persona + NULL 共享行
        from core.conversation_repository import active_persona_id

        persona = active_persona_id()
        if persona:
            rows = _db.query(
                "SELECT * FROM chat_log WHERE user_id = ? AND id > ? "
                "AND deleted_at IS NULL "
                "AND (persona_id = ? OR persona_id IS NULL) ORDER BY id",
                (user_id, since_id, persona),
            )
        else:
            rows = _db.query(
                "SELECT * FROM chat_log WHERE user_id = ? AND id > ? "
                "AND deleted_at IS NULL ORDER BY id",
                (user_id, since_id),
            )
        import json as _json
        for row in rows:
            if row.get("attachments"):
                try:
                    row["attachments"] = _json.loads(row["attachments"])
                except Exception:
                    row["attachments"] = []
            else:
                row["attachments"] = []
            if not row.get("ts"):
                row["ts"] = row.get("created_at")
        _hydrate_desktop_attachment_records(rows)
        return {"items": rows, "user_id": user_id}
    except Exception as e:
        return {"items": [], "error": str(e)}


# ── NapCat ─────────────────────────────────────────

@app.get("/api/napcat/status")
async def napcat_status() -> dict:
    launcher = get_launcher()
    return launcher.get_status()


@app.post("/api/napcat/start")
async def napcat_start() -> dict:
    launcher = get_launcher()
    return await launcher.start()


@app.post("/api/napcat/stop")
async def napcat_stop() -> dict:
    launcher = get_launcher()
    return await launcher.stop()


@app.get("/api/napcat/logs")
async def napcat_logs(limit: int = Query(default=50)) -> dict:
    launcher = get_launcher()
    return {"logs": launcher.get_logs(limit)}


@app.get("/api/napcat/qrcode")
async def napcat_qrcode() -> Response:
    launcher = get_launcher()
    data = launcher.read_qrcode()
    if data is None:
        return JSONResponse({"error": "no QR code available"}, status_code=404)
    return Response(content=data, media_type="image/png")


@app.post("/api/napcat/download")
async def napcat_download() -> dict:
    """触发 NapCat 一键下载（后台线程执行，前端轮询 status）。"""
    from core.napcat_downloader import get_downloader

    downloader = get_downloader()
    if downloader.is_running():
        return {"ok": False, "message": "NapCat 正在下载中", "error_code": "already_running"}
    asyncio.create_task(asyncio.to_thread(downloader.download_and_extract))
    return {"ok": True, "message": "下载任务已启动"}


@app.get("/api/napcat/download/status")
async def napcat_download_status() -> dict:
    from core.napcat_downloader import get_downloader

    return get_downloader().status()


@app.get("/api/napcat/update/check")
async def napcat_update_check() -> dict:
    from core.napcat_downloader import get_downloader

    return await asyncio.to_thread(get_downloader().check_update)


@app.get("/api/ilink/status")
async def ilink_status() -> dict:
    comp = get_companion()
    gateway = getattr(comp, "ilink_gateway", None) if comp else None
    if gateway is None:
        return {
            "phase": "disabled",
            "configured": False,
            "connected": False,
            "error_code": "backend_not_ready",
        }
    return gateway.get_status()


@app.post("/api/ilink/start")
async def ilink_start() -> dict:
    comp = get_companion()
    gateway = getattr(comp, "ilink_gateway", None) if comp else None
    if gateway is None:
        return await ilink_status()
    try:
        await gateway.start()
    except RuntimeError:
        return gateway.get_status()
    return gateway.get_status()


@app.post("/api/ilink/stop")
async def ilink_stop() -> dict:
    comp = get_companion()
    gateway = getattr(comp, "ilink_gateway", None) if comp else None
    if gateway is None:
        return await ilink_status()
    await gateway.stop()
    return gateway.get_status()


# ── Emotion ─────────────────────────────────────────

@app.get("/api/emotion/state")
async def emotion_state(user_id: int | None = None) -> dict:
    comp = get_companion()
    if not comp:
        return {"error": "backend not ready"}
    if user_id is None:
        return comp.get_primary_emotion_state()
    identity = comp.identity_resolver.resolve("qq", str(user_id))
    state = dict(comp.emotion.get_state(
        user_id,
        actor_id=identity.actor_id,
    ))
    state["primaryUserId"] = int(user_id)
    state.update(comp.state_store.freshness_metadata(
        user_id,
        actor_id=identity.actor_id,
        sampled_at=getattr(comp, "_emotion_last_sampled_at", None),
    ))
    return state


# ── Phase 4: Static file serving for uploads ────────────────

def _desktop_attachment_service():
    global _desktop_attachment_service_instance, _desktop_attachment_service_key
    companion = get_companion()
    companion_attributes = getattr(companion, "__dict__", {})
    if not isinstance(companion_attributes, dict):
        companion_attributes = {}
    owned_service = companion_attributes.get("desktop_attachment_service")
    if owned_service is not None:
        return owned_service

    database = companion_attributes.get("db") or _db
    from core.paths import data_dir

    configured_root = os.getenv("AERIE_DESKTOP_ATTACHMENT_ROOT", "").strip()
    if not configured_root:
        configured_root = os.getenv("AERIE_DESKTOP_ATTACHMENT_DIR", "").strip()
    storage_root = (
        Path(configured_root).expanduser().resolve()
        if configured_root
        else (data_dir() / "desktop_attachments").resolve()
    )
    cache_key = (id(database), str(storage_root))
    if (
        _desktop_attachment_service_instance is None
        or _desktop_attachment_service_key != cache_key
    ):
        from core.desktop_attachments import DesktopAttachmentService

        _desktop_attachment_service_instance = DesktopAttachmentService(
            database,
            storage_root=storage_root,
        )
        _desktop_attachment_service_key = cache_key
    return _desktop_attachment_service_instance


def _hydrate_desktop_attachment_records(items: list[dict[str, Any]]) -> None:
    service = _desktop_attachment_service()
    for item in items:
        attachments = item.get("attachments")
        if not isinstance(attachments, list):
            item["attachments"] = []
            continue
        hydrated: list[dict[str, Any]] = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            attachment_id = attachment.get("attachmentId") or attachment.get("id")
            public = service.public_record(str(attachment_id)) if attachment_id else None
            hydrated.append(public or attachment)
        item["attachments"] = hydrated


def _schedule_attachment_processing(service: Any, attachment_id: str) -> None:
    async def _run() -> None:
        try:
            await asyncio.to_thread(service.process, attachment_id)
        except Exception:
            logger.warning(
                "desktop attachment processing failed for %s",
                attachment_id,
                exc_info=True,
            )

    task = asyncio.create_task(_run())
    _attachment_processing_tasks.add(task)
    task.add_done_callback(_attachment_processing_tasks.discard)


@app.get("/api/attachments/capabilities")
async def desktop_attachment_capabilities() -> dict[str, Any]:
    from core.desktop_attachments import attachment_capabilities_payload

    return attachment_capabilities_payload()


@app.post("/api/attachments")
async def desktop_attachment_upload(file: UploadFile = File(...)) -> Response:
    from core.desktop_attachments import MAX_FILE_BYTES

    service = _desktop_attachment_service()
    incoming_root = service.storage_root / "incoming"
    incoming_root.mkdir(parents=True, exist_ok=True)
    temporary = incoming_root / f"upload-{os.getpid()}-{time.time_ns()}.part"
    total = 0
    try:
        with temporary.open("xb") as stream:
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_FILE_BYTES:
                    return JSONResponse(
                        {"error": "file_too_large", "maxFileBytes": MAX_FILE_BYTES},
                        status_code=413,
                    )
                stream.write(block)
        if total == 0:
            return JSONResponse({"error": "empty_file"}, status_code=400)
        record = service.ingest(
            temporary,
            original_name=file.filename or "attachment.bin",
            mime_type=file.content_type or "application/octet-stream",
        )
    except (OSError, ValueError) as exc:
        return JSONResponse(
            {"error": "invalid_attachment", "detail": str(exc)[:200]},
            status_code=400,
        )
    finally:
        await file.close()
        try:
            temporary.unlink()
        except OSError:
            pass
    if record["state"] == "queued":
        _schedule_attachment_processing(service, record["attachment_id"])
    return JSONResponse(
        {"attachment": service.public_record(record["attachment_id"])},
        status_code=202 if record["state"] == "queued" else 200,
    )


@app.get("/api/attachments/{attachment_id}")
async def desktop_attachment_get(attachment_id: str) -> Response:
    record = _desktop_attachment_service().public_record(attachment_id)
    if record is None:
        return JSONResponse({"error": "attachment_not_found"}, status_code=404)
    return JSONResponse({"attachment": record})


@app.post("/api/attachments/{attachment_id}/retry")
async def desktop_attachment_retry(attachment_id: str) -> Response:
    from core.desktop_attachments import AttachmentStateConflict

    service = _desktop_attachment_service()
    record = service.repository.get(attachment_id)
    if record is None:
        return JSONResponse({"error": "attachment_not_found"}, status_code=404)
    try:
        queued = service.repository.transition(attachment_id, "queued")
    except AttachmentStateConflict as exc:
        return JSONResponse(
            {"error": "attachment_state_conflict", "detail": str(exc)},
            status_code=409,
        )
    _schedule_attachment_processing(service, attachment_id)
    return JSONResponse(
        {"attachment": service._public(queued)},
        status_code=202,
    )


@app.delete("/api/attachments/{attachment_id}")
async def desktop_attachment_delete(attachment_id: str) -> Response:
    from core.desktop_attachments import AttachmentStateConflict

    service = _desktop_attachment_service()
    try:
        removed = service.remove(attachment_id)
    except AttachmentStateConflict as exc:
        return JSONResponse(
            {"error": "attachment_state_conflict", "detail": str(exc)},
            status_code=409,
        )
    if not removed:
        return JSONResponse({"error": "attachment_not_found"}, status_code=404)
    return Response(status_code=204)


@app.get("/api/attachments/{attachment_id}/download")
async def desktop_attachment_download(attachment_id: str) -> Response:
    from core.desktop_attachments import AttachmentStateConflict

    service = _desktop_attachment_service()
    record = service.public_record(attachment_id)
    if record is None:
        return JSONResponse({"error": "attachment_not_found"}, status_code=404)
    try:
        download_path, filename = service.download_path(attachment_id)
    except AttachmentStateConflict as exc:
        return JSONResponse(
            {"error": "attachment_not_ready", "detail": str(exc)},
            status_code=409,
        )
    return FileResponse(
        str(download_path),
        filename=filename,
        media_type=record.get("contentType") or "application/octet-stream",
    )


@app.get("/uploads/{filename:path}")
async def serve_upload(filename: str):
    """Serve uploaded files. Restricts to uploads/ directory (no traversal)."""
    target = _resolve_upload_target(filename)
    if target is None:
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target))


# ── Phase 4: Recall ─────────────────────────────────────────


# ── Upload ───────────────────────────────────────────

UPLOAD_DIR = "uploads"
ALLOWED_TYPES = {
    # Block-3 R0.3: full office + document coverage
    # images
    "image/png", "image/jpeg", "image/gif", "image/webp",
    # plain text / data
    "text/plain", "text/html", "text/csv", "text/xml", "application/json", "application/xml",
    # pdf + office (markitdown covers all of these)
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    "application/msword",                                                          # .doc
    "application/vnd.ms-excel",                                                    # .xls
    "application/vnd.ms-powerpoint",                                               # .ppt
    "application/epub+zip",                                                        # .epub
    "application/rtf", "application/vnd.oasis.opendocument.text",                  # .odt (markitdown via)
}
MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB
IMAGE_UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _upload_root() -> Path:
    return Path(UPLOAD_DIR).resolve()


def _resolve_upload_target(filename: str) -> Path | None:
    """Resolve an uploads-relative path without allowing traversal."""
    if not filename or "\\" in filename or "\x00" in filename:
        return None
    base = _upload_root()
    try:
        target = (base / filename).resolve()
    except OSError:
        return None
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def _image_assets_enabled() -> bool:
    try:
        return FeatureFlags().is_enabled("image_assets_v1")
    except Exception:
        logger.exception("failed to read image_assets_v1 feature flag")
        return False


def _is_image_upload(filename: str, content_type: str | None) -> bool:
    suffix = Path(filename or "").suffix.lower()
    return suffix in IMAGE_UPLOAD_EXTS or str(content_type or "").lower().startswith("image/")


def _build_image_workflow():
    from core.image_service import (
        LLMCallerImageGenerationProvider,
        LLMCallerImageVisionProvider,
        ImageWorkflow,
    )

    brain = getattr(get_companion(), "brain", None)
    return ImageWorkflow(
        upload_base=_upload_root(),
        feature_enabled=_image_assets_enabled(),
        generation_provider=LLMCallerImageGenerationProvider(brain),
        vision_provider=LLMCallerImageVisionProvider(brain),
    )


def _image_workflow_error_response(exc: Exception) -> JSONResponse:
    status_code = int(getattr(exc, "status_code", 500) or 500)
    code = str(getattr(exc, "code", "image_workflow_error"))
    message = str(getattr(exc, "public_message", "image workflow failed"))
    return JSONResponse({"error": message, "code": code}, status_code=status_code)


async def _read_json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise ValueError("invalid json") from None
    if not isinstance(body, dict):
        raise ValueError("body must be a dict")
    return body


@app.post("/api/upload")
async def upload_file(request: Request) -> dict:
    """Upload a file to the uploads directory.

    Returns metadata (filename, size, content_type, url) on success.
    Enforces an allow-list of content types and a max size cap.
    """
    try:
        form = await request.form()
        file = form.get("file")
        if not file or not file.filename:
            return JSONResponse({"error": "no file provided"}, status_code=400)
        if file.content_type not in ALLOWED_TYPES:
            return JSONResponse(
                {"error": f"unsupported type: {file.content_type}"},
                status_code=415,
            )

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            return JSONResponse(
                {"error": f"file too large (>{MAX_UPLOAD_SIZE} bytes)"},
                status_code=413,
            )

        import uuid

        if _image_assets_enabled() and _is_image_upload(file.filename, file.content_type):
            try:
                from core.attachment_handler import process_image_upload

                return process_image_upload(
                    filename=file.filename,
                    content=content,
                    content_type=file.content_type or "",
                    upload_base=_upload_root(),
                )
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except RuntimeError as e:
                return JSONResponse({"error": str(e)}, status_code=503)

        upload_path = _upload_root()
        upload_path.mkdir(parents=True, exist_ok=True)

        ext = Path(file.filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        dest = upload_path / unique_name
        dest.write_bytes(content)

        return {
            "status": "ok",
            "filename": file.filename,
            "saved_as": unique_name,
            "size": len(content),
            "content_type": file.content_type,
            "url": f"/uploads/{unique_name}",
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/upload/types")
async def upload_types() -> dict:
    """Return upload configuration (directory + allowed types + size cap)."""
    return {
        "upload_dir": UPLOAD_DIR,
        "allowed_types": sorted(ALLOWED_TYPES),
        "max_size_bytes": MAX_UPLOAD_SIZE,
    }


@app.post("/api/upload/gc")
async def upload_gc(request: Request) -> dict:
    """Scan image assets, report or delete orphaned files."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a dict"}, status_code=400)

    dry_run = bool(body.get("dry_run", True))
    min_age_hours = body.get("min_age_hours", 24)
    try:
        min_age_seconds = int(float(min_age_hours) * 3600)
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid min_age_hours"}, status_code=400)
    if min_age_seconds < 0:
        return JSONResponse({"error": "min_age_hours must be non-negative"}, status_code=400)

    try:
        from core.attachment_handler import gc_image_assets

        result = gc_image_assets(
            _db,
            upload_base=_upload_root(),
            dry_run=dry_run,
            min_age_seconds=min_age_seconds,
        )
    except Exception as e:
        logger.exception("image asset GC failed")
        return JSONResponse({"error": str(e)}, status_code=500)

    emit(
        "image_assets_gc",
        dry_run=dry_run,
        orphan_count=result.get("orphan_count", 0),
        deleted_count=result.get("deleted_count", 0),
    )
    return result


@app.post("/api/images/generate")
async def image_generate(request: Request) -> dict:
    """Run the Phase 10 auditable image generation workflow."""
    try:
        body = await _read_json_object(request)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    try:
        workflow = _build_image_workflow()
        result = workflow.generate_image(
            prompt=str(body.get("prompt") or ""),
            idempotency_key=str(body.get("idempotency_key") or ""),
            owner_id=str(body.get("owner_id") or "master"),
            delivery=body.get("delivery") if isinstance(body.get("delivery"), dict) else None,
            conversation_id=(
                str(body.get("conversation_id"))
                if body.get("conversation_id") is not None
                else None
            ),
        )
    except Exception as e:
        try:
            from core.image_service import ImageWorkflowError
        except Exception:  # pragma: no cover - import failure fallback
            ImageWorkflowError = ()  # type: ignore[assignment]
        if isinstance(e, ImageWorkflowError):
            return _image_workflow_error_response(e)
        logger.exception("image generation workflow failed")
        return JSONResponse(
            {"error": "image workflow failed", "code": "image_workflow_error"},
            status_code=500,
        )

    emit(
        "image_generation_workflow",
        request_id=result.get("request_id", ""),
        status=result.get("status", ""),
        delivery_created=bool((result.get("side_effects") or {}).get("delivery_created")),
    )
    return result


@app.post("/api/images/edit")
async def image_edit(request: Request) -> dict:
    """Run the Phase 10 auditable image-to-image (图生图) workflow.

    ``reference`` accepts an upload path (``uploads/...``) or the token
    ``three_view:front`` which resolves to the active persona's front
    three-view reference image — the minimal path for using the 三视图
    to lock the character's appearance during image editing.
    """
    try:
        body = await _read_json_object(request)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    reference = body.get("reference") if isinstance(body.get("reference"), list) else None
    if not reference:
        single = str(body.get("reference") or body.get("image_ref") or "")
        reference = [single] if single else None
    if not reference:
        return JSONResponse({"error": "reference is required"}, status_code=400)

    try:
        workflow = _build_image_workflow()
        result = workflow.generate_image_edit(
            prompt=str(body.get("prompt") or ""),
            reference_assets=[str(r) for r in reference],
            idempotency_key=str(body.get("idempotency_key") or ""),
            owner_id=str(body.get("owner_id") or "master"),
            delivery=body.get("delivery") if isinstance(body.get("delivery"), dict) else None,
            conversation_id=(
                str(body.get("conversation_id"))
                if body.get("conversation_id") is not None
                else None
            ),
        )
    except Exception as e:
        try:
            from core.image_service import ImageWorkflowError
        except Exception:  # pragma: no cover - import failure fallback
            ImageWorkflowError = ()  # type: ignore[assignment]
        if isinstance(e, ImageWorkflowError):
            return _image_workflow_error_response(e)
        logger.exception("image edit workflow failed")
        return JSONResponse(
            {"error": "image workflow failed", "code": "image_workflow_error"},
            status_code=500,
        )

    emit(
        "image_edit_workflow",
        request_id=result.get("request_id", ""),
        status=result.get("status", ""),
    )
    return result


@app.post("/api/images/vision")
async def image_vision(request: Request) -> dict:
    """Run the Phase 10 auditable image understanding workflow."""
    try:
        body = await _read_json_object(request)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    try:
        workflow = _build_image_workflow()
        result = workflow.understand_image(
            image_ref=str(body.get("image_ref") or body.get("url") or ""),
            question=str(body.get("question") or "describe"),
            idempotency_key=str(body.get("idempotency_key") or ""),
            owner_id=str(body.get("owner_id") or "master"),
        )
    except Exception as e:
        try:
            from core.image_service import ImageWorkflowError
        except Exception:  # pragma: no cover - import failure fallback
            ImageWorkflowError = ()  # type: ignore[assignment]
        if isinstance(e, ImageWorkflowError):
            return _image_workflow_error_response(e)
        logger.exception("image vision workflow failed")
        return JSONResponse(
            {"error": "image workflow failed", "code": "image_workflow_error"},
            status_code=500,
        )

    emit(
        "image_vision_workflow",
        request_id=result.get("request_id", ""),
        status=result.get("status", ""),
    )
    return result


# ── Audio Transcription (Domestic ASR) ─────────────

@app.get("/api/audio/status")
async def audio_transcribe_status() -> dict:
    """Check if audio transcription is available and list configured providers."""
    transcriber = _get_audio_transcriber()
    return {
        "available": transcriber.is_available,
        "providers": transcriber.providers,
        "has_local": transcriber._local_model is not None,
    }


@app.post("/api/audio/transcribe")
async def audio_transcribe(
    file: UploadFile = File(...),
    language: str = Query("zh", description="Language code: zh, en, auto"),
) -> dict:
    """Transcribe audio to text using domestic ASR providers.

    Uses Whisper-compatible APIs with automatic fallback across
    configured providers (SiliconFlow, Qwen, Doubao, DeepSeek, etc.).
    """
    import uuid
    import tempfile
    from pathlib import Path

    transcriber = _get_audio_transcriber()
    if not transcriber.is_available:
        return JSONResponse({
            "status": "error",
            "error": "No ASR provider available. Configure an API key in settings.",
        }, status_code=503)

    try:
        content = await file.read()
        if not content:
            return JSONResponse({
                "status": "error",
                "error": "Empty audio file",
            }, status_code=400)

        if len(content) > 25 * 1024 * 1024:
            return JSONResponse({
                "status": "error",
                "error": "Audio file too large (max 25MB)",
            }, status_code=413)

        suffix = Path(file.filename or "audio.webm").suffix.lower()
        if not suffix:
            suffix = ".webm"
        allowed_suffixes = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".webm", ".mp4", ".wma", ".opus"}
        if suffix not in allowed_suffixes:
            suffix = ".webm"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            logger.info("AudioTranscribe: received file %s, size=%d bytes, suffix=%s", file.filename, len(content), suffix)
            
            if suffix in (".webm", ".ogg", ".opus", ".mp4", ".m4a", ".aac", ".wma"):
                try:
                    import av
                    import numpy as np
                    import soundfile as sf
                    wav_path = tmp_path.replace(suffix, ".wav")
                    container = av.open(tmp_path)
                    audio_frames = []
                    for frame in container.decode(audio=0):
                        arr = frame.to_ndarray()
                        if arr.ndim > 1:
                            arr = arr.mean(axis=0)
                        audio_frames.append(arr)
                    logger.info("AudioTranscribe: PyAV decoded %d frames", len(audio_frames))
                    if audio_frames:
                        max_len = max(len(f) for f in audio_frames)
                        padded = []
                        for f in audio_frames:
                            if len(f) < max_len:
                                f = np.pad(f, (0, max_len - len(f)))
                            padded.append(f)
                        data = np.concatenate(padded)
                        sr = container.streams.audio[0].rate
                        max_val = np.max(np.abs(data))
                        if max_val > 0.001:
                            data = data / max_val
                        else:
                            logger.info("AudioTranscribe: audio is mostly silent (max_val=%f), skipping normalization", max_val)
                        logger.info("AudioTranscribe: decoded data shape=%s, sr=%d, max=%f, min=%f (after normalization)", data.shape, sr, np.max(data), np.min(data))
                        sf.write(wav_path, data, sr)
                        tmp_path = wav_path
                        logger.info("AudioTranscribe: converted to WAV, size=%d bytes", Path(wav_path).stat().st_size)
                    container.close()
                except Exception as e:
                    logger.warning("Failed to convert audio to WAV using PyAV: %s", e)

            text = await transcriber.transcribe(tmp_path, language=language)
            logger.info("AudioTranscribe: transcription result: '%s'", text)
            return {
                "status": "ok",
                "text": text,
                "language": language,
                "duration_estimate": round(len(content) / 16000, 2),
            }
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
            try:
                if wav_path and wav_path != tmp_path:
                    Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass

    except Exception as e:
        logger.exception("Audio transcription failed")
        return JSONResponse({
            "status": "error",
            "error": str(e),
        }, status_code=500)

class _RecallRecord:
    """轻量撤回记录 (喂给 RecallAdapter)."""
    __slots__ = ("msg_id", "qq_message_id")
    def __init__(self, msg_id: int, qq_message_id) -> None:
        self.msg_id = msg_id
        self.qq_message_id = qq_message_id


@app.post("/api/chat/recall/{msg_id}")
async def chat_recall(msg_id: int) -> dict:
    """Recall a chat message. Marks DB + syncs to QQ via NapCat delete_msg.

    Rules:
      - User can recall own messages within recall window
      - Assistant messages go through RecallManager (which enforces persona limits)
    """
    comp = get_companion()
    if not comp:
        return JSONResponse({"error": "backend not ready"}, status_code=503)

    row = _db.query_one(
        "SELECT id, user_id, role, created_at, is_recalled, msg_type, qq_message_id FROM chat_log WHERE id = ?",
        (msg_id,),
    )
    if not row:
        return JSONResponse({"error": "message not found"}, status_code=404)
    if row["is_recalled"]:
        return {"status": "already_recalled", "id": msg_id}

    # Check recall window (2 minutes default)
    from datetime import datetime as _dt
    try:
        created = _dt.fromisoformat(row["created_at"])
        age = (_dt.now() - created).total_seconds()
    except Exception:
        age = 0
    if age > 120:
        return JSONResponse({"error": "recall window expired"}, status_code=400)

    # Update DB
    _db.update(
        "chat_log",
        {
            "is_recalled": 1,
            "recalled_at": _dt.now().isoformat(timespec="seconds"),
            "msg_state": "recalled",
        },
        "id = ?",
        (msg_id,),
    )

    # If assistant message and has QQ id, recall via QQ
    qq_recalled = False
    if row["role"] == "assistant":
        # 按 channel 分派真实撤回 (QQ → NapCat delete_msg, local → 本地标记)
        channel = row.get("channel") or ("qq" if row.get("qq_message_id") else "local")
        try:
            from communication.recall.factory import get_recall_adapter
            adapter = get_recall_adapter(channel, qq_client=getattr(comp, "qq", None))
            outcome = await adapter.recall(
                _RecallRecord(msg_id=msg_id, qq_message_id=row.get("qq_message_id"))
            )
            qq_recalled = bool(outcome.recalled and not adapter.local_mark_only())
        except Exception:
            pass

    # Emit IPC event
    emit("recall", id=msg_id, user_id=row["user_id"], role=row["role"])

    return {"status": "ok", "id": msg_id, "qq_recalled": qq_recalled}


@app.get("/api/chat/recall_status/{msg_id}")
async def chat_recall_status(msg_id: int) -> dict:
    """Check whether a message has been recalled."""
    row = _db.query_one(
        "SELECT id, is_recalled, recalled_at FROM chat_log WHERE id = ?",
        (msg_id,),
    )
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "id": row["id"],
        "is_recalled": bool(row["is_recalled"]),
        "recalled_at": row.get("recalled_at"),
    }


# ── Tools ───────────────────────────────────────────

@app.get("/api/tools/list")
async def tools_list() -> dict:
    comp = get_companion()
    if not comp:
        return {"tools": [], "error": "backend not ready"}
    schema = comp.tool_registry.get_openai_schema()
    return {"tools": schema, "count": len(schema)}


# ── Stats ───────────────────────────────────────────

@app.get("/api/emotion/thresholds")
async def emotion_thresholds() -> dict:
    """Return 4-slot cumulative threshold values."""
    comp = get_companion()
    if not comp:
        return {"error": "backend not ready"}
    return {
        "thresholds": comp.emotion.threshold_engine.get_slots_summary(),
        "panel": comp.emotion.threshold_engine.get_panel_text(),
    }


# ── Phase 9: SSE + cognition + emotion history ────

@app.get("/api/events/stream")
async def events_stream(request: Request):
    """Server-Sent Events stream of all chat events.

    Yields lines of ``data: {json}\\n\\n`` for every event emitted by
    the pipeline (user / assistant / recall / cognition_stage /
    cognition_committed / decision_made). Includes a 15s heartbeat
    comment to keep the connection alive through proxies.
    """
    stream_kwargs: dict[str, Any] = {}
    try:
        stream_v1 = FeatureFlags().is_enabled("chat_stream_v1")
    except Exception:
        stream_v1 = False
    if stream_v1:
        last_event_id = (
            request.headers.get("last-event-id")
            or request.query_params.get("last_event_id")
            or request.query_params.get("lastEventId")
        )
        stream_kwargs = {
            "last_event_id": last_event_id,
            "replay": True,
            "include_event_id": True,
        }

    async def gen():
        async for line in event_stream_generator(**stream_kwargs):
            if await request.is_disconnected():
                break
            yield line
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/cognition/recent")
async def cognition_recent(
    user_id: int | None = None,
    source: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    """Recent cognition traces (lightweight summary list)."""
    eng = CognitionEngine(_db)
    data: dict = {"traces": eng.recent(user_id=user_id, source=source, limit=limit)}
    # P4: 候选决策证据日志（伪主观性"她选了哪个候选"）附加返回最新 30 条。
    try:
        from core.decision_log import DecisionLogger
        from core.paths import data_dir

        data["decision_log"] = DecisionLogger(log_dir=data_dir()).recent(limit=30)
    except Exception:
        data["decision_log"] = []
    return data


@app.get("/api/stats/dashboard")
async def stats_dashboard(
    window: str = Query(default="7d", pattern="^(24h|7d|30d)$"),
) -> dict:
    """数据统计看板聚合端点（token/高频话题/决策统计）。"""
    try:
        from core.paths import data_dir
        from core.stats_service import StatsService

        svc = StatsService(db=_db, decision_log_dir=data_dir())
        return svc.dashboard(window=window)
    except Exception:
        logger.exception("stats dashboard failed")
        return {"error": "stats unavailable"}


# ── P4b 后台管理平台（§3.5.2） ───────────────────────────
# 访问控制：服务端门闩（runtime_config.admin_unlocked）+ 随机 token 头。
# Electron 管理窗口经 main 进程注入 token；浏览器端 unlock 后携 token 直连。
_admin_service_instance = None
_admin_purge_task: asyncio.Task | None = None

# 管理 API 的合法 Origin 白名单：Electron file:// 渲染、同源浏览器页、无 Origin 的内部调用。
# 拒绝任意网页（http/https Origin）跨源调用——防"访问恶意网站即解锁并清空本地数据"
# （CORS 通配只服务 Electron file://，不能把删除类端点暴露给公网页面）。
# 注：同源 POST 浏览器也会带 Origin（如 http://127.0.0.1:7890），须放行服务端自身 Origin。
_ALLOWED_ADMIN_ORIGINS = {"", "null", "file://", "app://"}


@app.middleware("http")
async def _admin_origin_guard(request: Request, call_next):
    if request.url.path.startswith("/api/admin/"):
        origin = (request.headers.get("origin") or "").strip()
        own_origin = f"{request.url.scheme}://{request.url.netloc}"
        if origin not in _ALLOWED_ADMIN_ORIGINS and origin != own_origin:
            return JSONResponse(
                {"error": "cross_origin_denied", "errorCode": "cross_origin_denied"},
                status_code=403,
            )
    return await call_next(request)


def _admin_service():
    global _admin_service_instance
    companion = get_companion()
    runtime_config = getattr(companion, "runtime_config_service", None) if companion else None
    # 启动早期可能 companion 未就绪 → 不缓存降级实例，待就绪后重建
    if _admin_service_instance is None or (
        _admin_service_instance._runtime_config is None and runtime_config is not None
    ):
        from core.admin_service import AdminService
        from core.paths import data_dir

        _admin_service_instance = AdminService(
            db=_db,
            data_dir=data_dir(),
            runtime_config=runtime_config,
            memory=getattr(companion, "memory", None) if companion else None,
        )
    return _admin_service_instance


def _require_admin(request: Request) -> bool:
    """管理 API 门闩：未解锁或 token 不符一律拒绝（无鉴权的管理 API = 数据毁灭级）。"""
    svc = _admin_service()
    if not svc.is_unlocked():
        return False
    token = request.headers.get("x-aerie-admin-token") or ""
    return svc.verify_token(token)


def _admin_denied() -> JSONResponse:
    return JSONResponse(
        {"error": "admin_locked", "errorCode": "admin_locked"},
        status_code=403,
    )


async def _admin_purge_loop() -> None:
    """每小时清理回收站过期数据（幂等，≤500/批），异步不阻塞请求。"""
    while True:
        try:
            _admin_service().purge_expired()
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("admin purge loop error")
            await asyncio.sleep(3600)


@app.on_event("startup")
async def _start_admin_purge() -> None:
    global _admin_purge_task
    if _admin_purge_task is None or _admin_purge_task.done():
        _admin_purge_task = asyncio.create_task(_admin_purge_loop())


@app.on_event("shutdown")
async def _stop_admin_purge() -> None:
    global _admin_purge_task
    if _admin_purge_task:
        _admin_purge_task.cancel()
        try:
            await _admin_purge_task
        except asyncio.CancelledError:
            pass
        _admin_purge_task = None


@app.post("/api/admin/unlock")
async def admin_unlock() -> dict:
    """置位服务端门闩并返回随机 token（浏览器端存入 sessionStorage）。"""
    token = _admin_service().unlock()
    return {"status": "ok", "token": token}


@app.post("/api/admin/lock")
async def admin_lock() -> dict:
    _admin_service().lock()
    return {"status": "ok"}


@app.get("/api/admin/status")
async def admin_status() -> dict:
    return {"unlocked": _admin_service().is_unlocked()}


@app.get("/api/admin/overview")
async def admin_overview(request: Request) -> Response:
    """概览 KPI 真实总量（会话/消息/记忆/回收站消息/审计）。"""
    if not _require_admin(request):
        return _admin_denied()
    return JSONResponse(_admin_service().overview())


@app.get("/api/admin/conversations")
async def admin_conversations(
    request: Request,
    channel: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    return JSONResponse(
        _admin_service().list_conversations(channel=channel, limit=limit, offset=offset)
    )


@app.get("/api/admin/conversations/{conversation_id}/messages")
async def admin_conversation_messages(
    request: Request,
    conversation_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    include_trashed: bool = Query(default=True),
) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    return JSONResponse(
        _admin_service().list_messages(
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
            include_trashed=include_trashed,
        )
    )


@app.put("/api/admin/messages/{message_id}")
async def admin_message_update(request: Request, message_id: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json", "errorCode": "invalid_json"}, status_code=400)
    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, str) or not content.strip():
        return JSONResponse({"error": "invalid_content", "errorCode": "invalid_content"}, status_code=400)
    row = _admin_service().update_message(message_id, content)
    if not row:
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse(row)


@app.delete("/api/admin/messages/{message_id}")
async def admin_message_delete(request: Request, message_id: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    if not _admin_service().trash_message(message_id):
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/messages/{message_id}/restore")
async def admin_message_restore(request: Request, message_id: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    if not _admin_service().restore_message(message_id):
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/conversations/trash")
async def admin_conversations_trash(request: Request) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json", "errorCode": "invalid_json"}, status_code=400)
    ids = body.get("conversation_ids") if isinstance(body, dict) else None
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "invalid_ids", "errorCode": "invalid_ids"}, status_code=400)
    return JSONResponse({"status": "ok", **_admin_service().trash_conversations(ids)})


@app.post("/api/admin/conversations/restore")
async def admin_conversations_restore(request: Request) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json", "errorCode": "invalid_json"}, status_code=400)
    ids = body.get("conversation_ids") if isinstance(body, dict) else None
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "invalid_ids", "errorCode": "invalid_ids"}, status_code=400)
    return JSONResponse({"status": "ok", **_admin_service().restore_conversations(ids)})


@app.post("/api/admin/trash/purge")
async def admin_trash_purge(request: Request) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    try:
        body = await request.json()
    except Exception:
        body = {}
    purge_all = bool((body or {}).get("all"))
    result = _admin_service().purge_all() if purge_all else _admin_service().purge_expired()
    return JSONResponse({"status": "ok", **result})


@app.get("/api/admin/memory")
async def admin_memory_list(
    request: Request,
    layer: str = Query(default="long_term"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_trashed: bool = Query(default=True),
) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    return JSONResponse(
        _admin_service().list_memory(
            layer=layer,
            limit=limit,
            offset=offset,
            include_trashed=include_trashed,
        )
    )


@app.get("/api/admin/memory/{memory_id}")
async def admin_memory_get(request: Request, memory_id: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    row = _admin_service().get_memory(memory_id)
    if not row:
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse(row)


@app.put("/api/admin/memory/{memory_id}")
async def admin_memory_update(request: Request, memory_id: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json", "errorCode": "invalid_json"}, status_code=400)
    row = _admin_service().update_memory(memory_id, body if isinstance(body, dict) else {})
    if not row:
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse(row)


@app.delete("/api/admin/memory/{memory_id}")
async def admin_memory_delete(request: Request, memory_id: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    if not _admin_service().delete_memory(memory_id):
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/memory/{memory_id}/restore")
async def admin_memory_restore(request: Request, memory_id: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    if not _admin_service().restore_memory(memory_id):
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok"})


@app.get("/api/admin/audit")
async def admin_audit(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    return JSONResponse({"items": _admin_service().recent_audit(limit=limit)})


@app.get("/api/admin/kb")
async def admin_kb_list(
    request: Request,
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    return JSONResponse(_admin_service().list_kb(category=category, limit=limit, offset=offset))


@app.delete("/api/admin/kb/{item_id}")
async def admin_kb_delete(request: Request, item_id: int) -> Response:
    """知识库删除：确认 + undo 快照（非回收站，软删后立即可 undo）。"""
    if not _require_admin(request):
        return _admin_denied()
    snapshot = _admin_service().delete_kb_with_undo(item_id)
    if not snapshot:
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok", "snapshot": {k: snapshot[k] for k in ("id", "category", "title")}})


@app.post("/api/admin/kb/{item_id}/undo")
async def admin_kb_undo(request: Request, item_id: int) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    if not _admin_service().undo_kb_delete(item_id):
        return JSONResponse({"error": "not_found", "errorCode": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok"})


@app.get("/api/admin/state")
async def admin_state_list(request: Request) -> Response:
    """状态文件列表（只读查看；重置走引擎方法，运行时验证）。"""
    if not _require_admin(request):
        return _admin_denied()
    return JSONResponse(_admin_service().list_state())


@app.get("/api/admin/state/{kind}")
async def admin_state_get(request: Request, kind: str) -> Response:
    if not _require_admin(request):
        return _admin_denied()
    data = _admin_service().get_state(kind)
    if data is None:
        return JSONResponse({"error": "unknown_state_kind", "errorCode": "unknown_state_kind"}, status_code=400)
    return JSONResponse(data)


@app.post("/api/admin/state/{kind}/reset")
async def admin_state_reset(request: Request, kind: str) -> Response:
    """状态重置：先落 undo 快照，再走引擎方法（desire 默认态 / topic tracker.reset）。"""
    if not _require_admin(request):
        return _admin_denied()
    result = _admin_service().reset_state(kind, companion=get_companion())
    if result.get("status") == "unavailable":
        return JSONResponse({"error": result.get("reason", "unavailable"), "errorCode": "engine_reset_unavailable", **result}, status_code=501)
    if result.get("status") != "ok":
        return JSONResponse({"error": "unknown_state_kind", "errorCode": "unknown_state_kind"}, status_code=400)
    return JSONResponse({"status": "ok", **result})


@app.post("/api/admin/state/{kind}/undo")
async def admin_state_undo(request: Request, kind: str) -> Response:
    """恢复最近一次重置前的状态快照。"""
    if not _require_admin(request):
        return _admin_denied()
    result = _admin_service().undo_state(kind)
    if result.get("status") == "no_snapshot":
        return JSONResponse({"error": "no_snapshot", "errorCode": "no_snapshot"}, status_code=404)
    if result.get("status") != "ok":
        return JSONResponse({"error": "unknown_state_kind", "errorCode": "unknown_state_kind"}, status_code=400)
    return JSONResponse({"status": "ok", **result})


@app.get("/admin.html")
async def admin_page() -> Response:
    """浏览器端管理页（Electron 管理窗口直接加载本地 renderer，不经此端点）。"""
    from fastapi.responses import FileResponse

    candidates = [
        Path(__file__).resolve().parent.parent / "electron" / "src" / "renderer" / "admin-window.html",
        Path(__file__).resolve().parent.parent / "electron" / "src" / "admin-window.html",
    ]
    for candidate in candidates:
        if candidate.exists():
            return FileResponse(str(candidate), headers={"Cache-Control": "no-store"})
    return JSONResponse({"error": "admin_page_missing", "errorCode": "admin_page_missing"}, status_code=404)


@app.get("/styles/admin-window.css")
async def admin_page_css() -> Response:
    from fastapi.responses import FileResponse

    target = (
        Path(__file__).resolve().parent.parent
        / "electron" / "src" / "renderer" / "styles" / "admin-window.css"
    )
    if target.exists():
        return FileResponse(str(target), media_type="text/css", headers={"Cache-Control": "no-store"})
    return JSONResponse({"error": "asset_missing", "errorCode": "asset_missing"}, status_code=404)


@app.get("/js/admin-window.js")
async def admin_page_js() -> Response:
    from fastapi.responses import FileResponse

    target = (
        Path(__file__).resolve().parent.parent
        / "electron" / "src" / "renderer" / "js" / "admin-window.js"
    )
    if target.exists():
        return FileResponse(str(target), media_type="application/javascript", headers={"Cache-Control": "no-store"})
    return JSONResponse({"error": "asset_missing", "errorCode": "asset_missing"}, status_code=404)


@app.get("/api/cognition/stats")
async def cognition_stats() -> dict:
    """Cognition log aggregate stats."""
    eng = CognitionEngine(_db)
    return eng.stats()


@app.get("/api/cognition/{row_id}")
async def cognition_detail(row_id: int) -> dict:
    """Full cognition_log row, all stages + decision_trace + react_trace."""
    eng = CognitionEngine(_db)
    row = eng.get(row_id)
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return row


@app.get("/api/emotion/history")
async def emotion_history(
    user_id: int | None = None,
    window: str = Query(default="24h", pattern="^(1h|24h|7d|30d)$"),
    downsample: bool = Query(default=True),
) -> dict:
    """Emotion state snapshot history. Window: 1h / 24h / 7d / 30d.

    Phase 9 Batch 5: When ``downsample=true`` (default), the server
    buckets the raw rows into a small number of evenly-spaced buckets
    so the client doesn't have to render thousands of points. Bucket
    size is chosen to keep the returned series at ~120-336 points
    regardless of the window.
    """
    companion = get_companion()
    actor_id = None
    if user_id is None and companion:
        primary = companion.get_primary_identity()
        if primary:
            user_id, identity = primary
            actor_id = identity.actor_id
    if user_id is None:
        now_ms = int(time.time() * 1000)
        return {
            "status": "unavailable",
            "error": "primary identity is not configured",
            "primaryUserId": None,
            "sampledAt": None,
            "latestPersistedAt": None,
            "serverNow": now_ms,
            "stale": True,
            "window": window,
            "since_ts": now_ms - {
                "1h": 3600 * 1000,
                "24h": 24 * 3600 * 1000,
                "7d": 7 * 24 * 3600 * 1000,
                "30d": 30 * 24 * 3600 * 1000,
            }[window],
            "count": 0,
            "raw_count": 0,
            "downsampled": False,
            "items": [],
        }
    if actor_id is None and companion and user_id:
        actor_id = companion.identity_resolver.resolve(
            "qq",
            str(user_id),
        ).actor_id
    window_ms = {
        "1h": 3600 * 1000,
        "24h": 24 * 3600 * 1000,
        "7d": 7 * 24 * 3600 * 1000,
        "30d": 30 * 24 * 3600 * 1000,
    }[window]
    since = int(time.time() * 1000) - window_ms
    if actor_id and companion:
        raw_rows = companion.state_store.history(
            user_id,
            since,
            limit=5000,
            actor_id=actor_id,
        )
    else:
        raw_rows = _db.query(
            "SELECT * FROM ("
            "SELECT ts, pleasure, arousal, dominance, label, "
            "patience_value, anxiety_value, desire_value, tenderness_value, "
            "active_eruption, trigger_event "
            "FROM emotion_state_snapshot WHERE user_id = ? AND ts >= ? "
            "ORDER BY ts DESC, id DESC LIMIT 5000"
            ") ORDER BY ts ASC",
            (user_id, since),
        )

    freshness = {
        "sampledAt": None,
        "latestPersistedAt": int(raw_rows[-1]["ts"]) if raw_rows else None,
        "serverNow": int(time.time() * 1000),
        "stale": True,
    }
    if companion:
        freshness = companion.state_store.freshness_metadata(
            user_id,
            actor_id=actor_id,
            sampled_at=getattr(companion, "_emotion_last_sampled_at", None),
        )
    freshness["primaryUserId"] = int(user_id)

    if not downsample or len(raw_rows) <= 120:
        return {
            "user_id": user_id,
            "actor_id": actor_id,
            "window": window,
            "since_ts": since,
            "count": len(raw_rows),
            "raw_count": len(raw_rows),
            "downsampled": False,
            "items": raw_rows,
            **freshness,
        }

    # Choose bucket size to land at 120-336 buckets.
    target_buckets = {
        "1h": 120,
        "24h": 144,
        "7d": 168,
        "30d": 240,
    }[window]
    bucket_ms = max(1, window_ms // target_buckets)
    buckets: dict[int, dict] = {}
    for r in raw_rows:
        b = int(r["ts"]) // bucket_ms
        cell = buckets.get(b)
        if cell is None:
            cell = {
                "ts": int(r["ts"]),
                "_count": 0,
                "_pleasure_sum": 0.0, "_arousal_sum": 0.0, "_dominance_sum": 0.0,
                "_patience_sum": 0.0, "_anxiety_sum": 0.0,
                "_desire_sum": 0.0, "_tenderness_sum": 0.0,
                "_label_counts": {},
                "active_eruption": None,
                "trigger_event": None,
            }
            buckets[b] = cell
        cell["_count"] += 1
        for k, sumk in (
            ("pleasure", "_pleasure_sum"),
            ("arousal", "_arousal_sum"),
            ("dominance", "_dominance_sum"),
            ("patience_value", "_patience_sum"),
            ("anxiety_value", "_anxiety_sum"),
            ("desire_value", "_desire_sum"),
            ("tenderness_value", "_tenderness_sum"),
        ):
            v = r.get(k)
            if v is not None:
                try:
                    cell[sumk] += float(v)
                except (TypeError, ValueError):
                    pass
        lab = r.get("label")
        if lab:
            cell["_label_counts"][lab] = cell["_label_counts"].get(lab, 0) + 1
        # Keep the most recent eruption / trigger (last write wins).
        if r.get("active_eruption"):
            cell["active_eruption"] = r.get("active_eruption")
        if r.get("trigger_event"):
            cell["trigger_event"] = r.get("trigger_event")

    items: list[dict] = []
    for b in sorted(buckets.keys()):
        cell = buckets[b]
        n = cell["_count"]
        if n <= 0:
            continue
        # Pick the dominant label.
        lc = cell["_label_counts"]
        label = max(lc.items(), key=lambda kv: kv[1])[0] if lc else "neutral"
        items.append({
            "ts": cell["ts"],
            "pleasure": round(cell["_pleasure_sum"] / n, 3),
            "arousal": round(cell["_arousal_sum"] / n, 3),
            "dominance": round(cell["_dominance_sum"] / n, 3),
            "label": label,
            "patience_value": round(cell["_patience_sum"] / n, 1),
            "anxiety_value": round(cell["_anxiety_sum"] / n, 1),
            "desire_value": round(cell["_desire_sum"] / n, 1),
            "tenderness_value": round(cell["_tenderness_sum"] / n, 1),
            "active_eruption": cell["active_eruption"],
            "trigger_event": cell["trigger_event"],
            "_bucket_count": n,
        })

    return {
        "user_id": user_id,
        "actor_id": actor_id,
        "window": window,
        "since_ts": since,
        "count": len(items),
        "raw_count": len(raw_rows),
        "downsampled": True,
        "bucket_ms": bucket_ms,
        "items": items,
        **freshness,
    }


# ── Phase 15 Batch 2: Memory archive (只读记忆档案) ──
_MEMORY_LAYERS: tuple[str, ...] = ("transient", "working", "long_term", "permanent")


@app.get("/api/memory/list")
async def memory_list(
    user_id: int | None = Query(default=None),
    layer: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """只读记忆档案列表（按层分组）。

    复用四层 LayeredMemory 的 list_by_user，仅暴露公开元数据字段，
    不做任何写入/删除，避免前端误操作记忆。
    """
    comp = get_companion()
    if user_id is None:
        user_id = _primary_user_id(comp) if comp is not None else None
    if user_id is None:
        return {"layers": {}, "total": 0}

    memory = getattr(comp, "memory", None)
    list_by_user = getattr(memory, "list_by_user", None)
    if not callable(list_by_user):
        return {"layers": {}, "total": 0}

    layers = _MEMORY_LAYERS
    if layer:
        layers = (layer,) if layer in _MEMORY_LAYERS else ()

    grouped: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for name in layers:
        rows = list_by_user(user_id=int(user_id), layer=name, limit=int(limit))
        grouped[name] = [dict(row) for row in (rows or [])]
        total += len(grouped[name])

    return {
        "user_id": int(user_id),
        "layers": grouped,
        "total": total,
        "sampledAt": int(time.time() * 1000),
    }


# ── Phase 9 Batch 3: YAML config editing (settings / persona / proactive) ──

# Whitelist of editable config files (only these 3 are exposed for user editing).
_YAML_ALLOWED_FILES: set[str] = {"settings.yaml", "persona.yaml", "proactive.yaml"}
_YAML_CONFIG_DIR = Path("config")

def _yaml_backup_dir() -> Path:
    from core.paths import data_dir
    return data_dir() / "backups" / "config"


def _yaml_path(filename: str) -> Path | None:
    """Resolve a yaml file path against the whitelist. Returns None when rejected."""
    if not filename or filename not in _YAML_ALLOWED_FILES:
        return None
    return _YAML_CONFIG_DIR / filename


def _yaml_backup_now(filename: str) -> Path:
    """Copy the current yaml file to a timestamped backup. Returns the backup path.

    Creates the backup directory on demand. When the source file is missing,
    still records the backup slot with an empty marker so the rollback path
    is always available.
    """
    backup_dir = _yaml_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    backup_path = backup_dir / f"{filename}.{ts_ms}.yaml"
    source = _YAML_CONFIG_DIR / filename
    if source.exists():
        backup_path.write_bytes(source.read_bytes())
    else:
        backup_path.write_text("# missing source — placeholder\n", encoding="utf-8")
    return backup_path


def _yaml_latest_backup(filename: str) -> Path | None:
    """Find the most recent backup for a given yaml filename."""
    backup_dir = _yaml_backup_dir()
    if not backup_dir.exists():
        return None
    candidates = sorted(
        backup_dir.glob(f"{filename}.*.yaml"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


@app.get("/api/config/yaml/list")
async def config_yaml_list() -> dict:
    """Whitelist of editable config files."""
    return {"files": sorted(_YAML_ALLOWED_FILES)}


@app.get("/api/config/yaml")
async def config_yaml_get(file: str = Query(...)) -> Response:
    """Return the raw UTF-8 text of a whitelisted yaml file."""
    target = _yaml_path(file)
    if target is None:
        return JSONResponse(
            {"error": "file not allowed", "allowed": sorted(_YAML_ALLOWED_FILES)},
            status_code=400,
        )
    if not target.exists():
        return JSONResponse(
            {"error": "not found", "file": file, "path": str(target)},
            status_code=404,
        )
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as e:
        return JSONResponse({"error": f"read failed: {e}"}, status_code=500)
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
    )


@app.put("/api/config/yaml")
async def config_yaml_put(file: str = Query(...), request: Request = None) -> dict:
    """Write a yaml file with strict validation, auto-backup, and rollback.

    Body is the raw UTF-8 yaml text. On any failure the original file is
    restored from the most recent backup and the error is reported.
    """
    target = _yaml_path(file)
    if target is None:
        return JSONResponse(
            {"error": "file not allowed", "allowed": sorted(_YAML_ALLOWED_FILES)},
            status_code=400,
        )
    if file == "persona.yaml":
        return JSONResponse(
            {"error": "persona.yaml is read-only; update Persona Hub instead"},
            status_code=409,
        )

    raw = (await request.body()).decode("utf-8", errors="replace")

    # ── 1) Strict parse: yaml.safe_load must succeed ──
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        logger.warning("yaml put rejected: parse error file=%s err=%s", file, str(e)[:120])
        return JSONResponse(
            {"error": "yaml parse failed", "detail": str(e)},
            status_code=400,
        )

    if parsed is None and not raw.strip():
        # Empty file is also a parse failure — disallow wiping the config
        return JSONResponse(
            {"error": "empty yaml not allowed", "detail": "refusing to write empty file"},
            status_code=400,
        )

    # ── 2) Snapshot current file (auto-backup before write) ──
    backup_path = _yaml_backup_now(file)
    backup_str = str(backup_path)

    # ── 3) Write atomically: write to .tmp then replace ──
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    try:
        tmp_path.write_text(raw, encoding="utf-8")
        tmp_path.replace(target)
    except Exception as e:
        # Rollback from backup
        try:
            if backup_path.exists():
                target.write_bytes(backup_path.read_bytes())
        except Exception:
            pass
        logger.exception("yaml put write error file=%s", file)
        return JSONResponse(
            {"error": f"write failed: {e}", "restored_from": backup_str},
            status_code=500,
        )

    # ── 4) Re-parse the freshly written file as a self-check ──
    try:
        with target.open("r", encoding="utf-8") as fh:
            yaml.safe_load(fh)
    except Exception as e:
        # Rollback: replace target with backup bytes
        try:
            if backup_path.exists():
                target.write_bytes(backup_path.read_bytes())
        except Exception:
            pass
        return JSONResponse(
            {"error": f"post-write reparse failed: {e}", "restored_from": backup_str},
            status_code=500,
        )

    logger.info(
        "settings_change: file=%s ts=%d bytes=%d backup=%s",
        file, int(time.time() * 1000), len(raw.encode("utf-8")), backup_str,
    )
    return {
        "status": "ok",
        "file": file,
        "bytes": len(raw.encode("utf-8")),
        "backup_path": backup_str,
        "ts": int(time.time() * 1000),
    }


@app.post("/api/config/yaml/backup")
async def config_yaml_backup(file: str = Query(...)) -> dict:
    """Manually snapshot a yaml file into data/backups/config/."""
    target = _yaml_path(file)
    if target is None:
        return JSONResponse(
            {"error": "file not allowed", "allowed": sorted(_YAML_ALLOWED_FILES)},
            status_code=400,
        )
    if not target.exists():
        return JSONResponse({"error": "source not found", "file": file}, status_code=404)
    try:
        backup_path = _yaml_backup_now(file)
    except Exception as e:
        return JSONResponse({"error": f"backup failed: {e}"}, status_code=500)
    return {
        "status": "ok",
        "file": file,
        "backup_path": str(backup_path),
        "ts": int(time.time() * 1000),
    }


# ── Phase 9 Batch 6: Self-Evolve endpoints ────────────


def _get_self_evolver() -> SelfEvolver | None:
    """Look up the SelfEvolver on the live companion.

    Returns None if the companion is not yet ready (e.g. during early
    boot). HTTP handlers translate None into 503.
    """
    comp = get_companion()
    if not comp:
        return None
    return getattr(comp, "self_evolver", None)


@app.get("/api/self_evolve/list")
async def self_evolve_list(
    user_id: int | None = None,
    status: str = Query(default="pending", pattern="^(pending|approved|rejected|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """List self-evolution proposals. Default status=pending.

    Phase 9 Batch 6: Brain center shows pending proposals as cards;
    approved/rejected are kept for audit + regression review.
    """
    ev = _get_self_evolver()
    if ev is None:
        return JSONResponse(
            {"error": "self_evolver not ready"}, status_code=503
        )
    try:
        items = ev.list_proposals(user_id=user_id, status=status, limit=limit)
        # Decode the JSON schema for the frontend (it expects an object).
        for it in items:
            raw = it.get("proposed_tool_schema")
            if raw and isinstance(raw, str):
                try:
                    it["proposed_tool_schema"] = json.loads(raw)
                except Exception:
                    pass
        return {
            "status": "ok",
            "filter": {"user_id": user_id, "decision": status, "limit": limit},
            "count": len(items),
            "items": items,
            "stats": ev.stats(),
        }
    except Exception as e:
        logger.exception("self_evolve_list error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/self_evolve/{proposal_id:int}")
async def self_evolve_detail(proposal_id: int) -> dict:
    """Fetch a single proposal (full row + parsed schema)."""
    ev = _get_self_evolver()
    if ev is None:
        return JSONResponse(
            {"error": "self_evolver not ready"}, status_code=503
        )
    row = ev.get_proposal(proposal_id)
    if not row:
        return JSONResponse(
            {"error": "not found", "id": proposal_id}, status_code=404
        )
    raw = row.get("proposed_tool_schema")
    if raw and isinstance(raw, str):
        try:
            row["proposed_tool_schema"] = json.loads(raw)
        except Exception:
            pass
    return row


@app.post("/api/self_evolve/{proposal_id}/preview")
async def self_evolve_preview(proposal_id: int) -> dict:
    """Re-render the sandbox preview for an existing proposal.

    Useful when the user clicks "查看预演 / Preview" on a card.
    """
    ev = _get_self_evolver()
    if ev is None:
        return JSONResponse(
            {"error": "self_evolver not ready"}, status_code=503
        )
    preview = ev.render_preview(proposal_id)
    if not preview.get("ok") and preview.get("error") == "not_found":
        return JSONResponse(preview, status_code=404)
    return preview


@app.post("/api/self_evolve/{proposal_id}/approve")
async def self_evolve_approve(proposal_id: int) -> dict:
    """Approve a proposal: register the proposed tool in the live registry.

    Idempotent — repeated approvals return already=True.
    """
    ev = _get_self_evolver()
    if ev is None:
        return JSONResponse(
            {"error": "self_evolver not ready"}, status_code=503
        )
    result = ev.approve(proposal_id)
    if result.get("status") == "error":
        if result.get("reason") == "not_found":
            return JSONResponse(result, status_code=404)
        return JSONResponse(result, status_code=400)
    return result


@app.post("/api/self_evolve/{proposal_id}/reject")
async def self_evolve_reject(proposal_id: int) -> dict:
    """Reject a proposal. Idempotent."""
    ev = _get_self_evolver()
    if ev is None:
        return JSONResponse(
            {"error": "self_evolver not ready"}, status_code=503
        )
    result = ev.reject(proposal_id)
    if result.get("status") == "error":
        if result.get("reason") == "not_found":
            return JSONResponse(result, status_code=404)
        return JSONResponse(result, status_code=400)
    return result


# ── Self Evolve Stats ───────────────────────────────

@app.get("/api/self_evolve/stats")
async def self_evolve_stats() -> dict:
    """Self-evolve proposal statistics."""
    ev = _get_self_evolver()
    if ev is None:
        return {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "rolled_back": 0}
    try:
        return ev.stats()
    except Exception as e:
        logger.exception("self_evolve_stats error")
        return {"error": str(e)}


# ── L4 自进化（内测）：代码自修改 提案/闸门/审批/回滚 ──────────

def _get_l4_evolution() -> L4SelfEvolution | None:
    """Look up the L4 self-evolution engine on the live companion."""
    comp = get_companion()
    if not comp:
        return None
    return getattr(comp, "l4_evolution", None)


@app.get("/api/self_evolve/l4/stats")
async def self_evolve_l4_stats() -> dict:
    """L4 code self-modification statistics."""
    l4 = _get_l4_evolution()
    if l4 is None:
        return {"status": "ok", "enabled": False, "total": 0, "applied": 0}
    try:
        comp = get_companion()
        enabled = bool(
            getattr(getattr(comp, "self_evolver", None), "enabled", False)
        )
        return {"status": "ok", "enabled": enabled, **l4.get_stats()}
    except Exception as e:
        logger.exception("self_evolve_l4_stats error")
        return {"error": str(e)}


@app.get("/api/self_evolve/l4/list")
async def self_evolve_l4_list(
    status: str = Query(default="", pattern="^$|^(proposed|gate1_passed|gate2_passed|gate3_passed|gate4_passed|approved|applied|rejected|rolled_back|pending_review)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """List L4 evolution proposals (newest first)."""
    l4 = _get_l4_evolution()
    if l4 is None:
        return JSONResponse({"error": "l4 not ready"}, status_code=503)
    try:
        return {
            "proposals": l4.archive.list_proposals(
                status=status or None,
                limit=limit,
            ),
        }
    except Exception as e:
        logger.exception("self_evolve_l4_list error")
        return {"error": str(e)}


@app.post("/api/self_evolve/l4/{proposal_id}/approve")
async def self_evolve_l4_approve(proposal_id: str) -> dict:
    """人工审批并应用一个 L4 提案（核心/高风险提案必走此步）。"""
    l4 = _get_l4_evolution()
    if l4 is None:
        return JSONResponse({"error": "l4 not ready"}, status_code=503)
    try:
        ok, msg = l4.approve_and_apply(proposal_id)
        return {"ok": ok, "message": msg}
    except Exception as e:
        logger.exception("self_evolve_l4_approve error")
        return {"error": str(e)}


@app.post("/api/self_evolve/l4/{proposal_id}/reject")
async def self_evolve_l4_reject(proposal_id: str) -> dict:
    """拒绝一个 L4 提案。"""
    l4 = _get_l4_evolution()
    if l4 is None:
        return JSONResponse({"error": "l4 not ready"}, status_code=503)
    try:
        ok, msg = l4.reject_proposal(proposal_id, reason="rejected via settings panel")
        return {"ok": ok, "message": msg}
    except Exception as e:
        logger.exception("self_evolve_l4_reject error")
        return {"error": str(e)}


@app.post("/api/self_evolve/l4/{proposal_id}/rollback")
async def self_evolve_l4_rollback(proposal_id: str) -> dict:
    """回滚一个已应用的 L4 提案（24h 窗口内）。"""
    l4 = _get_l4_evolution()
    if l4 is None:
        return JSONResponse({"error": "l4 not ready"}, status_code=503)
    try:
        ok, msg = l4.rollback(proposal_id)
        return {"ok": ok, "message": msg}
    except Exception as e:
        logger.exception("self_evolve_l4_rollback error")
        return {"error": str(e)}


# ── Computer Control ────────────────────────────────

@app.get("/api/computer_control/stats")
async def computer_control_stats() -> dict:
    """Computer control statistics (today ops, blocked, etc)."""
    try:
        ctrl = _get_computer_controller()
        logs = ctrl.get_audit_logs(limit=200)
        today_start = int(time.time()) - 86400
        today_ops = sum(1 for l in logs if l.get("ts", 0) >= today_start and l.get("status") == "success")
        blocked_ops = sum(1 for l in logs if l.get("status") == "blocked")
        return {
            "mode": ctrl.mode.value,
            "today_operations": today_ops,
            "blocked_operations": blocked_ops,
            "total_operations": len(logs),
        }
    except Exception as e:
        logger.exception("computer_control_stats error")
        return {"error": str(e)}


@app.get("/api/computer_control/mode")
async def computer_control_get_mode() -> dict:
    """Get current permission mode: manual / auto / full / custom."""
    try:
        ctrl = _get_computer_controller()
        return {"mode": ctrl.mode.value}
    except Exception as e:
        return {"error": str(e)}


@app.put("/api/computer_control/mode")
async def computer_control_set_mode(request: Request) -> dict:
    """Set permission mode: manual / auto / full / custom."""
    try:
        body = await request.json()
        mode_str = (body.get("mode") or "").lower()
        valid = {m.value for m in ControlMode}
        if mode_str not in valid:
            return JSONResponse(
                {"error": f"invalid mode, must be one of: {sorted(valid)}"},
                status_code=400,
            )
        ctrl = _get_computer_controller()
        ctrl.set_mode(ControlMode(mode_str))
        emit("computer_control_mode_changed", mode=mode_str)
        return {"status": "ok", "mode": mode_str}
    except Exception as e:
        logger.exception("computer_control_set_mode error")
        return {"error": str(e)}


@app.get("/api/computer_control/policy")
async def computer_control_policy() -> dict:
    """Get current policy: mode + whitelist + blacklist + custom rules."""
    try:
        ctrl = _get_computer_controller()
        return {"policy": ctrl.policy.to_dict()}
    except Exception as e:
        logger.exception("computer_control_policy error")
        return {"error": str(e)}


def _validate_list_body(body: dict) -> tuple[str, str, str]:
    """校验黑白名单请求体，返回 (entry_type, value, note)。"""
    entry_type = str(body.get("type") or "").lower()
    value = str(body.get("value") or "").strip()
    note = str(body.get("note") or "")
    valid_types = {t.value for t in PolicyEntryType}
    if entry_type not in valid_types:
        raise ValueError(f"invalid type, must be one of: {sorted(valid_types)}")
    if not value:
        raise ValueError("value is required")
    return entry_type, value, note


@app.post("/api/computer_control/whitelist")
async def computer_control_whitelist_add(request: Request) -> dict:
    """Add a whitelist entry.

    body: {"type": "action|command|pattern", "value": "...", "note": ""}
    """
    try:
        body = await request.json()
        entry_type, value, note = _validate_list_body(body)
        ctrl = _get_computer_controller()
        entry = ctrl.policy.add_whitelist(entry_type, value, note)
        emit("computer_control_policy_changed", list_name="whitelist",
             action="add", entry=entry.to_dict())
        return {"status": "ok", "entry": entry.to_dict(), "policy": ctrl.policy.to_dict()}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("whitelist_add error")
        return {"error": str(e)}


@app.delete("/api/computer_control/whitelist/{entry_id}")
async def computer_control_whitelist_remove(entry_id: str) -> dict:
    """Remove a whitelist entry."""
    try:
        ctrl = _get_computer_controller()
        ok = ctrl.policy.remove_whitelist(entry_id)
        if not ok:
            return JSONResponse({"error": "entry not found"}, status_code=404)
        emit("computer_control_policy_changed", list_name="whitelist",
             action="remove", id=entry_id)
        return {"status": "ok", "removed": True, "policy": ctrl.policy.to_dict()}
    except Exception as e:
        logger.exception("whitelist_remove error")
        return {"error": str(e)}


@app.post("/api/computer_control/blacklist")
async def computer_control_blacklist_add(request: Request) -> dict:
    """Add a blacklist entry.

    body: {"type": "action|command|pattern", "value": "...", "note": ""}
    """
    try:
        body = await request.json()
        entry_type, value, note = _validate_list_body(body)
        ctrl = _get_computer_controller()
        entry = ctrl.policy.add_blacklist(entry_type, value, note)
        emit("computer_control_policy_changed", list_name="blacklist",
             action="add", entry=entry.to_dict())
        return {"status": "ok", "entry": entry.to_dict(), "policy": ctrl.policy.to_dict()}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("blacklist_add error")
        return {"error": str(e)}


@app.delete("/api/computer_control/blacklist/{entry_id}")
async def computer_control_blacklist_remove(entry_id: str) -> dict:
    """Remove a blacklist entry."""
    try:
        ctrl = _get_computer_controller()
        ok = ctrl.policy.remove_blacklist(entry_id)
        if not ok:
            return JSONResponse({"error": "entry not found"}, status_code=404)
        emit("computer_control_policy_changed", list_name="blacklist",
             action="remove", id=entry_id)
        return {"status": "ok", "removed": True, "policy": ctrl.policy.to_dict()}
    except Exception as e:
        logger.exception("blacklist_remove error")
        return {"error": str(e)}


@app.get("/api/computer_control/logs")
async def computer_control_logs(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """Recent computer control audit logs."""
    try:
        ctrl = _get_computer_controller()
        logs = ctrl.get_audit_logs(limit=limit)
        return {"logs": logs}
    except Exception as e:
        logger.exception("computer_control_logs error")
        return {"error": str(e)}


# ── Approval Flow ───────────────────────────────────

@app.get("/api/computer_control/approvals/pending")
async def computer_control_approvals_pending() -> dict:
    """Get pending approval requests."""
    try:
        ctrl = _get_computer_controller()
        approvals = ctrl.get_pending_approvals()
        return {"approvals": approvals, "count": len(approvals)}
    except Exception as e:
        logger.exception("approvals_pending error")
        return {"error": str(e)}


@app.post("/api/computer_control/approvals/{approval_id}/approve")
async def computer_control_approve(approval_id: str, request: Request) -> dict:
    """Approve a pending action.

    body: {"whitelist": true} — 放行并加入白名单（后续同类操作自动放行）。
    """
    try:
        body = {}
        try:
            body = await request.json() or {}
        except Exception:
            body = {}
        whitelist = bool(body.get("whitelist", False))
        ctrl = _get_computer_controller()
        result = ctrl.approve_action(approval_id, whitelist=whitelist)
        if result:
            return {"status": "ok", "approved": True, "whitelist": whitelist}
        return JSONResponse({"error": "approval not found"}, status_code=404)
    except Exception as e:
        logger.exception("approve error")
        return {"error": str(e)}


@app.post("/api/computer_control/approvals/{approval_id}/reject")
async def computer_control_reject(approval_id: str, request: Request) -> dict:
    """Reject a pending action.

    body: {"blacklist": true} — 拒绝并加入黑名单（后续同类操作直接拦截）。
    """
    try:
        body = {}
        try:
            body = await request.json() or {}
        except Exception:
            body = {}
        blacklist = bool(body.get("blacklist", False))
        ctrl = _get_computer_controller()
        result = ctrl.reject_action(approval_id, blacklist=blacklist)
        if result:
            return {"status": "ok", "rejected": True, "blacklist": blacklist}
        return JSONResponse({"error": "approval not found"}, status_code=404)
    except Exception as e:
        logger.exception("reject error")
        return {"error": str(e)}


# ── Fine-Grained Permission Manager (v13.9) ───────────

@app.get("/api/permissions/config")
async def permissions_get_config() -> dict:
    """获取细粒度权限配置。"""
    try:
        pm = _get_permission_manager()
        cfg = pm.config
        return {
            "config": cfg.to_dict(),
            "authorized_dirs": pm.list_authorized_dirs(),
        }
    except Exception as e:
        logger.exception("permissions_get_config error")
        return {"error": str(e)}


@app.put("/api/permissions/config")
async def permissions_update_config(request: Request) -> dict:
    """更新细粒度权限配置。"""
    try:
        body = await request.json()
        pm = _get_permission_manager()
        new_cfg = pm.update_config(body)
        emit("permissions_config_changed", **new_cfg.to_dict())
        return {"status": "ok", "config": new_cfg.to_dict()}
    except Exception as e:
        logger.exception("permissions_update_config error")
        return {"error": str(e)}


@app.get("/api/permissions/dirs")
async def permissions_list_dirs() -> dict:
    """获取授权目录列表。"""
    try:
        pm = _get_permission_manager()
        return {"dirs": pm.list_authorized_dirs()}
    except Exception as e:
        logger.exception("permissions_list_dirs error")
        return {"error": str(e)}


@app.post("/api/permissions/dirs")
async def permissions_add_dir(request: Request) -> dict:
    """添加授权目录。"""
    try:
        body = await request.json()
        dir_path = body.get("path", "")
        if not dir_path:
            return JSONResponse({"error": "path is required"}, status_code=400)
        pm = _get_permission_manager()
        ok = pm.add_authorized_dir(dir_path)
        if ok:
            emit("permissions_dirs_changed", action="add", path=dir_path)
            return {"status": "ok", "dirs": pm.list_authorized_dirs()}
        return JSONResponse({"error": "无法添加该目录（系统路径或不存在）"}, status_code=400)
    except Exception as e:
        logger.exception("permissions_add_dir error")
        return {"error": str(e)}


@app.delete("/api/permissions/dirs")
async def permissions_remove_dir(path: str = "") -> dict:
    """移除授权目录。"""
    try:
        if not path:
            return JSONResponse({"error": "path is required"}, status_code=400)
        pm = _get_permission_manager()
        ok = pm.remove_authorized_dir(path)
        if ok:
            emit("permissions_dirs_changed", action="remove", path=path)
            return {"status": "ok", "dirs": pm.list_authorized_dirs()}
        return JSONResponse({"error": "目录不在白名单中"}, status_code=404)
    except Exception as e:
        logger.exception("permissions_remove_dir error")
        return {"error": str(e)}


@app.post("/api/permissions/check")
async def permissions_check(request: Request) -> dict:
    """权限检查接口。"""
    try:
        from core.permission_manager import OperationType
        body = await request.json()
        operation_str = body.get("operation", "")
        target_path = body.get("path", "")
        batch_count = int(body.get("batch_count", 1))
        try:
            operation = OperationType(operation_str)
        except ValueError:
            return JSONResponse({"error": f"未知操作类型: {operation_str}"}, status_code=400)
        pm = _get_permission_manager()
        result = pm.check(operation, target_path, batch_count)
        return result.to_dict()
    except Exception as e:
        logger.exception("permissions_check error")
        return {"error": str(e)}


@app.get("/api/permissions/audit")
async def permissions_audit_log(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """获取权限审计日志。"""
    try:
        pm = _get_permission_manager()
        return {"logs": pm.get_audit_log(limit=limit)}
    except Exception as e:
        logger.exception("permissions_audit_log error")
        return {"error": str(e)}


@app.post("/api/permissions/revoke_all")
async def permissions_revoke_all() -> dict:
    """一键撤销所有非必要权限。"""
    try:
        pm = _get_permission_manager()
        pm.revoke_all()
        emit("permissions_config_changed", **pm.config.to_dict())
        return {"status": "ok", "config": pm.config.to_dict()}
    except Exception as e:
        logger.exception("permissions_revoke_all error")
        return {"error": str(e)}


# ── Async Task Manager (v13.9) ───────────────────────

def _get_async_task_manager():
    """获取共享的异步任务管理器实例。"""
    try:
        from core.companion import get_companion
        comp = get_companion()
        if comp and hasattr(comp, "async_task_manager") and comp.async_task_manager:
            return comp.async_task_manager
    except Exception:
        pass
    from core.async_task_manager import AsyncTaskManager
    return AsyncTaskManager()


@app.get("/api/tasks")
async def tasks_list(
    status: str = "",
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """获取任务列表。"""
    try:
        mgr = _get_async_task_manager()
        from core.async_task_manager import AsyncTaskStatus
        status_filter = None
        if status:
            try:
                status_filter = AsyncTaskStatus(status)
            except ValueError:
                pass
        tasks = mgr.list_tasks(status=status_filter, limit=limit)
        return {
            "tasks": [t.to_dict() for t in tasks],
            "stats": mgr.stats(),
        }
    except Exception as e:
        logger.exception("tasks_list error")
        return {"error": str(e)}


@app.get("/api/tasks/stats")
async def tasks_stats() -> dict:
    """获取任务统计。"""
    try:
        mgr = _get_async_task_manager()
        return {"stats": mgr.stats()}
    except Exception as e:
        logger.exception("tasks_stats error")
        return {"error": str(e)}


@app.get("/api/tasks/{task_id}")
async def tasks_get(task_id: str) -> dict:
    """获取单个任务详情。"""
    try:
        mgr = _get_async_task_manager()
        task = mgr.get_task(task_id)
        if not task:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        return {"task": task.to_dict()}
    except Exception as e:
        logger.exception("tasks_get error")
        return {"error": str(e)}


@app.post("/api/tasks")
async def tasks_submit(request: Request) -> dict:
    """提交异步任务。"""
    try:
        body = await request.json()
        name = body.get("name") or body.get("title") or "未命名任务"
        description = body.get("description", "")
        task_type = body.get("task_type", "generic")
        raw_priority = body.get("priority", "medium")
        task_data = body.get("data", {})

        from core.async_task_manager import TaskPriority
        priority_map = {
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
        }
        if isinstance(raw_priority, int):
            # 兼容 1=high / 2=medium / 3=low，以及 0-2 风格
            if raw_priority <= 0:
                priority = TaskPriority.HIGH
            elif raw_priority == 1:
                priority = TaskPriority.MEDIUM
            else:
                priority = TaskPriority.LOW
        else:
            priority = priority_map.get(
                str(raw_priority).strip().lower(), TaskPriority.MEDIUM
            )

        mgr = _get_async_task_manager()
        # 确保管理器已启动
        if not mgr._running:
            mgr.start()

        task = mgr.submit_task(
            name=name,
            description=description,
            task_type=task_type,
            priority=priority,
            task_data=task_data,
        )
        emit("task_submitted", **task.to_dict())
        return {"task": task.to_dict()}
    except Exception as e:
        logger.exception("tasks_submit error")
        return {"error": str(e)}


@app.post("/api/tasks/{task_id}/cancel")
async def tasks_cancel(task_id: str) -> dict:
    """取消任务。"""
    try:
        mgr = _get_async_task_manager()
        ok = mgr.cancel_task(task_id)
        if ok:
            emit("task_cancelled", task_id=task_id)
            return {"status": "ok", "cancelled": True}
        return JSONResponse({"error": "无法取消该任务"}, status_code=400)
    except Exception as e:
        logger.exception("tasks_cancel error")
        return {"error": str(e)}


@app.post("/api/tasks/{task_id}/retry")
async def tasks_retry(task_id: str) -> dict:
    """重试失败的任务。"""
    try:
        mgr = _get_async_task_manager()
        new_task = mgr.retry_task(task_id)
        if new_task:
            emit("task_submitted", **new_task.to_dict())
            return {"task": new_task.to_dict()}
        return JSONResponse({"error": "无法重试该任务"}, status_code=400)
    except Exception as e:
        logger.exception("tasks_retry error")
        return {"error": str(e)}


@app.get("/api/tasks/{task_id}/progress")
async def tasks_progress(task_id: str) -> dict:
    """获取任务进度历史。"""
    try:
        mgr = _get_async_task_manager()
        task = mgr.get_task(task_id)
        if not task:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        return {
            "task_id": task_id,
            "progress": task.progress,
            "current_step": task.current_step,
            "history": [p.to_dict() for p in task.progress_history[-20:]],
        }
    except Exception as e:
        logger.exception("tasks_progress error")
        return {"error": str(e)}


# ── QQ Whitelist (v13.9) ────────────────────────────

@app.get("/api/qq/whitelist")
async def qq_whitelist_list() -> dict:
    """获取 QQ 白名单列表和统计信息。"""
    try:
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return {"items": [], "stats": {"enabled": False, "total": 0, "active": 0, "mode": "compatible"}}
        items = comp.qq_whitelist.list_all()
        stats = comp.qq_whitelist.stats()
        return {"items": items, "stats": stats}
    except Exception as e:
        logger.exception("qq whitelist list error")
        return {"error": str(e)}


@app.post("/api/qq/whitelist")
async def qq_whitelist_add(request: Request) -> dict:
    """添加白名单用户。"""
    try:
        body = await request.json()
        qq_number = body.get("qq_number")
        remark = body.get("remark", "")
        if not qq_number:
            return JSONResponse({"error": "qq_number is required"}, status_code=400)
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return JSONResponse({"error": "whitelist not available"}, status_code=503)
        ok = comp.qq_whitelist.add(qq_number, remark)
        emit("qq_whitelist_changed", action="add", qq_number=str(qq_number))
        return {"status": "ok", "added": ok}
    except Exception as e:
        logger.exception("qq whitelist add error")
        return {"error": str(e)}


@app.delete("/api/qq/whitelist/{qq_number}")
async def qq_whitelist_remove(qq_number: str) -> dict:
    """移除白名单用户。"""
    try:
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return JSONResponse({"error": "whitelist not available"}, status_code=503)
        ok = comp.qq_whitelist.remove(qq_number)
        emit("qq_whitelist_changed", action="remove", qq_number=qq_number)
        return {"status": "ok", "removed": ok}
    except Exception as e:
        logger.exception("qq whitelist remove error")
        return {"error": str(e)}


@app.put("/api/qq/whitelist/{qq_number}/toggle")
async def qq_whitelist_toggle(qq_number: str, request: Request) -> dict:
    """启用/禁用单个白名单用户。"""
    try:
        body = await request.json()
        enabled = body.get("enabled", True)
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return JSONResponse({"error": "whitelist not available"}, status_code=503)
        ok = comp.qq_whitelist.toggle(qq_number, enabled)
        emit("qq_whitelist_changed", action="toggle", qq_number=qq_number, enabled=enabled)
        return {"status": "ok", "toggled": ok}
    except Exception as e:
        logger.exception("qq whitelist toggle error")
        return {"error": str(e)}


@app.put("/api/qq/whitelist/{qq_number}/remark")
async def qq_whitelist_remark(qq_number: str, request: Request) -> dict:
    """更新白名单用户备注。"""
    try:
        body = await request.json()
        remark = body.get("remark", "")
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return JSONResponse({"error": "whitelist not available"}, status_code=503)
        ok = comp.qq_whitelist.update_remark(qq_number, remark)
        return {"status": "ok", "updated": ok}
    except Exception as e:
        logger.exception("qq whitelist remark error")
        return {"error": str(e)}


@app.put("/api/qq/whitelist/enabled")
async def qq_whitelist_set_enabled(request: Request) -> dict:
    """启用/禁用白名单机制。"""
    try:
        body = await request.json()
        enabled = body.get("enabled", True)
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return JSONResponse({"error": "whitelist not available"}, status_code=503)
        comp.qq_whitelist.set_enabled(enabled)
        emit("qq_whitelist_changed", action="enabled_changed", enabled=enabled)
        return {"status": "ok", "enabled": enabled}
    except Exception as e:
        logger.exception("qq whitelist set enabled error")
        return {"error": str(e)}


@app.post("/api/qq/whitelist/bulk")
async def qq_whitelist_bulk_add(request: Request) -> dict:
    """批量添加白名单。"""
    try:
        body = await request.json()
        qq_numbers = body.get("qq_numbers", [])
        remark_prefix = body.get("remark_prefix", "")
        if not isinstance(qq_numbers, list):
            return JSONResponse({"error": "qq_numbers must be array"}, status_code=400)
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return JSONResponse({"error": "whitelist not available"}, status_code=503)
        count = comp.qq_whitelist.bulk_add(qq_numbers, remark_prefix)
        emit("qq_whitelist_changed", action="bulk_add", count=count)
        return {"status": "ok", "added_count": count, "total": len(qq_numbers)}
    except Exception as e:
        logger.exception("qq whitelist bulk add error")
        return {"error": str(e)}


@app.delete("/api/qq/whitelist")
async def qq_whitelist_clear() -> dict:
    """清空白名单（恢复兼容模式）。"""
    try:
        from core.companion import get_companion
        comp = get_companion()
        if not comp or not comp.qq_whitelist:
            return JSONResponse({"error": "whitelist not available"}, status_code=503)
        ok = comp.qq_whitelist.clear()
        emit("qq_whitelist_changed", action="clear")
        return {"status": "ok", "cleared": ok}
    except Exception as e:
        logger.exception("qq whitelist clear error")
        return {"error": str(e)}


# ── Office Mode (v13.0) ────────────────────────────

@app.get("/api/office/mode")
async def office_mode_get() -> dict:
    """Get current office mode and context."""
    try:
        from core.office_mode import get_office_mode_manager
        mgr = get_office_mode_manager()
        ctx = mgr.get_context()
        return {
            "mode": ctx.mode.value,
            "detected_mode": ctx.detected_mode.value if ctx.detected_mode else None,
            "is_office": ctx.is_office_mode(),
            "task_type": ctx.task_type.value if ctx.task_type else None,
            "task_keywords": ctx.task_keywords,
            "confidence": ctx.confidence,
            "preferred_provider": mgr.get_preferred_provider(),
        }
    except Exception as e:
        logger.exception("office mode get error")
        return {"error": str(e)}


@app.put("/api/office/mode")
async def office_mode_set(request: Request) -> dict:
    """Set office mode: chat / office / auto."""
    try:
        body = await request.json()
        mode_str = (body.get("mode") or "auto").lower()
        valid_modes = {"chat", "office", "auto"}
        if mode_str not in valid_modes:
            return JSONResponse({"error": "invalid mode"}, status_code=400)

        from core.office_mode import get_office_mode_manager
        mgr = get_office_mode_manager()
        mgr.set_mode(mode_str)

        emit("office_mode_changed", mode=mode_str)
        return {"status": "ok", "mode": mode_str}
    except Exception as e:
        logger.exception("office mode set error")
        return {"error": str(e)}


@app.post("/api/office/detect")
async def office_mode_detect(request: Request) -> dict:
    """Detect office mode from a message."""
    try:
        body = await request.json()
        message = body.get("message", "") or ""
        history = body.get("history") or []

        from core.office_mode import get_office_mode_manager
        mgr = get_office_mode_manager()
        ctx = mgr.detect(message, history)

        return {
            "is_office": ctx.is_office_mode(),
            "detected_mode": ctx.detected_mode.value if ctx.detected_mode else None,
            "task_type": ctx.task_type.value if ctx.task_type else None,
            "task_keywords": ctx.task_keywords,
            "confidence": ctx.confidence,
        }
    except Exception as e:
        logger.exception("office mode detect error")
        return {"error": str(e)}


@app.get("/api/office/device")
async def office_device_info(request: Request) -> dict:
    """Detect device type from User-Agent."""
    try:
        ua = request.headers.get("user-agent", "")
        from core.office_mode import detect_device
        device_info = detect_device(ua)
        return device_info
    except Exception as e:
        logger.exception("device detect error")
        return {"error": str(e)}


@app.get("/api/office/dir")
async def office_dir_get() -> dict:
    """获取当前办公文件保存目录。"""
    try:
        from core.office_tools import get_office_dir
        p = get_office_dir()
        return {
            "success": True,
            "path": str(p),
            "exists": p.exists(),
        }
    except Exception as e:
        logger.exception("office dir get error")
        return {"success": False, "error": str(e)}


@app.put("/api/office/dir")
async def office_dir_set(request: Request) -> dict:
    """设置办公文件保存目录。"""
    try:
        body = await request.json()
        path = body.get("path", "") or ""
        if not path:
            return JSONResponse(
                {"success": False, "error": "路径不能为空"},
                status_code=400,
            )
        from core.office_tools import set_office_dir
        result = set_office_dir(path)
        if result.get("success"):
            emit("office_dir_changed", path=result["path"])
        return result
    except Exception as e:
        logger.exception("office dir set error")
        return {"success": False, "error": str(e)}


# ── Response Validator ────────────────────────────

@app.post("/api/validation/check")
async def validation_check(request: Request) -> dict:
    """校验回复文本的准确性与质量"""
    try:
        body = await request.json()
        text = body.get("text", "") or ""
        user_message = body.get("user_message", "") or ""
        office_mode = bool(body.get("office_mode", False))
        persona_style = body.get("persona_style", "warm")

        from core.response_validator import get_response_validator
        validator = get_response_validator()
        # 同步兼容旧字段：office_mode / persona_style 走 kwargs，不改校验语义
        result = await validator.validate(
            text,
            user_message=user_message,
            persona_hint=persona_style,
            route_mode="OFFICE" if office_mode else "FULL",
        )

        return {
            "passed": result.passed,
            "score": result.judge_score,
            "guard_score": 1.0 if result.guard_passed else 0.0,
            "judge_score": result.judge_score,
            "issues": [
                {
                    "code": i.get("category", "unknown"),
                    "severity": i.get("level", "info"),
                    "message": i.get("message", ""),
                    "layer": "guard" if str(i.get("category", "")).startswith("sensitive") or i.get("category") == "empty_reply" else "judge",
                    "details": i,
                }
                for i in result.issues
            ],
            "needs_revision": False,
            "revision_suggestion": "",
            "content_policy": "unrestricted_expression",
        }
    except Exception as e:
        logger.exception("validation check error")
        return {"error": str(e)}


@app.get("/api/validation/config")
async def validation_config() -> dict:
    """获取校验配置状态"""
    try:
        from core.response_validator import get_response_validator
        validator = get_response_validator()
        return {
            "enabled": True,
            "guard_rules": [
                "empty_reply",  # 仅结构检查；内容主题已解放
            ],
            "judge_dimensions": [
                "length",
                "relevance",
                "tone_consistency",
                "emotion_value",
            ],
            "content_policy": "unrestricted_expression",
        }
    except Exception as e:
        logger.exception("validation config error")
        return {"error": str(e)}


# ── Proactive Push ────────────────────────────

@app.get("/api/proactive/status")
async def proactive_status() -> dict:
    """获取主动推送状态"""
    try:
        from core.push_event_engine import get_event_engine
        engine = get_event_engine()
        status = engine.get_status()

        # 尝试获取 scheduler 状态
        try:
            from core.companion import get_companion
            comp = get_companion()
            if hasattr(comp, "push_scheduler") and comp.push_scheduler:
                sched = comp.push_scheduler
                status["scheduler"] = {
                    "running": sched.running,
                    "scene_count": len(sched.scenes),
                    "daily_count": sched.policy.daily_count,
                }
        except Exception:
            pass

        return status
    except Exception as e:
        logger.exception("proactive status error")
        return {"error": str(e)}


@app.get("/api/proactive/scenes")
async def proactive_scenes() -> dict:
    """获取所有推送场景列表"""
    try:
        from core.companion import get_companion
        comp = get_companion()
        scenes = {}
        if hasattr(comp, "push_scheduler") and comp.push_scheduler:
            sched = comp.push_scheduler
            for name, cfg in sched.scenes.items():
                scenes[name] = {
                    "cron": cfg.get("cron"),
                    "trigger": cfg.get("trigger"),
                    "mood_aware": cfg.get("mood_aware", False),
                    "exempt_quiet": cfg.get("exempt_quiet", False),
                    "custom_dispatcher": cfg.get("custom_dispatcher"),
                    "template": cfg.get("template", ""),
                }
        return {"scenes": scenes}
    except Exception as e:
        logger.exception("proactive scenes error")
        return {"error": str(e)}


@app.post("/api/proactive/trigger")
async def proactive_trigger(request: Request) -> dict:
    """手动触发推送场景"""
    try:
        body = await request.json()
        scene = body.get("scene", "")

        from core.companion import get_companion
        comp = get_companion()
        if hasattr(comp, "push_scheduler") and comp.push_scheduler:
            success = await comp.push_scheduler.trigger(scene)
            return {"success": success, "scene": scene}
        return {"success": False, "error": "scheduler not available"}
    except Exception as e:
        logger.exception("proactive trigger error")
        return {"error": str(e)}


@app.post("/api/proactive/toggle")
async def proactive_toggle(request: Request) -> dict:
    """开关主动推送"""
    try:
        body = await request.json()
        enabled = bool(body.get("enabled", True))

        from core.companion import get_companion
        comp = get_companion()
        if hasattr(comp, "push_scheduler") and comp.push_scheduler:
            policy = comp.push_scheduler.policy
            if hasattr(policy, "set_enabled"):
                policy.set_enabled(enabled)
            else:
                policy.enabled = enabled
            return {"enabled": enabled}
        return {"error": "scheduler not available"}
    except Exception as e:
        logger.exception("proactive toggle error")
        return {"error": str(e)}


def _current_proactive_policy():
    from core.companion import get_companion

    comp = get_companion()
    if not hasattr(comp, "push_scheduler") or not comp.push_scheduler:
        return None
    return getattr(comp.push_scheduler, "policy", None)


@app.get("/api/proactive/policy")
async def proactive_policy() -> dict:
    """Return persistent proactive policy state for settings UI."""
    try:
        policy = _current_proactive_policy()
        if not policy:
            return {"error": "scheduler not available"}
        if hasattr(policy, "snapshot"):
            return {"policy": policy.snapshot()}
        return {
            "policy": {
                "enabled": bool(getattr(policy, "enabled", False)),
                "daily_count": int(getattr(policy, "daily_count", 0)),
            }
        }
    except Exception as e:
        logger.exception("proactive policy error")
        return {"error": str(e)}


@app.post("/api/proactive/feedback")
async def proactive_feedback(request: Request) -> dict:
    """Record user feedback for a proactive scene."""
    try:
        body = await request.json()
        scene = str(body.get("scene") or "")
        if not scene:
            return {"error": "scene required"}
        action = str(body.get("action") or "negative")
        hours = body.get("hours")

        policy = _current_proactive_policy()
        if not policy or not hasattr(policy, "record_feedback"):
            return {"error": "scheduler not available"}
        kwargs = {}
        if hours is not None:
            kwargs["hours"] = float(hours)
        return policy.record_feedback(scene, action, **kwargs)
    except Exception as e:
        logger.exception("proactive feedback error")
        return {"error": str(e)}


@app.post("/api/proactive/mute")
async def proactive_mute(request: Request) -> dict:
    """Mute proactive delivery globally for a bounded window."""
    try:
        body = await request.json()
        hours = float(body.get("hours", 12))
        policy = _current_proactive_policy()
        if not policy or not hasattr(policy, "mute"):
            return {"error": "scheduler not available"}
        return policy.mute(hours=hours)
    except Exception as e:
        logger.exception("proactive mute error")
        return {"error": str(e)}


@app.post("/api/proactive/postpone")
async def proactive_postpone(request: Request) -> dict:
    """Postpone one proactive scene for a bounded window."""
    try:
        body = await request.json()
        scene = str(body.get("scene") or "")
        if not scene:
            return {"error": "scene required"}
        hours = float(body.get("hours", 2))
        policy = _current_proactive_policy()
        if not policy or not hasattr(policy, "postpone"):
            return {"error": "scheduler not available"}
        return policy.postpone(scene, hours=hours)
    except Exception as e:
        logger.exception("proactive postpone error")
        return {"error": str(e)}


@app.get("/api/proactive/events")
async def proactive_events(limit: int = 20) -> dict:
    """获取最近的事件历史"""
    try:
        from core.push_event_engine import get_event_engine
        engine = get_event_engine()
        history = engine.bus.get_history(limit=limit)
        return {
            "events": [
                {
                    "type": e.event_type.value,
                    "source": e.source,
                    "priority": e.priority,
                    "timestamp": e.timestamp.isoformat(),
                    "payload": e.payload,
                }
                for e in history
            ]
        }
    except Exception as e:
        logger.exception("proactive events error")
        return {"error": str(e)}


# ── File Organizer ──────────────────────────────────

@app.get("/api/file_organizer/stats")
async def file_organizer_stats() -> dict:
    """File organizer statistics."""
    try:
        records = _file_organizer.list_undo_records(limit=200)
        total_organized = len(records)
        undoable = sum(1 for r in records if r.get("can_undo", False))
        return {
            "total_organized": total_organized,
            "undoable": undoable,
            "saved_space_bytes": 0,
        }
    except Exception as e:
        logger.exception("file_organizer_stats error")
        return {"error": str(e)}


@app.get("/api/file_organizer/history")
async def file_organizer_history(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """File organizer history."""
    try:
        records = _file_organizer.list_undo_records(limit=limit)
        return {"records": records}
    except Exception as e:
        logger.exception("file_organizer_history error")
        return {"error": str(e)}


@app.get("/api/file_organizer/undo_list")
async def file_organizer_undo_list(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """Undoable file organizer operations."""
    try:
        records = _file_organizer.list_undo_records(limit=limit)
        undoable = [r for r in records if r.get("can_undo", False)]
        return {"records": undoable}
    except Exception as e:
        logger.exception("file_organizer_undo_list error")
        return {"error": str(e)}


def _validate_source_dir(source_dir: str) -> str | None:
    """校验源目录存在且为目录，返回错误信息（合法返回 None）。"""
    if not source_dir or not str(source_dir).strip():
        return "source_dir 不能为空"
    p = Path(source_dir).expanduser()
    if not p.exists() or not p.is_dir():
        return f"目录不存在或不是目录: {source_dir}"
    return None


@app.post("/api/file_organizer/quick_organize")
async def file_organizer_quick_organize(request: Request):
    """一键整理（按类别归档），用于图片/文档/视频整理按钮。"""
    body = await request.json()
    source_dir = body.get("source_dir")
    err = _validate_source_dir(source_dir)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    target_dir = body.get("target_dir")
    recursive = bool(body.get("recursive", False))

    plan = _file_organizer.preview_organize(source_dir, target_dir, recursive)

    # 按类别过滤：仅整理指定类别的文件
    category = body.get("category")
    if category and plan.actions:
        plan.actions = [a for a in plan.actions if a.category.value == category]
        plan.files = [f for f in plan.files if f.category.value == category]

    if not plan.actions:
        return {"success": False, "message": "没有需要整理的文件", "plan": plan.to_dict()}

    ok, message, undo_id = _file_organizer.execute_organize(
        plan, description=f"一键整理 {Path(source_dir).name}",
    )
    return {"success": ok, "message": message, "undo_id": undo_id,
            "plan": plan.to_dict(), "source_dir": source_dir}


@app.post("/api/file_organizer/quick_dedup")
async def file_organizer_quick_dedup(request: Request):
    """一键去重（哈希去重，保留最新副本，多余的移入回收目录）。"""
    body = await request.json()
    source_dir = body.get("source_dir")
    err = _validate_source_dir(source_dir)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    recursive = bool(body.get("recursive", False))
    keep = body.get("keep", "newest")
    if keep not in ("newest", "oldest"):
        keep = "newest"

    plan = _file_organizer.preview_dedup(source_dir, recursive=recursive, keep=keep)
    if not plan.actions:
        return {"success": False, "message": "没有发现重复文件",
                "plan": plan.to_dict(), "source_dir": source_dir}

    ok, message, undo_id = _file_organizer.execute_cleanup(
        plan, description=f"去重 {Path(source_dir).name}",
    )
    return {"success": ok, "message": message, "undo_id": undo_id,
            "plan": plan.to_dict(), "source_dir": source_dir}


@app.post("/api/file_organizer/quick_cleanup")
async def file_organizer_quick_cleanup(request: Request):
    """一键过期清理（按 mtime 清理 N 天未使用文件）。"""
    body = await request.json()
    source_dir = body.get("source_dir")
    err = _validate_source_dir(source_dir)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    recursive = bool(body.get("recursive", False))
    try:
        older_than_days = max(1, int(body.get("older_than_days", 30)))
    except (TypeError, ValueError):
        older_than_days = 30

    plan = _file_organizer.preview_expired_cleanup(
        source_dir, older_than_days=older_than_days, recursive=recursive,
    )
    if not plan.actions:
        return {"success": False, "message": "没有过期文件需要清理",
                "plan": plan.to_dict(), "source_dir": source_dir}

    ok, message, undo_id = _file_organizer.execute_cleanup(
        plan, description=f"过期清理 {Path(source_dir).name}",
    )
    return {"success": ok, "message": message, "undo_id": undo_id,
            "plan": plan.to_dict(), "source_dir": source_dir}


@app.post("/api/file_organizer/preview_cleanup")
async def file_organizer_preview_cleanup(request: Request):
    """预览清理计划（不执行），用于前端展示确认。"""
    body = await request.json()
    source_dir = body.get("source_dir")
    err = _validate_source_dir(source_dir)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    mode = body.get("mode", "downloads")
    recursive = bool(body.get("recursive", False))
    try:
        older_than_days = max(1, int(body.get("older_than_days", 30)))
    except (TypeError, ValueError):
        older_than_days = 30

    if mode == "dedup":
        plan = _file_organizer.preview_dedup(source_dir, recursive=recursive)
    elif mode == "expired":
        plan = _file_organizer.preview_expired_cleanup(
            source_dir, older_than_days=older_than_days, recursive=recursive,
        )
    else:
        plan = _file_organizer.preview_downloads_cleanup(
            source_dir, older_than_days=older_than_days, recursive=recursive,
        )

    return {"success": True, "plan": plan.to_dict(), "source_dir": source_dir}


@app.post("/api/file_organizer/undo")
async def file_organizer_undo(request: Request):
    """撤销一次整理/清理操作。"""
    body = await request.json()
    undo_id = body.get("undo_id")
    if not undo_id:
        return JSONResponse({"error": "undo_id 不能为空"}, status_code=400)
    ok, message, count = _file_organizer.undo(undo_id)
    return {"success": ok, "message": message, "restored": count}


# ── Doc Writer ──────────────────────────────────────

@app.get("/api/doc_writer/stats")
async def doc_writer_stats() -> dict:
    """Document writer statistics."""
    try:
        docs = _doc_writer.list_documents()
        return {"total_documents": len(docs)}
    except Exception as e:
        logger.exception("doc_writer_stats error")
        return {"error": str(e)}


@app.get("/api/doc_writer/list")
async def doc_writer_list(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """List recent documents."""
    try:
        docs = _doc_writer.list_documents()
        docs = docs[:limit]
        result = []
        for d in docs:
            result.append({
                "name": d.name,
                "path": str(d),
                "size": d.stat().st_size if d.exists() else 0,
                "modified": d.stat().st_mtime if d.exists() else 0,
                "format": d.suffix.lstrip(".").upper(),
            })
        return {"documents": result}
    except Exception as e:
        logger.exception("doc_writer_list error")
        return {"error": str(e)}


def _resolve_doc_type(raw: str) -> DocType:
    """将字符串解析为 DocType，非法值抛 ValueError。"""
    try:
        return DocType(raw)
    except ValueError:
        raise ValueError(
            f"未知文档类型: {raw}，可选: {', '.join(t.value for t in DocType)}"
        )


def _resolve_export_format(raw: str) -> ExportFormat:
    """将字符串解析为 ExportFormat，非法值抛 ValueError。"""
    try:
        return ExportFormat(raw)
    except ValueError:
        raise ValueError(
            f"未知导出格式: {raw}，可选: {', '.join(f.value for f in ExportFormat)}"
        )


def _resolve_style(raw: str) -> str:
    """校验 HTML 样式，仅支持 default/elegant/minimal。"""
    if raw not in ("default", "elegant", "minimal"):
        return "default"
    return raw


@app.post("/api/doc_writer/create")
async def doc_writer_create(request: Request):
    """创建文档对象（不落盘，返回文档结构 + 默认字段）。"""
    body = await request.json()
    try:
        doc_type = _resolve_doc_type(body.get("doc_type", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    title = body.get("title", "").strip()
    if not title:
        return JSONResponse({"error": "title 不能为空"}, status_code=400)

    doc = _doc_writer.create_document(
        doc_type=doc_type,
        title=title,
        fields=body.get("fields") or {},
        content=body.get("content", ""),
    )
    return {
        "success": True,
        "document": doc.to_dict(),
        "default_fields": _doc_writer.get_template_fields(doc_type),
        "templates": [t.value for t in DocType],
    }


@app.post("/api/doc_writer/render")
async def doc_writer_render(request: Request):
    """渲染文档为指定格式的字符串（预览，不落盘）。

    fmt: md/html/pdf/docx；style: default/elegant/minimal（仅 HTML 生效）。
    PDF/DOCX 无对应依赖时由后端回退为 HTML/Markdown 内容。
    """
    body = await request.json()
    try:
        doc_type = _resolve_doc_type(body.get("doc_type", ""))
        fmt = _resolve_export_format(body.get("fmt", "md"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    title = body.get("title", "").strip() or "未命名文档"
    doc = _doc_writer.create_document(
        doc_type=doc_type,
        title=title,
        fields=body.get("fields") or {},
        content=body.get("content", ""),
    )
    style = _resolve_style(body.get("style", "default"))

    try:
        if fmt in (ExportFormat.PDF, ExportFormat.DOCX):
            # 预览态：渲染为对应回退内容字符串
            if fmt == ExportFormat.PDF:
                content = doc.render_html(style=style)
                actual_format = "html"
            else:
                content = doc.render_markdown()
                actual_format = "md"
        else:
            content = _doc_writer.render(doc, fmt, style)
            actual_format = fmt.value
        return {"success": True, "format": actual_format, "content": content,
                "document": doc.to_dict()}
    except Exception as e:
        logger.exception("doc_writer_render error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/doc_writer/export")
async def doc_writer_export(request: Request):
    """导出文档为文件，落盘到 data/documents。

    fmt: md/html/pdf/docx；style: default/elegant/minimal（仅 HTML 生效）。
    PDF/DOCX 依赖缺失时回退为 HTML/Markdown 文件并标注 actual_format。
    """
    body = await request.json()
    try:
        doc_type = _resolve_doc_type(body.get("doc_type", ""))
        fmt = _resolve_export_format(body.get("fmt", "md"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    title = body.get("title", "").strip() or "未命名文档"
    doc = _doc_writer.create_document(
        doc_type=doc_type,
        title=title,
        fields=body.get("fields") or {},
        content=body.get("content", ""),
    )
    style = _resolve_style(body.get("style", "default"))
    filename = body.get("filename")

    try:
        filepath = _doc_writer.export(doc, fmt, filename=filename, style=style)
        actual_format = filepath.suffix.lstrip(".").lower()
        return {
            "success": True,
            "requested_format": fmt.value,
            "actual_format": actual_format,
            "name": filepath.name,
            "path": str(filepath),
            "size": filepath.stat().st_size if filepath.exists() else 0,
        }
    except Exception as e:
        logger.exception("doc_writer_export error")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Calendar ────────────────────────────────────────

@app.get("/api/calendar/events")
async def calendar_events(
    start: str = Query(default=None),
    end: str = Query(default=None),
    event_type: str = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: int | None = Query(default=None),
) -> dict:
    """List calendar events in a date range."""
    try:
        events = _calendar.list_events(
            start_date=start, end_date=end,
            event_type=event_type, limit=limit, user_id=user_id,
        )
        return {"events": events}
    except Exception as e:
        logger.exception("calendar_events error")
        return JSONResponse({"error": str(e), "code": "calendar_list_failed"}, status_code=500)


@app.get("/api/calendar/timeline")
async def calendar_timeline(start: str = Query(...), end: str = Query(...), user_id: int | None = Query(default=None)) -> dict:
    try:
        return _calendar.get_timeline(start, end, user_id)
    except ValueError as e:
        return JSONResponse({"error": str(e), "code": "invalid_range"}, status_code=400)
    except Exception as e:
        logger.exception("calendar_timeline error")
        return JSONResponse({"error": str(e), "code": "timeline_failed"}, status_code=500)


@app.get("/api/calendar/events/{event_id}")
async def calendar_event_detail(event_id: int) -> dict:
    """Get a single calendar event."""
    try:
        event = _calendar.get_event(event_id)
        if not event:
            return JSONResponse({"error": "not found"}, status_code=404)
        return event
    except Exception as e:
        return JSONResponse({"error": str(e), "code": "calendar_detail_failed"}, status_code=500)


@app.post("/api/calendar/events")
async def calendar_create(request: Request) -> dict:
    """Create a new calendar event."""
    try:
        body = await request.json()
        event_id = _calendar.create_event(**body)
        event = _calendar.get_event(event_id)
        emit("calendar_event_created", id=event_id, event=event)
        emit("timeline_changed", date=event["start_time"][:10], kind="event", action="created", id=f"event:{event_id}")
        return {"status": "ok", "id": event_id, "event": event}
    except ValueError as e:
        return JSONResponse({"error": str(e), "code": "invalid_event"}, status_code=400)
    except Exception as e:
        logger.exception("calendar_create error")
        return JSONResponse({"error": str(e), "code": "calendar_create_failed"}, status_code=500)


@app.put("/api/calendar/events/{event_id}")
async def calendar_update(event_id: int, request: Request) -> dict:
    """Update a calendar event."""
    try:
        body = await request.json()
        ok = _calendar.update_event(event_id, **body)
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
        emit("calendar_event_updated", id=event_id)
        event = _calendar.get_event(event_id)
        emit("timeline_changed", date=event["start_time"][:10], kind="event", action="updated", id=f"event:{event_id}")
        return {"status": "ok"}
    except ValueError as e:
        return JSONResponse({"error": str(e), "code": "invalid_event"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e), "code": "calendar_update_failed"}, status_code=500)


@app.delete("/api/calendar/events/{event_id}")
async def calendar_delete(event_id: int) -> dict:
    """Delete a calendar event."""
    try:
        event = _calendar.get_event(event_id)
        ok = _calendar.delete_event(event_id)
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
        emit("calendar_event_deleted", id=event_id)
        emit("timeline_changed", date=event["start_time"][:10], kind="event", action="deleted", id=f"event:{event_id}")
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e), "code": "calendar_delete_failed"}, status_code=500)


@app.get("/api/calendar/stats")
async def calendar_stats() -> dict:
    """Calendar statistics and upcoming events."""
    try:
        return _calendar.get_stats()
    except Exception as e:
        logger.exception("calendar_stats error")
        return JSONResponse({"error": str(e), "code": "calendar_stats_failed"}, status_code=500)


@app.get("/api/calendar/companion")
async def calendar_companion() -> dict:
    """Companion stats: days together, message counts, etc."""
    try:
        return _calendar.get_companion_stats()
    except Exception as e:
        logger.exception("calendar_companion error")
        return JSONResponse({"error": str(e), "code": "calendar_companion_failed"}, status_code=500)


# ── Stats ───────────────────────────────────────────

@app.get("/api/stats/tokens")
async def stats_tokens(user_id: int | None = Query(default=None)) -> dict:
    if user_id is None:
        # 所有 LLM 调用统一记录在 user_id=0（全局），见 llm_caller.chat()。
        # 不能再按 primary user_id 查询，否则与写入的 user_id=0 不匹配，导致统计恒为 0。
        user_id = 0
    tracker = get_token_tracker()
    try:
        today = tracker.get_today(user_id)
        week = tracker.get_week(user_id)
        by_provider = tracker.get_by_provider(user_id)
        return {
            "today": today,
            "week": week,
            "by_provider": by_provider,
            "user_id": user_id,
        }
    except Exception as e:
        return {"error": str(e)}


# ── Settings ─────────────────────────────────────────

@app.get("/api/settings")
async def settings_get() -> dict:
    """Return current merged settings (YAML + defaults)."""
    try:
        result = load_settings()
    except Exception as e:
        return {"error": str(e)}

    # Attach live proactive image budget readout (read-only, best-effort).
    try:
        comp = get_companion()
        consumer = getattr(comp, "world_image_candidate_consumer", None)
        budget = getattr(consumer, "image_budget", None)
        if budget is not None and hasattr(budget, "snapshot"):
            snap = budget.snapshot()
            pro = snap.get("proactive", {}) or {}
            if isinstance(result, dict):
                result.setdefault("proactive", {})["image_used_today"] = int(pro.get("used", 0))
                if "image_max_per_day" not in result["proactive"]:
                    result["proactive"]["image_max_per_day"] = int(pro.get("limit", 0))
    except Exception:
        logger.debug("settings_get: proactive image budget readout failed", exc_info=True)
    return result



@app.put("/api/settings")
async def settings_put(request: Request) -> dict:
    """Update settings (partial merge)."""
    try:
        body = await request.json()
        if isinstance(body, dict):
            # 统一世界位置与天气城市：两者之一非空时同步到另一个，
            # 避免世界位置与天气各用各的城市导致"改了没生效"。
            world_loc = ""
            weather_city = ""
            if isinstance(body.get("world"), dict):
                world_loc = str(body["world"].get("location") or "").strip()
            if isinstance(body.get("weather"), dict):
                weather_city = str(body["weather"].get("city") or "").strip()
            if world_loc and not weather_city:
                body.setdefault("weather", {})["city"] = world_loc
                weather_city = world_loc
            if weather_city and not world_loc:
                body.setdefault("world", {})["location"] = weather_city
        save_settings(body)
        if isinstance(body, dict) and isinstance(body.get("weather"), dict) and "city" in body["weather"]:
            try:
                from core.location_resolver import clear_city_cache
                clear_city_cache()
            except Exception as e:
                logger.warning("settings_put: location cache clear failed: %s", e)
        # 热更新：proactive 频控设置立即作用于运行中的 PushPolicy，
        # 无需重启（仅当 running policy 存在且本次提交携带相关字段）。
        if isinstance(body, dict) and isinstance(body.get("proactive"), dict):
            try:
                from core.companion import get_companion
                _comp = get_companion()
                _pol = getattr(_comp, "push_scheduler", None)
                if _pol is not None:
                    _pol = getattr(_pol, "policy", None)
                _p = body.get("proactive", {})
                if _pol is not None:
                    if _p.get("max_per_day") is not None:
                        _pol.max_per_day = int(_p["max_per_day"])
                    if _p.get("min_interval_min") is not None:
                        _pol.min_interval_min = int(_p["min_interval_min"])
                # 热更新：发图每日上限 → 运行中的 ImageBudget（0=不限制），即时生效。
                if _p.get("image_max_per_day") is not None:
                    _consumer = getattr(_comp, "world_image_candidate_consumer", None)
                    _budget = getattr(_consumer, "image_budget", None)
                    if _budget is not None and hasattr(_budget, "set_limit"):
                        _budget.set_limit("proactive", int(_p["image_max_per_day"]))
            except Exception:
                logger.warning("settings_put: hot-apply proactive frequency failed", exc_info=True)
        # 热更新：L4 自进化内测开关 → 立即作用于运行中的 SelfEvolver（无需重启）。
        if (
            isinstance(body, dict)
            and isinstance(body.get("feature_flags"), dict)
            and "self_evolve_l4_enabled" in body["feature_flags"]
        ):
            try:
                from core.companion import get_companion
                _comp = get_companion()
                _ev = getattr(_comp, "self_evolver", None)
                if _ev is not None and hasattr(_ev, "enabled"):
                    _ev.enabled = bool(body["feature_flags"]["self_evolve_l4_enabled"])
                    logger.info(
                        "settings_put: self_evolve_l4_enabled hot-applied -> %s",
                        _ev.enabled,
                    )
            except Exception:
                logger.warning("settings_put: hot-apply l4 toggle failed", exc_info=True)
        # 热更新：DSH 工作模式委托开关 → 立即热切换运行中的 Pipeline(无需重启)。
        if isinstance(body, dict) and isinstance(body.get("dsh"), dict) and "enabled" in body["dsh"]:
            try:
                from core.companion import get_companion
                _comp = get_companion()
                _pipeline = getattr(_comp, "pipeline", None)
                if _pipeline is not None and hasattr(_pipeline, "set_dsh_enabled"):
                    _ok = await _pipeline.set_dsh_enabled(bool(body["dsh"]["enabled"]))
                    logger.info(
                        "settings_put: dsh.enabled hot-applied -> %s (ok=%s)",
                        body["dsh"]["enabled"], _ok,
                    )
            except Exception:
                logger.warning("settings_put: hot-apply dsh toggle failed", exc_info=True)
        return {"status": "ok", "saved": list(body.keys())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/dsh/status")
async def dsh_status() -> dict:
    """返回运行中 Pipeline 的 DSH 委托状态(供测试脚本/设置页验证热加载)。"""
    from core.companion import get_companion

    comp = get_companion()
    pipeline = getattr(comp, "pipeline", None)
    if pipeline is None:
        return {"enabled": False, "initialized": False, "running": False, "error": "no pipeline"}
    cli = getattr(pipeline, "_dsh_cli", None)
    running = False
    if cli is not None:
        try:
            st = await cli.status()
            running = bool(st.get("running"))
        except Exception:
            running = False
    return {
        "enabled": bool(getattr(pipeline, "_dsh_enabled", False)),
        "initialized": cli is not None,
        "running": running,
    }


# ── v0.4.1: 工作区管理 API(文件树/缩略图/打开/操作日志) ──────────────


def _ws() -> Any:
    """延迟获取工作区管理器单例(避免模块导入时读 YAML)。"""
    from core.workspace import get_workspace_manager

    return get_workspace_manager()


@app.get("/api/workspace/roots")
async def workspace_roots() -> dict:
    """列出全部工作区根目录 + 当前激活目录(带来源标记)。"""
    return {
        "roots": _ws().roots(),
        "roots_info": _ws().roots_info(),
        "active_root": _ws().active_root(),
        "activities": _ws().activities(limit=10),
    }


@app.post("/api/workspace/active")
async def workspace_set_active(request: Request) -> dict:
    """把某已注册目录设为当前激活工作区(Agent 感知的操作范围)。"""
    body = await request.json()
    path = str(body.get("path", "")).strip()
    if not path:
        return {"ok": False, "error": "path required"}
    active = _ws().set_active_root(path)
    return {"ok": True, "active_root": active}


@app.get("/api/workspace/permission")
async def workspace_permission() -> dict:
    """返回工作区权限状态(与电脑操控共用): mode + 四级语义说明。"""
    ws = _ws()
    mode = ""
    try:
        from core.computer_control import ControlMode

        if ws._access_policy is not None:
            mode = getattr(ws._access_policy, "mode", None)
            mode = mode.value if hasattr(mode, "value") else str(mode)
        else:
            mode = ControlMode.MANUAL.value
    except Exception:
        mode = "manual"
    levels = [
        {"mode": "manual", "label": "手动审批", "desc": "所有写操作需你确认"},
        {"mode": "auto", "label": "自动批阅", "desc": "低风险放行，中高风险需确认"},
        {"mode": "full", "label": "完全访问", "desc": "写操作全部放行"},
        {"mode": "custom", "label": "自定义", "desc": "按名单/规则放行或拦截"},
    ]
    return {
        "mode": mode,
        "scope": "write",  # 仅写操作(移动/删除/改名/生成)受权限约束;浏览/打开永远放行
        "levels": levels,
    }


@app.get("/api/workspace/tree")
async def workspace_tree(path: str = "") -> dict:
    """扫描某目录返回直接子项(懒加载,不递归)。"""
    try:
        return _ws().tree(path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/api/workspace/thumbnail")
async def workspace_thumbnail(path: str = "", size: int = 160) -> Response:
    """返回图片缩略图 PNG;非图片/越界返回 404。"""
    data = _ws().thumbnail(path, size=size)
    if data is None:
        return Response(status_code=404)
    return Response(content=data, media_type="image/png")


@app.post("/api/workspace/open")
async def workspace_open(request: Request) -> dict:
    """用系统默认程序打开文件 / 资源管理器打开文件夹(仅限工作区内)。"""
    body = await request.json()
    path = str(body.get("path", "")).strip()
    if not path:
        return {"ok": False, "error": "path required"}
    ok, msg = _ws().open_path(path)
    return {"ok": ok, "message": msg}


@app.get("/api/workspace/activities")
async def workspace_activities(limit: int = 50) -> dict:
    """工作区操作日志时间线(倒序)。"""
    return {"activities": _ws().activities(limit=limit)}


@app.post("/api/workspace/activities/clear")
async def workspace_activities_clear() -> dict:
    """清空工作区操作日志。"""
    _ws().clear_activities()
    return {"ok": True}


@app.post("/api/workspace/roots/temp")
async def workspace_add_temp(request: Request) -> dict:
    """手动把某目录注册为自定义工作区(持久化)。"""
    body = await request.json()
    path = str(body.get("path", "")).strip()
    if not path:
        return {"ok": False, "error": "path required"}
    added = _ws().add_temp_root(path)
    return {"ok": True, "added": added, "roots_info": _ws().roots_info()}


@app.post("/api/workspace/roots/remove")
async def workspace_remove_temp(request: Request) -> dict:
    """移除一个自定义工作区目录(预设根不可移除)。"""
    body = await request.json()
    path = str(body.get("path", "")).strip()
    if not path:
        return {"ok": False, "error": "path required"}
    removed = _ws().remove_temp_root(path)
    return {"ok": True, "removed": removed, "roots_info": _ws().roots_info()}


@app.post("/api/settings/reset")
async def settings_reset() -> dict:
    """Reset settings to defaults."""
    try:
        settings = reset_settings()
        return {"status": "ok", "settings": settings}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── v13.9.9: API Key management & self-check ──

_PROVIDER_META = [
    {"key": "deepseek", "name": "DeepSeek", "env_key": "DEEPSEEK_API_KEY",
     "env_url": "DEEPSEEK_BASE_URL", "env_model": "DEEPSEEK_MODEL",
     "default_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat",
     "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"key": "dashscope", "name": "通义千问 (DashScope)", "env_key": "DASHSCOPE_API_KEY",
     "env_url": "QWEN_BASE_URL", "env_model": "QWEN_MODEL",
     "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus",
     "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long", "qwen3-max"]},
    {"key": "doubao", "name": "豆包 (Doubao)", "env_key": "DOUBAO_API_KEY",
     "env_url": "DOUBAO_BASE_URL", "env_model": "DOUBAO_MODEL",
     "default_url": "https://ark.cn-beijing.volces.com/api/v3", "default_model": "doubao-seed-2-1-turbo-260628",
     "models": ["doubao-seed-2-1-turbo-260628", "doubao-1-5-pro-32k", "doubao-1-5-lite-32k"]},
    {"key": "siliconflow", "name": "SiliconFlow", "env_key": "SILICONFLOW_API_KEY",
     "env_url": "SILICONFLOW_BASE_URL", "env_model": "SILICONFLOW_MODEL",
     "default_url": "https://api.siliconflow.com/v1", "default_model": "google/gemma-4-26B-A4B-it",
     "models": ["Qwen/Qwen3-235B-A22B", "deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct", "google/gemma-4-26B-A4B-it"]},
    {"key": "openai", "name": "OpenAI / GPT", "env_key": "OPENAI_API_KEY",
     "env_url": "OPENAI_BASE_URL", "env_model": "OPENAI_MODEL",
     "default_url": "https://api.codexgood.com/v1", "default_model": "gpt-5.5",
     "models": ["gpt-5.5", "gpt-4o", "gpt-4o-mini"]},
    {"key": "gemini", "name": "Gemini", "env_key": "GEMINI_API_KEY",
     "env_url": "GEMINI_BASE_URL", "env_model": "GEMINI_MODEL",
     "default_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-2.0-flash-exp",
     "models": ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"]},
    {"key": "glm", "name": "智谱 GLM", "env_key": "BIGMODEL_API_KEY",
     "env_url": "BIGMODEL_BASE_URL", "env_model": "BIGMODEL_MODEL",
     "default_url": "https://open.bigmodel.cn/api/paas/v4/", "default_model": "glm-4-plus",
     "models": ["glm-4-plus", "glm-4-flash", "glm-4-air"]},
    {"key": "minimax", "name": "MiniMax", "env_key": "MINIMAX_API_KEY",
     "env_url": "MINIMAX_BASE_URL", "env_model": "MINIMAX_MODEL",
     "default_url": "https://api.minimaxi.com/v1", "default_model": "MiniMax-M3",
     "models": ["MiniMax-M3", "MiniMax-Text-01", "abab6.5s-chat"]},
]

# 模型功能点（role）→ 环境变量的映射（自定义 API 配置面板）。
_MODEL_ROLES = [
    {"key": "main_chat", "name": "对话 AI", "env_key": "DEEPSEEK_MODEL",
     "desc": "主对话场景的默认模型"},
    {"key": "subagent", "name": "辅助 AI", "env_key": "AERIE_WS_MODEL",
     "desc": "子 Agent / 轻量任务"},
    {"key": "subagent_code", "name": "代码辅助", "env_key": "AERIE_WS_CODE_MODEL",
     "desc": "代码类子 Agent"},
    {"key": "light_assist", "name": "轻量辅助", "env_key": "SILICONFLOW_LIGHT_MODEL",
     "desc": "快速辅助（问候纠错 / 生图提示词接力）"},
    {"key": "asr", "name": "语音转写", "env_key": "AERIE_WS_ASR_MODEL",
     "desc": "语音转写 ASR"},
]

# 功能 API（外部服务）元数据：设置页「功能 API 配置」界面展示。
# builtin=True 表示内置免费、无需密钥；fields 中 secret=True 的字段脱敏展示。
_FEATURE_APIS = [
    {
        "key": "bocha_search",
        "name": "Bocha 网页搜索",
        "desc": "资讯简报搜索的最终兜底层（AI / IT / 新闻搜索）",
        "tutorial": "https://open.bochaai.com",
        "how_to": "注册博查 AI 开放平台 → 右上角登录（微信扫码）→ API KEY 管理 → 创建密钥（sk-xxxxxx）填入下方",
        "fields": [{"env_key": "BOCHA_API_KEY", "label": "API Key", "secret": True}],
    },
    {
        "key": "baidu_map",
        "name": "百度地图 Web 服务",
        "desc": "天气优先源 + 附近地点/本地活动 + 地理编码/POI",
        "tutorial": "https://lbsyun.baidu.com/",
        "how_to": "创建应用并开启 Web 服务 API。推荐 SN 校验模式（同时填 AK + SK，无需 IP 白名单）；只填 AK 则走 IP 白名单模式",
        "fields": [
            {"env_key": "BAIDU_MAP_AK", "label": "AK · Access Key", "secret": False},
            {"env_key": "BAIDU_MAP_SK", "label": "SK · Security Key（SN 校验）", "secret": True},
        ],
    },
    {
        "key": "dailyhot",
        "name": "今日热榜聚合",
        "desc": "资讯简报的热榜聚合数据源（DailyHotApi）",
        "tutorial": "https://github.com/imsyy/DailyHotApi",
        "how_to": "本地或服务器部署 DailyHotApi 后填入其地址，默认 http://127.0.0.1:6688",
        "fields": [{"env_key": "DAILYHOT_API_BASE", "label": "API 地址", "secret": False}],
    },
    {
        "key": "open_meteo",
        "name": "Open-Meteo 天气",
        "desc": "免费天气回退源，无需密钥，开箱即用",
        "tutorial": "https://open-meteo.com/",
        "how_to": "无需配置，百度地图不可用时自动回退",
        "builtin": True,
        "fields": [],
    },
]


def _env_file_path() -> Path:
    """Return path to .env file (same directory as main.py)."""
    return Path(__file__).resolve().parent.parent / ".env"


def _read_env_file() -> dict[str, str]:
    """Parse .env file into a dict. Returns empty dict if file doesn't exist."""
    env_path = _env_file_path()
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def _write_env_file(data: dict[str, str]) -> None:
    """Write env dict back to .env file, preserving comments and order where possible."""
    env_path = _env_file_path()
    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in data:
                new_lines.append(f"{k}={data[k]}")
                updated.add(k)
                continue
        new_lines.append(line)

    for k, v in data.items():
        if k not in updated:
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# provider key 到健康状态名的别名映射（provider_health.json 使用运行时的 provider name）
_HEALTH_ALIAS = {"siliconflow": "siliconflow-light"}


def _read_provider_health_state() -> dict[str, Any]:
    """读取 provider_health.json 的 providers 状态（余额/健康/禁用原因）。"""
    try:
        from core.paths import data_dir

        p = data_dir() / "provider_health.json"
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return (data or {}).get("providers", {}) or {}
    except Exception:
        return {}


def _mask_secret(value: str) -> str:
    """脱敏展示密钥：保留末 4 位，其余以圆点遮挡。"""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * 8 + value[-4:]


_CUSTOM_PROVIDERS_ENV_KEY = "AERIE_CUSTOM_PROVIDERS"


def _read_custom_providers() -> list[dict]:
    """Read user-added custom OpenAI-compatible providers from .env (JSON array)."""
    raw = _read_env_file().get(_CUSTOM_PROVIDERS_ENV_KEY, "")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def _write_custom_providers(providers: list[dict]) -> None:
    """Persist custom providers to .env as a JSON array."""
    env = _read_env_file()
    env[_CUSTOM_PROVIDERS_ENV_KEY] = json.dumps(providers, ensure_ascii=False)
    _write_env_file(env)


@app.get("/api/env/providers")
async def env_providers() -> dict:
    """Return list of AI providers with config status (keys masked) + 余额/健康状态。"""
    env = _read_env_file()
    health = _read_provider_health_state()
    providers = []
    for meta in _PROVIDER_META:
        key_val = env.get(meta["env_key"], "")
        h = health.get(meta["key"]) or health.get(_HEALTH_ALIAS.get(meta["key"], "")) or {}
        providers.append({
            "key": meta["key"],
            "name": meta["name"],
            "configured": bool(key_val),
            "api_key_masked": "•" * 8 + key_val[-4:] if len(key_val) > 4 else ("•" * len(key_val) if key_val else ""),
            "base_url": env.get(meta["env_url"], meta["default_url"]),
            "model": env.get(meta["env_model"], meta["default_model"]),
            "env_key": meta["env_key"],
            "env_url": meta["env_url"],
            "env_model": meta["env_model"],
            "default_url": meta["default_url"],
            "default_model": meta["default_model"],
            "models": meta.get("models", [meta["default_model"]]),
            "balance": h.get("balance"),
            "health_status": h.get("status", "unknown"),
            "health_reason": h.get("reason", ""),
        })
    return {
        "providers": providers,
        "configured_count": sum(1 for p in providers if p["configured"]),
    }


@app.get("/api/providers/connectivity")
async def providers_connectivity() -> dict:
    """主动探测每个已配置 provider 的连通性（轻量 /models 请求，短超时）。

    并发探测所有 provider，每个最多 5s；2xx/4xx 视为端点可达（401/403 是
    鉴权问题但网络连通），仅连接失败 / 超时标记为 ok=False。
    """
    import httpx

    env = _read_env_file()

    async def _probe(meta: dict) -> dict:
        key = env.get(meta["env_key"], "")
        if not key:
            return {
                "key": meta["key"],
                "name": meta["name"],
                "configured": False,
                "ok": None,
                "latency_ms": 0,
            }
        base_url = (env.get(meta["env_url"]) or meta["default_url"]).rstrip("/")
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    base_url + "/models",
                    headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                )
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "key": meta["key"],
                "name": meta["name"],
                "configured": True,
                "ok": resp.status_code < 400,
                "http_status": resp.status_code,
                "latency_ms": elapsed,
            }
        except Exception as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "key": meta["key"],
                "name": meta["name"],
                "configured": True,
                "ok": False,
                "http_status": None,
                "latency_ms": elapsed,
                "error": str(exc)[:120],
            }

    providers = await asyncio.gather(*(_probe(m) for m in _PROVIDER_META))
    return {"providers": providers}


@app.post("/api/env/save")
async def env_save(request: Request) -> dict:
    """Save provider API key / base_url / model to .env file.

    Body: {"provider_key": "deepseek", "api_key": "...", "base_url": "...", "model": "..."}
    """
    try:
        body = await request.json()
        provider_key = body.get("provider_key", "")
        meta = next((m for m in _PROVIDER_META if m["key"] == provider_key), None)
        if not meta:
            return JSONResponse({"error": "Unknown provider: " + provider_key}, status_code=400)

        env = _read_env_file()
        changed: dict[str, str] = {}
        api_key = body.get("api_key")
        if api_key is not None:
            env[meta["env_key"]] = api_key
            changed[meta["env_key"]] = api_key
        base_url = body.get("base_url")
        if base_url is not None:
            env[meta["env_url"]] = base_url
            changed[meta["env_url"]] = base_url
        model = body.get("model")
        if model is not None:
            env[meta["env_model"]] = model
            changed[meta["env_model"]] = model

        _write_env_file(env)
        # 热加载：更新进程内环境变量并重建对话 brain，使新 API Key / model / url 立即生效，
        # 无需重启后端。临时实例化的 LLMCaller / ASR 客户端会读取新 env。
        if changed:
            os.environ.update(changed)
            try:
                comp = get_companion()
                if comp and hasattr(comp, "brain"):
                    from core.llm_caller import LLMCaller
                    comp.brain = LLMCaller()
            except Exception:
                logger.debug("provider env hot-reload failed", exc_info=True)
        return {"status": "ok", "provider": provider_key, "hot_reloaded": list(changed.keys())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/env/custom-providers")
async def env_custom_providers_get() -> dict:
    """Return user-added custom API providers (keys masked)."""
    providers = []
    for cp in _read_custom_providers():
        extra_kv = cp.get("extra_kv")
        if not isinstance(extra_kv, dict):
            extra_kv = {}
        providers.append({
            "id": cp.get("id", ""),
            "name": cp.get("name", ""),
            "base_url": cp.get("base_url", ""),
            "api_key_masked": _mask_secret(cp.get("api_key", "")),
            "model": cp.get("model", ""),
            "extra_kv": extra_kv,
            "max_tool_calls": cp.get("max_tool_calls", 8),
        })
    return {"providers": providers}


@app.post("/api/env/custom-providers")
async def env_custom_providers_save(request: Request) -> dict:
    """Save user-added custom API providers. Body: {"providers": [...]}"""
    try:
        body = await request.json()
        items = body.get("providers")
        if not isinstance(items, list):
            return JSONResponse({"error": "invalid_providers"}, status_code=400)
        clean = []
        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            base_url = str(it.get("base_url") or "").strip()
            api_key = str(it.get("api_key") or "").strip()
            model = str(it.get("model") or "").strip()
            if not name and not base_url:
                continue
            extra_kv = it.get("extra_kv")
            if not isinstance(extra_kv, dict):
                extra_kv = {}
            try:
                max_tool_calls = int(it.get("max_tool_calls") or 8)
            except (TypeError, ValueError):
                max_tool_calls = 8
            clean.append({
                "id": str(it.get("id") or "").strip() or f"cp_{int(time.time() * 1000)}_{idx}",
                "name": name,
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "extra_kv": extra_kv,
                "max_tool_calls": max_tool_calls,
            })
        # 保留已有 provider 的 api_key（前端返回的是脱敏值，未修改时留空）
        existing_by_id = {cp.get("id"): cp for cp in _read_custom_providers() if cp.get("id")}
        for it in clean:
            if not it["api_key"]:
                old = existing_by_id.get(it["id"])
                if old and old.get("api_key"):
                    it["api_key"] = old["api_key"]
        _write_custom_providers(clean)
        return {"status": "ok", "count": len(clean)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/env/model-roles")
async def env_model_roles_get() -> dict:
    """返回模型功能点（role）的当前映射（对话 AI / 辅助 AI / 代码辅助 / 轻量辅助 / 语音转写）。"""
    env = _read_env_file()
    roles = []
    for meta in _MODEL_ROLES:
        roles.append({
            "key": meta["key"],
            "name": meta["name"],
            "desc": meta["desc"],
            "env_key": meta["env_key"],
            "model": env.get(meta["env_key"], ""),
        })
    return {"roles": roles}


@app.post("/api/env/model-roles")
async def env_model_roles_save(request: Request) -> dict:
    """保存模型功能点映射到 .env（热加载）。Body: {"roles": [{"key": "...", "model": "..."}]}"""
    try:
        body = await request.json()
        roles = body.get("roles") if isinstance(body, dict) else None
        if not isinstance(roles, list):
            return JSONResponse({"error": "invalid_roles", "errorCode": "invalid_roles"}, status_code=400)
        env = _read_env_file()
        changed_env: dict[str, str] = {}
        for item in roles:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            model = str(item.get("model") or "").strip()
            meta = next((m for m in _MODEL_ROLES if m["key"] == key), None)
            if meta and model:
                env[meta["env_key"]] = model
                changed_env[meta["env_key"]] = model
        _write_env_file(env)
        # 热加载：更新进程内环境变量并重建对话 brain，使新模型立即生效，
        # 无需重启后端。临时实例化的 LLMCaller / ASR 客户端会读取新 env。
        if changed_env:
            os.environ.update(changed_env)
            try:
                comp = get_companion()
                if comp and hasattr(comp, "brain"):
                    from core.llm_caller import LLMCaller
                    comp.brain = LLMCaller()
            except Exception:
                pass
        return {"status": "ok", "hot_reloaded": list(changed_env.keys())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/env/feature-apis")
async def env_feature_apis_get() -> dict:
    """返回功能 API（搜索/天气/位置等）配置项、教程与当前状态。"""
    env = _read_env_file()
    features = []
    for meta in _FEATURE_APIS:
        item = {
            "key": meta["key"],
            "name": meta["name"],
            "desc": meta["desc"],
            "tutorial": meta["tutorial"],
            "how_to": meta["how_to"],
        }
        if meta.get("builtin"):
            item["builtin"] = True
            item["configured"] = True
            item["status"] = "builtin"
            item["fields"] = []
        else:
            fields = []
            values = []
            for f in meta["fields"]:
                raw = env.get(f["env_key"], "")
                values.append(raw.strip())
                fields.append({
                    "env_key": f["env_key"],
                    "label": f["label"],
                    "secret": f.get("secret", False),
                    "masked": _mask_secret(raw) if f.get("secret") else raw,
                })
            item["builtin"] = False
            item["configured"] = any(values)
            item["status"] = "configured" if item["configured"] else "unconfigured"
            item["fields"] = fields
        features.append(item)
    return {"features": features}


@app.post("/api/env/feature-apis")
async def env_feature_apis_save(request: Request) -> dict:
    """保存功能 API 密钥到 .env（热加载）。Body: {"feature_key": "...", "fields": {"ENV_KEY": "value"}}"""
    try:
        body = await request.json()
        feature_key = body.get("feature_key") if isinstance(body, dict) else None
        meta = next((m for m in _FEATURE_APIS if m["key"] == feature_key), None)
        if not meta or meta.get("builtin"):
            return JSONResponse({"error": "unknown_feature"}, status_code=400)
        fields = body.get("fields") if isinstance(body, dict) else None
        if not isinstance(fields, dict):
            return JSONResponse({"error": "invalid_fields"}, status_code=400)
        env = _read_env_file()
        changed: dict[str, str] = {}
        for f in meta["fields"]:
            env_key = f["env_key"]
            if env_key in fields:
                val = str(fields[env_key] or "").strip()
                env[env_key] = val
                changed[env_key] = val
        _write_env_file(env)
        if changed:
            os.environ.update(changed)
        return {"status": "ok", "hot_reloaded": list(changed.keys())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/env/baidu-map")
async def env_baidu_map_get() -> dict:
    """返回百度地图 AK/SK 配置状态（密钥脱敏）。

    SK 用于 SN 校验（官方无 IP 依赖的鉴权方式）：只要在控制台把校验方式配成
    SN 校验并填好 AK+SK，任意用户的任意 IP 都能调用，无需维护 IP 白名单。
    未配置时系统自动回退内置城市数据 / Open-Meteo，仍可开箱即用。
    """
    env = _read_env_file()
    ak = env.get("BAIDU_MAP_AK", "")
    sk = env.get("BAIDU_MAP_SK", "")
    return {
        "ak_configured": bool(ak),
        "sk_configured": bool(sk),
        "ak_masked": (ak[:4] + "••••" + ak[-4:]) if len(ak) > 8 else ("•" * len(ak) if ak else ""),
        "sk_masked": (sk[:4] + "••••" + sk[-4:]) if len(sk) > 8 else ("•" * len(sk) if sk else ""),
    }


@app.post("/api/env/baidu-map")
async def env_baidu_map_save(request: Request) -> dict:
    """保存百度地图 AK/SK 到 .env。Body: {"ak": "...", "sk": "..."}"""
    try:
        body = await request.json()
        env = _read_env_file()
        ak = body.get("ak")
        if ak is not None:
            env["BAIDU_MAP_AK"] = str(ak).strip()
        sk = body.get("sk")
        if sk is not None:
            env["BAIDU_MAP_SK"] = str(sk).strip()
        _write_env_file(env)
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/self-check")
async def self_check() -> dict:
    """First-run self-check: API key status, DB health, etc."""
    env = _read_env_file()
    has_any_key = any(env.get(m["env_key"], "") for m in _PROVIDER_META)
    configured = [m["key"] for m in _PROVIDER_META if env.get(m["env_key"], "")]
    return {
        "has_api_key": has_any_key,
        "providers_configured": configured,
        "db_ok": _db is not None,
    }


# R7.3: dedicated city-set endpoint so the brief-drawer pin button can
# write the weather city + bust the IP cache atomically. The previous
# path (/api/settings PUT) does not clear data/cache/city.json, which
# meant the next /api/brief/today still returned the cached IP city.
_CITY_INDEX = [
    {"city": "上海", "country": "中国", "keywords": "上海 shanghai china"},
    {"city": "北京", "country": "中国", "keywords": "北京 beijing peking china"},
    {"city": "广州", "country": "中国", "keywords": "广州 guangzhou canton china"},
    {"city": "深圳", "country": "中国", "keywords": "深圳 shenzhen china"},
    {"city": "济南", "country": "中国", "keywords": "济南 jinan china"},
    {"city": "东京", "country": "日本", "keywords": "东京 tokyo japan"},
    {"city": "首尔", "country": "韩国", "keywords": "首尔 seoul korea"},
    {"city": "新加坡", "country": "新加坡", "keywords": "新加坡 singapore"},
    {"city": "巴黎", "country": "法国", "keywords": "巴黎 paris france"},
    {"city": "伦敦", "country": "英国", "keywords": "伦敦 london uk england"},
    {"city": "纽约", "country": "美国", "keywords": "纽约 new york usa"},
    {"city": "洛杉矶", "country": "美国", "keywords": "洛杉矶 los angeles usa"},
    {"city": "悉尼", "country": "澳大利亚", "keywords": "悉尼 sydney australia"},
    {"city": "柏林", "country": "德国", "keywords": "柏林 berlin germany"},
    {"city": "多伦多", "country": "加拿大", "keywords": "多伦多 toronto canada"},
]


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


async def _fetch_current_weather(force_location: bool = False) -> dict:
    from core.weather_service import fetch_weather_for_current_location
    return await fetch_weather_for_current_location(force_location=force_location)


def _search_city_items(query: str) -> list[dict]:
    q = (query or "").strip().lower()
    rows = _CITY_INDEX if not q else [r for r in _CITY_INDEX if q in r["city"].lower() or q in r["country"].lower() or q in r["keywords"].lower()]
    return [{"city": r["city"], "country": r["country"], "label": f"{r['city']} · {r['country']}"} for r in rows[:12]]


@app.get("/api/location/status")
async def location_status(force: int = Query(default=0, ge=0, le=1)) -> dict:
    from core.location_resolver import resolve_location_async
    return await resolve_location_async(force_refresh=bool(force))


@app.get("/api/location/search")
async def location_search(q: str = Query(default="")) -> dict:
    return {"items": _search_city_items(q)}


@app.get("/api/weather/current")
async def weather_current(force: int = Query(default=0, ge=0, le=1)) -> dict:
    start = time.perf_counter()
    weather = await _fetch_current_weather(force_location=bool(force))
    weather["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
    return weather


@app.post("/api/location/set")
async def location_set(request: Request) -> dict:
    """Set the manual city override used by the daily brief weather."""
    start = time.perf_counter()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    city = str((body or {}).get("city") or "").strip()
    try:
        from core.location_resolver import set_manual_city
        set_manual_city(city)
        weather = await _fetch_current_weather(force_location=not bool(city))
        from core import brief_fetcher
        try:
            brief_fetcher.update_brief_weather(_today_str(), weather)
        except Exception as e:
            logger.warning("location_set: brief weather update failed: %s", e)
        return {
            "status": "ok",
            "city": weather.get("city") or city,
            "manual": bool(city),
            "weather": weather,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Anniversary ──────────────────────────────────────

@app.get("/api/anniversary/list")
async def anniversary_list() -> dict:
    """List all anniversaries with days_since calculated."""
    try:
        rows = _db.query("SELECT * FROM calendar_events WHERE event_type = 'anniversary' ORDER BY start_time")
        from datetime import datetime as dt
        items = []
        for row in rows:
            item = dict(row)
            item["name"] = item["title"]
            item["date"] = item["start_time"][:10]
            item["days_since"] = (dt.now() - dt.strptime(item["date"], "%Y-%m-%d")).days
            items.append(item)
        return {"items": items, "count": len(items)}
    except Exception as e:
        return {"items": [], "error": str(e)}


@app.post("/api/anniversary/add")
async def anniversary_add(request: Request) -> dict:
    """Add a new anniversary."""
    try:
        body = await request.json()
        aid = _calendar.create_event(
            title=body.get("name", ""),
            start_time=body.get("date", "") + "T00:00:00",
            event_type="anniversary",
            description=body.get("description", ""),
            all_day=1,
            source="legacy_anniversary_api",
        )
        emit("timeline_changed", date=body.get("date", ""), kind="event", action="created", id=f"event:{aid}")
        return {"status": "ok", "id": aid}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/anniversary/update/{item_id}")
async def anniversary_update(item_id: int, request: Request) -> dict:
    """Update an anniversary."""
    try:
        body = await request.json()
        data = {}
        for field in ["name", "date", "type", "description"]:
            if field in body:
                data[field] = body[field]
        if data:
            _db.update("anniversary", data, "id = ?", (item_id,))
        return {"status": "ok", "id": item_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/anniversary/delete/{item_id}")
async def anniversary_delete(item_id: int) -> dict:
    """Delete an anniversary."""
    try:
        _db.delete("anniversary", "id = ?", (item_id,))
        return {"status": "ok", "id": item_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/anniversary/upcoming")
async def anniversary_upcoming(days: int = Query(default=7)) -> dict:
    """List anniversaries within the next N days."""
    try:
        from datetime import datetime as dt, timedelta
        now = dt.now()
        cutoff = now + timedelta(days=days)
        rows = _db.query("SELECT * FROM anniversary WHERE date >= ? AND date <= ? ORDER BY date",
                         (now.strftime("%Y-%m-%d"), cutoff.strftime("%Y-%m-%d")))
        return {"items": rows, "count": len(rows)}
    except Exception as e:
        return {"items": [], "error": str(e)}


# ── Knowledge ─────────────────────────────────────────

@app.get("/api/knowledge/list")
async def knowledge_list(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    category: str = Query(default=""),
    search: str = Query(default=""),
) -> dict:
    try:
        items, total = _knowledge.list(page, limit, category.strip(), search.strip())
        return {"items": items, "total": total, "page": page, "limit": limit}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/knowledge/{item_id}")
async def knowledge_get(item_id: int) -> dict:
    try:
        item = _knowledge.get(item_id)
        if not item:
            return JSONResponse({"error": "knowledge not found"}, status_code=404)
        return item
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _knowledge_fields(body: dict) -> tuple[str, str, str, str] | None:
    category = str(body.get("category") or "").strip()
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    tags = str(body.get("tags") or "").strip()
    if not category or not title or not content:
        return None
    return category, title, content, tags


@app.post("/api/knowledge")
async def knowledge_add(request: Request) -> dict:
    if not _main_process_request_authorized(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    fields = _knowledge_fields(await request.json())
    if not fields:
        return JSONResponse({"error": "category, title and content are required"}, status_code=400)
    try:
        item_id = _knowledge.add(*fields)
        result = _knowledge.get(item_id)
        # P2 写入校验门（§3.7-2）：flag 开启时对关键知识做一致性校验，
        # 结果附加到响应与日志，不阻塞写入（PoC 观察期）。
        if _memory_write_validation_enabled():
            try:
                from core.memory_validation import validate_fact

                verdict = await validate_fact(
                    str(fields[2] or ""),
                    channel="system",
                    source="knowledge_add",
                    importance=7,
                    timeout=5.0,
                )
                result = dict(result or {})
                result["validation"] = verdict
                logger.info("knowledge_add validation verdict=%s", verdict.get("status"))
            except Exception:
                logger.exception("knowledge_add validation error")
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/knowledge/{item_id}")
async def knowledge_update(item_id: int, request: Request) -> dict:
    if not _main_process_request_authorized(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    fields = _knowledge_fields(await request.json())
    if not fields:
        return JSONResponse({"error": "category, title and content are required"}, status_code=400)
    try:
        if not _knowledge.update(item_id, *fields):
            return JSONResponse({"error": "knowledge not found"}, status_code=404)
        return _knowledge.get(item_id)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/knowledge/{item_id}")
async def knowledge_delete(item_id: int, request: Request) -> dict:
    if not _main_process_request_authorized(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        if not _knowledge.delete(item_id):
            return JSONResponse({"error": "knowledge not found"}, status_code=404)
        return {"status": "ok", "id": item_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── System Stats ──────────────────────────────────────

_SYSTEM_NET_SAMPLE: tuple[float, int, int] | None = None

@app.get("/api/stats/system")
async def system_stats() -> dict:
    """Return system-level stats."""
    try:
        uptime_seconds = int(time.time() - _START_TIME)
        hours = uptime_seconds // 3600
        mins = (uptime_seconds % 3600) // 60
        uptime_str = f"{hours}h {mins}m"

        # Count total messages (exclude trashed)
        msg_count = _db.query_one(
            "SELECT COUNT(*) as cnt FROM chat_log WHERE deleted_at IS NULL"
        )
        message_count = msg_count["cnt"] if msg_count else 0

        # Try to get CPU and memory (platform-specific)
        cpu_str = "N/A"
        memory_str = "N/A"
        cpu_percent = None
        memory_percent = None
        network_receive_kbps = None
        network_send_kbps = None
        try:
            import psutil
            cpu_percent = float(psutil.cpu_percent(interval=0.1))
            cpu_str = f"{cpu_percent:.1f}%"
            mem = psutil.virtual_memory()
            memory_percent = float(mem.percent)
            memory_str = f"{mem.percent:.1f}% ({mem.used // 1048576}MB)"

            global _SYSTEM_NET_SAMPLE
            counters = psutil.net_io_counters()
            sampled_monotonic = time.monotonic()
            if _SYSTEM_NET_SAMPLE is not None:
                previous_at, previous_recv, previous_sent = _SYSTEM_NET_SAMPLE
                elapsed = sampled_monotonic - previous_at
                if elapsed > 0:
                    network_receive_kbps = max(
                        0.0,
                        (int(counters.bytes_recv) - previous_recv) / elapsed / 1024.0,
                    )
                    network_send_kbps = max(
                        0.0,
                        (int(counters.bytes_sent) - previous_sent) / elapsed / 1024.0,
                    )
            _SYSTEM_NET_SAMPLE = (
                sampled_monotonic,
                int(counters.bytes_recv),
                int(counters.bytes_sent),
            )
        except ImportError:
            pass

        sampled_at = time.strftime(
            "%Y-%m-%dT%H:%M:%S%z", time.localtime()
        )
        return {
            "uptime": uptime_str,
            "uptime_seconds": uptime_seconds,
            "cpu": cpu_str,
            "memory": memory_str,
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "network_receive_kbps": network_receive_kbps,
            "network_send_kbps": network_send_kbps,
            "sampled_at": sampled_at,
            "sampledAt": sampled_at,
            "message_count": message_count,
            "backend_started_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S%z", time.localtime(_START_TIME)
            ),
            "database_path": str(_db.db_path.resolve()),
            "project_root": str(PROJECT_ROOT),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Block-2 A2: Persona (name / english_name / avatar) ──────

_PERSONA_AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_PERSONA_AVATAR_TYPES = {"image/png", "image/jpeg"}


@app.get("/api/persona")
async def persona_get() -> dict:
    """Return persona summary: name / english_name / avatar_url.

    R8.1 (Persona 9/10): 在原有 summary 基础上额外返回
    ``persona_9_10`` 布尔标志和 ``archetype`` 字符串，让前端 /
    外部客户端能识别 9/10 基线并做 UI 适配（如更高的语气强度
    视觉提示）。字段为**新增**非替换，保持向后兼容。
    """
    try:
        summary = get_persona_summary()
        # R8.1: 加载 persona.yaml 拿 Big Five + archetype
        # lazy import 避免循环依赖
        from config.persona_loader import load_persona
        cfg = load_persona() or {}
        profile = (cfg.get("persona") or {}).get("profile") or {}
        big_five = profile.get("big_five") or {}
        extraversion = float(big_five.get("extraversion", 0) or 0)
        return {
            **summary,
            "persona_9_10": extraversion >= 0.7,
            "archetype": profile.get("personality_archetype", ""),
            "extraversion": extraversion,
            # gender drives pronoun-aware UI labels (她/他/TA)
            "gender": (
                (_persona_mgr.get_active().get("basic") or {}).get("gender", "")
                or profile.get("gender", "")
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@app.put("/api/persona")
async def persona_put(request: Request) -> dict:
    """Update persona name / english_name. Atomic write + backup + validation."""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a dict"}, status_code=400)
    try:
        persona = save_persona(body)
        return {"status": "ok", "persona": persona}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/persona/avatar")
async def persona_avatar_upload(
    file: UploadFile = File(...),
    persona_id: str | None = Query(default=None),
) -> dict:
    """Upload persona avatar. PNG/JPG only, ≤2 MB. Auto-backs up previous.

    角色级隔离：默认写入当前激活角色；人设中心编辑器可传 ``persona_id``
    为任意角色上传（无需先激活）。
    """
    if file.content_type not in _PERSONA_AVATAR_TYPES:
        return JSONResponse(
            {"error": f"unsupported type: {file.content_type}"},
            status_code=415,
        )
    data = await file.read()
    if len(data) > _PERSONA_AVATAR_MAX_BYTES:
        return JSONResponse(
            {"error": f"file too large (>{_PERSONA_AVATAR_MAX_BYTES} bytes)"},
            status_code=413,
        )
    if not data:
        return JSONResponse({"error": "empty file"}, status_code=400)
    ext = "png" if file.content_type == "image/png" else "jpg"
    try:
        url = save_avatar_bytes(data, ext=ext, persona_id=persona_id or None)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    import base64 as _b64
    dataurl = (
        "data:" + file.content_type + ";base64,"
        + _b64.b64encode(data).decode("ascii")
    )
    effective_pid = persona_id or (_persona_mgr.get_active_id() if _persona_mgr else "") or ""
    return {
        "status": "ok",
        "url": url,
        "size": len(data),
        "content_type": file.content_type,
        "avatar_dataurl": dataurl,
        "persona_id": effective_pid,
    }


@app.get("/api/persona/avatar")
async def persona_avatar_get() -> Response:
    """Serve persona avatar bytes (or 404 if not set).

    R7.5: use the actual file extension to set the correct
    content-type. The previous version always returned image/png which
    silently broke when the file on disk was a JPG wearing a .png
    extension (it happens).
    """
    pair = load_avatar_bytes()
    if not pair:
        return JSONResponse({"error": "not set"}, status_code=404)
    data, ct = pair
    persona_id = _persona_mgr.get_active_id() if _persona_mgr else ""
    return Response(
        content=data,
        media_type=ct,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Persona-Id": persona_id,
        },
    )


# ── 三视图（辅助生图参考图）──
# 每套人设独立存 front/side/back 三张参考图，用于图生图锁定角色外观。
# 数据层由 persona_manager 的 three_view_* 方法负责（data_dir/personas/three_views/）。


def _three_view_max_bytes() -> int:
    try:
        return max(64 * 1024, int(os.environ.get("AERIE_THREE_VIEW_MAX_BYTES", "0") or "0") or 8 * 1024 * 1024)
    except Exception:
        return 8 * 1024 * 1024


def _compress_three_view_image(data: bytes, max_bytes: int) -> Tuple[bytes, str]:
    """将图片压缩到 max_bytes 以内，返回 (bytes, ext)。

    超限图片自动降质/降采样为 JPEG，尽力压到上限内。
    PIL 不可用时抛出 RuntimeError，由调用方兜底拒绝。
    """
    try:
        from io import BytesIO
        from PIL import Image
    except Exception as e:  # pragma: no cover - PIL 通常可用
        raise RuntimeError(f"PIL unavailable: {e}")

    img = Image.open(BytesIO(data))
    img.load()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    best: bytes | None = None
    quality = 88
    scale = 1.0
    for _ in range(30):
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        probe = img.resize((w, h), Image.LANCZOS) if scale < 1.0 else img
        buf = BytesIO()
        probe.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) <= max_bytes:
            return out, "jpg"
        # 记录当前最接近目标的结果，供最终兜底
        if best is None or len(out) < len(best):
            best = out
        # 逐级降质，质量到下限后改降采样
        if quality > 30:
            quality -= 10
        else:
            scale *= 0.7
            quality = 88

    if best is not None:
        return best, "jpg"
    raise RuntimeError("cannot compress image under limit")


@app.get("/api/persona/three-view")
async def persona_three_view_summary(persona_id: str = Query(default="")) -> dict:
    """返回人设三视图摘要（每视角 dataURL/url/是否存在）。默认当前激活人设。"""
    try:
        pid = persona_id or _persona_mgr.get_active_id()
        if not _persona_mgr.has_persona(pid):
            return JSONResponse({"error": "persona not found"}, status_code=404)
        return {
            "status": "ok",
            "persona_id": pid,
            "views": _persona_mgr.get_three_view_summary(pid),
        }
    except Exception as e:
        logger.exception("persona three-view summary error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/persona/three-view/{persona_id}/{view}")
async def persona_three_view_get(persona_id: str, view: str) -> Response:
    """读取某张三视图原始字节。"""
    try:
        pair = _persona_mgr.load_three_view(persona_id, view)
        if pair is None:
            return JSONResponse({"error": "not set"}, status_code=404)
        data, ct = pair
        return Response(
            content=data,
            media_type=ct,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as e:
        logger.exception("persona three-view get error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/persona/three-view/{persona_id}/{view}")
async def persona_three_view_upload(
    persona_id: str,
    view: str,
    file: UploadFile = File(...),
) -> dict:
    """上传一张三视图。PNG/JPG，超过 8MB 自动压缩至上限内。"""
    try:
        if not _persona_mgr.has_persona(persona_id):
            return JSONResponse({"error": "persona not found"}, status_code=404)
        data = await file.read()
        if len(data) < 4:
            return JSONResponse({"error": "empty file"}, status_code=400)
        max_bytes = _three_view_max_bytes()
        if len(data) > max_bytes:
            try:
                data, _ = _compress_three_view_image(data, max_bytes)
            except Exception as e:
                logger.warning("three-view compress failed: %s", e)
                return JSONResponse({"error": "file too large and cannot be compressed"}, status_code=413)
        ok, suffix = _persona_mgr.save_three_view(persona_id, view, data, ext=file.filename or "")
        if not ok:
            return JSONResponse({"error": suffix}, status_code=400)
        pair = _persona_mgr.load_three_view(persona_id, view)
        dataurl = ""
        if pair:
            import base64 as _b64
            dataurl = "data:" + pair[1] + ";base64," + _b64.b64encode(pair[0]).decode("ascii")
        return {
            "status": "ok",
            "persona_id": persona_id,
            "view": view,
            "file": suffix,
            "dataurl": dataurl,
        }
    except Exception as e:
        logger.exception("persona three-view upload error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/persona/three-view/{persona_id}/{view}")
async def persona_three_view_delete(persona_id: str, view: str) -> dict:
    """删除某张三视图；view 传 '*' 删除整套。"""
    try:
        ok, msg = _persona_mgr.delete_three_view(persona_id, view)
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        return {"status": "ok", "persona_id": persona_id, "view": view}
    except Exception as e:
        logger.exception("persona three-view delete error")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── v13.0: Persona Hub (人设中心) ──────────────────────


def _persona_avatar_dataurl(persona_id: str) -> str:
    """按 persona 读取头像并转 inline dataURL（无头像返回空串）。

    角色级隔离：头像按 persona_id 分区存储，必须按角色读，
    绝不能回落到全局缓存。
    """
    try:
        from config.persona_loader import load_avatar_bytes
        pair = load_avatar_bytes(persona_id)
        if not pair:
            return ""
        import base64 as _b64
        data, ct = pair
        mime = "image/jpeg" if ct == "image/jpeg" else "image/png"
        return "data:" + mime + ";base64," + _b64.b64encode(data).decode("ascii")
    except Exception:
        logger.exception("persona avatar dataurl error pid=%s", persona_id)
        return ""


@app.get("/api/persona/hub/list")
async def persona_hub_list() -> dict:
    """列出所有人设模板（含各自头像，按角色独立）。"""
    try:
        personas = _persona_mgr.list_personas()
        for p in personas:
            p["avatar_dataurl"] = _persona_avatar_dataurl(p.get("id") or "")
        return {"status": "ok", "personas": personas, "active_id": _persona_mgr.get_active_id()}
    except Exception as e:
        logger.exception("persona hub list error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/persona/hub/{persona_id}")
async def persona_hub_get(persona_id: str) -> dict:
    """获取指定人设的完整配置（含该角色头像）。"""
    try:
        if not _persona_mgr.has_persona(persona_id):
            return JSONResponse({"error": "persona not found"}, status_code=404)
        persona = _persona_mgr.get_persona(persona_id)
        persona = dict(persona)
        persona["avatar_dataurl"] = _persona_avatar_dataurl(persona_id)
        return {"status": "ok", "persona": persona}
    except Exception as e:
        logger.exception("persona hub get error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/persona/hub")
async def persona_hub_create(request: Request) -> dict:
    """创建新人设。"""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a dict"}, status_code=400)
    try:
        ok, msg = _persona_mgr.create_persona(body)
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        return {"status": "ok", "persona_id": msg}
    except Exception as e:
        logger.exception("persona hub create error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/persona/hub/{persona_id}")
async def persona_hub_update(persona_id: str, request: Request) -> dict:
    """更新人设配置。"""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a dict"}, status_code=400)
    try:
        ok, msg = _persona_mgr.update_persona(persona_id, body)
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        return {"status": "ok", "persona_id": msg}
    except Exception as e:
        logger.exception("persona hub update error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/persona/hub/{persona_id}")
async def persona_hub_delete(persona_id: str) -> dict:
    """伪删除人设：隐藏而非真删，全部隐藏后自动恢复伊塔。"""
    try:
        ok, msg = _persona_mgr.delete_persona(persona_id)
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("persona hub delete error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/persona/hub/{persona_id}/activate")
async def persona_hub_activate(persona_id: str) -> dict:
    """切换激活人设。"""
    try:
        ok, msg = _persona_mgr.switch_persona(persona_id)
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        # 通知前端人设已切换
        emit("persona:changed", persona_id=persona_id)
        return {"status": "ok", "active_id": msg}
    except Exception as e:
        logger.exception("persona hub activate error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/persona/hub/{persona_id}/export")
async def persona_hub_export(persona_id: str):
    """导出人设配置（JSON 下载）。"""
    try:
        data = _persona_mgr.export_persona(persona_id)
        if not data:
            return JSONResponse({"error": "persona not found"}, status_code=404)
        import json as _json
        content = _json.dumps(data, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="persona_{persona_id}.json"',
            },
        )
    except Exception as e:
        logger.exception("persona hub export error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/persona/hub/import")
async def persona_hub_import(file: UploadFile = File(...)) -> dict:
    """导入人设模板（JSON 文件）。"""
    try:
        data = await file.read()
        import json as _json
        persona_data = _json.loads(data.decode("utf-8"))
    except Exception as e:
        return JSONResponse({"error": f"invalid file: {e}"}, status_code=400)
    if not isinstance(persona_data, dict):
        return JSONResponse({"error": "file must contain a JSON object"}, status_code=400)
    try:
        # 确保导入的 ID 不冲突
        import_id = persona_data.get("id", "imported")
        if _persona_mgr.has_persona(import_id):
            persona_data["id"] = f"{import_id}_imported"
        ok, msg = _persona_mgr.create_persona(persona_data)
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        return {"status": "ok", "persona_id": msg}
    except Exception as e:
        logger.exception("persona hub import error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/persona/hub/reset-default")
async def persona_hub_reset_default() -> dict:
    """重置为默认伊塔人设。"""
    try:
        ok, msg = _persona_mgr.switch_persona("yita_default")
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        emit("persona:changed", persona_id="yita_default")
        return {"status": "ok", "active_id": "yita_default"}
    except Exception as e:
        logger.exception("persona hub reset error")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── v13.x: Persona AI 智能生成 ─────────────────────


@app.post("/api/persona/hub/generate/concepts")
async def persona_hub_generate_concepts(request: Request) -> dict:
    """Recommend story concepts ("两人故事起因") based on relationship type + seed."""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a dict"}, status_code=400)
    relationship_type = (body.get("relationship_type") or "").strip()
    story_seed = (body.get("story_seed") or "").strip()
    description = (body.get("description") or "").strip()
    try:
        from core.persona_hub.persona_generator import recommend_story_concepts
        concepts = await recommend_story_concepts(
            relationship_type,
            story_seed,
            description,
        )
    except Exception as e:
        logger.exception("persona hub generate concepts error")
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"status": "ok", "concepts": concepts}


@app.post("/api/persona/hub/generate")
async def persona_hub_generate(request: Request) -> dict:
    """Create an AI persona generation task from a free-text description."""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a dict"}, status_code=400)
    description = (body.get("description") or "").strip()
    if not description:
        return JSONResponse({"error": "description is required"}, status_code=400)
    options = body.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    try:
        from core.persona_hub.persona_generator import create_generation_task
        task_id = create_generation_task(description, options)
    except Exception as e:
        logger.exception("persona hub generate error")
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"status": "ok", "task_id": task_id}


@app.get("/api/persona/hub/generate/{task_id}")
async def persona_hub_generate_status(task_id: str) -> dict:
    """Poll an AI persona generation task."""
    try:
        from core.persona_hub.persona_generator import get_generation_task
        task = get_generation_task(task_id)
    except Exception as e:
        logger.exception("persona hub generate status error")
        return JSONResponse({"error": str(e)}, status_code=500)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)
    return {"status": "ok", "task": task}


# ── Daily Brief (Block-4A R1.4) ────────────────────────
@app.get("/api/brief/today")
async def brief_today() -> dict:
    """Return today's brief JSON. If missing, lazily generate."""
    from datetime import datetime
    from core import brief_fetcher
    from core.llm_caller import LLMCaller

    today = datetime.now().strftime("%Y-%m-%d")
    cached = brief_fetcher.load_brief(today)
    if cached and cached.get("ai_news") is not None:
        # Never serve stale todo snapshots baked into an old cache file (e.g.
        # sample todos seeded by a previous backend run). Refresh live todos
        # from the DB so deleted tasks do not reappear on restart.
        cached["todos"] = brief_fetcher.get_today_todos(today)
        cached["todo_stats"] = brief_fetcher.get_todo_stats(today)
        return {"date": today, "brief": cached}

    # Lazy generate
    try:
        sections = await brief_fetcher.run_all()
    except Exception as e:
        logger.warning("brief_today: run_all failed: %s", e)
        return JSONResponse({"error": "fetch_failed", "detail": str(e)}, status_code=500)

    # Compose greeting
    greeting = ""
    try:
        brain = LLMCaller()
        greeting = await brain.compose_brief_greeting(
            time_of_day=sections.get("time_of_day", "morning"),
            date_str=today,
            todo_count=sections.get("todo_stats", {}).get("remaining", 0),
            weather=sections.get("weather"),
        )
    except Exception as e:
        logger.warning("brief_today: greeting failed: %s", e)

    # Compose Markdown
    try:
        md = await brain.compose_brief(sections)
    except Exception as e:
        logger.warning("brief_today: compose_brief failed: %s", e)
        md = ""

    sections["greeting"] = greeting

    # Persist (no HTML for now — renderer renders JSON to DOM)
    brief_fetcher.save_brief(today, sections, html=md)
    return {"date": today, "brief": sections, "markdown": md}


@app.post("/api/brief/greeting")
async def brief_greeting_fresh() -> dict:
    """Regenerate today's brief greeting via the light/cheap provider.

    Called by the drawer on every open so the welcome line feels alive while
    the rest of the brief stays cached. Never blocks long (4s hard cap); on
    failure falls back to the cached greeting (or empty string).
    """
    from datetime import datetime
    from core import brief_fetcher
    from core.llm_caller import LLMCaller

    today = datetime.now().strftime("%Y-%m-%d")
    cached = brief_fetcher.load_brief(today) or {}
    # The disk cache may predate task creation, so never trust its todo
    # snapshot when composing the greeting — always read live from the DB.
    todo_stats = brief_fetcher.get_todo_stats(today)
    todos = brief_fetcher.get_today_todos(today)
    # Highest-priority incomplete task title, if any.
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    top_task: str | None = None
    for t in sorted(todos, key=lambda it: priority_rank.get(it.get("priority"), 1)):
        if not t.get("completed") and (t.get("title") or "").strip():
            top_task = t["title"].strip()
            break
    greeting = ""
    try:
        brain = LLMCaller()
        greeting = await brain.compose_quick_greeting(
            time_of_day=cached.get("time_of_day") or brief_fetcher.get_time_of_day(),
            date_str=today,
            todo_count=todo_stats.get("remaining", 0),
            weather=cached.get("weather"),
            top_task=top_task,
        )
    except Exception as e:
        logger.warning("brief_greeting: quick greeting failed: %s", e)
    if not greeting:
        greeting = cached.get("greeting") or ""
    # Persist the fresh greeting so the cached /api/brief/today response
    # (which serves the saved brief) stays in sync with the live todos.
    if greeting and greeting != cached.get("greeting"):
        cached["greeting"] = greeting
        try:
            brief_fetcher.save_brief(today, cached)
        except Exception as e:
            logger.warning("brief_greeting: persist greeting failed: %s", e)
    return {"date": today, "greeting": greeting}


@app.post("/api/brief/feedback")
async def brief_feedback(request: Request) -> dict:
    """Save user feedback for today's brief."""
    from datetime import datetime
    from core import brief_fetcher

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        path = brief_fetcher.save_feedback(today, body or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"status": "ok", "path": str(path)}


# ── R7.1: /api/brief/export and /api/brief/full removed. They were
# only consumed by the legacy detail BrowserWindow. The drawer uses
# ``/api/brief/today`` (and ``/api/brief/feedback`` for thumbs).


@app.post("/api/brief/run")
async def brief_run(request: Request, limit: int = Query(default=0, ge=0, le=50)) -> dict:
    """Force re-run the brief (manual refresh).

    R7.2: optional ``?limit=N`` query param (and matching body field)
    overrides per-section caps. The drawer uses ``?limit=8`` to fetch
    the expanded 8/section view. ``limit=0`` (default) keeps the
    feedback-driven limit so a manual refresh does not undo a
    "disliked" section's smaller depth.
    """
    from datetime import datetime
    from core import brief_fetcher
    from core.llm_caller import LLMCaller

    # Body can also carry a limit, but query param wins (more idiomatic).
    body_limit = 0
    try:
        body = await request.json()
        if isinstance(body, dict):
            raw = body.get("limit")
            if isinstance(raw, int) and 0 < raw <= 50:
                body_limit = raw
    except Exception:
        body = {}
    effective_limit = limit or body_limit or None

    try:
        sections = await brief_fetcher.run_all(limit=effective_limit)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    today = sections.get("date") or datetime.now().strftime("%Y-%m-%d")
    try:
        brain = LLMCaller()
        greeting = await brain.compose_brief_greeting(
            time_of_day=sections.get("time_of_day", "morning"),
            date_str=today,
            todo_count=sections.get("todo_stats", {}).get("remaining", 0),
            weather=sections.get("weather"),
        )
        sections["greeting"] = greeting
        md = await brain.compose_brief(sections)
    except Exception:
        md = ""
        sections["greeting"] = ""
    brief_fetcher.save_brief(today, sections, html=md)
    return {"status": "ok", "date": today, "markdown": md, "brief": sections, "limit": effective_limit or 0}


# ── v12.2.0: Todo Management API ────────────────────────

@app.get("/api/todos")
async def get_todos(date: str | None = None) -> dict:
    """Get todos for a given date (default: today)."""
    try:
        from core import todo_manager
        todos = todo_manager.get_todos(date)
        s = todo_manager.stats(date)
        return {"status": "ok", "todos": todos, "stats": s}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/todos")
async def add_todo(request: Request) -> dict:
    """Add a new todo."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    try:
        from core import todo_manager
        todo = todo_manager.add_todo(
            title=body.get("title", ""),
            priority=body.get("priority", "medium"),
            notes=body.get("notes"),
            due_time=body.get("due_time"),
            estimated_minutes=body.get("estimated_minutes"),
            date_str=body.get("date_str"),
        )
        emit("timeline_changed", date=(todo.get("due_time") or body.get("date_str") or datetime.now().strftime("%Y-%m-%d"))[:10], kind="todo", action="created", id=f"todo:{todo['id']}")
        return {"status": "ok", "todo": todo}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.patch("/api/todos/{todo_id}")
async def update_todo(todo_id: str, request: Request, date: str | None = None) -> dict:
    """Update a todo by id."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    try:
        from core import todo_manager
        updated = todo_manager.update_todo(todo_id, body, date)
        if updated is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        emit("timeline_changed", date=(updated.get("due_time") or date or datetime.now().strftime("%Y-%m-%d"))[:10], kind="todo", action="updated", id=f"todo:{todo_id}")
        return {"status": "ok", "todo": updated}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/todos/{todo_id}")
async def delete_todo(todo_id: str, date: str | None = None) -> dict:
    """Delete a todo by id."""
    try:
        from core import todo_manager
        todo = todo_manager.get_todo(todo_id)
        if todo is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        ok = todo_manager.delete_todo(todo_id, date)
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
        emit("timeline_changed", date=(todo.get("due_time") or date or datetime.now().strftime("%Y-%m-%d"))[:10], kind="todo", action="deleted", id=f"todo:{todo_id}")
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/todos/{todo_id}/toggle")
async def toggle_todo(todo_id: str, date: str | None = None) -> dict:
    """Toggle todo completion status."""
    try:
        from core import todo_manager
        updated = todo_manager.toggle_todo(todo_id, date)
        if updated is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        emit("timeline_changed", date=(updated.get("due_time") or date or datetime.now().strftime("%Y-%m-%d"))[:10], kind="todo", action="toggled", id=f"todo:{todo_id}")
        return {"status": "ok", "todo": updated}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Block-5C: AI Provider options + safe shell ──────────────
@app.get("/api/brain/ai-options")
async def brain_ai_options() -> dict:
    """Return the 11 ai_options (id/label/model) from persona_behavior.yaml.

    Plus the default provider id.
    """
    try:
        from core.llm_caller import LLMCaller
        opts = LLMCaller().get_ai_options()
        default = LLMCaller().get_default_provider()
        return {
            "default": default,
            "count": len(opts),
            "options": opts,
        }
    except Exception as e:
        return JSONResponse({"error": str(e), "options": []}, status_code=500)


@app.post("/api/brain/shell")
async def brain_shell(request: Request) -> dict:
    """Whitelisted shell exec: dir / echo / type / where / python / py.

    Body: {"command": "dir", "args": ["uploads"]}
    """
    try:
        from core.llm_caller import LLMCaller
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body or {}
        cmd = (body.get("command") or "").strip()
        args = body.get("args") or []
        if not cmd:
            return JSONResponse({"error": "missing command"}, status_code=400)
        result = LLMCaller().safe_shell(cmd, args)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Block-4B R2.2: Desire engine endpoints ──────────────────

@app.get("/api/desire/state")
async def desire_state() -> dict:
    """Return the desire engine's current state, score, and 5 variables."""
    comp = get_companion()
    if not comp or not comp.desire:
        return {"error": "desire engine not ready"}
    return comp.desire.get_state()


@app.post("/api/desire/cooldown")
async def desire_cooldown(request: Request) -> dict:
    """Set a manual cooldown window (default 12h)."""
    comp = get_companion()
    if not comp or not comp.desire:
        return JSONResponse({"error": "desire engine not ready"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        body = {}
    hours = float((body or {}).get("hours", 12))
    if hours < 0 or hours > 168:
        return JSONResponse({"error": "hours must be 0..168"}, status_code=400)
    comp.desire.set_cooldown(hours)
    return {"status": "ok", "cooldown_hours": hours}


@app.post("/api/desire/reject")
async def desire_reject() -> dict:
    """Mark a desire push as rejected. After 3 rejections, auto-cooldown kicks in."""
    comp = get_companion()
    if not comp or not comp.desire:
        return JSONResponse({"error": "desire engine not ready"}, status_code=503)
    comp.desire.mark_rejected()
    return {"status": "ok", "reject_count": comp.desire.state.get("reject_count", 0)}


# ── Block-4C R3.4: Skills endpoints ──────────────────

@app.get("/api/skills/list")
async def skills_list() -> dict:
    """Return discovered skills + provider_hint + read_only flag."""
    comp = get_companion()
    if not comp or not comp.skill_loader:
        return {"skills": [], "count": 0, "error": "skill loader not ready"}
    out = []
    for name, meta in comp.skill_loader.discovered.items():
        out.append({
            "name": name,
            "provider_hint": meta.get("hint", "text"),
            "read_only": meta.get("read_only", False),
            "description": meta.get("desc", ""),
        })
    return {"skills": out, "count": len(out)}


@app.get("/api/skills/{name}")
async def skills_get(name: str) -> Response:
    """Return the SKILL.md content for a given skill."""
    comp = get_companion()
    if not comp or not comp.skill_loader:
        return JSONResponse({"error": "skill loader not ready"}, status_code=503)
    meta = comp.skill_loader.discovered.get(name)
    if not meta:
        return JSONResponse({"error": "skill not found", "name": name}, status_code=404)
    skill_md = meta["path"] / "SKILL.md"
    if not skill_md.exists():
        return JSONResponse({"error": "SKILL.md missing"}, status_code=404)
    try:
        text = skill_md.read_text(encoding="utf-8")
    except Exception as e:
        return JSONResponse({"error": f"read failed: {e}"}, status_code=500)
    return Response(content=text, media_type="text/markdown; charset=utf-8")


@app.post("/api/skills/{name}/call")
async def skills_call(name: str, request: Request) -> dict:
    """Invoke a skill by name. Body: {args: dict}.

    The skill is dynamic-imported fresh on each call so a code change in
    ``run.py`` is picked up after backend restart. The response is the
    raw dict returned by ``run()`` plus a status envelope.
    """
    import importlib.util
    comp = get_companion()
    if not comp or not comp.skill_loader:
        return JSONResponse({"error": "skill loader not ready"}, status_code=503)
    meta = comp.skill_loader.discovered.get(name)
    if not meta:
        return JSONResponse({"error": "skill not found", "name": name}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    args = (body or {}).get("args") or {}
    run_py = meta["path"] / "run.py"
    if not run_py.exists():
        return JSONResponse({"error": "run.py missing", "name": name}, status_code=500)
    try:
        # Always import fresh so dev iteration works without restart.
        spec = importlib.util.spec_from_file_location(f"skill_runtime_{name}", run_py)
        if spec is None or spec.loader is None:
            return JSONResponse({"error": "spec failed", "name": name}, status_code=500)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "run"):
            return JSONResponse({"error": "run() not found in run.py", "name": name}, status_code=500)
        result = mod.run(args)
        return {"status": "ok", "name": name, "provider_hint": meta.get("hint", "text"), "result": result}
    except Exception as e:
        logger.exception("skill_call %s failed", name)
        return JSONResponse({"status": "error", "name": name, "error": str(e)}, status_code=500)


async def start_api(host: str = "127.0.0.1", port: int = 7890) -> Any:
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    # R7.5: Intercept uvicorn's default SystemExit on bind failure so the
    #       error propagates to main.py as a regular Python exception.
    #       The default behavior (sys.exit(3)) kills the process immediately
    #       without giving main.py's try/except any chance to log details.
    task: Optional[asyncio.Task] = None
    exc_holder: list[BaseException] = []
    async def _serve_catch():
        try:
            await server.serve()
        except BaseException as e:  # noqa: BLE001
            exc_holder.append(e)
            raise
    # Run in background
    import asyncio
    task = asyncio.create_task(_serve_catch())
    # Give it a moment to start.  bind-failure tends to finish within the
    # first 0.5s, but if the task is already done we must also read the
    # exception out of the Task so it does not surface later as an
    # unhandled Task exception.
    try:
        done, _pending = await asyncio.wait([task], timeout=0.5)
    except BaseException:  # noqa: BLE001
        done = set()

    class Runner:
        async def cleanup(self):
            server.should_exit = True
            await asyncio.sleep(0.2)
            if task is not None and not task.done():
                task.cancel()

    if exc_holder or (task.done() and task.exception() is not None):
        e: BaseException
        if exc_holder:
            e = exc_holder[0]
        else:
            e = task.exception() or RuntimeError(f"Server on {host}:{port} exited without error info")
        # sys.exit(3) is the exact error raised by uvicorn when port bind fails.
        # SystemExit bypasses most try/except Exception, so we translate it to
        # a plain OSError for main.py's reporting path.
        if isinstance(e, SystemExit):
            raise OSError(
                f"Failed to start Aerie API server on {host}:{port}. "
                f"uvicorn reported code={e.code!r}. The most common root cause on "
                f"Windows is a leftover python.exe holding LISTENING on this port "
                f"(WinError 10048). Inner={e!r}"
            ) from e
        raise
    return Runner()

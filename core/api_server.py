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
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, FileResponse, StreamingResponse

from communication.message import IncomingMessage
import main  # R6.6: for PROCESS_START_TIME / GIT_COMMIT (stale-code detection)
from config.persona_loader import (
    get_master_qq,
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
from core.self_evolver import SelfEvolver
from core.computer_control import ComputerController, PermissionLevel
from core.file_organizer import FileOrganizer
from core.doc_writer import DocWriter
from core.calendar_manager import CalendarManager
from core.persona_hub import get_persona_manager
from core.multimodal_input import AudioTranscriber
from knowledge.kb import KnowledgeBase

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(main.PROJECT_ROOT).resolve()

app = FastAPI(title="Aerie · 云栖", version="0.1.0-beta.1")

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
async def world_dashboard_snapshot(user_id: int = Query(default=0)) -> dict[str, Any]:
    """Redacted World Dashboard snapshot contract.

    This endpoint exposes only public dashboard fields. Raw world payloads,
    prompt text, message text, plugin config values, and provider details are
    deliberately dropped by whitelisting instead of recursively echoing handler
    output.
    """
    if not FeatureFlags().is_enabled("world_sidecar_v1"):
        return _world_dashboard_public_snapshot(
            {
                "status": "disabled",
                **_WORLD_DASHBOARD_EMPTY_SNAPSHOT,
            },
            status="disabled",
            handler_called=False,
        )

    comp = get_companion()
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

    if not FeatureFlags().is_enabled("world_sidecar_v1"):
        return _world_candidate_approval_response(
            status="disabled",
            candidate_id=approval["candidate_id"],
            ack=False,
            handler_called=False,
        )

    comp = get_companion()
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


# ── Health ──────────────────────────────────────────

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
        "version": "0.1.0-beta.1",
        "uptime_seconds": uptime,
        "qq_connected": qq_ws_connected,
        "git_commit": getattr(main, "GIT_COMMIT", "unknown"),
        "process_started_at": getattr(main, "PROCESS_START_ISO", ""),
        "data_path_id": str(_db.db_path.resolve()).lower(),
        "stale_code": stale_info,
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
        },
    }


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
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            cwd=str(project_root),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as e:
        return JSONResponse({"error": "spawn_failed", "detail": str(e)}, status_code=500)
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
        user_id = get_master_qq()
    else:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "invalid_message"}, status_code=400)
    if not getattr(comp, "pipeline", None):
        return JSONResponse({"error": "backend not ready"}, status_code=503)

    # Phase 4: quote + attachments

    # Block-3 R0.3: enrich attachments with extracted markdown (best-effort)
    if attachments:
        try:
            from core.attachment_handler import extract_markdown
            for att in attachments:
                if not isinstance(att, dict):
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
    result = await comp.pipeline.handle(msg, force_full=True)
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


@app.get("/api/chat/history")
async def chat_history(
    user_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    try:
        where = " WHERE user_id = ?" if user_id is not None else ""
        params = (user_id,) if user_id is not None else ()
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
    user_id: int = Query(default=None),
    since_id: int = Query(default=0),
) -> dict:
    if user_id is None:
        user_id = get_master_qq()
    try:
        rows = _db.query(
            "SELECT * FROM chat_log WHERE user_id = ? AND id > ? ORDER BY id",
            (user_id, since_id),
        )
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


# ── Emotion ─────────────────────────────────────────

@app.get("/api/emotion/state")
async def emotion_state(user_id: int | None = None) -> dict:
    comp = get_companion()
    if not comp:
        return {"error": "backend not ready"}
    if user_id is None:
        return comp.get_primary_emotion_state()
    identity = comp.identity_resolver.resolve("qq", str(user_id))
    return comp.emotion.get_state(
        user_id,
        actor_id=identity.actor_id,
    )


# ── Phase 4: Static file serving for uploads ────────────────

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
        BrainImageGenerationProvider,
        BrainImageVisionProvider,
        ImageWorkflow,
    )

    brain = getattr(get_companion(), "brain", None)
    return ImageWorkflow(
        upload_base=_upload_root(),
        feature_enabled=_image_assets_enabled(),
        generation_provider=BrainImageGenerationProvider(brain),
        vision_provider=BrainImageVisionProvider(brain),
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
    if row["role"] == "assistant" and row.get("qq_message_id"):
        try:
            qq_recalled = await comp.qq.recall_message(int(row["qq_message_id"]))
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
    return {"traces": eng.recent(user_id=user_id, source=source, limit=limit)}


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
        user_id = get_master_qq()
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
            "SELECT ts, pleasure, arousal, dominance, label, "
            "patience_value, anxiety_value, desire_value, tenderness_value, "
            "active_eruption, trigger_event "
            "FROM emotion_state_snapshot WHERE user_id = ? AND ts >= ? "
            "ORDER BY ts ASC LIMIT 5000",
            (user_id, since),
        )

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
    }


# ── Phase 9 Batch 3: YAML config editing (settings / persona / proactive) ──

# Whitelist of editable config files (only these 3 are exposed for user editing).
_YAML_ALLOWED_FILES: set[str] = {"settings.yaml", "persona.yaml", "proactive.yaml"}
_YAML_CONFIG_DIR = Path("config")
_YAML_BACKUP_DIR = Path("data/backups/config")


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
    _YAML_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    backup_path = _YAML_BACKUP_DIR / f"{filename}.{ts_ms}.yaml"
    source = _YAML_CONFIG_DIR / filename
    if source.exists():
        backup_path.write_bytes(source.read_bytes())
    else:
        backup_path.write_text("# missing source — placeholder\n", encoding="utf-8")
    return backup_path


def _yaml_latest_backup(filename: str) -> Path | None:
    """Find the most recent backup for a given yaml filename."""
    if not _YAML_BACKUP_DIR.exists():
        return None
    candidates = sorted(
        _YAML_BACKUP_DIR.glob(f"{filename}.*.yaml"),
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
            "permission_level": ctrl.permission_level.value,
            "today_operations": today_ops,
            "blocked_operations": blocked_ops,
            "total_operations": len(logs),
        }
    except Exception as e:
        logger.exception("computer_control_stats error")
        return {"error": str(e)}


@app.get("/api/computer_control/level")
async def computer_control_get_level() -> dict:
    """Get current permission level."""
    try:
        ctrl = _get_computer_controller()
        return {"level": ctrl.permission_level.value}
    except Exception as e:
        return {"error": str(e)}


@app.put("/api/computer_control/level")
async def computer_control_set_level(request: Request) -> dict:
    """Set permission level: view_only / standard / full."""
    try:
        body = await request.json()
        level_str = (body.get("level") or "").lower()
        level_map = {
            "view_only": PermissionLevel.VIEW_ONLY,
            "standard": PermissionLevel.STANDARD,
            "full": PermissionLevel.FULL,
        }
        if level_str not in level_map:
            return JSONResponse({"error": "invalid level"}, status_code=400)
        ctrl = _get_computer_controller()
        ctrl.set_permission(level_map[level_str])
        emit("computer_control_level_changed", level=level_str)
        return {"status": "ok", "level": level_str}
    except Exception as e:
        logger.exception("computer_control_set_level error")
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
async def computer_control_approve(approval_id: str) -> dict:
    """Approve a pending action."""
    try:
        ctrl = _get_computer_controller()
        result = ctrl.approve_action(approval_id)
        if result:
            emit("computer_control_approval_updated",
                id=approval_id,
                status="approved",
            )
            return {"status": "ok", "approved": True}
        return JSONResponse({"error": "approval not found"}, status_code=404)
    except Exception as e:
        logger.exception("approve error")
        return {"error": str(e)}


@app.post("/api/computer_control/approvals/{approval_id}/reject")
async def computer_control_reject(approval_id: str) -> dict:
    """Reject a pending action."""
    try:
        ctrl = _get_computer_controller()
        result = ctrl.reject_action(approval_id)
        if result:
            emit("computer_control_approval_updated",
                id=approval_id,
                status="rejected",
            )
            return {"status": "ok", "rejected": True}
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
        name = body.get("name", "未命名任务")
        description = body.get("description", "")
        task_type = body.get("task_type", "generic")
        priority_str = body.get("priority", "medium")
        task_data = body.get("data", {})

        from core.async_task_manager import TaskPriority
        priority_map = {
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
        }
        priority = priority_map.get(priority_str.lower(), TaskPriority.MEDIUM)

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
async def stats_tokens(user_id: int = Query(default=None)) -> dict:
    if user_id is None:
        user_id = get_master_qq()
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
        return load_settings()
    except Exception as e:
        return {"error": str(e)}


@app.put("/api/settings")
async def settings_put(request: Request) -> dict:
    """Update settings (partial merge)."""
    try:
        body = await request.json()
        save_settings(body)
        if isinstance(body, dict) and isinstance(body.get("weather"), dict) and "city" in body["weather"]:
            try:
                from core.location_resolver import clear_city_cache
                clear_city_cache()
            except Exception as e:
                logger.warning("settings_put: location cache clear failed: %s", e)
        return {"status": "ok", "saved": list(body.keys())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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
     "default_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
    {"key": "dashscope", "name": "通义千问 (DashScope)", "env_key": "DASHSCOPE_API_KEY",
     "env_url": "QWEN_BASE_URL", "env_model": "QWEN_MODEL",
     "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus"},
    {"key": "doubao", "name": "豆包 (Doubao)", "env_key": "DOUBAO_API_KEY",
     "env_url": "DOUBAO_BASE_URL", "env_model": "DOUBAO_MODEL",
     "default_url": "https://ark.cn-beijing.volces.com/api/v3", "default_model": "doubao-seed-2-1-turbo-260628"},
    {"key": "siliconflow", "name": "SiliconFlow", "env_key": "SILICONFLOW_API_KEY",
     "env_url": "SILICONFLOW_BASE_URL", "env_model": "SILICONFLOW_MODEL",
     "default_url": "https://api.siliconflow.com/v1", "default_model": "google/gemma-4-26B-A4B-it"},
    {"key": "openai", "name": "OpenAI / GPT", "env_key": "OPENAI_API_KEY",
     "env_url": "OPENAI_BASE_URL", "env_model": "OPENAI_MODEL",
     "default_url": "https://api.codexgood.com/v1", "default_model": "gpt-5.5"},
    {"key": "gemini", "name": "Gemini", "env_key": "GEMINI_API_KEY",
     "env_url": "GEMINI_BASE_URL", "env_model": "GEMINI_MODEL",
     "default_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-2.0-flash-exp"},
    {"key": "glm", "name": "智谱 GLM", "env_key": "BIGMODEL_API_KEY",
     "env_url": "BIGMODEL_BASE_URL", "env_model": "BIGMODEL_MODEL",
     "default_url": "https://open.bigmodel.cn/api/paas/v4/", "default_model": "glm-4-plus"},
    {"key": "minimax", "name": "MiniMax", "env_key": "MINIMAX_API_KEY",
     "env_url": "MINIMAX_BASE_URL", "env_model": "MINIMAX_MODEL",
     "default_url": "https://api.minimaxi.com/v1", "default_model": "MiniMax-M3"},
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


@app.get("/api/env/providers")
async def env_providers() -> dict:
    """Return list of AI providers with config status (keys masked)."""
    env = _read_env_file()
    providers = []
    for meta in _PROVIDER_META:
        key_val = env.get(meta["env_key"], "")
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
        })
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
        api_key = body.get("api_key")
        if api_key is not None:
            env[meta["env_key"]] = api_key
        base_url = body.get("base_url")
        if base_url is not None:
            env[meta["env_url"]] = base_url
        model = body.get("model")
        if model is not None:
            env[meta["env_model"]] = model

        _write_env_file(env)
        return {"status": "ok", "provider": provider_key}
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
    fields = _knowledge_fields(await request.json())
    if not fields:
        return JSONResponse({"error": "category, title and content are required"}, status_code=400)
    try:
        item_id = _knowledge.add(*fields)
        return JSONResponse(_knowledge.get(item_id), status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/knowledge/{item_id}")
async def knowledge_update(item_id: int, request: Request) -> dict:
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
async def knowledge_delete(item_id: int) -> dict:
    try:
        if not _knowledge.delete(item_id):
            return JSONResponse({"error": "knowledge not found"}, status_code=404)
        return {"status": "ok", "id": item_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── System Stats ──────────────────────────────────────

@app.get("/api/stats/system")
async def system_stats() -> dict:
    """Return system-level stats."""
    try:
        uptime_seconds = int(time.time() - _START_TIME)
        hours = uptime_seconds // 3600
        mins = (uptime_seconds % 3600) // 60
        uptime_str = f"{hours}h {mins}m"

        # Count total messages
        msg_count = _db.query_one(
            "SELECT COUNT(*) as cnt FROM chat_log"
        )
        message_count = msg_count["cnt"] if msg_count else 0

        # Try to get CPU and memory (platform-specific)
        cpu_str = "N/A"
        memory_str = "N/A"
        try:
            import psutil
            cpu_str = f"{psutil.cpu_percent(interval=0.1):.1f}%"
            mem = psutil.virtual_memory()
            memory_str = f"{mem.percent:.1f}% ({mem.used // 1048576}MB)"
        except ImportError:
            pass

        return {
            "uptime": uptime_str,
            "uptime_seconds": uptime_seconds,
            "cpu": cpu_str,
            "memory": memory_str,
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
async def persona_avatar_upload(file: UploadFile = File(...)) -> dict:
    """Upload persona avatar. PNG/JPG only, ≤2 MB. Auto-backs up previous."""
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
        url = save_avatar_bytes(data, ext=ext)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    # R7.5: return the inline dataURL too so the renderer can update
    # <img src> immediately without a follow-up GET /api/persona round
    # trip. Saves one network hop and avoids the brief flash of the
    # broken-image icon while /api/persona is in flight.
    import base64 as _b64
    dataurl = (
        "data:" + file.content_type + ";base64,"
        + _b64.b64encode(data).decode("ascii")
    )
    return {
        "status": "ok",
        "url": url,
        "size": len(data),
        "content_type": file.content_type,
        "avatar_dataurl": dataurl,
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
    return Response(
        content=data,
        media_type=ct,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ── v13.0: Persona Hub (人设中心) ──────────────────────


@app.get("/api/persona/hub/list")
async def persona_hub_list() -> dict:
    """列出所有人设模板。"""
    try:
        personas = _persona_mgr.list_personas()
        return {"status": "ok", "personas": personas, "active_id": _persona_mgr.get_active_id()}
    except Exception as e:
        logger.exception("persona hub list error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/persona/hub/{persona_id}")
async def persona_hub_get(persona_id: str) -> dict:
    """获取指定人设的完整配置。"""
    try:
        if not _persona_mgr.has_persona(persona_id):
            return JSONResponse({"error": "persona not found"}, status_code=404)
        persona = _persona_mgr.get_persona(persona_id)
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
    """删除人设（内置人设不可删除）。"""
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


# ── Daily Brief (Block-4A R1.4) ────────────────────────
@app.get("/api/brief/today")
async def brief_today() -> dict:
    """Return today's brief JSON. If missing, lazily generate."""
    from datetime import datetime
    from core import brief_fetcher
    from core.brain import Brain

    today = datetime.now().strftime("%Y-%m-%d")
    cached = brief_fetcher.load_brief(today)
    if cached and cached.get("ai_news") is not None:
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
        brain = Brain()
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
    from core.brain import Brain

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
        brain = Brain()
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
        from core.brain import Brain
        opts = Brain().get_ai_options()
        default = Brain().get_default_provider()
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
        from core.brain import Brain
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body or {}
        cmd = (body.get("command") or "").strip()
        args = body.get("args") or []
        if not cmd:
            return JSONResponse({"error": "missing command"}, status_code=400)
        result = Brain().safe_shell(cmd, args)
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
    # Run in background
    import asyncio
    task = asyncio.create_task(server.serve())
    # Give it a moment to start
    await asyncio.sleep(0.5)

    class Runner:
        async def cleanup(self):
            server.should_exit = True
            await asyncio.sleep(0.2)
            if not task.done():
                task.cancel()

    return Runner()

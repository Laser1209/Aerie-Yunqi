"""Aerie · 云栖 v9.0 — HTTP API server (FastAPI + uvicorn).

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
import json
import logging
import time
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
from core.token_tracker import get_token_tracker
from core.cognition import CognitionEngine
from core.event_stream import stream as event_stream_generator
from core.self_evolver import SelfEvolver

logger = logging.getLogger(__name__)

app = FastAPI(title="Aerie · 云栖", version="9.0.0")

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
_START_TIME = time.time()


# ── Health ──────────────────────────────────────────

@app.get("/api/health")
async def health(request: Request) -> dict:
    comp = get_companion()
    qq_connected = comp.qq.is_connected if comp else False
    uptime = int(time.time() - _START_TIME)
    # R6.6: also report whether the running process is stale (i.e. some
    # source file has been modified after this Python process started).
    stale_info = _check_stale_code()
    return {
        "status": "ok",
        "app": "Aerie · 云栖",
        "version": "9.0.0",
        "uptime_seconds": uptime,
        "qq_connected": qq_connected,
        "git_commit": getattr(main, "GIT_COMMIT", "unknown"),
        "process_started_at": getattr(main, "PROCESS_START_ISO", ""),
        "stale_code": stale_info,
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


# ── Chat ───────────────────────────────────────────

@app.post("/api/chat/send")
async def chat_send(request: Request) -> dict:
    body = await request.json()
    text = (body.get("text") or body.get("content") or "").strip()
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)

    user_id = body.get("user_id")
    if user_id is None:
        user_id = get_master_qq()
    else:
        user_id = int(user_id)

    comp = get_companion()
    if not comp or not comp.pipeline:
        return JSONResponse({"error": "backend not ready"}, status_code=503)

    # Phase 4: quote + attachments
    reply_to_id = int(body.get("reply_to_id", 0) or 0)
    attachments = body.get("attachments") or []

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

    return {
        "reply": result.get("reply", ""),
        "user_msg_id": result.get("user_msg_id", 0),
        "ai_msg_id": result.get("ai_msg_id", 0),
        "reply_to_id": reply_to_id,
        "status": "ok",
    }


@app.get("/api/chat/history")
async def chat_history(
    user_id: int = Query(default=None),
    limit: int = Query(default=50),
) -> dict:
    if user_id is None:
        user_id = get_master_qq()
    try:
        rows = _db.query(
            "SELECT * FROM chat_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows.reverse()
        # Parse attachments JSON
        import json as _json
        for r in rows:
            if r.get("attachments"):
                try:
                    r["attachments"] = _json.loads(r["attachments"])
                except Exception:
                    r["attachments"] = []
            else:
                r["attachments"] = []
        return {"history": rows, "user_id": user_id}
    except Exception as e:
        return {"history": [], "error": str(e)}


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
async def emotion_state(user_id: int = Query(default=0)) -> dict:
    comp = get_companion()
    if not comp:
        return {"error": "backend not ready"}
    return comp.emotion.get_state(user_id)


# ── Phase 4: Static file serving for uploads ────────────────

@app.get("/uploads/{filename}")
async def serve_upload(filename: str):
    """Serve uploaded files. Restricts to uploads/ directory (no traversal)."""
    from pathlib import Path
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    target = Path(UPLOAD_DIR) / filename
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target))


# ── Phase 4: Recall ─────────────────────────────────────────


# ── Upload ───────────────────────────────────────────

UPLOAD_DIR = "uploads"
ALLOWED_TYPES = {
    # Block-3 R0.3: full office + document coverage
    # images
    "image/png", "image/jpeg", "image/gif",
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
        from pathlib import Path

        upload_path = Path(UPLOAD_DIR)
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
    async def gen():
        async for line in event_stream_generator():
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
    if user_id is None:
        user_id = get_master_qq()
    window_ms = {
        "1h": 3600 * 1000,
        "24h": 24 * 3600 * 1000,
        "7d": 7 * 24 * 3600 * 1000,
        "30d": 30 * 24 * 3600 * 1000,
    }[window]
    since = int(time.time() * 1000) - window_ms
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


@app.get("/api/self_evolve/{proposal_id}")
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


# R7.3: dedicated city-set endpoint so the brief-drawer pin button can
# write the weather city + bust the IP cache atomically. The previous
# path (/api/settings PUT) does not clear data/cache/city.json, which
# meant the next /api/brief/today still returned the cached IP city.
@app.post("/api/location/set")
async def location_set(request: Request) -> dict:
    """Set the manual city override used by the daily brief weather.

    Body: ``{"city": "上海"}`` (empty string clears the override).
    Side effects:
      1. Writes ``settings.yaml.weather.city`` (partial merge).
      2. Deletes ``data/cache/city.json`` so the next call to
         ``location_resolver.resolve_city()`` re-evaluates from
         manual → IP instead of returning the stale cache.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    city = str((body or {}).get("city") or "").strip()
    try:
        save_settings({"weather": {"city": city}})
    except Exception as e:
        return JSONResponse({"error": f"settings save failed: {e}"}, status_code=500)
    # Bust the IP cache so resolve_city() picks up the new manual value
    # immediately on the next /api/brief/today call.
    try:
        cache_file = Path("data/cache/city.json")
        if cache_file.exists():
            cache_file.unlink()
            logger.info("location_set: cleared data/cache/city.json")
    except Exception as e:
        logger.warning("location_set: cache clear failed: %s", e)
    return {"status": "ok", "city": city, "manual": bool(city)}


# ── Anniversary ──────────────────────────────────────

@app.get("/api/anniversary/list")
async def anniversary_list() -> dict:
    """List all anniversaries with days_since calculated."""
    try:
        rows = _db.query("SELECT * FROM anniversary ORDER BY date")
        from datetime import datetime as dt
        for row in rows:
            d = dt.strptime(row["date"], "%Y-%m-%d")
            row["days_since"] = (dt.now() - d).days
        return {"items": rows, "count": len(rows)}
    except Exception as e:
        return {"items": [], "error": str(e)}


@app.post("/api/anniversary/add")
async def anniversary_add(request: Request) -> dict:
    """Add a new anniversary."""
    try:
        body = await request.json()
        aid = _db.insert("anniversary", {
            "name": body.get("name", ""),
            "date": body.get("date", ""),
            "type": body.get("type", "custom"),
            "description": body.get("description", ""),
        })
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
    category: str = Query(default=""),
    search: str = Query(default=""),
) -> dict:
    """List knowledge base entries with optional filters."""
    try:
        sql = "SELECT id, category, title, tags, created_at FROM knowledge_base WHERE 1=1"
        params = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        if search:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        sql += " ORDER BY updated_at DESC LIMIT 100"
        rows = _db.query(sql, tuple(params))
        return {"items": rows, "count": len(rows)}
    except Exception as e:
        return {"items": [], "error": str(e)}


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
        }
    except Exception as e:
        return {"error": str(e)}


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

    # Compose Markdown
    try:
        brain = Brain()
        md = await brain.compose_brief(sections)
    except Exception as e:
        logger.warning("brief_today: compose_brief failed: %s", e)
        md = ""

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
    try:
        brain = Brain()
        md = await brain.compose_brief(sections)
    except Exception:
        md = ""
    today = sections.get("date") or datetime.now().strftime("%Y-%m-%d")
    brief_fetcher.save_brief(today, sections, html=md)
    return {"status": "ok", "date": today, "markdown": md, "brief": sections, "limit": effective_limit or 0}


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

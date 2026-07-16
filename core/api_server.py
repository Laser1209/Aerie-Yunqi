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
"""

from __future__ import annotations
import logging
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from communication.message import IncomingMessage
from config.persona_loader import get_master_qq
from core.companion import get_companion
from core.database import Database
from core.napcat_launcher import get_launcher
from core.chat_events import emit

logger = logging.getLogger(__name__)

app = FastAPI(title="Aerie · 云栖", version="9.0.0")

_db = Database()
_START_TIME = time.time()


# ── Health ──────────────────────────────────────────

@app.get("/api/health")
async def health(request: Request) -> dict:
    comp = get_companion()
    qq_connected = comp.qq.is_connected if comp else False
    uptime = int(time.time() - _START_TIME)
    return {
        "status": "ok",
        "app": "Aerie · 云栖",
        "version": "9.0.0",
        "uptime_seconds": uptime,
        "qq_connected": qq_connected,
    }


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

    msg = IncomingMessage.from_local(text, user_id)
    result = await comp.pipeline.handle(msg, force_full=True)
    if not result:
        return {"reply": "(已收到)", "status": "ok"}

    return {
        "reply": result.get("reply", ""),
        "user_msg_id": result.get("user_msg_id", 0),
        "ai_msg_id": result.get("ai_msg_id", 0),
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


# ── Tools ───────────────────────────────────────────

@app.get("/api/tools/list")
async def tools_list() -> dict:
    comp = get_companion()
    if not comp:
        return {"tools": [], "error": "backend not ready"}
    schema = comp.tool_registry.get_openai_schema()
    return {"tools": schema, "count": len(schema)}


# ── Stats ───────────────────────────────────────────

@app.get("/api/stats/tokens")
async def stats_tokens(user_id: int = Query(default=None)) -> dict:
    if user_id is None:
        user_id = get_master_qq()
    try:
        total = _db.query_one(
            "SELECT SUM(total_tokens) as total, COUNT(*) as count FROM token_usage WHERE user_id = ?",
            (user_id,),
        )
        return {
            "total_tokens": total.get("total", 0) if total else 0,
            "total_calls": total.get("count", 0) if total else 0,
            "user_id": user_id,
        }
    except Exception as e:
        return {"error": str(e)}


# ── Startup ─────────────────────────────────────────

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

"""Aerie · 云栖 v9.0 — HTTP API server (aiohttp).

22+ endpoints for Electron renderer and external tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from aiohttp import web

from communication.router import Router
from core.brain import Brain
from core.companion import Companion, get_companion
from core.database import Database
from core.napcat_launcher import get_launcher
from core.token_tracker import TokenTracker
from core.system_monitor import SystemMonitor
from config.persona_loader import load_proactive, load_settings
from core.backup import BackupManager


logger = logging.getLogger(__name__)


APP_VERSION = "9.0.0"
APP_NAME = "Aerie · 云栖"


def _json(obj: Any, status: int = 200) -> web.Response:
    return web.json_response(obj, status=status, dumps=lambda x: json.dumps(x, ensure_ascii=False))


async def health(request: web.Request) -> web.Response:
    return _json({"status": "ok", "app": APP_NAME, "version": APP_VERSION})


async def version(request: web.Request) -> web.Response:
    return _json({"name": APP_NAME, "version": APP_VERSION})


async def capabilities(request: web.Request) -> web.Response:
    return _json({
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "modules": {
            "auto_wake": True,
            "persona_yita": True,
            "emotion_pad": True,
            "cumulative_threshold": True,
            "recall_mechanism": True,
            "multi_provider": True,
            "tool_calling": True,
            "knowledge_base": True,
            "long_term_memory": True,
            "data_backup": True,
            "self_healing": True,
        },
    })


async def llm_providers(request: web.Request) -> web.Response:
    comp = get_companion()
    providers = []
    if comp and comp.brain:
        for p in comp.brain.providers:
            providers.append({"name": p.name, "model": p.model})
    return _json({"providers": providers})


async def qq_status(request: web.Request) -> web.Response:
    comp = get_companion()
    if comp and comp.qq:
        s = await comp.qq.get_status()
        return _json(s)
    return _json({"connected": False, "self_qq": 0})


# ----- NapCat launcher endpoints -----
async def napcat_status(request: web.Request) -> web.Response:
    try:
        launcher = get_launcher()
        launcher.refresh_status()
        return _json(launcher._status.to_dict())
    except Exception as e:  # noqa: BLE001
        return _json({"installed": False, "running": False, "error": str(e)[:200]}, status=500)


async def napcat_start(request: web.Request) -> web.Response:
    body = await request.json() if request.body_exists else {}
    prefer_user = bool(body.get("prefer_user", True))
    wait_port = bool(body.get("wait_port", True))
    try:
        launcher = get_launcher()
        result = await launcher.start(prefer_user=prefer_user, wait_port=wait_port)
        return _json(result)
    except Exception as e:  # noqa: BLE001
        return _json({"started": False, "error": str(e)[:200]}, status=500)


async def napcat_stop(request: web.Request) -> web.Response:
    try:
        launcher = get_launcher()
        result = await launcher.stop()
        return _json(result)
    except Exception as e:  # noqa: BLE001
        return _json({"stopped": False, "error": str(e)[:200]}, status=500)


async def napcat_bootstrap(request: web.Request) -> web.Response:
    """Auto-connect: ensure NapCat is up, then verify the QQ WS is reachable.

    Called at app startup. Returns a summary suitable for the Electron UI.
    """
    body = await request.json() if request.body_exists else {}
    prefer_user = bool(body.get("prefer_user", True))
    try:
        launcher = get_launcher()
        launcher.refresh_status()
        if launcher._status.ws_port_open:
            return _json({"status": "already_ready", "port_open": True, "installed": launcher._status.installed})
        if not launcher._status.installed:
            return _json({"status": "not_installed", "installed": False, "port_open": False}, status=404)
        result = await launcher.start(prefer_user=prefer_user, wait_port=True)
        return _json({
            "status": "ok" if result.get("port_open") else "starting",
            "installed": True,
            "port_open": result.get("port_open", False),
            "message": result.get("message", ""),
        })
    except Exception as e:  # noqa: BLE001
        return _json({"status": "error", "error": str(e)[:200]}, status=500)


async def scheduler_jobs(request: web.Request) -> web.Response:
    comp = get_companion()
    if comp and comp.scheduler:
        return _json({"jobs": comp.scheduler.list_jobs()})
    return _json({"jobs": []})


async def list_tools(request: web.Request) -> web.Response:
    comp = get_companion()
    if comp:
        return _json({"tools": comp.tool_registry.list_tools()})
    return _json({"tools": []})


async def knowledge_stats(request: web.Request) -> web.Response:
    comp = get_companion()
    if comp:
        return _json(comp.knowledge.stats())
    return _json({"entries": 0, "categories": 0})


async def emotion_current(request: web.Request) -> web.Response:
    user_id = int(request.query.get("user_id", 0))
    comp = get_companion()
    if not comp:
        return _json({"label": "neutral"})
    state = comp.emotion.get_state(user_id)
    return _json(state.as_dict())


async def emotion_history(request: web.Request) -> web.Response:
    user_id = int(request.query.get("user_id", 0))
    limit = int(request.query.get("limit", 50))
    comp = get_companion()
    if not comp:
        return _json({"history": []})
    return _json({"history": comp.emotion.get_history(user_id, limit=limit)})


async def proactive_pause(request: web.Request) -> web.Response:
    body = await request.json() if request.body_exists else {}
    minutes = int(body.get("minutes", 60))
    comp = get_companion()
    if comp:
        comp.policy.pause(minutes=minutes)
        return _json({"status": "paused", "until": comp.policy.pause_until.isoformat() if comp.policy.pause_until else None})
    return _json({"status": "not_ready"})


async def proactive_resume(request: web.Request) -> web.Response:
    comp = get_companion()
    if comp:
        comp.policy.resume()
        return _json({"status": "resumed"})
    return _json({"status": "not_ready"})


async def proactive_state(request: web.Request) -> web.Response:
    comp = get_companion()
    if comp:
        return _json(comp.policy.get_state())
    return _json({"enabled": False})


async def proactive_push(request: web.Request) -> web.Response:
    body = await request.json() if request.body_exists else {}
    scene = body.get("scene", "morning_brief")
    template = body.get("template", "")
    comp = get_companion()
    if not comp or not comp.messenger:
        return _json({"status": "not_ready"}, status=503)
    master_id = int(load_settings().get("qq", {}).get("self_qq", 0))
    result = await comp.messenger.push(scene, master_id, template, **body)
    return _json(result)


async def chat_send(request: web.Request) -> web.Response:
    body = await request.json() if request.body_exists else {}
    user_id = int(body.get("user_id", 0))
    content = body.get("content", "")
    comp = get_companion()
    if not comp or not comp.pipeline:
        return _json({"status": "not_ready"}, status=503)
    from communication.message import IncomingMessage, MessageType
    msg = IncomingMessage(
        user_id=user_id,
        content=content,
        msg_type=MessageType.PRIVATE,
    )
    try:
        result = await comp.pipeline.handle(msg)
        return _json({"status": "ok", "result": result})
    except Exception as e:
        return _json({"status": "error", "error": str(e)[:200]}, status=500)


async def chat_history(request: web.Request) -> web.Response:
    user_id = int(request.query.get("user_id", 0))
    limit = int(request.query.get("limit", 50))
    db = Database()
    rows = db.query(
        "SELECT id, role, content, msg_type, route_mode, created_at FROM chat_log "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    return _json({"history": list(reversed(rows))})


async def chat_poll(request: web.Request) -> web.Response:
    user_id = int(request.query.get("user_id", 0))
    since_id = int(request.query.get("since_id", 0))
    db = Database()
    rows = db.query(
        "SELECT id, role, content, msg_type, route_mode, created_at FROM chat_log "
        "WHERE user_id = ? AND id > ? ORDER BY id ASC",
        (user_id, since_id),
    )
    return _json({"messages": rows, "max_id": max((r["id"] for r in rows), default=since_id)})


async def token_usage(request: web.Request) -> web.Response:
    user_id = int(request.query.get("user_id", 0))
    tracker = TokenTracker()
    return _json(tracker.get_today_stats(user_id))


async def model_calls(request: web.Request) -> web.Response:
    user_id = int(request.query.get("user_id", 0))
    days = int(request.query.get("days", 7))
    tracker = TokenTracker()
    return _json({"by_model": tracker.get_by_model(user_id, days=days)})


async def status_system(request: web.Request) -> web.Response:
    return _json(SystemMonitor().get_stats())


async def status_all(request: web.Request) -> web.Response:
    sys_stats = SystemMonitor().get_stats()
    comp = get_companion()
    qq = await comp.qq.get_status() if comp else {"connected": False}
    scheduler = comp.scheduler.list_jobs() if comp and comp.scheduler else []
    tools = comp.tool_registry.list_tools() if comp else []
    token = TokenTracker().get_today_stats(0) if comp else {}
    return _json({
        "system": sys_stats,
        "qq": qq,
        "scheduler": scheduler,
        "tools": tools,
        "token": token,
    })


async def memorial_list(request: web.Request) -> web.Response:
    return _json({"items": []})


async def memorial_anniversary(request: web.Request) -> web.Response:
    return _json({"days_together": 0})


async def get_config(request: web.Request) -> web.Response:
    return _json(load_settings())


async def post_config(request: web.Request) -> web.Response:
    body = await request.json() if request.body_exists else {}
    settings = load_settings()
    settings.update(body)
    try:
        with open("config/settings.yaml", "w", encoding="utf-8") as f:
            import yaml
            yaml.safe_dump(settings, f, allow_unicode=True, default_flow_style=False)
        return _json({"status": "ok"})
    except Exception as e:
        return _json({"status": "error", "error": str(e)[:200]}, status=500)


async def data_stats(request: web.Request) -> web.Response:
    db = Database()
    chat = db.query_one("SELECT COUNT(*) AS n FROM chat_log") or {"n": 0}
    mem = db.query_one("SELECT COUNT(*) AS n FROM long_term_memory") or {"n": 0}
    kb = db.query_one("SELECT COUNT(*) AS n FROM knowledge_base") or {"n": 0}
    emo = db.query_one("SELECT COUNT(*) AS n FROM emotion_log") or {"n": 0}
    push = db.query_one("SELECT COUNT(*) AS n FROM push_log") or {"n": 0}
    tools = db.query_one("SELECT COUNT(*) AS n FROM tool_usage") or {"n": 0}
    return _json({
        "chat_log": chat["n"],
        "long_term_memory": mem["n"],
        "knowledge_base": kb["n"],
        "emotion_log": emo["n"],
        "push_log": push["n"],
        "tool_usage": tools["n"],
    })


async def backup_create(request: web.Request) -> web.Response:
    bm = BackupManager()
    path = bm.create_backup()
    return _json({"status": "ok", "path": str(path)})


async def backup_migrate(request: web.Request) -> web.Response:
    body = await request.json() if request.body_exists else {}
    target = body.get("target", str(_desktop_dir()))
    bm = BackupManager()
    path = bm.migrate_to(target)
    return _json({"status": "ok", "path": str(path)})


def _desktop_dir() -> str:
    import os
    return os.path.join(os.path.expanduser("~"), "Desktop")


async def emotion_panel(request: web.Request) -> web.Response:
    """Hidden slot panel for the sidebar (debug view)."""
    user_id = int(request.query.get("user_id", 0))
    comp = get_companion()
    if not comp:
        return _json({"panel": ""})
    return _json({"panel": comp.cum_emotion.get_panel(user_id)})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/version", version)
    app.router.add_get("/api/capabilities", capabilities)
    app.router.add_get("/api/llm/providers", llm_providers)
    app.router.add_get("/api/qq/status", qq_status)
    app.router.add_get("/api/napcat/status", napcat_status)
    app.router.add_post("/api/napcat/start", napcat_start)
    app.router.add_post("/api/napcat/stop", napcat_stop)
    app.router.add_post("/api/napcat/bootstrap", napcat_bootstrap)
    app.router.add_get("/api/scheduler/jobs", scheduler_jobs)
    app.router.add_get("/api/tools", list_tools)
    app.router.add_get("/api/knowledge/stats", knowledge_stats)
    app.router.add_get("/api/emotion/current", emotion_current)
    app.router.add_get("/api/emotion/history", emotion_history)
    app.router.add_get("/api/emotion/panel", emotion_panel)
    app.router.add_post("/api/proactive/pause", proactive_pause)
    app.router.add_post("/api/proactive/resume", proactive_resume)
    app.router.add_get("/api/proactive/state", proactive_state)
    app.router.add_post("/api/proactive/push", proactive_push)
    app.router.add_post("/api/chat/send", chat_send)
    app.router.add_get("/api/chat/history", chat_history)
    app.router.add_get("/api/chat/poll", chat_poll)
    app.router.add_get("/api/token/usage", token_usage)
    app.router.add_get("/api/model/calls", model_calls)
    app.router.add_get("/api/status/system", status_system)
    app.router.add_get("/api/status/all", status_all)
    app.router.add_get("/api/memorial/list", memorial_list)
    app.router.add_get("/api/memorial/anniversary", memorial_anniversary)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", post_config)
    app.router.add_get("/api/data/stats", data_stats)
    app.router.add_post("/api/backup/create", backup_create)
    app.router.add_post("/api/backup/migrate", backup_migrate)
    return app


async def start_api(host: str = "127.0.0.1", port: int = 7890) -> web.AppRunner:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    return runner

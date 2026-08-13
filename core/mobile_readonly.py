"""Read-only capability facade for the isolated mobile gateway.

This module deliberately exposes only safe, read-only views of desktop
capabilities.  It never accepts POST/PUT/DELETE and never proxies the broad
local management API.  All data flows through the shared Companion instance
so the mobile gateway observes exactly what the desktop sees.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from core.brief_fetcher import load_brief
from core.weather_service import (
    fetch_weather_for_city,
    fetch_weather_for_current_location,
)

logger = logging.getLogger(__name__)

_LAYER_ORDER = ("transient", "short_term", "long_term", "permanent")


class MobileReadonlyError(Exception):
    """Raised when a read-only capability cannot be produced safely."""

    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _companion() -> Any:
    from core.companion import get_companion

    comp = get_companion()
    if comp is None:
        raise MobileReadonlyError("service_unavailable", status_code=503)
    return comp


def _safe_text(value: Any, fallback: str = "") -> str:
    return str(value).strip() if value is not None else fallback


async def get_brief() -> dict[str, Any]:
    """Return today's brief (lazy-generated cache) with a safety fallback."""

    try:
        payload = await asyncio.to_thread(load_brief, datetime.now().strftime("%Y-%m-%d"))
    except Exception:
        logger.warning("readonly brief load failed", exc_info=True)
        payload = None
    if payload is None:
        raise MobileReadonlyError("brief_unavailable", status_code=404)
    return {"brief": payload}


async def get_world() -> dict[str, Any]:
    """Return the redacted World Dashboard snapshot (read-only)."""

    comp = _companion()
    handler = getattr(comp, "get_world_dashboard_snapshot", None)
    if not callable(handler):
        raise MobileReadonlyError("world_unavailable", status_code=503)
    try:
        result = handler(user_id=0)
        if hasattr(result, "__await__"):
            result = await result
    except Exception:
        logger.warning("readonly world snapshot failed", exc_info=True)
        raise MobileReadonlyError("world_unavailable", status_code=503) from None
    return {"world": result or {}}


async def get_memory(user_id: int) -> dict[str, Any]:
    """Return the layered memory archive for the given user (read-only)."""

    comp = _companion()
    memory = getattr(comp, "memory", None)
    if memory is None:
        raise MobileReadonlyError("memory_unavailable", status_code=503)
    layers: dict[str, list[Any]] = {}
    for layer_name in _LAYER_ORDER:
        try:
            items = memory.list_by_user(user_id, layer=layer_name, limit=50)
        except Exception:
            logger.warning("readonly memory layer %s failed", layer_name, exc_info=True)
            items = []
        layers[layer_name] = [
            {
                "id": str(item.get("id", "") if isinstance(item, dict) else getattr(item, "memory_id", "") or ""),
                "content": str(item.get("content", "") if isinstance(item, dict) else getattr(item, "content", "")),
                "memoryType": str(item.get("memory_type", "") if isinstance(item, dict) else ""),
                "importance": item.get("importance", "") if isinstance(item, dict) else "",
                "createdAt": str(item.get("created_at", "") if isinstance(item, dict) else ""),
            }
            for item in (items or [])
        ]
    return {"layers": layers}


async def get_weather() -> dict[str, Any]:
    """Return current weather plus position (read-only)."""

    comp = _companion()
    city = ""
    try:
        location = getattr(comp, "get_current_location", None)
        if callable(location):
            loc = location()
            city = _safe_text(loc.get("city") if isinstance(loc, dict) else "")
    except Exception:
        logger.debug("readonly location lookup failed", exc_info=True)
    try:
        if city:
            weather = await fetch_weather_for_city(city)
        else:
            weather = await fetch_weather_for_current_location()
    except Exception:
        logger.warning("readonly weather fetch failed", exc_info=True)
        raise MobileReadonlyError("weather_unavailable", status_code=503) from None
    return {"weather": weather or {}, "city": city}

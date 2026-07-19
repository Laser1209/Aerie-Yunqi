from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _value(data: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def normalize_weather(city: str, result: dict[str, Any] | None, location: dict | None = None) -> dict:
    location = location or {}
    result = result or {}
    forecast = result.get("forecast") or result.get("forecasts") or []
    if not isinstance(forecast, list):
        forecast = []
    return {
        "city": (city or location.get("city") or "上海").strip(),
        "source": location.get("source") or "manual",
        "manual": bool(location.get("manual")),
        "fallback": bool(location.get("fallback")),
        "temp": _value(result, "temperature", "temp", default="—"),
        "desc": _value(result, "weather", "desc", "text", default="—"),
        "humidity": _value(result, "humidity"),
        "wind": _value(result, "wind", "wind_direction", "windPower"),
        "suggestion": _value(result, "suggestion", "tips", default="穿合适的衣服。"),
        "forecast": forecast,
        "ts": int(time.time()),
        "error": "",
        "stub": False,
    }


def fallback_weather(city: str, location: dict | None = None, error: str = "") -> dict:
    location = location or {}
    return {
        "city": (city or location.get("city") or "上海").strip(),
        "source": location.get("source") or "fallback",
        "manual": bool(location.get("manual")),
        "fallback": bool(location.get("fallback")),
        "temp": "26" if not error else "—",
        "desc": "多云" if not error else "获取失败",
        "humidity": "",
        "wind": "",
        "suggestion": "穿合适的衣服。" if not error else "天气暂时获取失败，请稍后重试。",
        "forecast": [],
        "ts": int(time.time()),
        "error": error,
        "stub": True,
    }


async def fetch_weather_for_city(city: str, location: dict | None = None) -> dict:
    city = (city or "").strip() or "上海"
    location = location or {"city": city, "source": "manual", "manual": True, "fallback": False}
    try:
        from mcp_Bai_Du_Di_Tu import map_weather  # type: ignore
    except Exception:
        logger.debug("weather_service: map_weather MCP unavailable; using stub")
        return fallback_weather(city, location)
    try:
        result = map_weather(city=city)
        if inspect.iscoroutine(result):
            result = await result
        else:
            result = await asyncio.to_thread(lambda: result)
        if not isinstance(result, dict):
            return fallback_weather(city, location, "天气数据格式异常")
        return normalize_weather(city, result, location)
    except Exception as e:
        logger.warning("weather_service: map_weather error: %s", e)
        return fallback_weather(city, location, str(e))


async def fetch_weather_for_current_location(force_location: bool = False) -> dict:
    from core.location_resolver import resolve_location_async

    location = await resolve_location_async(force_refresh=force_location)
    return await fetch_weather_for_city(str(location.get("city") or ""), location)

"""Aerie · 云栖 — city resolver with IP auto-detect + manual override."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time

from core.paths import city_cache_path

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 24 * 3600
_FALLBACK_CITY = "上海"


def _read_settings_city() -> str:
    try:
        from config.persona_loader import load_settings  # type: ignore
        cfg = load_settings() or {}
        weather = cfg.get("weather") or {}
        return str(weather.get("city") or "").strip()
    except Exception as e:
        logger.debug("location_resolver: load_settings failed: %s", e)
        return ""


def _location(city: str, source: str, error: str = "") -> dict:
    city = (city or "").strip() or _FALLBACK_CITY
    return {
        "city": city,
        "source": source,
        "manual": source == "manual",
        "fallback": source == "fallback",
        "error": error,
        "cache_ttl_sec": _CACHE_TTL_SEC,
    }


def _read_cache() -> str:
    path = city_cache_path()
    try:
        if not path.exists():
            return ""
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = int(data.get("ts") or 0)
        city = str(data.get("city") or "").strip()
        if not city:
            return ""
        if (time.time() - ts) > _CACHE_TTL_SEC:
            return ""
        return city
    except Exception as e:
        logger.debug("location_resolver: cache read failed: %s", e)
        return ""


def _write_cache(city: str) -> None:
    path = city_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"city": city, "ts": int(time.time())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug("location_resolver: cache write failed: %s", e)


def clear_city_cache() -> None:
    try:
        path = city_cache_path()
        if path.exists():
            path.unlink()
    except Exception as e:
        logger.debug("location_resolver: cache clear failed: %s", e)


def _parse_ip_city(result: object) -> str:
    try:
        if isinstance(result, dict):
            content = result.get("content") or {}
            detail = content.get("address_detail") or {}
            city = str(detail.get("city") or "").strip()
            if city and city not in {"None", "null"}:
                return city
            addr = str(content.get("address") or "").strip()
            if addr and "|" in addr:
                parts = [p.strip() for p in addr.split("|")]
                if len(parts) >= 2 and parts[1] and parts[1] not in {"0", "None"}:
                    return parts[1]
            return ""
        if isinstance(result, str):
            value = result.strip()
            if not value:
                return ""
            if "|" in value:
                parts = [p.strip() for p in value.split("|")]
                if len(parts) >= 2:
                    return parts[1]
            return value
    except Exception as e:
        logger.debug("location_resolver: parse_ip_city failed: %s", e)
    return ""


def _call_map_ip_location() -> object:
    try:
        from mcp_Bai_Du_Di_Tu import map_ip_location  # type: ignore
        result = map_ip_location(ip="")
        if inspect.iscoroutine(result):
            result.close()
            return None
        return result
    except Exception as e:
        logger.debug("location_resolver: map_ip_location failed: %s", e)
        return None


async def _call_map_ip_location_async() -> object:
    try:
        from mcp_Bai_Du_Di_Tu import map_ip_location  # type: ignore
        result = map_ip_location(ip="")
        if inspect.iscoroutine(result):
            return await result
        return await asyncio.to_thread(lambda: result)
    except Exception as e:
        logger.debug("location_resolver: async map_ip_location failed: %s", e)
        return None


def resolve_location(*, force_refresh: bool = False) -> dict:
    manual = _read_settings_city()
    if manual:
        return _location(manual, "manual")
    if not force_refresh:
        cached = _read_cache()
        if cached:
            return _location(cached, "cache")
    detected = _parse_ip_city(_call_map_ip_location())
    if detected:
        _write_cache(detected)
        return _location(detected, "ip")
    return _location(_FALLBACK_CITY, "fallback", "定位失败，已使用默认城市")


async def resolve_location_async(*, force_refresh: bool = False) -> dict:
    manual = _read_settings_city()
    if manual:
        return _location(manual, "manual")
    if not force_refresh:
        cached = _read_cache()
        if cached:
            return _location(cached, "cache")
    detected = _parse_ip_city(await _call_map_ip_location_async())
    if detected:
        _write_cache(detected)
        return _location(detected, "ip")
    return _location(_FALLBACK_CITY, "fallback", "定位失败，已使用默认城市")


def resolve_city(*, force_refresh: bool = False) -> str:
    return resolve_location(force_refresh=force_refresh)["city"]


def set_manual_city(city: str) -> dict:
    from config.persona_loader import save_settings  # type: ignore

    city = (city or "").strip()
    save_settings({"weather": {"city": city}})
    clear_city_cache()
    return resolve_location(force_refresh=True)


async def get_weather_for_brief(city: str | None = None) -> dict | None:
    from core.weather_service import fetch_weather_for_city, fetch_weather_for_current_location
    if city:
        return await fetch_weather_for_city(city)
    return await fetch_weather_for_current_location()

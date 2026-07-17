"""Aerie · 云栖 — city resolver with IP auto-detect + manual override.

Priority order (highest → lowest):
  1. ``settings.yaml.weather.city``  (manual override, user-controlled)
  2. ``data/cache/city.json``        (24h IP cache, persisted)
  3. ``mcp_Bai_Du_Di_Tu.map_ip_location`` (live IP geolocation)
  4. fallback "上海"                  (only if all three above fail)

R7.1 brief-refactor: the previous brief_fetcher hardcoded
``city: str = "上海"`` which made the brief say 上海 for every user.
This module isolates the resolution so the rest of the system can call
``resolve_city()`` without caring about the source.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_FILE = Path("data/cache/city.json")
_CACHE_TTL_SEC = 24 * 3600
_FALLBACK_CITY = "上海"


def _read_settings_city() -> str:
    """Read settings.yaml.weather.city. Empty string means "no override"."""
    try:
        import yaml
        from config.persona_loader import load_settings  # type: ignore
        cfg = load_settings() or {}
        w = cfg.get("weather") or {}
        c = (w.get("city") or "").strip()
        return c
    except Exception as e:
        logger.debug("location_resolver: load_settings failed: %s", e)
        return ""


def _read_cache() -> str:
    """Return cached city if fresh (within 24h), else empty string."""
    try:
        if not _CACHE_FILE.exists():
            return ""
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ts = int(data.get("ts") or 0)
        city = (data.get("city") or "").strip()
        if not city:
            return ""
        if (time.time() - ts) > _CACHE_TTL_SEC:
            return ""
        return city
    except Exception as e:
        logger.debug("location_resolver: cache read failed: %s", e)
        return ""


def _write_cache(city: str) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({"city": city, "ts": int(time.time())},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug("location_resolver: cache write failed: %s", e)


def _parse_ip_city(result: object) -> str:
    """Best-effort parse of map_ip_location result.

    Baidu's map_ip_location typically returns:
      {
        "status": 0,
        "content": {
          "address": "CN|北京|北京|None|None|...",
          "address_detail": {"city": "北京", "province": "北京市", ...},
          "point": {"x": ..., "y": ...}
        }
      }

    Accept either dict with ``address_detail.city`` or string form
    "CN|北京|..."; in the latter case take the second pipe segment.
    """
    try:
        if isinstance(result, dict):
            content = result.get("content") or {}
            detail = content.get("address_detail") or {}
            city = (detail.get("city") or "").strip()
            if city and city not in ("None", "null", ""):
                return city
            # Fallback to address pipe string
            addr = (content.get("address") or "").strip()
            if addr and "|" in addr:
                parts = [p.strip() for p in addr.split("|")]
                # Index 1 is city in CN|Jiangsu|Nanjing|... format
                if len(parts) >= 2 and parts[1] and parts[1] not in ("0", "None"):
                    return parts[1]
            return ""
        if isinstance(result, str):
            # Plain "北京" or "CN|北京|..."
            s = result.strip()
            if not s:
                return ""
            if "|" in s:
                parts = [p.strip() for p in s.split("|")]
                if len(parts) >= 2:
                    return parts[1]
            return s
    except Exception as e:
        logger.debug("location_resolver: parse_ip_city failed: %s", e)
    return ""


def _call_map_ip_location() -> str:
    """Call the Baidu Map MCP map_ip_location. Returns city or ''.

    Empty ``ip`` argument lets Baidu use the caller's IP (which is
    exactly what we want for a desktop app that doesn't know its own
    public IP).
    """
    try:
        # Local import — MCP is only available on the dev machine.
        from mcp_Bai_Du_Di_Tu import map_ip_location  # type: ignore
        # Some MCP wrappers are sync, some are coroutines. Handle both.
        import inspect
        result = map_ip_location(ip="")
        if inspect.iscoroutine(result):
            try:
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(result) \
                    if asyncio.get_event_loop().is_running() else None
            except Exception:
                result = None
        return _parse_ip_city(result)
    except Exception as e:
        logger.debug("location_resolver: map_ip_location failed: %s", e)
        return ""


def resolve_city(*, force_refresh: bool = False) -> str:
    """Resolve the city to use for the daily brief.

    Args:
        force_refresh: bypass cache and re-call map_ip_location.

    Returns:
        City name as a string. Never empty (falls back to 上海).
    """
    # 1) manual override always wins
    manual = _read_settings_city()
    if manual:
        return manual
    # 2) cached IP result
    if not force_refresh:
        cached = _read_cache()
        if cached:
            return cached
    # 3) live IP geolocation
    detected = _call_map_ip_location()
    if detected:
        _write_cache(detected)
        return detected
    # 4) fallback
    return _FALLBACK_CITY


def get_weather_for_brief(city: str | None = None) -> dict | None:
    """Convenience wrapper: call ``brief_fetcher.fetch_weather(resolve_city())``.

    Kept in this module so callers don't need to know about
    brief_fetcher's signature.
    """
    from core.brief_fetcher import fetch_weather  # local import to avoid cycle
    return fetch_weather(city=city or resolve_city())

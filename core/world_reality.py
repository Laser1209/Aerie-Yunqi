"""World reality enrichment.

Pulls *real* facts into the world simulation so the dashboard behaves like a
real place instead of a scripted template:

- weather: real weather for the world's city (via core.weather_service)
- nearby_places: real nearby POIs (via Baidu Maps MCP, best-effort)
- city_events: real happenings (via core.brief_fetcher real news, best-effort)

Every provider is best-effort and never raises; a missing provider simply
falls back to the simulation's existing procedural defaults.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _norm_places(raw: Any, limit: int = 4) -> list[dict[str, str]]:
    """Normalize Baidu map_search_places output into a small name list.

    Accepts a list of dicts, a list of strings, or a single dict/string.
    """
    places: list[dict[str, str]] = []
    items = raw if isinstance(raw, list) else [raw]
    for it in items:
        if not it:
            continue
        if isinstance(it, dict):
            name = str(it.get("name") or it.get("title") or it.get("addr") or "").strip()
        else:
            name = str(it).strip()
        if not name:
            continue
        places.append({"name": name, "type": str((it.get("tag") or it.get("type") or "") if isinstance(it, dict) else "")})
        if len(places) >= limit:
            break
    return places


def _norm_events(items: Any, limit: int = 4) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    if not isinstance(items, list):
        return events
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        events.append(
            {
                "title": title,
                "url": str(it.get("url") or "").strip(),
                "source": str(it.get("source") or "").strip(),
            }
        )
        if len(events) >= limit:
            break
    return events


async def fetch_reality(city: str) -> dict[str, Any]:
    """Fetch real weather + nearby places + city events for ``city``.

    Returns a stable dict with the same shape whether providers succeed or not,
    so callers never have to special-case errors.
    """
    city = (city or "").strip()
    reality: dict[str, Any] = {
        "city": city,
        "weather": {},
        "nearby_places": [],
        "city_events": [],
        "error": "",
        "stub": False,
        "ts": int(time.time()),
    }

    # 1) Real weather.
    try:
        from core import weather_service

        w = await weather_service.fetch_weather_for_city(city)
        reality["weather"] = w or {}
        if isinstance(w, dict) and w.get("error"):
            reality["error"] = str(w.get("error") or "")
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("world_reality: weather failed: %s", e)
        reality["error"] = str(e)
        reality["stub"] = True

    # 2) Real nearby places (Baidu Maps MCP).
    if city:
        try:
            from mcp_Bai_Du_Di_Tu import map_search_places  # type: ignore

            raw = map_search_places(query="公园 咖啡 书店 地标", region=city)
            if raw is not None:
                reality["nearby_places"] = _norm_places(raw)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("world_reality: nearby places unavailable: %s", e)

    # 3) Real city events (real news, best-effort).
    try:
        from core import brief_fetcher

        items, _err = await brief_fetcher.fetch_cn_news(limit=4)
        reality["city_events"] = _norm_events(items)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("world_reality: city events unavailable: %s", e)

    return reality

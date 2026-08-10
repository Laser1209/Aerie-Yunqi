"""World reality enrichment.

Pulls *real* facts into the world simulation so the dashboard behaves like a
real place instead of a scripted template:

- weather: real weather for the world's city (via core.weather_service)
- nearby_places: real nearby POIs (via Baidu Maps Web Service REST, best-effort)
- city_events: real happenings (via core.brief_fetcher real news, best-effort)

Every provider is best-effort and never raises; a missing provider simply
falls back to the simulation's existing procedural defaults.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.weather_service import _http_get_json, _baidu_signed_url

logger = logging.getLogger(__name__)


def _baidu_search_places(query: str, region: str, limit: int = 10) -> list[dict[str, str]]:
    """百度地图 place/v2/search REST（替代 MCP map_search_places）。

    返回规整后的 POI dict 列表（name/addr/area/tag/type），可直接喂给
    _norm_places / _norm_local_events。无 AK / 请求失败 / 非零 status 时返回空。
    """
    if not query or not region:
        return []
    url = _baidu_signed_url(
        "/place/v2/search",
        {"query": query, "region": region, "output": "json", "page_size": int(limit)},
    )
    if not url:
        return []
    data = _http_get_json(url)
    if not data or int(data.get("status", -1)) != 0:
        return []
    results = data.get("results")
    if not isinstance(results, list):
        return []
    out: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        detail = item.get("detail_info") or {}
        out.append({
            "name": str(item.get("name") or "").strip(),
            "addr": str(item.get("address") or "").strip(),
            "area": str(item.get("area") or "").strip(),
            "tag": str(detail.get("tag") or "").strip(),
            "type": str(detail.get("navi_location_type") or "").strip(),
        })
    return out


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


def _norm_local_events(items: Any, limit: int = 4) -> list[dict[str, str]]:
    """把地图搜索结果（当地活动/场馆 POI）规整为 city_events 条目。

    与 _norm_events 相同结构（title/url/source），但接受 name/addr 的 POI 形状，
    用于把"重庆当地的展览/演出/景点"当作世界里的当地活动。
    """
    events: list[dict[str, str]] = []
    items = items if isinstance(items, list) else [items]
    for it in items:
        if not it:
            continue
        if isinstance(it, dict):
            title = str(it.get("name") or it.get("title") or it.get("addr") or "").strip()
            src = str(it.get("tag") or it.get("type") or "本地活动").strip()
        else:
            title = str(it).strip()
            src = "本地活动"
        if not title:
            continue
        events.append({"title": title, "url": "", "source": src})
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

    # 2) Real nearby places (Baidu Maps Web Service REST) → 回退内置城市数据（开箱即用）。
    if city:
        try:
            raw = _baidu_search_places("公园 咖啡 书店 地标", city)
            if raw:
                reality["nearby_places"] = _norm_places(raw)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("world_reality: nearby places unavailable: %s", e)
        if not reality.get("nearby_places"):
            from core.builtin_places import builtin_places

            reality["nearby_places"] = builtin_places(city)

    # 3) Real city events (real news, best-effort).
    try:
        from core import brief_fetcher

        items, _err = await brief_fetcher.fetch_cn_news(limit=4)
        reality["city_events"] = _norm_events(items)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("world_reality: city events unavailable: %s", e)

    # 4) 城市本地活动（角色所在城市，如重庆的展览/演出/景点；best-effort）。
    #    追加到 city_events 末尾，保持新闻优先；地图不可用时回退内置数据。
    if city:
        try:
            raw = _baidu_search_places("展览 演出 展会 活动 景点", city)
            if not raw:
                from core.builtin_places import builtin_local_events

                raw = builtin_local_events(city)
            if raw:
                existing = reality.get("city_events") or []
                local_events = _norm_local_events(raw)
                seen = {e["title"] for e in existing}
                reality["city_events"] = existing + [
                    e for e in local_events if e["title"] not in seen
                ]
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("world_reality: local events unavailable: %s", e)

    return reality

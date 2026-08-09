from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# 当百度地图 MCP 不可用时，使用 Open-Meteo 拉取真实天气（免费、无需 key）。
_OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
_HTTP_TIMEOUT_SEC = 8.0

# Open-Meteo WMO weather code → 中文天气描述
_WMO_DESC: dict[int, str] = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "毛毛雨",
    56: "冻雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷雨",
    96: "雷雨伴冰雹",
    99: "雷雨伴冰雹",
}


def _http_get_json(url: str) -> dict[str, Any] | None:
    """同步 HTTP GET 并解析 JSON；任何失败返回 None（best-effort）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aerie/1.0"})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.debug("weather_service: http get failed %s: %s", url, e)
        return None


def _open_meteo_geocode(city: str) -> tuple[float, float] | None:
    """把城市名解析为经纬度（Open-Meteo 地理编码）。"""
    q = urllib.parse.quote(city)
    data = _http_get_json(f"{_OPEN_METEO_GEOCODE}?name={q}&count=1&language=zh&format=json")
    if not data:
        return None
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    lat = first.get("latitude")
    lon = first.get("longitude")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def _open_meteo_weather(city: str) -> dict[str, Any] | None:
    """通过 Open-Meteo 拉取真实当前天气 + 未来 5 天预报，返回可直接喂给 normalize_weather 的 dict。"""
    latlon = _open_meteo_geocode(city)
    if latlon is None:
        return None
    lat, lon = latlon
    url = (
        f"{_OPEN_METEO_FORECAST}?latitude={lat}&longitude={lon}"
        "&current_weather=true"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min"
        "&forecast_days=5&timezone=Asia%2FShanghai"
    )
    data = _http_get_json(url)
    if not data:
        return None
    cur = data.get("current_weather")
    if not isinstance(cur, dict):
        return None
    # 解析未来 5 天 daily 预报
    daily = data.get("daily") or {}
    forecast: list[dict] = []
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    for i, d in enumerate(times):
        forecast.append({
            "date": str(d),
            "day": str(d),
            "weather": _WMO_DESC.get(int(codes[i]) if i < len(codes) else 0, "多云"),
            "temp_max": str(int(round(float(highs[i])))) if i < len(highs) and highs[i] is not None else "—",
            "temp_min": str(int(round(float(lows[i])))) if i < len(lows) and lows[i] is not None else "—",
        })
    code = int(cur.get("weathercode") or 0)
    desc = _WMO_DESC.get(code, "多云")
    temp = cur.get("temperature")
    wind = cur.get("windspeed")
    return {
        "temperature": str(int(round(float(temp)))) if temp is not None else "—",
        "weather": desc,
        "wind": f"{wind} km/h" if wind is not None else "",
        "forecast": forecast,
        "suggestion": "根据实时天气，记得带合适的衣物。",
    }


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
        # 百度地图 MCP 不可导入 → 退而使用 Open-Meteo 真实天气；仍失败才用 stub。
        real = await asyncio.to_thread(_open_meteo_weather, city)
        if real is not None:
            return normalize_weather(city, real, {**location, "source": "open_meteo", "manual": True})
        logger.debug("weather_service: open_meteo unavailable; using stub")
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

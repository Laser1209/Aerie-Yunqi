from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# 当百度地图不可用（无 AK / IP 白名单未放行）时，使用 Open-Meteo 拉取真实天气（免费、无需 key）。
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


def baidu_ak() -> str:
    """读取百度地图 Web 服务 AK；未配置返回空串（调用方据此回退）。"""
    return os.environ.get("BAIDU_MAP_AK", "").strip()


def baidu_sk() -> str:
    """读取百度地图 Web 服务 SK（SN 校验密钥）；未配置则退回 IP 白名单模式。"""
    return os.environ.get("BAIDU_MAP_SK", "").strip()


def _baidu_sn(params: dict[str, Any], path: str, sk: str) -> str:
    """百度 SN 签名（官方附录算法）：参数按 key 字典序拼接 → 整串 URL 编码
    （保留分隔符）→ 末尾拼接 SK → 普通 MD5 → 32 位小写 hex。

    启用 SN 校验后百度只验签、不校验来源 IP，任意用户（任意 IP）都可用同一
    AK/SK 调用，无需维护 IP 白名单。
    """
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    path_query = f"{path}?{query}"
    encoded = urllib.parse.quote(path_query, safe="/:=&?#+!$,;'@()*[]")
    return hashlib.md5((encoded + sk).encode("utf-8")).hexdigest()


def _baidu_signed_url(path: str, params: dict[str, Any]) -> str:
    """构造百度 Web 服务请求 URL。

    - 配置了 SK → SN 校验模式：参数加 timestamp，签名后附加 &sn=
    - 仅 AK → IP 白名单模式：直接带 ak（需在控制台登记本机出口 IP）
    - 无 AK → 返回空串（调用方回退）
    """
    ak = baidu_ak()
    if not ak:
        return ""
    base = f"https://api.map.baidu.com{path}"
    sk = baidu_sk()
    if sk:
        payload = {**params, "ak": ak, "timestamp": str(int(time.time()))}
        sn = _baidu_sn(payload, path, sk)
        query = "&".join(
            f"{key}={urllib.parse.quote(str(val), safe='')}"
            for key, val in sorted(payload.items())
        )
        return f"{base}?{query}&sn={sn}"
    query = urllib.parse.urlencode({**params, "ak": ak})
    return f"{base}?{query}"


def _baidu_adcode(city: str) -> str | None:
    """通过 place 检索拿城市行政区划代码（adcode），作为天气接口的 district_id。"""
    if not city:
        return None
    url = _baidu_signed_url(
        "/place/v2/search",
        {"query": city, "region": city, "output": "json", "extensions_adcode": 1, "page_size": 1},
    )
    if not url:
        return None
    data = _http_get_json(url)
    if not data or int(data.get("status", -1)) != 0:
        return None
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    adcode = str((results[0] or {}).get("adcode") or "").strip()
    return adcode or None


def _baidu_weather(city: str) -> dict[str, Any] | None:
    """通过百度天气 v1 REST 拉取实时天气 + 5 天预报，返回可直接喂给 normalize_weather 的 dict。"""
    district_id = _baidu_adcode(city)
    if not district_id:
        return None
    url = _baidu_signed_url("/weather/v1/", {"district_id": district_id, "data_type": "all"})
    if not url:
        return None
    data = _http_get_json(url)
    if not data or int(data.get("status", -1)) != 0:
        return None
    result = data.get("result") or {}
    now = result.get("now") or {}
    forecasts = result.get("forecasts") or []
    forecast: list[dict[str, str]] = []
    for item in forecasts if isinstance(forecasts, list) else []:
        if not isinstance(item, dict):
            continue
        forecast.append({
            "date": str(item.get("date") or ""),
            "day": str(item.get("date") or ""),
            "weather": str(item.get("text_day") or item.get("text_night") or ""),
            "temp_max": str(item.get("high") or "—"),
            "temp_min": str(item.get("low") or "—"),
        })
    wind_parts = [str(now.get("wind_dir") or "").strip(), str(now.get("wind_power") or "").strip()]
    return {
        "temperature": str(now.get("temp") or "—"),
        "weather": str(now.get("text") or ""),
        "humidity": str(now.get("humidity") or ""),
        "wind": " ".join(p for p in wind_parts if p),
        "forecast": forecast,
        "suggestion": str(result.get("suggestion") or "") if isinstance(result.get("suggestion"), str) else "",
    }


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
    # 百度天气 REST（需 BAIDU_MAP_AK 且 AK 的 IP 白名单放行本机）→ Open-Meteo → stub。
    if baidu_ak():
        try:
            real = await asyncio.to_thread(_baidu_weather, city)
            if real is not None:
                return normalize_weather(city, real, {**location, "source": "baidu", "manual": True})
            logger.debug("weather_service: baidu weather unavailable; falling back to open_meteo")
        except Exception as e:
            logger.warning("weather_service: baidu weather error: %s", e)
    real = await asyncio.to_thread(_open_meteo_weather, city)
    if real is not None:
        return normalize_weather(city, real, {**location, "source": "open_meteo", "manual": True})
    logger.debug("weather_service: open_meteo unavailable; using stub")
    return fallback_weather(city, location)


async def fetch_weather_for_current_location(force_location: bool = False) -> dict:
    from core.location_resolver import resolve_location_async

    location = await resolve_location_async(force_refresh=force_location)
    return await fetch_weather_for_city(str(location.get("city") or ""), location)

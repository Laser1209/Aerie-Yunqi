# -*- coding: utf-8 -*-
"""Daily astronomical ephemeris for Ita (Chongqing, 29.5630°N / 106.5516°E).

Layered data source (mature API first, local computation as 保底):

* **Sunrise / sunset** — primary: Open-Meteo `daily=sunrise,sunset`
  (free, no key, already used by weather_service); fallback: local
  `solar_time.solar_position` scan.
* **Moon phase** — local synodic-month computation (accurate to ~1 day).
* **Moonrise / moonset** — local approximation (moon drifts ~50 min/day later;
  new moon rises with the sun, full moon at ~18:00).
* **Solar terms (节气)** — computed from the sun's ecliptic longitude
  (each term = 15° of longitude; 0°=春分, 90°=夏至 …).
* **Astronomical events** — curated annual table (meteor showers etc.);
  best-effort, degrades gracefully.

Daily results are cached (in-memory, keyed by date).  This is the single
source of truth that both the daily-brief subscription item and the image
prompt time/light descriptor read from.
"""
from __future__ import annotations

import math
from datetime import datetime, date as _date, timedelta, timezone
from typing import Any

from core import solar_time

CHONGQING_LAT = solar_time.CHONGQING_LAT
CHONGQING_LON = solar_time.CHONGQING_LON
LOCAL_TZ = solar_time.LOCAL_TZ

_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"

# ── Moon phase (synodic) ──────────────────────────────────────────
_SYNODIC_MONTH = 29.53058867
_NEW_MOON_EPOCH = datetime(2000, 1, 6, 18, 14, 0, tzinfo=timezone.utc)

# ── Solar terms by ecliptic-longitude index (0°=春分) ─────────────
_SOLAR_TERMS = [
    "春分", "清明", "谷雨", "立夏", "小满", "芒种",
    "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
    "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
    "冬至", "小寒", "大寒", "立春", "雨水", "惊蛰",
]

# ── Curated annual astronomical events (best-effort, MM-DD) ───────
_ASTRO_EVENTS = [
    ("01-03", "象限仪座流星雨极大"),
    ("04-22", "天琴座流星雨极大"),
    ("05-06", "宝瓶座η流星雨极大"),
    ("08-12", "英仙座流星雨极大"),
    ("10-21", "猎户座流星雨极大"),
    ("11-17", "狮子座流星雨极大"),
    ("12-13", "双子座流星雨极大"),
    ("12-22", "小熊座流星雨极大"),
]

_cache: dict[str, dict[str, Any]] = {}


def _to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def _http_get_json(url: str) -> dict[str, Any] | None:
    try:
        import httpx
        with httpx.Client(trust_env=False, timeout=10) as c:
            r = c.get(url)
            if r.status_code == 200:
                return r.json()
    except Exception:
        return None
    return None


def _open_meteo_astro(day: _date) -> dict[str, Any] | None:
    """Fetch both sun and moon times from Open-Meteo (mature, no key).

    Primary source for sunrise/sunset AND moonrise/moonset/moon_phase.
    Returns None if the request fails or required fields are missing, so the
    caller can fall back to local computation (保底).
    """
    url = (
        f"{_OPEN_METEO_FORECAST}?latitude={CHONGQING_LAT}&longitude={CHONGQING_LON}"
        f"&daily=sunrise,sunset,moonrise,moonset,moon_phase"
        f"&timezone=Asia%2FShanghai&forecast_days=1"
    )
    data = _http_get_json(url)
    if not data or not data.get("daily"):
        return None
    daily = data["daily"]

    def _at(key: str) -> str:
        v = (daily.get(key) or [None])[0]
        return str(v)[-5:] if v else ""

    out: dict[str, Any] = {
        "sunrise": _at("sunrise"),
        "sunset": _at("sunset"),
        "moonrise": _at("moonrise"),
        "moonset": _at("moonset"),
    }
    # Sun times are the core signal; if they're missing treat the whole
    # fetch as failed so local computation kicks in.
    if not out["sunrise"] or not out["sunset"]:
        return None
    # moon_phase (Open-Meteo): fraction 0..1 (0=new, 0.25=first quarter,
    # 0.5=full, 0.75=last quarter, 1=new). Map to name/emoji + illumination.
    frac = daily.get("moon_phase") or [None]
    frac = frac[0] if frac else None
    if frac is not None and isinstance(frac, (int, float)):
        name, emoji = _moon_phase_from_fraction(float(frac))
        illum = (1.0 - math.cos(2 * math.pi * float(frac))) / 2.0
        out.update({
            "moon_phase": name,
            "moon_phase_emoji": emoji,
            "moon_phase_fraction": round(float(frac), 2),
            "moon_illumination_pct": round(illum * 100),
        })
    return out


def _moon_phase_from_fraction(fraction: float) -> tuple[str, str]:
    """Map a synodic fraction (0=new … 0.5=full … 1=new) to name + emoji."""
    if fraction < 0.03 or fraction >= 0.97:
        return "新月", "🌑"
    if fraction < 0.22:
        return "娥眉月", "🌒"
    if fraction < 0.28:
        return "上弦月", "🌓"
    if fraction < 0.47:
        return "盈凸月", "🌔"
    if fraction < 0.53:
        return "满月", "🌕"
    if fraction < 0.72:
        return "亏凸月", "🌖"
    if fraction < 0.78:
        return "下弦月", "🌗"
    return "残月", "🌘"


def _local_sun_times(day: _date) -> dict[str, str]:
    dt = datetime.combine(day, datetime.min.time(), tzinfo=LOCAL_TZ)
    sunrise, sunset = solar_time.sunrise_sunset(dt)
    return {"sunrise": sunrise or "", "sunset": sunset or ""}


def moon_phase(dt: datetime) -> dict[str, Any]:
    """Moon phase for a local datetime (accurate to ~1 day)."""
    dt = _to_local(dt)
    days = (dt - _NEW_MOON_EPOCH).total_seconds() / 86400.0
    age = days % _SYNODIC_MONTH
    fraction = age / _SYNODIC_MONTH
    illumination = (1.0 - math.cos(2 * math.pi * fraction)) / 2.0
    name, emoji = _moon_phase_from_fraction(fraction)
    return {
        "phase_name": name,
        "emoji": emoji,
        "fraction": round(fraction, 2),
        "illumination_pct": round(illumination * 100),
    }


def _moonrise_moonset(dt: datetime) -> dict[str, str]:
    """Approximate local moonrise/moonset.

    Moon rises ~50 min later each day; at new moon it rises with the sun (~06:00).
    """
    dt = _to_local(dt)
    days = (dt - _NEW_MOON_EPOCH).total_seconds() / 86400.0
    age_days = days % _SYNODIC_MONTH
    rise_min = int((6 * 60 + age_days * 50) % 1440)
    set_min = int((rise_min + 12 * 60 + 25) % 1440)

    def _fmt(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    return {"moonrise": _fmt(rise_min), "moonset": _fmt(set_min)}


def _solar_longitude(dt: datetime) -> float:
    """Approximate sun's apparent ecliptic longitude (deg) for a UTC datetime."""
    j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    n = (dt - j2000).total_seconds() / 86400.0
    L = 280.460 + 0.9856474 * n
    g = math.radians(357.528 + 0.9856003 * n)
    return (L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360.0


def solar_term(dt: datetime) -> str:
    """Current solar term (节气) in effect for the date."""
    dt = _to_local(dt)
    lon = _solar_longitude(dt)
    idx = int(lon // 15.0) % 24
    return _SOLAR_TERMS[idx]


def _astronomical_events(dt: datetime) -> list[str]:
    """Events active on/around the date (best-effort, curated)."""
    dt = _to_local(dt)
    mmdd = dt.strftime("%m-%d")
    out = []
    for mdd, name in _ASTRO_EVENTS:
        if mdd == mmdd:
            out.append(name)
    return out


def get_daily_ephemeris(day: _date | datetime | None = None) -> dict[str, Any]:
    """Daily astronomical snapshot for Chongqing (cached by date)."""
    if day is None:
        day = _to_local(datetime.now(LOCAL_TZ)).date()
    elif isinstance(day, datetime):
        day = _to_local(day).date()
    key = day.isoformat()
    if key in _cache:
        return _cache[key]

    dt = datetime.combine(day, datetime.min.time(), tzinfo=LOCAL_TZ)

    # Sun + moon: Open-Meteo primary, local computation as 保底.
    fetched = _open_meteo_astro(day)
    if fetched:
        sun_src = "open_meteo"
        moon_src = "open_meteo" if fetched.get("moon_phase") else "local"
        sun = fetched
        if moon_src == "local":
            moon = moon_phase(dt)
            sun["moon_phase"] = moon["phase_name"]
            sun["moon_phase_emoji"] = moon["emoji"]
            sun["moon_illumination_pct"] = moon["illumination_pct"]
            if not fetched.get("moonrise") or not fetched.get("moonset"):
                mr = _moonrise_moonset(dt)
                sun["moonrise"] = mr["moonrise"]
                sun["moonset"] = mr["moonset"]
    else:
        sun_src = "local"
        moon_src = "local"
        sun = _local_sun_times(day)
        moon = moon_phase(dt)
        mr = _moonrise_moonset(dt)
        sun["moon_phase"] = moon["phase_name"]
        sun["moon_phase_emoji"] = moon["emoji"]
        sun["moon_illumination_pct"] = moon["illumination_pct"]
        sun["moonrise"] = mr["moonrise"]
        sun["moonset"] = mr["moonset"]

    result = {
        "date": key,
        "sunrise": sun.get("sunrise", ""),
        "sunset": sun.get("sunset", ""),
        "moon_phase": sun.get("moon_phase", ""),
        "moon_phase_emoji": sun.get("moon_phase_emoji", ""),
        "moon_illumination_pct": sun.get("moon_illumination_pct", 0),
        "moonrise": sun.get("moonrise", ""),
        "moonset": sun.get("moonset", ""),
        "solar_term": solar_term(dt),
        "events": _astronomical_events(dt),
        "source": sun_src,
        "moon_source": moon_src,
    }
    _cache[key] = result
    return result


def format_astronomy_line(day: _date | datetime | None = None) -> str:
    """Human-readable one-liner for the daily-brief subscription item."""
    e = get_daily_ephemeris(day)
    parts = [
        f"日出 {e['sunrise']} / 日落 {e['sunset']}",
        f"月相 {e['moon_phase_emoji']}{e['moon_phase']}（亮度{e['moon_illumination_pct']}%）",
        f"月出 {e['moonrise']} / 月落 {e['moonset']}",
    ]
    if e["solar_term"]:
        parts.insert(0, f"今日节气：{e['solar_term']}")
    for ev in e["events"]:
        parts.append(f"天象：{ev}")
    return "，".join(parts)

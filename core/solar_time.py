# -*- coding: utf-8 -*-
"""Fine-grained solar time for Ita's Chongqing apartment.

Two responsibilities:

1. **Real solar position** (NOAA-style) for a fixed Chongqing location,
   computing sun elevation/azimuth for the exact local date+time. Used to
   produce day-specific, fine-grained Chinese period + light descriptions
   (太阳未出/刚出/已出/太阳高度约X度、鱼肚白、日落、深夜、凌晨、清晨…).

2. **Fixed apartment spatial model** (定死，不再改): the duplex's room
   orientation, what is outside each window, and the 3D layout. Because the
   prompt's light/outside-view must stay consistent with the sun data, this
   module is the single source of truth for "她家到底朝哪、窗外是什么、
   空间怎么摆" so every generated image agrees.

Location: Chongqing (长江/嘉陵江交汇段, 临江高层).  Main living room window
faces 西南(SW) — morning sun is oblique/indirect there, afternoon→evening the
sun streams straight in and you watch the river sunset.  Master bedroom faces
南偏东(SE) (first morning sun); studio faces 北(N) (stable indirect light,
city-night view).  This orientation makes the solar data self-consistent.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

# ── Fixed location: Chongqing ────────────────────────────────────
CHONGQING_LAT = 29.5630   # °N
CHONGQING_LON = 106.5516  # °E
LOCAL_TZ: timezone = timezone(timedelta(hours=8))

_DEG = math.pi / 180.0


# ── Fixed apartment spatial model (定死，不再改) ───────────────────
APARTMENT_LAYOUT: dict[str, Any] = {
    "name": "伊塔的复式公寓（重庆·临江高层）",
    "level": "高层，视野开阔",
    "river": "长江/嘉陵江交汇段",
    "floors": {
        1: ["入户玄关", "客厅", "开放式厨房", "餐厅", "公用卫生间", "通往二楼的楼梯"],
        2: ["主卧套房", "工作室", "带玻璃栏杆的走廊"],
    },
    "living_room": {
        "window": "西南(SW)",
        "window_view": "窗外正对长江江面，对岸是重庆城市天际线，江上有跨江大桥，远处黛色山影",
        "sun": "上午阳光只斜斜、间接地照进来；午后到傍晚，阳光直直洒进西南落地窗，正好看江上日落",
        "layout": "落地窗在西南墙；灰色沙发靠着窗边；书架与挂画在客厅；暖色地灯在沙发旁",
    },
    "master_bedroom": {
        "window": "南偏东(SE)",
        "window_view": "窗下是小区绿植与远处江面",
        "sun": "清晨第一缕阳光照进主卧",
        "layout": "床靠着南窗，衣柜在床侧，主卫在房间一角",
    },
    "studio": {
        "window": "北(N)",
        "window_view": "窗外是城市楼宇与夜景霓虹，无直射阳光",
        "sun": "全天稳定漫射光，适合设计工作；夜里看城市霓虹",
        "layout": "设计台靠北窗，iMac 与数位屏在工作台上，软木板墙贴着灵感便签",
    },
}

_ROOM_KEY = {
    "environment_object": "living_room",
    "role_in_scene": "living_room",
    "role_selfie": "master_bedroom",
    "couple_photo": "living_room",
}


# ── NOAA-style solar position ────────────────────────────────────
def solar_position(dt: datetime, lat: float = CHONGQING_LAT, lon: float = CHONGQING_LON) -> dict[str, float]:
    """Sun elevation/azimuth (deg) for a timezone-aware local datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    utc = dt.astimezone(timezone.utc)
    day = utc.timetuple().tm_yday
    frac_day = day + (utc.hour + utc.minute / 60.0 + utc.second / 3600.0) / 24.0
    gamma = (2.0 * math.pi / 365.0) * (frac_day - 1.0)

    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    tz_offset_h = dt.utcoffset().total_seconds() / 3600.0
    time_offset = eqtime + 4.0 * lon - 60.0 * tz_offset_h  # minutes
    tst = dt.hour * 60.0 + dt.minute + dt.second / 60.0 + time_offset
    ha_deg = (tst / 4.0) - 180.0

    lat_rad = lat * _DEG
    cos_zenith = (
        math.sin(lat_rad) * math.sin(decl)
        + math.cos(lat_rad) * math.cos(decl) * math.cos(ha_deg * _DEG)
    )
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.acos(cos_zenith)
    altitude = 90.0 - zenith / _DEG

    denom = math.cos(zenith) * math.cos(lat_rad)
    alt_rad = (90.0 - zenith / _DEG) * _DEG
    if abs(denom) < 1e-9:
        azimuth = 0.0 if ha_deg <= 0 else 180.0
    else:
        cos_az = (math.sin(decl) - math.sin(alt_rad) * math.sin(lat_rad)) / (
            math.cos(alt_rad) * math.cos(lat_rad)
        )
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth = math.acos(cos_az) / _DEG
        if ha_deg > 0:
            azimuth = 360.0 - azimuth
    return {"altitude_deg": altitude, "azimuth_deg": azimuth}


def _scan_day(dt: datetime) -> tuple[datetime | None, datetime | None]:
    """Find local sunrise/sunset by scanning the day's minutes (robust)."""
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    prev = solar_position(start)["altitude_deg"]
    rises: list[datetime] = []
    sets: list[datetime] = []
    for m in range(1, 1440):
        t = start + timedelta(minutes=m)
        alt = solar_position(t)["altitude_deg"]
        if prev < 0.0 <= alt:
            rises.append(t)
        if prev >= 0.0 > alt:
            sets.append(t)
        prev = alt
    return (rises[0] if rises else None), (sets[-1] if sets else None)


def sunrise_sunset(dt: datetime) -> tuple[str | None, str | None]:
    """Local sunrise/sunset as 'HH:MM' strings for the date of ``dt``."""
    sunrise, sunset = _scan_day(dt)
    return (
        sunrise.strftime("%H:%M") if sunrise else None,
        sunset.strftime("%H:%M") if sunset else None,
    )


# ── Fine Chinese period + light descriptor ───────────────────────
def _to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def fine_time_descriptor(
    dt: datetime,
    prompt_key: str = "environment_object",
) -> dict[str, str]:
    """Day-specific fine time + light description for the fixed apartment.

    Returns ``time_cn`` (精细时段 + 太阳高度) and ``light_cn`` (房间光线与窗外，
    结合公寓固定朝向).  Chosen so the light relay / deterministic fallback can
    drop either directly into an image prompt.
    """
    dt = _to_local(dt)
    pos = solar_position(dt)
    alt = pos["altitude_deg"]
    az = pos["azimuth_deg"]
    sunrise, sunset = sunrise_sunset(dt)
    hhmm = dt.strftime("%H:%M")

    # Solar noon estimate = midpoint of sunrise/sunset.
    solar_noon_min = None
    if sunrise and sunset:
        def _to_min(s: str) -> int:
            h, m = s.split(":")
            return int(h) * 60 + int(m)
        solar_noon_min = (_to_min(sunrise) + _to_min(sunset)) // 2
    now_min = dt.hour * 60 + dt.minute
    rising = solar_noon_min is None or now_min < solar_noon_min

    # ── 精细时段（含太阳高度）──
    if alt < -18.0:
        time_cn = f"{hhmm}，深夜，天完全黑着"
    elif alt < -12.0:
        time_cn = f"{hhmm}，夜色正浓，天边还没有任何亮光"
    elif alt < -6.0:
        time_cn = f"{hhmm}，天色将明，天边刚泛起一点微光（太阳高度约{round(alt)}°）"
    elif alt < 0.0:
        # civil twilight
        if rising:
            time_cn = f"{hhmm}，黎明，天边泛起鱼肚白，太阳还没出来（高度约{round(alt)}°）"
        else:
            time_cn = f"{hhmm}，太阳刚落下山，天边还留着橘红的余晖（高度约{round(alt)}°）"
    elif alt < 5.0:
        if rising:
            time_cn = f"{hhmm}，太阳刚升起，柔和的晨光（太阳高度约{round(alt)}°）"
        else:
            time_cn = f"{hhmm}，太阳刚落下，天边还有最后一抹光（太阳高度约{round(alt)}°）"
    elif alt < 20.0:
        if rising:
            time_cn = f"{hhmm}，太阳已升起，低角度柔和的晨光（太阳高度约{round(alt)}°）"
        else:
            time_cn = f"{hhmm}，太阳西斜，快落山了（太阳高度约{round(alt)}°）"
    elif solar_noon_min is not None and abs(now_min - solar_noon_min) <= 45:
        time_cn = f"{hhmm}，正午，太阳几乎在头顶（太阳高度约{round(alt)}°）"
    else:
        time_cn = f"{hhmm}，太阳已升起，光线明亮（太阳高度约{round(alt)}°）"

    # ── 房间光线与窗外（结合固定朝向）──
    room = _ROOM_KEY.get(prompt_key, "living_room")
    room_cfg = APARTMENT_LAYOUT.get(room, APARTMENT_LAYOUT["living_room"])
    outside = str(room_cfg.get("window_view") or "")
    if alt < 0.0:
        light_cn = f"屋内暖灯亮着，窗外是{outside}的夜色"
    elif alt < 20.0 and not rising:
        light_cn = f"暖橘色的夕阳余晖洒进{room_cfg['window']}的落地窗，窗外是{outside}的江上日落"
    elif 150.0 <= az <= 290.0 and alt >= 20.0:
        light_cn = f"午后的阳光直直洒进{room_cfg['window']}的落地窗，窗外是{outside}"
    elif 60.0 <= az < 150.0 and alt >= 5.0:
        light_cn = f"柔和的晨光斜斜照进{room_cfg['window']}的窗外，窗外是{outside}"
    else:
        light_cn = f"明亮的自然光从{room_cfg['window']}的窗外照进来，窗外是{outside}"

    return {
        "time_cn": time_cn,
        "light_cn": light_cn,
        "sunrise": sunrise or "",
        "sunset": sunset or "",
        "sun_altitude_deg": str(round(alt)),
    }

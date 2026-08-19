"""内置公历节假日判定（零依赖、离线、确定性）。

供"人设驱动出门"的事件加权使用：法定/传统节日 + 周末影响角色的
出门概率与外出场景偏好。

设计边界：
- 只内置公历日期（元旦/劳动节/国庆/中秋窗/端午窗等公历锚点），
  农历节日取公历近似区间；不引入任何第三方日历依赖。
- 纯函数、无 IO、无随机：同一 (date) 永远返回相同结果，保证世界
  模拟的 tick 幂等确定性。
"""

from __future__ import annotations

from datetime import date, timedelta

# ── 公历节假日区间（月, 日）→ 名称 ──────────────────────────
# 春节/中秋/端午等农历节日无法用公历精确表达，这里给出所在年份的
# 公历近似窗口（中国大陆通常放假 1-7 天），后续如需要精确农历可替换。
_MONTH_DAY = tuple[int, int]
_HOLIDAY_RANGES: dict[str, tuple[_MONTH_DAY, _MONTH_DAY]] = {
    "元旦": ((1, 1), (1, 3)),
    "春节": ((2, 8), (2, 18)),        # 农历初一公历近似区间
    "清明": ((4, 3), (4, 5)),         # 公历 4/4-4/6 附近
    "劳动节": ((5, 1), (5, 5)),
    "端午": ((5, 28), (6, 5)),        # 农历五月初五公历近似区间
    "中秋": ((9, 13), (9, 17)),       # 农历八月十五公历近似区间
    "国庆": ((10, 1), (10, 7)),
    "元旦新年": ((12, 30), (12, 31)),
}

# ── 情人节/七夕等"约会型"节日（恋人场景加权更高）────────────
_ROMANCE_RANGES: list[tuple[str, _MONTH_DAY, _MONTH_DAY]] = [
    ("情人节", (2, 14), (2, 14)),
    ("520", (5, 20), (5, 20)),
    ("七夕", (8, 20), (8, 24)),       # 农历七夕近似公历区间
]

_ROMANCE_KEYS = {name for name, _, _ in _ROMANCE_RANGES}


def _in_range(day: tuple[int, int], start: _MONTH_DAY, end: _MONTH_DAY) -> bool:
    """判断 (月,日) 是否落在 [start, end] 区间（跨月不处理）。"""
    return start <= day <= end  # 元组逐位比较：先月后日


def holiday_name(d: date) -> str:
    """返回日期命中的节日名；无则空串。"""
    md = (d.month, d.day)
    for name, (start, end) in _HOLIDAY_RANGES.items():
        if _in_range(md, start, end):
            return name
    for name, start, end in _ROMANCE_RANGES:
        if _in_range(md, start, end):
            return name
    return ""


def is_holiday(d: date) -> bool:
    return bool(holiday_name(d))


def is_romance_holiday(d: date) -> bool:
    md = (d.month, d.day)
    for name, start, end in _ROMANCE_RANGES:
        if _in_range(md, start, end):
            return True
    return False


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def event_factor(d: date) -> float:
    """事件加权系数：节假日 1.6，周末 1.2，平日 1.0。"""
    if holiday_name(d):
        return 1.6
    if is_weekend(d):
        return 1.2
    return 1.0


def event_preference(d: date) -> str:
    """按日头给出外出偏好场景关键词（节假日/浪漫日），供地点池择优。"""
    name = holiday_name(d)
    if not name:
        return "weekend_stroll" if is_weekend(d) else ""
    if name in _ROMANCE_KEYS:
        return "romance"
    return "festival"
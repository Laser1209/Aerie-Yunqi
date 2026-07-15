"""Aerie · 云栖 v9.0 — 9 proactive scene definitions.

Each scene provides a build_payload function that returns
(template, kwargs) for the messenger. Event-driven scenes have
no cron expression and are triggered by emotion/cumulative events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from config.persona_loader import load_proactive


def _now_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# Cron-driven scenes
def morning_brief(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("morning_brief", {})
    template = cfg.get("template", "早安。{weather}今天{date}。")
    return template, {
        "weather": kwargs.get("weather", "晴。"),
        "date": _now_date_str(),
    }


def weather_push(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("weather_push", {})
    template = cfg.get("template", "{city}今天{weather}，{temp}度。{suggestion}。")
    return template, {
        "city": kwargs.get("city", "北京"),
        "weather": kwargs.get("weather", "晴"),
        "temp": kwargs.get("temp", "20"),
        "suggestion": kwargs.get("suggestion", "出门记得带外套"),
    }


def lunch_remind(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("lunch_remind", {})
    return cfg.get("template", "吃饭。"), {}


def evening_check(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("evening_check", {})
    return cfg.get("template", "今天怎么样。"), {}


def goodnight(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("goodnight", {})
    return cfg.get("template", "睡吧。"), {}


def todo_remind(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("todo_remind", {})
    template = cfg.get("template", "{todo_count}件事没做。")
    todo_count = int(kwargs.get("todo_count", 0))
    return template, {"todo_count": todo_count}


def anniversary(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("anniversary", {})
    template = cfg.get("template", "今天{anniversary_name}。{days}天了。")
    return template, {
        "anniversary_name": kwargs.get("anniversary_name", "纪念日"),
        "days": int(kwargs.get("days", 0)),
    }


# Event-driven scenes (no cron)
def idle_care(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("idle_care", {})
    return cfg.get("template", "在干嘛。"), {}


def emotion_comfort(user_id: int, **kwargs: Any) -> tuple[str, dict]:
    cfg = load_proactive().get("scenes", {}).get("emotion_comfort", {})
    template = cfg.get("template", "……{comfort_word}。")
    comfort_word = kwargs.get("comfort_word", "我在")
    return template, {"comfort_word": comfort_word}


# Scene registry: name → (handler)
SCENES = {
    "morning_brief": morning_brief,
    "weather_push": weather_push,
    "lunch_remind": lunch_remind,
    "evening_check": evening_check,
    "goodnight": goodnight,
    "todo_remind": todo_remind,
    "anniversary": anniversary,
    "idle_care": idle_care,
    "emotion_comfort": emotion_comfort,
}

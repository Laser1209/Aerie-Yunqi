"""Morning brief scene — sends a morning greeting to the user."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render morning_brief template with date/weather context."""
    template = scene_cfg.get("template", "早安。{weather}今天{date}。")
    weather = kwargs.get("weather", "天气不错")
    date_str = kwargs.get("date", "")
    return template.format(weather=weather, date=date_str)

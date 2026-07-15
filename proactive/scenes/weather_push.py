"""Weather push scene — sends weather information to the user."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render weather_push template with city/weather/temp context."""
    template = scene_cfg.get("template", "{city}今天{weather}，{temp}度。{suggestion}。")
    city = kwargs.get("city", "你那儿")
    weather = kwargs.get("weather", "天气还行")
    temp = kwargs.get("temp", "??")
    suggestion = kwargs.get("suggestion", "")
    return template.format(city=city, weather=weather, temp=temp, suggestion=suggestion)

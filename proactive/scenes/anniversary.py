"""Anniversary scene — celebrates special dates and milestones."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render anniversary template with name and days count."""
    template = scene_cfg.get("template", "今天{anniversary_name}。{days}天了。")
    anniversary_name = kwargs.get("anniversary_name", "我们的纪念日")
    days = kwargs.get("days", 0)
    return template.format(anniversary_name=anniversary_name, days=days)

"""Lunch remind scene — reminds the user to eat lunch."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render lunch_remind template."""
    return scene_cfg.get("template", "吃饭。")

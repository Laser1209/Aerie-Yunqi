"""Idle care scene — checks in when the user has been inactive."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render idle_care template."""
    return scene_cfg.get("template", "在干嘛。")

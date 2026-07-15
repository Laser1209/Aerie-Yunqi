"""Goodnight scene — sends a goodnight message."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render goodnight template."""
    return scene_cfg.get("template", "睡吧。")

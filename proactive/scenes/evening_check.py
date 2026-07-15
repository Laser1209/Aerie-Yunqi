"""Evening check scene — checks in with the user in the evening."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render evening_check template."""
    return scene_cfg.get("template", "今天怎么样。")

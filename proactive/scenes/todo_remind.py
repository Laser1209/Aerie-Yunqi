"""Todo remind scene — reminds the user of pending todos."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render todo_remind template with pending count."""
    template = scene_cfg.get("template", "{todo_count}件事没做。")
    todo_count = kwargs.get("todo_count", 0)
    return template.format(todo_count=todo_count)

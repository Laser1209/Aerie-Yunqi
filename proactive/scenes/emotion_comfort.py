"""Emotion comfort scene — triggered when cumulative threshold breaks."""

from __future__ import annotations


def build(scene_cfg: dict, mood: str, **kwargs) -> str:
    """Render emotion_comfort template with comfort word based on mood."""
    template = scene_cfg.get("template", "……{comfort_word}。")
    slot = kwargs.get("slot", "")
    comfort_words = {
        "patience": "我一直都在",
        "anxiety": "别担心",
        "desire": "想你了",
        "tenderness": "过来",
    }
    comfort_word = kwargs.get("comfort_word") or comfort_words.get(slot, "……")
    return template.format(comfort_word=comfort_word)

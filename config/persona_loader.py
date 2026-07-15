"""Aerie · 云栖 v9.0 — Persona configuration loader."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_CACHE: dict[str, Any] = {}


def load_persona(path: str | Path = "config/persona.yaml") -> dict[str, Any]:
    """Load persona YAML with in-process caching."""
    key = str(Path(path).resolve())
    if key in _CACHE:
        return _CACHE[key]
    if not Path(path).exists():
        # Return minimal default
        return {
            "persona": {"name": "伊塔", "english_name": "Yita"},
            "speech": {"max_chars": 15, "emoji_frequency": 0.05, "taboo_phrases": ["主人"]},
            "system_prompt": "你是伊塔。",
        }
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _CACHE[key] = data
    return data


def load_settings(path: str | Path = "config/settings.yaml") -> dict[str, Any]:
    """Load settings YAML with caching."""
    key = str(Path(path).resolve())
    if key in _CACHE:
        return _CACHE[key]
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _CACHE[key] = data
    return data


def load_proactive(path: str | Path = "config/proactive.yaml") -> dict[str, Any]:
    """Load proactive YAML with caching."""
    key = str(Path(path).resolve())
    if key in _CACHE:
        return _CACHE[key]
    if not Path(path).exists():
        return {"proactive": {"enabled": False}, "scenes": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _CACHE[key] = data
    return data


def clear_cache() -> None:
    _CACHE.clear()

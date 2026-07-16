"""Aerie · 云栖 v9.0 — YAML config loader."""

from __future__ import annotations
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"


def _load_yaml(filename: str) -> dict[str, Any]:
    path = _CONFIG_DIR / filename
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings() -> dict[str, Any]:
    """Load main settings from config/settings.yaml."""
    return _load_yaml("settings.yaml")


def load_persona() -> dict[str, Any]:
    """Load persona from config/persona.yaml."""
    return _load_yaml("persona.yaml")


def load_proactive_config() -> dict[str, Any]:
    """Load proactive messaging config from config/proactive.yaml."""
    return _load_yaml("proactive.yaml")


def get_master_qq() -> int:
    settings = load_settings()
    qq_cfg = settings.get("qq", {})
    return int(qq_cfg.get("self_qq", 0))


def get_friends_qq() -> list[int]:
    settings = load_settings()
    qq_cfg = settings.get("qq", {})
    return list(qq_cfg.get("friends_qq", []))


def get_napcat_config() -> dict[str, Any]:
    settings = load_settings()
    return dict(settings.get("napcat", {}))


def get_http_config() -> dict[str, Any]:
    settings = load_settings()
    return dict(settings.get("http_api", {}))

"""Aerie · 云栖 v9.0 — YAML config loader."""

from __future__ import annotations
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"

_DEFAULTS = {
    "theme": {"current": "yita-pink", "available": ["yita-pink", "midnight-purple", "sakura-white", "ocean-blue", "forest-green"]},
    "startup": {"auto_start": False, "start_minimized": False},
    "proactive": {"enabled": True},
}

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


def save_settings(data: dict[str, Any]) -> bool:
    """Atomically save partial settings to config/settings.yaml.
    
    Merges with existing settings rather than overwriting.
    """
    current = load_settings()
    merged = _deep_merge(current, data)
    path = _CONFIG_DIR / "settings.yaml"
    
    content = yaml.dump(merged, default_flow_style=False, allow_unicode=True)
    
    # Atomic write: write to temp file, then rename
    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", dir=str(_CONFIG_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(path))
        return True
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def reset_settings() -> dict[str, Any]:
    """Reset settings to defaults."""
    save_settings(_DEFAULTS)
    return _DEFAULTS


def _deep_merge(base: dict, update: dict) -> dict:
    """Recursively merge update into base."""
    result = dict(base)
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


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

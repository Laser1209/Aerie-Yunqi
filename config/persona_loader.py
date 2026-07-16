"""Aerie · 云栖 v9.0 — YAML config loader."""

from __future__ import annotations
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"
_DATA_DIR = _PROJECT_ROOT / "data"
_PERSONA_AVATAR_DIR = _DATA_DIR / "persona"
_PERSONA_AVATAR_PATH = _PERSONA_AVATAR_DIR / "avatar.png"
_AVATAR_BACKUP_RETENTION_DAYS = 28

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


def save_persona(patch: dict[str, Any]) -> dict[str, Any]:
    """Block-2 A2: deep-merge patch into persona.yaml, atomic write.

    Only top-level fields under ``persona.*`` are accepted for safety
    (name, english_name). The schema is validated by attempting a
    re-parse after write; on failure the previous file is restored.
    """
    if not isinstance(patch, dict):
        raise ValueError("persona patch must be a dict")
    allowed_top = {"name", "english_name"}
    safe_patch = {k: v for k, v in patch.items() if k in allowed_top}
    path = _CONFIG_DIR / "persona.yaml"
    current = load_persona() or {}
    persona = dict(current.get("persona") or {})
    persona.update(safe_patch)
    merged = dict(current)
    merged["persona"] = persona

    # Backup before write
    backup_dir = _DATA_DIR / "backups" / "config"
    backup_dir.mkdir(parents=True, exist_ok=True)
    if path.exists():
        ts = int(time.time() * 1000)
        backup_path = backup_dir / f"persona.yaml.{ts}.yaml"
        try:
            shutil.copy2(path, backup_path)
        except OSError:
            pass

    content = yaml.dump(merged, default_flow_style=False, allow_unicode=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", dir=str(_CONFIG_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # Validate by re-parse
        with open(tmp_path, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
        os.replace(tmp_path, str(path))
        return persona
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_persona_summary() -> dict[str, Any]:
    """Block-2 A2: return name/english_name + avatar_url for the renderer."""
    p = load_persona() or {}
    persona = p.get("persona") or {}
    return {
        "name": persona.get("name") or "伊塔",
        "english_name": persona.get("english_name") or "Ita",
        "avatar_url": "/api/persona/avatar?v=" + str(int(time.time())) if _PERSONA_AVATAR_PATH.exists() else "",
    }


def save_avatar_bytes(data: bytes, ext: str = "png") -> str:
    """Block-2 A2: write avatar bytes to data/persona/avatar.<ext>.

    Backs up the previous avatar (if any) and enforces a 28-day retention
    on the backup folder. Returns the public URL suffix.
    """
    ext = (ext or "png").lower().lstrip(".")
    if ext not in {"png", "jpg", "jpeg"}:
        raise ValueError("unsupported avatar format")
    _PERSONA_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    # Backup previous
    if _PERSONA_AVATAR_PATH.exists():
        backup_dir = _DATA_DIR / "backups" / "persona_avatar"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        try:
            shutil.copy2(_PERSONA_AVATAR_PATH, backup_dir / f"avatar.{ts}.{ext}")
        except OSError:
            pass
    # Cleanup old backups
    backup_dir = _DATA_DIR / "backups" / "persona_avatar"
    if backup_dir.exists():
        cutoff = time.time() - _AVATAR_BACKUP_RETENTION_DAYS * 86400
        for p in backup_dir.iterdir():
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                continue
    dest = _PERSONA_AVATAR_DIR / f"avatar.{ext}"
    # Normalize to .png as the canonical filename (we keep ext tag)
    fd, tmp_path = tempfile.mkstemp(suffix=f".{ext}", dir=str(_PERSONA_AVATAR_DIR))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, str(dest))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return f"/api/persona/avatar?v={int(time.time())}"


def load_avatar_bytes() -> tuple[bytes, str] | None:
    """Block-2 A2: load avatar bytes; return (bytes, content_type) or None."""
    for ext in ("png", "jpg", "jpeg"):
        p = _PERSONA_AVATAR_DIR / f"avatar.{ext}"
        if p.exists() and p.is_file():
            try:
                data = p.read_bytes()
                ct = "image/png" if ext == "png" else "image/jpeg"
                return data, ct
            except OSError:
                continue
    return None


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

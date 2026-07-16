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


# R0.3.2: centralized behavior config (emotion / desire / decision / cognition)
def load_behavior_config() -> dict[str, Any]:
    """Load persona behavior config from config/persona_behavior.yaml.

    Single source of truth for emotion thresholds, desire variables,
    decision weights, cognition visibility, and AI provider options.
    All modules MUST read from here; no hardcoded constants.

    Returns deep-merged dict (file overrides defaults).
    """
    file_cfg = _load_yaml("persona_behavior.yaml")
    merged = _deep_merge(_DEFAULT_BEHAVIOR_CONFIG, file_cfg)
    return merged


_DEFAULT_BEHAVIOR_CONFIG: dict[str, Any] = {
    "version": "1.0",
    "emotion": {
        "baseline": {"pleasure": 0.10, "arousal": 0.20, "dominance": 0.80, "label": "neutral"},
        "tree": {
            "default": "Neutral",
            "stackable": True,
            "states": {
                "joy":     {"P": 0.6,  "A": 0.5,  "D": 0.3},
                "anger":   {"P": -0.5, "A": 0.7,  "D": 0.6},
                "sad":     {"P": -0.6, "A": -0.3, "D": -0.4},
                "fear":    {"P": -0.7, "A": 0.6,  "D": -0.5},
                "neutral": {"P": 0.0,  "A": 0.0,  "D": 0.0},
            },
        },
        "thresholds": {
            "patience":   {"label": "忍耐值",       "threshold": 100, "decay_per_day": 5,  "eruption_label": "冷暴模式", "post_decay": -15, "description": ""},
            "anxiety":    {"label": "不安值",       "threshold": 100, "decay_per_day": 3,  "eruption_label": "坍塌模式", "post_decay": 20,  "description": ""},
            "desire":     {"label": "渴望值",       "threshold": 80,  "decay_per_day": 8,  "eruption_label": "索求模式", "post_decay": 0,   "description": ""},
            "tenderness": {"label": "温柔透支值",   "threshold": 60,  "decay_per_day": 10, "eruption_label": "反扑模式", "post_decay": 0,   "description": ""},
        },
    },
    "desire": {
        "tick_seconds": 300,
        "variables": {
            "user_absence_hours": {"max": 12,  "weight": 1.0, "label": "用户缺位小时"},
            "emotion_overdraft":  {"max": 60,  "weight": 0.8, "label": "温柔透支"},
            "patience_loss":      {"max": 100, "weight": 1.0, "label": "累积忍耐消耗"},
            "weather_impact":     {"max": 10,  "weight": 0.5, "label": "天气影响"},
            "time_of_day_boost":  {"max": 15,  "weight": 0.7, "label": "时段加成"},
            "anniversary_boost":  {"max": 30,  "weight": 1.5, "label": "纪念日加成"},
        },
        "triggers": {"care": 50, "voice": 80, "cooldown_hours": 12},
        "persistence": "data/desire_state.json",
    },
    "decision": {
        "weights": {"emotion": 0.35, "context": 0.30, "persona": 0.20, "user_history": 0.15},
    },
    "cognition": {
        "trace_visibility": {
            "route": True, "emotion": True, "threshold": True, "context": False,
            "brain": True, "tools": True, "split": False, "postprocess": True, "output": True,
        },
        "decision_visibility": True,
        "react_visibility": True,
        "max_recent_in_panel": 20,
    },
    "ai_options": [
        {"id": "main_llm",     "label": "主对话 / Main Chat",     "model": "deepseek-chat"},
        {"id": "image_sdxl",   "label": "图像生成 / Image Gen",   "model": "sdxl"},
        {"id": "voice_tts",    "label": "语音合成 / TTS",         "model": "qwen3-tts"},
        {"id": "vision_llava", "label": "视觉理解 / Vision QA",   "model": "llava"},
        {"id": "shell_safe",   "label": "受限 shell / Safe",      "model": "internal"},
    ],
    "default": "main_llm",
}


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

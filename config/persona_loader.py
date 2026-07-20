"""Aerie · 云栖 v0.1.0-beta.1 — YAML config loader."""

from __future__ import annotations
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from core.feature_flags import FeatureFlags
from core.persona_hub.legacy_projector import project_persona_to_legacy
from core.persona_hub.persona_manager import get_persona_manager

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
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError:
        import logging
        logging.getLogger(__name__).exception(
            "YAML parse error in %s; returning empty config", filename
        )
        return {}


def load_settings() -> dict[str, Any]:
    """Load main settings from config/settings.yaml."""
    try:
        return _load_yaml("settings.yaml")
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Unexpected error loading settings.yaml; returning empty dict"
        )
        return {}


def load_persona() -> dict[str, Any]:
    """Load the active persona through the configured compatibility source."""
    try:
        if FeatureFlags().is_enabled("persona_hub_source_v1"):
            return project_persona_to_legacy(get_persona_manager().get_active())
        return _load_yaml("persona.yaml") or {}
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Unexpected error loading persona; returning empty dict"
        )
        return {}


def load_proactive_config() -> dict[str, Any]:
    """Load proactive messaging config from config/proactive.yaml."""
    try:
        return _load_yaml("proactive.yaml") or {}
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Unexpected error loading proactive.yaml; returning empty dict"
        )
        return {}


# R0.3.2: centralized behavior config (emotion / desire / decision / cognition)
def load_behavior_config() -> dict[str, Any]:
    """Load persona behavior config from config/persona_behavior.yaml.

    Single source of truth for emotion thresholds, desire variables,
    decision weights, cognition visibility, and AI provider options.
    All modules MUST read from here; no hardcoded constants.

    Returns deep-merged dict (file overrides defaults).
    """
    try:
        file_cfg = _load_yaml("persona_behavior.yaml") or {}
        merged = _deep_merge(_DEFAULT_BEHAVIOR_CONFIG, file_cfg)
        return merged
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Unexpected error loading persona_behavior.yaml; returning defaults"
        )
        return dict(_DEFAULT_BEHAVIOR_CONFIG)


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
        # R8.1 (Persona 9/10): initial_value 跟 config/persona_behavior.yaml
        # 同步 9/10 基线：patience 60→45（更易冷暴）、anxiety 15→25（更
        # 易坍塌）、desire 35→55（更易索求）、tenderness 25→15（更易
        # 反扑）。本默认值仅在 config/persona_behavior.yaml 缺失时被用——
        # 跟最新基线一致避免 fallback 走 7/10 老值。
        "thresholds": {
            "patience":   {"label": "忍耐值",       "threshold": 100, "decay_per_day": 5,  "initial_value": 45, "eruption_label": "冷暴模式", "post_decay": -15, "description": ""},  # R8.1: 60→45
            "anxiety":    {"label": "不安值",       "threshold": 100, "decay_per_day": 3,  "initial_value": 25, "eruption_label": "坍塌模式", "post_decay": 20,  "description": ""},  # R8.1: 15→25
            "desire":     {"label": "渴望值",       "threshold": 80,  "decay_per_day": 8,  "initial_value": 55, "eruption_label": "索求模式", "post_decay": 0,   "description": ""},  # R8.1: 35→55
            "tenderness": {"label": "温柔透支值",   "threshold": 60,  "decay_per_day": 10, "initial_value": 15, "eruption_label": "反扑模式", "post_decay": 0,   "description": ""},  # R8.1: 25→15
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
    if FeatureFlags().is_enabled("persona_hub_source_v1"):
        manager = get_persona_manager()
        ok, result = manager.update_persona(
            manager.get_active_id(),
            {"basic": safe_patch},
        )
        if not ok:
            raise ValueError(result)
        return {
            key: manager.get_active().get("basic", {}).get(key)
            for key in allowed_top
        }

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
    """Block-2 A2: return name/english_name + avatar URL for the renderer.

    R7.5: prefer ``avatar_dataurl`` (base64 inline) so the Electron
    renderer can drop the image straight into an ``<img src>`` without
    going through a loopback HTTP fetch. The relative-path version is
    still returned for backwards-compat (non-Electron clients).

    R6.6: check ALL supported extensions (PNG/JPG/JPEG), not just the
    hardcoded .png path. The previous check missed JPG uploads and
    reported an empty avatar_url even when the file existed on disk.
    """
    p = load_persona() or {}
    persona = p.get("persona") or {}
    pair = load_avatar_bytes()
    if pair:
        data, _ct = pair
        import base64 as _b64
        dataurl = "data:image/" + ("jpeg" if pair[1] == "image/jpeg" else "png") + ";base64," + _b64.b64encode(data).decode("ascii")
    else:
        dataurl = ""
    return {
        "name": persona.get("name") or "伊塔",
        "english_name": persona.get("english_name") or "Ita",
        # Inline dataURL is the primary form. Renderer must prefer this
        # over the http URL (file:// in Electron can't load relative
        # HTTP paths so /api/... would 404 into a broken-image icon).
        "avatar_dataurl": dataurl,
        # HTTP path retained for external / non-Electron clients.
        "avatar_url": ("/api/persona/avatar?v=" + str(int(time.time()))) if pair else "",
    }


def save_avatar_bytes(data: bytes, ext: str = "png") -> str:
    """Block-2 A2: write avatar bytes to data/persona/avatar.<ext>.

    Backs up the previous avatar (if any) and enforces a 28-day retention
    on the backup folder. Returns the public URL suffix.

    R7.5: before writing, **delete any sibling avatar files** in other
    formats so we never end up with avatar.png + avatar.jpg + avatar.jpeg
    all coexisting (which previously made ``load_avatar_bytes()`` always
    pick the .png and silently ignore the user's latest upload).
    Also auto-correct the extension by sniffing the first magic bytes
    — uploading a PNG with ext="jpg" (or vice-versa) won't bite us.
    """
    # R7.5: sniff actual format from magic bytes; trust bytes over caller hint.
    real_ext = _sniff_image_ext(data) or (ext or "png").lower().lstrip(".")
    ext = real_ext
    if ext == "jpeg":
        ext = "jpg"
    if ext not in {"png", "jpg"}:
        raise ValueError("unsupported avatar format")
    _PERSONA_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    # R7.5: clean up sibling files in OTHER formats so the directory
    # holds at most one canonical avatar.<ext> at any time.
    for sibling_ext in ("png", "jpg", "jpeg"):
        if sibling_ext == ext:
            continue
        sibling = _PERSONA_AVATAR_DIR / f"avatar.{sibling_ext}"
        if sibling.exists():
            try:
                # Back up the about-to-be-replaced sibling so the user
                # doesn't lose their previous avatar if the new upload
                # is broken / rejected later.
                backup_dir = _DATA_DIR / "backups" / "persona_avatar"
                backup_dir.mkdir(parents=True, exist_ok=True)
                ts = int(time.time() * 1000)
                shutil.copy2(sibling, backup_dir / f"avatar.{ts}.{sibling_ext}")
            except OSError:
                pass
            try:
                sibling.unlink()
            except OSError:
                pass
    # Backup the file we're about to overwrite (same ext).
    target = _PERSONA_AVATAR_DIR / f"avatar.{ext}"
    if target.exists():
        backup_dir = _DATA_DIR / "backups" / "persona_avatar"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        try:
            shutil.copy2(target, backup_dir / f"avatar.{ts}.{ext}")
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
    # Atomic write
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


def _sniff_image_ext(data: bytes) -> str | None:
    """Return 'png' / 'jpg' / 'jpeg' / None from the first magic bytes.

    PNG: 89 50 4E 47 0D 0A 1A 0A
    JPEG: FF D8 FF
    WebP: RIFF....WEBP (we don't support it, return None)
    """
    if not data or len(data) < 8:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return None


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


class ConfigHotReloader:
    """Monitor config/ YAML files and notify subscribers on changes.

    Usage::

        reloader = ConfigHotReloader()
        reloader.subscribe("settings.yaml", lambda: print("settings changed"))
        await reloader.start()
        # ... later, call reloader.stop() to shut down the watcher
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, list[callable]] = {}
        self._mtimes: dict[str, float] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._poll_interval = 2.0

    def subscribe(self, filename: str, callback: callable) -> None:
        """Register a callback for when a specific yaml file changes."""
        if filename not in self._callbacks:
            self._callbacks[filename] = []
        self._callbacks[filename].append(callback)
        path = _CONFIG_DIR / filename
        if path.exists():
            try:
                self._mtimes[filename] = path.stat().st_mtime
            except OSError:
                pass

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        import asyncio as _asyncio
        self._task = _asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _poll_loop(self) -> None:
        import asyncio as _asyncio
        while self._running:
            try:
                self._check_once()
            except Exception:
                pass
            await _asyncio.sleep(self._poll_interval)

    def _check_once(self) -> None:
        import logging
        logger = logging.getLogger(__name__)
        for filename in list(self._callbacks.keys()):
            path = _CONFIG_DIR / filename
            if not path.exists():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            prev = self._mtimes.get(filename)
            if prev is not None and mtime > prev + 0.1:
                self._mtimes[filename] = mtime
                logger.info("config changed: %s", filename)
                for cb in self._callbacks.get(filename, []):
                    try:
                        cb()
                    except Exception:
                        logger.exception("config reload callback failed for %s", filename)
            elif prev is None:
                self._mtimes[filename] = mtime


_RELOADER: ConfigHotReloader | None = None


def get_config_reloader() -> ConfigHotReloader:
    """Get or create the singleton ConfigHotReloader."""
    global _RELOADER
    if _RELOADER is None:
        _RELOADER = ConfigHotReloader()
    return _RELOADER

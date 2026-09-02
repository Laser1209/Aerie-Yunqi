"""Aerie · 云栖 — diagnostics telemetry.

Tracks cumulative application runtime, packages diagnostic data into a zip
at user-defined milestones, and (optionally) uploads the package to a
configured receiver endpoint.

Milestones are cumulative, each triggered exactly once:
  - 1h  (3600 s)
  - 3h  (10800 s)
  - 3d  (259200 s)

Runtime is persisted to ``data/telemetry_state.json`` and flushed every 60 s
so a hard kill loses at most one flush interval. Packages land in
``data/diagnostics/`` as ``aerie-diag-<timestamp>.zip``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.paths import data_dir, project_root
from core.version import APP_VERSION

logger = logging.getLogger("aerie.telemetry")

FLUSH_INTERVAL_SECONDS = 60

# Cumulative milestones: (key, seconds). Triggered once each, in order.
MILESTONES: list[tuple[str, int]] = [
    ("1h", 3600),
    ("3h", 10800),
    ("3d", 259200),
]

PACKAGES_DIR_NAME = "diagnostics"

# Subdirectories of data/ that are intentionally excluded from diagnostics.
# Media/vector binaries are large and not useful for bug triage; the chat DB,
# config, state JSON and logs carry the diagnostic signal.
_EXCLUDED_DATA_SUBDIRS = {
    "diagnostics",
    "qq_media",
    "chroma",
    "chroma_attachments",
    "undo",
    "briefs",
    "cache",
    "persona",
    "personas",
}


def _state_path() -> Path:
    return data_dir() / "telemetry_state.json"


def _packages_dir() -> Path:
    p = data_dir() / PACKAGES_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _device_id() -> str:
    seed = f"{platform.node()}|{project_root()}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {
            "total_seconds": 0.0,
            "last_flush_ts": time.time(),
            "milestones_triggered": [],
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("telemetry state corrupt, resetting")
        return {
            "total_seconds": 0.0,
            "last_flush_ts": time.time(),
            "milestones_triggered": [],
        }
    raw.setdefault("total_seconds", 0.0)
    raw.setdefault("last_flush_ts", time.time())
    raw.setdefault("milestones_triggered", [])
    return raw


def _save_state(state: dict[str, Any]) -> None:
    state = dict(state)
    state["updated_at"] = _now_iso()
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_state_path())


def flush_runtime() -> float:
    """Accumulate wall-clock runtime since the last flush and persist it."""
    state = _load_state()
    now = time.time()
    last = float(state.get("last_flush_ts") or now)
    delta = max(0.0, now - last)
    state["total_seconds"] = float(state.get("total_seconds", 0.0)) + delta
    state["last_flush_ts"] = now
    _save_state(state)
    return float(state["total_seconds"])


def check_milestones() -> list[str]:
    """Return milestone keys newly crossed since the last check, marking them."""
    state = _load_state()
    total = float(state.get("total_seconds", 0.0))
    triggered = set(state.get("milestones_triggered", []))
    new_ones: list[str] = []
    for key, threshold in MILESTONES:
        if total >= threshold and key not in triggered:
            new_ones.append(key)
            triggered.add(key)
    if new_ones:
        state["milestones_triggered"] = sorted(triggered)
        _save_state(state)
    return new_ones


def _collect_paths() -> list[tuple[Path, str]]:
    """Return (absolute_path, archive_name) pairs for the diagnostic package."""
    root = project_root()
    collected: list[tuple[Path, str]] = []

    # Config: YAML only, skip persona_loader.py.
    config_dir = root / "config"
    if config_dir.is_dir():
        for f in sorted(config_dir.glob("*.yaml")):
            collected.append((f, f"config/{f.name}"))

    # SQLite chat/memory DB (full, unredacted).
    db = data_dir() / "aerie.db"
    if db.exists():
        collected.append((db, "data/aerie.db"))

    # Top-level JSON + JSONL state files (no media/vector subdirs).
    data = data_dir()
    if data.is_dir():
        for f in sorted(data.iterdir()):
            if not f.is_file():
                continue
            if f.name == "telemetry_state.json":
                continue
            if f.suffix.lower() in {".json", ".jsonl"}:
                collected.append((f, f"data/{f.name}"))

    # Logs.
    logs_dir = root / "logs"
    if logs_dir.is_dir():
        main_log = logs_dir / "main.log"
        if main_log.exists():
            collected.append((main_log, "logs/main.log"))
        restart_log = logs_dir / "restart_helper.log"
        if restart_log.exists():
            collected.append((restart_log, "logs/restart_helper.log"))
        diag_logs = sorted(logs_dir.glob("diag_*.log"))[-5:]
        for f in diag_logs:
            collected.append((f, f"logs/{f.name}"))

    return collected


def _manifest(reason: str, files: list[tuple[Path, str]], hardware_code: str = "") -> dict[str, Any]:
    try:
        import main as main_mod

        git_commit = getattr(main_mod, "GIT_COMMIT", "unknown")
        instance_id = getattr(main_mod, "BACKEND_INSTANCE_ID", "") or _device_id()
        process_started = getattr(main_mod, "PROCESS_START_ISO", "")
    except Exception:
        git_commit = "unknown"
        instance_id = _device_id()
        process_started = ""

    return {
        "app": "Aerie · 云栖",
        "version": APP_VERSION,
        "generated_at": _now_iso(),
        "reason": reason,
        "git_commit": git_commit,
        "backend_instance_id": instance_id,
        "device_id": _device_id(),
        "process_started_at": process_started,
        "hardware_code": hardware_code,
        "total_runtime_seconds": round(float(_load_state().get("total_seconds", 0.0)), 1),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
        "files": [
            {"path": arc, "bytes": p.stat().st_size}
            for p, arc in files
            if p.exists()
        ],
    }


def create_package(reason: str = "manual") -> dict[str, Any]:
    """Collect diagnostics and write a zip into data/diagnostics/.

    Returns metadata about the created package (path is absolute, filename is
    the basename safe to reference in follow-up upload/list/download calls).
    """
    _packages_dir()
    files = _collect_paths()

    # 硬件指纹护照：生成 64 字符码 + 完整快照，码写入 manifest，快照写入 zip 顶层。
    hardware_code = ""
    passport_snapshot: dict[str, Any] | None = None
    try:
        from core.hardware_passport import generate_passport

        passport = generate_passport()
        hardware_code = str(passport.get("code") or "")
        passport_snapshot = passport.get("snapshot")
    except Exception:
        logger.exception("hardware passport generation failed, continuing without it")

    manifest = _manifest(reason, files, hardware_code)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"aerie-diag-{stamp}.zip"
    target = _packages_dir() / filename

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if passport_snapshot is not None:
            zf.writestr(
                "hardware_passport.json",
                json.dumps(passport_snapshot, ensure_ascii=False, indent=2),
            )
        for p, arc in files:
            if p.exists() and p.is_file():
                zf.write(p, arc)

    logger.info("diagnostics package created: %s (%d files)", filename, len(files))
    return {
        "filename": filename,
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "reason": reason,
        "file_count": len(files),
        "created_at": manifest["generated_at"],
    }


def list_packages() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in sorted(_packages_dir().glob("*.zip"), reverse=True):
        items.append(
            {
                "filename": p.name,
                "size_bytes": p.stat().st_size,
                "modified_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    return items


def _upload_config() -> tuple[str, str]:
    return (
        os.environ.get("AERIE_TELEMETRY_UPLOAD_URL", "").strip(),
        os.environ.get("AERIE_TELEMETRY_UPLOAD_TOKEN", "").strip(),
    )


def upload_package(filename: str) -> dict[str, Any]:
    """POST a previously created package to the configured receiver.

    Protocol: raw zip bytes as the request body, ``Content-Type: application/zip``,
    filename and device id in headers. Auth is a Bearer token when configured.
    """
    url, token = _upload_config()
    if not url:
        return {"ok": False, "error": "upload_url_not_configured"}

    target = _packages_dir() / filename
    if not target.exists():
        return {"ok": False, "error": "not_found", "filename": filename}

    data = target.read_bytes()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/zip")
    req.add_header("X-Diagnostic-Filename", filename)
    req.add_header("X-Device-Id", _device_id())
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
            return {"ok": True, "status": resp.status, "filename": filename, "body": body[:500]}
    except urllib.error.HTTPError as e:
        body = (e.read() or b"").decode("utf-8", "replace")
        return {"ok": False, "error": f"http_{e.code}", "filename": filename, "body": body[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e), "filename": filename}


def get_status() -> dict[str, Any]:
    state = _load_state()
    url, token = _upload_config()
    total = float(state.get("total_seconds", 0.0))
    return {
        "total_runtime_seconds": round(total, 1),
        "total_runtime_human": _human_duration(total),
        "milestones_triggered": list(state.get("milestones_triggered", [])),
        "milestones": [
            {"key": key, "seconds": sec, "triggered": key in state.get("milestones_triggered", [])}
            for key, sec in MILESTONES
        ],
        "upload_configured": bool(url),
        "upload_url_masked": _mask_url(url),
        "packages": list_packages(),
        "device_id": _device_id(),
    }


def _human_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, sec = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if sec or not parts:
        parts.append(f"{sec}s")
    return " ".join(parts)


def _mask_url(url: str) -> str:
    if not url:
        return ""
    # Hide any query string that may carry credentials.
    base = url.split("?", 1)[0]
    return base


async def _telemetry_loop() -> None:
    # First tick initializes the clock and immediately evaluates milestones.
    while True:
        try:
            flush_runtime()
            for key in check_milestones():
                try:
                    info = await asyncio.to_thread(create_package, key)
                    logger.info("milestone %s package: %s", key, info["filename"])
                except Exception:
                    logger.exception("milestone %s package failed", key)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telemetry loop error")
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)


class TelemetryRunner:
    def __init__(self, task: asyncio.Task) -> None:
        self._task = task

    async def cleanup(self) -> None:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("telemetry task shutdown error")
        # Final flush so a clean shutdown doesn't lose the last interval.
        try:
            flush_runtime()
        except Exception:
            logger.exception("final telemetry flush failed")


def start_telemetry() -> TelemetryRunner:
    task = asyncio.create_task(_telemetry_loop())
    return TelemetryRunner(task)

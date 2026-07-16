"""vram skill — 显存调整 / GPU VRAM limit.

Block-4C R3.3 scaffold. Tries to call the native module
``local_vram`` when it is importable; otherwise returns a stub
response so the main pipeline is never broken by a missing
dependency.

Stub contract:
  - missing required arg  -> {"error": "missing <key>"}
  - module not installed  -> {"status": "stub", "error": "..."}
  - other exception       -> {"status": "error", "error": "..."}
"""
from __future__ import annotations
import logging
import os
logger = logging.getLogger(__name__)

PROVIDER_HINT = "shell-safe"
READ_ONLY = False


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'percent'.
    """
    args = args or {}
    percent_value = args.get("percent")
    if not percent_value:
        return {"error": "missing percent", "provider_hint": PROVIDER_HINT}

    try:
        from local_vram import set_limit as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_vram not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "percent": str(percent_value)[:80],
        }

    try:
        result = _impl(percent_value, **{k: v for k, v in args.items() if k != "percent"})
    except Exception as e:
        logger.exception("vram skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"ok": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

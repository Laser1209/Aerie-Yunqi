"""obsidian-bases skill — Obsidian Bases 读取 / Obsidian Bases.

Block-4C R3.3 scaffold. Tries to call the native module
``obsidian_bases`` when it is importable; otherwise returns a stub
response so the main pipeline is never broken by a missing
dependency.

Stub contract:
  - missing required arg  -> {"error": "missing <key>"}
  - module not installed  -> {"status": "stub", "error": "..."}
  - other exception       -> {"status": "error", "error": "..."}
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

PROVIDER_HINT = "text"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'base_path'.
    """
    args = args or {}
    base_path_value = args.get("base_path")
    if not base_path_value:
        return {"error": "missing base_path", "provider_hint": PROVIDER_HINT}

    try:
        from obsidian_bases import load as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"obsidian_bases not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "base_path": str(base_path_value)[:80],
        }

    try:
        result = _impl(base_path_value, **{k: v for k, v in args.items() if k != "base_path"})
    except Exception as e:
        logger.exception("obsidian-bases skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"structure": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

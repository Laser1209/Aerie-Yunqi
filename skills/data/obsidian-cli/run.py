"""obsidian-cli skill — Obsidian CLI 调用 / Obsidian vault.

Block-4C R3.3 scaffold. Tries to call the native module
``obsidian_cli`` when it is importable; otherwise returns a stub
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

PROVIDER_HINT = "text"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'subcommand'.
    """
    args = args or {}
    subcommand_value = args.get("subcommand")
    if not subcommand_value:
        return {"error": "missing subcommand", "provider_hint": PROVIDER_HINT}

    try:
        from obsidian_cli import run as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"obsidian_cli not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "subcommand": str(subcommand_value)[:80],
        }

    try:
        result = _impl(subcommand_value, **{k: v for k, v in args.items() if k != "subcommand"})
    except Exception as e:
        logger.exception("obsidian-cli skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"stdout": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

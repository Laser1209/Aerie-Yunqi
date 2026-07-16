"""computer-use skill — 系统状态查询 / System query.

Block-4C R3.3 scaffold. Tries to call the native module
``local_computer_use`` when it is importable; otherwise returns a stub
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
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'category'.
    """
    args = args or {}
    category_value = args.get("category")
    if not category_value:
        return {"error": "missing category", "provider_hint": PROVIDER_HINT}

    try:
        from local_computer_use import query as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_computer_use not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "category": str(category_value)[:80],
        }

    try:
        result = _impl(category_value, **{k: v for k, v in args.items() if k != "category"})
    except Exception as e:
        logger.exception("computer-use skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"value": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

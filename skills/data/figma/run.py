"""figma skill — Figma MCP 调用 / Figma MCP.

Block-4C R3.3 scaffold. Tries to call the native module
``figma_mcp`` when it is importable; otherwise returns a stub
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
    the API caller; convention keys: 'method'.
    """
    args = args or {}
    method_value = args.get("method")
    if not method_value:
        return {"error": "missing method", "provider_hint": PROVIDER_HINT}

    try:
        from figma_mcp import call as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"figma_mcp not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "method": str(method_value)[:80],
        }

    try:
        result = _impl(method_value, **{k: v for k, v in args.items() if k != "method"})
    except Exception as e:
        logger.exception("figma skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"data": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

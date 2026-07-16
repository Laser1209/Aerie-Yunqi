"""markitdown skill — Office→MD / Office to Markdown.

Block-4C R3.3 scaffold. Tries to call the native module
``markitdown`` when it is importable; otherwise returns a stub
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
    the API caller; convention keys: 'file_path'.
    """
    args = args or {}
    file_path_value = args.get("file_path")
    if not file_path_value:
        return {"error": "missing file_path", "provider_hint": PROVIDER_HINT}

    try:
        from markitdown import MarkItDown as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"markitdown not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "file_path": str(file_path_value)[:80],
        }

    try:
        result = _impl(file_path_value, **{k: v for k, v in args.items() if k != "file_path"})
    except Exception as e:
        logger.exception("markitdown skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"markdown": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

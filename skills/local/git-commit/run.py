"""git-commit skill — 提交信息生成 / Commit message gen.

Block-4C R3.3 scaffold. Tries to call the native module
``git_commit`` when it is importable; otherwise returns a stub
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
    the API caller; convention keys: 'diff_text'.
    """
    args = args or {}
    diff_text_value = args.get("diff_text")
    if not diff_text_value:
        return {"error": "missing diff_text", "provider_hint": PROVIDER_HINT}

    try:
        from git_commit import generate as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"git_commit not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "diff_text": str(diff_text_value)[:80],
        }

    try:
        result = _impl(diff_text_value, **{k: v for k, v in args.items() if k != "diff_text"})
    except Exception as e:
        logger.exception("git-commit skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"message": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

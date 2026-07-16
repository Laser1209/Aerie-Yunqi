"""spec-to-impl skill — Spec→tasks 拆解 / Spec to implementation.

Block-4C R3.3 scaffold. Tries to call the native module
``spec_to_impl`` when it is importable; otherwise returns a stub
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
    the API caller; convention keys: 'spec_text'.
    """
    args = args or {}
    spec_text_value = args.get("spec_text")
    if not spec_text_value:
        return {"error": "missing spec_text", "provider_hint": PROVIDER_HINT}

    try:
        from spec_to_impl import decompose as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"spec_to_impl not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "spec_text": str(spec_text_value)[:80],
        }

    try:
        result = _impl(spec_text_value, **{k: v for k, v in args.items() if k != "spec_text"})
    except Exception as e:
        logger.exception("spec-to-impl skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"tasks": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

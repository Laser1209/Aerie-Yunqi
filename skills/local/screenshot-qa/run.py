"""screenshot-qa skill — 截图问答 / Screenshot Q&A.

Block-4C R3.3 scaffold. Tries to call the native module
``local_screenshot_qa`` when it is importable; otherwise returns a stub
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

PROVIDER_HINT = "vision-llava"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'image_path'.
    """
    args = args or {}
    image_path_value = args.get("image_path")
    if not image_path_value:
        return {"error": "missing image_path", "provider_hint": PROVIDER_HINT}

    try:
        from local_screenshot_qa import ask as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_screenshot_qa not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "image_path": str(image_path_value)[:80],
        }

    try:
        result = _impl(image_path_value, **{k: v for k, v in args.items() if k != "image_path"})
    except Exception as e:
        logger.exception("screenshot-qa skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"answer": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

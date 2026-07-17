"""txt2img skill — 文生图 / Text-to-image.

Block-4C R3.3 scaffold. Tries to call the native module
``local_txt2img`` when it is importable; otherwise returns a stub
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

PROVIDER_HINT = "image-sdxl"
READ_ONLY = False


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'prompt'.
    """
    args = args or {}
    prompt_value = args.get("prompt")
    if not prompt_value:
        return {"error": "missing prompt", "provider_hint": PROVIDER_HINT}

    try:
        from local_txt2img import generate as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_txt2img not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "prompt": str(prompt_value)[:80],
        }

    try:
        result = _impl(prompt_value, **{k: v for k, v in args.items() if k != "prompt"})
    except Exception as e:
        logger.exception("txt2img skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"output_path": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

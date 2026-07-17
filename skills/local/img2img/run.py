"""img2img skill — 图像编辑 / Image-to-image.

Block-4C R3.3 scaffold. Tries to call the native module
``local_img2img`` when it is importable; otherwise returns a stub
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
    the API caller; convention keys: 'source'.
    """
    args = args or {}
    source_value = args.get("source")
    if not source_value:
        return {"error": "missing source", "provider_hint": PROVIDER_HINT}

    try:
        from local_img2img import transform as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_img2img not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "source": str(source_value)[:80],
        }

    try:
        result = _impl(source_value, **{k: v for k, v in args.items() if k != "source"})
    except Exception as e:
        logger.exception("img2img skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"output_path": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

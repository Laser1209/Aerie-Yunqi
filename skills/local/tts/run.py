"""tts skill — 文字转语音 / Text to speech.

Block-4C R3.3 scaffold. Tries to call the native module
``local_tts`` when it is importable; otherwise returns a stub
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

PROVIDER_HINT = "tts-openvino"
READ_ONLY = False


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'text'.
    """
    args = args or {}
    text_value = args.get("text")
    if not text_value:
        return {"error": "missing text", "provider_hint": PROVIDER_HINT}

    try:
        from local_tts import synthesize as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_tts not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "text": str(text_value)[:80],
        }

    try:
        result = _impl(text_value, **{k: v for k, v in args.items() if k != "text"})
    except Exception as e:
        logger.exception("tts skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"wav_path": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

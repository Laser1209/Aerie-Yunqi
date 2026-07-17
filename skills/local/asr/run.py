"""asr skill — 语音识别 / Speech recognition.

Block-4C R3.3 scaffold. Tries to call the native module
``local_asr`` when it is importable; otherwise returns a stub
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

PROVIDER_HINT = "asr-whisper"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict from
    the API caller; convention keys: 'audio_path'.
    """
    args = args or {}
    audio_path_value = args.get("audio_path")
    if not audio_path_value:
        return {"error": "missing audio_path", "provider_hint": PROVIDER_HINT}

    try:
        from local_asr import transcribe as _impl
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_asr not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "audio_path": str(audio_path_value)[:80],
        }

    try:
        result = _impl(audio_path_value, **{k: v for k, v in args.items() if k != "audio_path"})
    except Exception as e:
        logger.exception("asr skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    if not isinstance(result, dict):
        result = {"text": result}
    result.setdefault("status", "ok")
    result.setdefault("provider_hint", PROVIDER_HINT)
    result.setdefault("read_only", READ_ONLY)
    return result

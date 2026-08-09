"""siliconflow-vision skill — 图片视觉理解 / Vision Q&A (SiliconFlow).

Calls the SiliconFlow vision API (OpenAI-compatible chat completions)
to describe an image, extract text, or answer a question about it.

Adapted from the open-source "deepseek-3pmode-image-recognition-skill"
(siliconflow-vision) into Aerie's SkillLoader contract::

  run(args: dict) -> dict

Contract:
  - missing required arg  -> {"error": "missing <key>"}
  - API key not set       -> {"status": "stub", "error": "..."}
  - other exception       -> {"status": "error", "error": "..."}
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path

logger = logging.getLogger(__name__)

PROVIDER_HINT = "text"
READ_ONLY = True

_DEFAULT_BASE_URL = "https://api.siliconflow.com/v1"
_DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
# Cap the longest edge so very large screenshots don't blow up vision
# token usage.  Resize is a no-op for already-small images.
_MAX_EDGE = 1600

_EXT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("image/"):
        return mime
    return _EXT_MIME.get(path.suffix.lower(), "image/png")


def _encode_image(path: Path) -> str:
    """Return base64 of the image, downscaled to ``_MAX_EDGE`` if larger."""
    data = path.read_bytes()
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(data))
        w, h = img.size
        longest = max(w, h)
        if longest > _MAX_EDGE:
            scale = _MAX_EDGE / float(longest)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            buf = io.BytesIO()
            fmt = img.format or "PNG"
            img.save(buf, format=fmt)
            data = buf.getvalue()
    except ImportError:
        logger.debug("Pillow not installed, skipping image downscale")
    except Exception as e:  # non-fatal: fall back to raw bytes
        logger.warning("image downscale failed, using original: %s", e)
    return base64.b64encode(data).decode()


def run(args: dict) -> dict:
    """Skill entry point. ``args`` keys: 'image_path' (required), 'question' (optional)."""
    args = args or {}
    image_path_value = args.get("image_path")
    if not image_path_value:
        return {"error": "missing image_path", "provider_hint": PROVIDER_HINT}

    path = Path(image_path_value)
    if not path.exists():
        return {"status": "error", "error": f"file not found: {image_path_value}",
                "provider_hint": PROVIDER_HINT}

    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        return {
            "status": "stub",
            "error": "SILICONFLOW_API_KEY not set in .env",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "image_path": str(image_path_value)[:80],
        }

    question = str(args.get("question") or (
        "请详细描述这张图片的内容，包括画面中的物体、人物、场景、文字、颜色等所有细节。"
    ))

    try:
        from openai import OpenAI
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"openai not installed: {e}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    base_url = os.getenv("SILICONFLOW_BASE_URL", _DEFAULT_BASE_URL)
    model = os.getenv("VISION_MODEL", _DEFAULT_MODEL)
    mime_type = _guess_mime(path)
    b64 = _encode_image(path)

    try:
        import httpx
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            # Bypass the flaky ambient HTTP(S)_PROXY on this box; direct
            # connections to SiliconFlow are reliable here.
            http_client=httpx.Client(trust_env=False, timeout=60),
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    {"type": "text", "text": question},
                ],
            }],
            max_tokens=4096,
        )
        answer = response.choices[0].message.content or ""
    except Exception as e:
        logger.exception("siliconflow-vision skill failed")
        return {"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}

    return {
        "status": "ok",
        "answer": answer,
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
        "model": model,
    }

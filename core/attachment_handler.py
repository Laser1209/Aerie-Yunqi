"""Aerie · 云栖 v0.1.0-beta.1 — Office / PDF → Markdown conversion via markitdown.

Block-3 R0.2: when a user uploads a non-image file to chat, the backend
runs it through markitdown and stores the extracted markdown under
``data/attachments_md/``. The LLM system prompt then embeds the markdown
in place of the raw filename, so the model can actually read the document.

Security notes (per TRAE-security-review):
- Whitelist of supported extensions is enforced.
- File path is validated to live under UPLOAD_DIR (no path traversal).
- markitdown is a pure-Python library (no shell-out, no pickle).
- Output is truncated to 8000 chars (project-wide knowledge-base cap).
"""

from __future__ import annotations
import io
import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageOps
except Exception as e:  # pragma: no cover - import-time guard
    Image = None
    ImageOps = None
    logging.getLogger(__name__).warning("Pillow unavailable: %s", e)

try:
    from markitdown import MarkItDown
    _MD = MarkItDown()
except Exception as e:  # pragma: no cover - import-time guard
    _MD = None
    logging.getLogger(__name__).warning("markitdown unavailable: %s", e)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ATTACH_DIR = _PROJECT_ROOT / "data" / "attachments_md"
_ATTACH_DIR.mkdir(parents=True, exist_ok=True)

# Whitelist: extensions we know markitdown can handle.
_EXTS = {
    ".pdf",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".ppt", ".pptx",
    ".html", ".htm",
    ".csv", ".tsv",
    ".json", ".xml",
    ".epub",
    ".txt", ".md", ".markdown",
    ".rtf",
}

# Project-wide cap so the LLM context does not blow up.
_MAX_MD_CHARS = 8000

_TRUNCATION_MARK = "\n\n(truncated to 8000 chars)"

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_IMAGE_FORMAT_TO_EXT = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "JPG": ".jpg",
    "GIF": ".gif",
    "WEBP": ".webp",
}
_IMAGE_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
_MAX_IMAGE_PIXELS = 64_000_000
_THUMBNAIL_SIZE = (512, 512)


def _image_asset_root(upload_base: str | Path) -> Path:
    base = Path(upload_base)
    if not base.is_absolute():
        base = _PROJECT_ROOT / base
    return base.resolve().parent / ".image_assets"


def _image_index_path(upload_base: str | Path) -> Path:
    return _image_asset_root(upload_base) / "index.json"


def _load_image_index(upload_base: str | Path) -> dict:
    p = _image_index_path(upload_base)
    if not p.exists():
        return {"files": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logging.getLogger(__name__).warning(
            "attachment_handler: image index corrupt for %s", p, exc_info=True
        )
        return {"files": {}}
    if not isinstance(data, dict):
        return {"files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        data["files"] = {}
    return data


def _save_image_index(upload_base: str | Path, payload: dict) -> None:
    p = _image_index_path(upload_base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(p)


def _sanitize_image_bytes(raw: bytes, original_name: str) -> dict:
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow unavailable")

    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img)
        img.load()
        width, height = img.size
        if width <= 0 or height <= 0:
            raise ValueError("invalid image dimensions")
        if width * height > _MAX_IMAGE_PIXELS:
            raise ValueError("image too large")

        fmt = (img.format or "").upper()
        if fmt not in _IMAGE_FORMAT_TO_EXT:
            suffix = Path(original_name).suffix.lower()
            fmt = {
                ".png": "PNG",
                ".jpg": "JPEG",
                ".jpeg": "JPEG",
                ".gif": "GIF",
                ".webp": "WEBP",
            }.get(suffix, "PNG")

        if fmt in {"JPEG", "JPG"} and img.mode not in {"RGB", "L"}:
            img = img.convert("RGB")
        elif fmt == "GIF" and img.mode not in {"P", "L", "RGB"}:
            img = img.convert("RGB")

        cleaned = io.BytesIO()
        img.save(cleaned, format=fmt)
        sanitized = cleaned.getvalue()

        thumb = img.copy()
        thumb.thumbnail(_THUMBNAIL_SIZE)
        thumb_buf = io.BytesIO()
        thumb.save(thumb_buf, format="PNG")

    sha256 = hashlib.sha256(sanitized).hexdigest()
    return {
        "bytes": sanitized,
        "thumbnail": thumb_buf.getvalue(),
        "sha256": sha256,
        "width": width,
        "height": height,
        "format": fmt,
        "mime_type": _IMAGE_FORMAT_TO_MIME.get(fmt, "application/octet-stream"),
        "ext": _IMAGE_FORMAT_TO_EXT.get(fmt, Path(original_name).suffix.lower() or ".png"),
    }


def process_image_upload(
    *,
    filename: str,
    content: bytes,
    content_type: str,
    upload_base: str | Path = "uploads",
) -> dict:
    """Persist an image upload with normalization, dedupe, and metadata."""
    if Image is None:
        raise RuntimeError("Pillow unavailable")
    if not content:
        raise ValueError("empty image")
    if not str(content_type or "").lower().startswith("image/"):
        raise ValueError(f"unsupported image type: {content_type}")

    base = Path(upload_base)
    if not base.is_absolute():
        base = _PROJECT_ROOT / base
    base.mkdir(parents=True, exist_ok=True)
    asset_root = _image_asset_root(base)
    asset_root.mkdir(parents=True, exist_ok=True)
    thumb_dir = asset_root / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    normalized = _sanitize_image_bytes(content, filename)
    digest = normalized["sha256"]
    index = _load_image_index(base)
    files = index.setdefault("files", {})
    existing = files.get(digest)
    if isinstance(existing, dict):
        saved_as = existing.get("saved_as")
        if saved_as and (base / str(saved_as)).exists():
            return {
                "status": "ok",
                "filename": filename,
                "saved_as": saved_as,
                "size": len(content),
                "content_type": content_type,
                "mime_type": existing.get("mime_type", normalized["mime_type"]),
                "width": int(existing.get("width") or normalized["width"]),
                "height": int(existing.get("height") or normalized["height"]),
                "sha256": digest,
                "url": f"/uploads/{saved_as}",
                "thumbnail_url": existing.get("thumbnail_url", ""),
                "deduplicated": True,
                "duplicate_of": saved_as,
                "is_image": True,
            }

    unique_name = f"{uuid.uuid4().hex}{normalized['ext']}"
    dest = base / unique_name
    dest.write_bytes(normalized["bytes"])

    thumb_name = f"{uuid.uuid4().hex}.png"
    thumb_path = thumb_dir / thumb_name
    thumb_path.write_bytes(normalized["thumbnail"])

    thumbnail_url = f"/uploads/.image_assets/thumbs/{thumb_name}"
    record = {
        "filename": filename,
        "saved_as": unique_name,
        "size": len(normalized["bytes"]),
        "content_type": content_type,
        "mime_type": normalized["mime_type"],
        "width": normalized["width"],
        "height": normalized["height"],
        "sha256": digest,
        "thumbnail_url": thumbnail_url,
        "is_image": True,
    }
    files[digest] = record
    _save_image_index(base, index)

    return {
        "status": "ok",
        **record,
        "url": f"/uploads/{unique_name}",
        "deduplicated": False,
        "duplicate_of": "",
    }


def _safe_resolve_under(base: Path, candidate: Path) -> Optional[Path]:
    """Resolve ``candidate`` and ensure it is inside ``base``.

    Returns the resolved path on success, None on path-traversal attempts.
    """
    try:
        base_resolved = base.resolve()
        cand_resolved = candidate.resolve()
        # Python 3.9+: is_relative_to; fall back to manual for 3.8.
        if hasattr(cand_resolved, "is_relative_to"):
            if not cand_resolved.is_relative_to(base_resolved):
                return None
        else:
            try:
                cand_resolved.relative_to(base_resolved)
            except ValueError:
                return None
        return cand_resolved
    except OSError:
        return None


def _cache_path(file_path: Path) -> Path:
    """Stable cache file path keyed by SHA-1 of content."""
    h = hashlib.sha1(file_path.read_bytes()).hexdigest()[:16]
    return _ATTACH_DIR / f"{h}.md"


def extract_markdown(file_path: str | Path, upload_base: str | Path = "uploads") -> Optional[str]:
    """Convert ``file_path`` to markdown text via markitdown.

    Args:
        file_path: absolute or relative path to the uploaded file.
        upload_base: root directory the file must live under (default: ``uploads``).

    Returns:
        Extracted markdown (truncated to 8000 chars) or None on any failure.
    """
    if _MD is None:
        return None

    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return None

    ext = p.suffix.lower()
    if ext not in _EXTS:
        return None

    # Path-traversal guard
    base = Path(upload_base)
    if not base.is_absolute():
        base = _PROJECT_ROOT / base
    safe = _safe_resolve_under(base, p)
    if safe is None:
        logging.getLogger(__name__).warning(
            "attachment_handler: rejected %s (outside %s)", p, base
        )
        return None

    # Cache hit?
    try:
        cache = _cache_path(safe)
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="replace")[:_MAX_MD_CHARS]
    except OSError:
        return None

    # Convert
    try:
        result = _MD.convert(str(safe))
        text = (getattr(result, "text_content", "") or "").strip()
    except Exception as e:
        logging.getLogger(__name__).warning(
            "markitdown failed for %s: %s", safe, e
        )
        return None

    if not text:
        return None

    # Truncate + persist
    if len(text) > _MAX_MD_CHARS:
        text = text[:_MAX_MD_CHARS] + _TRUNCATION_MARK
    try:
        cache.write_text(text, encoding="utf-8")
    except OSError:
        # If we can't cache, still return the freshly-converted text.
        return text

    return text


def is_supported_extension(ext: str) -> bool:
    """Return True if ``ext`` is in the markitdown-eligible whitelist."""
    return ext.lower().startswith(".") and ext.lower() in _EXTS

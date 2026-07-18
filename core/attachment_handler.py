"""Aerie · 云栖 v13.9.8 — Office / PDF → Markdown conversion via markitdown.

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
import hashlib
import logging
from pathlib import Path
from typing import Optional

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

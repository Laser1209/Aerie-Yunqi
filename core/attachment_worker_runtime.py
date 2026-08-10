from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import stat
import sys
import wave
import zipfile
from importlib import import_module
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


WORKER_CONTRACT_VERSION = 1
DEFAULT_CHUNK_CHARS = 4000
DEFAULT_MAX_OUTPUT_CHARS = 120_000
DEFAULT_ZIP_LIMITS = {
    "maxMembers": 1000,
    "maxUncompressedBytes": 200 * 1024 * 1024,
    "maxCompressionRatio": 100,
    "maxTextMemberBytes": 2 * 1024 * 1024,
}
DEFAULT_ARCHIVE_LIMITS = {
    key: value
    for key, value in DEFAULT_ZIP_LIMITS.items()
    if key != "maxTextMemberBytes"
}
ZIP_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml",
    ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".css",
    ".sql", ".yaml", ".yml", ".toml", ".ini", ".log", ".sh", ".ps1",
    ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs",
}


class ZipSafetyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArchiveSafetyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AttachmentExtractionError(RuntimeError):
    """Stable worker failure that may carry safe, path-free metadata."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = dict(metadata or {})


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolved_under(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise ValueError("worker path escapes allowed root") from None
    return resolved


def validate_zip_archive(
    path: str | Path,
    *,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    cfg = dict(DEFAULT_ZIP_LIMITS)
    if limits:
        for key in cfg:
            value = limits.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                cfg[key] = value

    entries: list[dict[str, Any]] = []
    total_uncompressed = 0
    total_compressed = 0
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile):
        raise ZipSafetyError("invalid_zip", "archive is not a valid ZIP") from None

    with archive:
        infos = archive.infolist()
        if len(infos) > cfg["maxMembers"]:
            raise ZipSafetyError("zip_member_limit", "archive has too many members")
        for info in infos:
            raw_name = info.filename
            normalized = raw_name.replace("\\", "/")
            posix = PurePosixPath(normalized)
            windows = PureWindowsPath(raw_name)
            if (
                not raw_name
                or "\x00" in raw_name
                or posix.is_absolute()
                or windows.is_absolute()
                or windows.drive
                or ".." in posix.parts
            ):
                raise ZipSafetyError(
                    "zip_path_traversal",
                    "archive contains an unsafe member path",
                )
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(unix_mode) == stat.S_IFLNK:
                raise ZipSafetyError(
                    "zip_symlink",
                    "archive contains a symbolic link",
                )
            if info.flag_bits & 0x1:
                raise ZipSafetyError(
                    "zip_encrypted",
                    "encrypted archive members are unsupported",
                )
            total_uncompressed += int(info.file_size)
            total_compressed += int(info.compress_size)
            if total_uncompressed > cfg["maxUncompressedBytes"]:
                raise ZipSafetyError(
                    "zip_size_limit",
                    "archive expands beyond the configured size limit",
                )
            if info.file_size > 0:
                ratio = (
                    float("inf")
                    if info.compress_size == 0
                    else info.file_size / info.compress_size
                )
                if ratio > cfg["maxCompressionRatio"]:
                    raise ZipSafetyError(
                        "zip_ratio_limit",
                        "archive member exceeds the compression ratio limit",
                    )
            entries.append(
                {
                    "name": normalized,
                    "size": int(info.file_size),
                    "compressedSize": int(info.compress_size),
                    "directory": info.is_dir(),
                }
            )
    overall_ratio = (
        total_uncompressed / max(total_compressed, 1)
        if total_uncompressed
        else 0.0
    )
    if overall_ratio > cfg["maxCompressionRatio"]:
        raise ZipSafetyError(
            "zip_ratio_limit",
            "archive exceeds the total compression ratio limit",
        )
    return {
        "memberCount": len(entries),
        "totalUncompressedBytes": total_uncompressed,
        "totalCompressedBytes": total_compressed,
        "compressionRatio": round(overall_ratio, 3),
        "entries": entries,
        "limits": cfg,
    }


def _normalized_archive_limits(limits: dict[str, int] | None) -> dict[str, int]:
    cfg = dict(DEFAULT_ARCHIVE_LIMITS)
    if limits:
        for key in cfg:
            value = limits.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                cfg[key] = value
    return cfg


def _validate_archive_member_name(raw_name: str) -> str:
    normalized = raw_name.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(raw_name)
    if (
        not raw_name
        or "\x00" in raw_name
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
    ):
        raise ArchiveSafetyError(
            "archive_path_traversal",
            "archive contains an unsafe member path",
        )
    return normalized


def _validate_archive_entries(
    raw_entries: list[dict[str, Any]],
    *,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    cfg = _normalized_archive_limits(limits)
    if len(raw_entries) > cfg["maxMembers"]:
        raise ArchiveSafetyError(
            "archive_member_limit",
            "archive has too many members",
        )

    entries: list[dict[str, Any]] = []
    total_uncompressed = 0
    total_compressed = 0
    for raw_entry in raw_entries:
        name = _validate_archive_member_name(str(raw_entry.get("name") or ""))
        if bool(raw_entry.get("symlink")):
            raise ArchiveSafetyError(
                "archive_symlink",
                "archive contains a symbolic link",
            )
        if bool(raw_entry.get("encrypted")):
            raise ArchiveSafetyError(
                "archive_encrypted",
                "encrypted archive members are unsupported",
            )

        try:
            size = int(raw_entry.get("size") or 0)
            compressed_value = raw_entry.get("compressedSize")
            compressed_size = (
                None if compressed_value is None else int(compressed_value)
            )
        except (TypeError, ValueError):
            raise ArchiveSafetyError(
                "invalid_archive",
                "archive contains invalid member sizes",
            ) from None
        if size < 0 or (compressed_size is not None and compressed_size < 0):
            raise ArchiveSafetyError(
                "invalid_archive",
                "archive contains invalid member sizes",
            )

        total_uncompressed += size
        if compressed_size is not None:
            total_compressed += compressed_size
        if total_uncompressed > cfg["maxUncompressedBytes"]:
            raise ArchiveSafetyError(
                "archive_size_limit",
                "archive expands beyond the configured size limit",
            )
        if size > 0 and compressed_size is not None:
            ratio = float("inf") if compressed_size == 0 else size / compressed_size
            if ratio > cfg["maxCompressionRatio"]:
                raise ArchiveSafetyError(
                    "archive_ratio_limit",
                    "archive member exceeds the compression ratio limit",
                )
        entries.append(
            {
                "name": name,
                "size": size,
                "compressedSize": compressed_size,
                "entryType": "directory"
                if bool(raw_entry.get("directory"))
                else "file",
            }
        )

    overall_ratio = (
        total_uncompressed / total_compressed
        if total_uncompressed and total_compressed
        else (float("inf") if total_uncompressed else 0.0)
    )
    if overall_ratio > cfg["maxCompressionRatio"]:
        raise ArchiveSafetyError(
            "archive_ratio_limit",
            "archive exceeds the total compression ratio limit",
        )
    return {
        "memberCount": len(entries),
        "totalUncompressedBytes": total_uncompressed,
        "totalCompressedBytes": total_compressed,
        "compressionRatio": round(overall_ratio, 3),
        "entries": entries,
        "limits": cfg,
    }


def validate_7z_archive(
    path: str | Path,
    *,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    try:
        py7zr = import_module("py7zr")
    except (ImportError, ModuleNotFoundError):
        raise ArchiveSafetyError(
            "archive_parser_unavailable",
            "7Z metadata parser is unavailable",
        ) from None

    try:
        with py7zr.SevenZipFile(path, "r") as archive:
            if archive.needs_password():
                raise ArchiveSafetyError(
                    "archive_encrypted",
                    "encrypted archives are unsupported",
                )
            raw_entries = [
                {
                    "name": info.filename,
                    "size": info.uncompressed,
                    "compressedSize": info.compressed,
                    "directory": info.is_directory,
                    "symlink": info.is_symlink,
                }
                for info in archive.list()
            ]
    except ArchiveSafetyError:
        raise
    except Exception:
        raise ArchiveSafetyError(
            "invalid_7z",
            "archive is not a valid readable 7Z file",
        ) from None
    return _validate_archive_entries(raw_entries, limits=limits)


def validate_rar_archive(
    path: str | Path,
    *,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    try:
        rarfile = import_module("rarfile")
    except (ImportError, ModuleNotFoundError):
        raise ArchiveSafetyError(
            "archive_parser_unavailable",
            "RAR metadata parser is unavailable",
        ) from None

    try:
        with rarfile.RarFile(path, "r") as archive:
            if archive.needs_password():
                raise ArchiveSafetyError(
                    "archive_encrypted",
                    "encrypted archives are unsupported",
                )
            raw_entries = [
                {
                    "name": info.filename,
                    "size": info.file_size,
                    "compressedSize": info.compress_size,
                    "directory": info.is_dir(),
                    "symlink": info.is_symlink(),
                    "encrypted": info.needs_password(),
                }
                for info in archive.infolist()
            ]
    except ArchiveSafetyError:
        raise
    except Exception:
        raise ArchiveSafetyError(
            "invalid_rar",
            "archive is not a valid readable RAR file",
        ) from None
    if not raw_entries:
        # rarfile is lenient on garbage that only carries the RAR signature;
        # unlike a real (even empty) archive it yields no readable members.
        raise ArchiveSafetyError(
            "invalid_rar",
            "archive contains no readable members",
        )
    return _validate_archive_entries(raw_entries, limits=limits)


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_zip_text(path: Path, manifest: dict[str, Any]) -> tuple[str, int]:
    limit = int(manifest["limits"]["maxTextMemberBytes"])
    sections = [
        "ZIP manifest:\n"
        + json.dumps(
            {key: value for key, value in manifest.items() if key != "entries"},
            ensure_ascii=False,
            sort_keys=True,
        )
    ]
    used = len(sections[0])
    extracted_members = 0
    with zipfile.ZipFile(path, "r") as archive:
        for entry in manifest["entries"]:
            if entry["directory"] or entry["size"] > limit:
                continue
            suffix = Path(entry["name"]).suffix.lower()
            if suffix not in ZIP_TEXT_EXTENSIONS:
                continue
            with archive.open(entry["name"], "r") as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                continue
            section = f"\n\n## {entry['name']}\n{_decode_text(raw)}"
            if used + len(section) > DEFAULT_MAX_OUTPUT_CHARS:
                break
            sections.append(section)
            used += len(section)
            extracted_members += 1
    return "".join(sections), extracted_members


def _extract_with_markitdown(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except Exception:
        return ""
    try:
        result = MarkItDown().convert(str(path))
    except Exception:
        return ""
    return str(getattr(result, "text_content", "") or "").strip()


def _media_metadata(path: Path, category: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if category == "image":
        try:
            from PIL import Image

            with Image.open(path) as image:
                metadata.update(
                    {
                        "width": int(image.width),
                        "height": int(image.height),
                        "format": str(image.format or ""),
                        "frames": int(getattr(image, "n_frames", 1)),
                    }
                )
        except Exception:
            metadata["metadataWarning"] = "image_metadata_unavailable"
    elif category == "audio" and path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                frames = audio.getnframes()
                rate = audio.getframerate()
                metadata.update(
                    {
                        "channels": audio.getnchannels(),
                        "sampleRate": rate,
                        "frames": frames,
                        "durationSeconds": round(frames / rate, 3) if rate else 0,
                    }
                )
        except (OSError, wave.Error):
            metadata["metadataWarning"] = "audio_metadata_unavailable"
    return metadata


def _metadata_text(path: Path, metadata: dict[str, Any]) -> str:
    return "File metadata (content was not executed):\n" + json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def _chunks(text: str, chunk_chars: int, max_chars: int) -> list[dict[str, Any]]:
    clipped = text[:max_chars]
    result = []
    for ordinal, start in enumerate(range(0, len(clipped), chunk_chars)):
        content = clipped[start : start + chunk_chars]
        result.append(
            {
                "ordinal": ordinal,
                "content": content,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    return result


def process_worker_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("version") != WORKER_CONTRACT_VERSION:
        raise ValueError("unsupported worker contract version")
    attachment_id = str(request.get("attachmentId") or "")
    if not attachment_id:
        raise ValueError("attachmentId is required")
    allowed_root = Path(str(request.get("allowedRoot") or ""))
    candidate = Path(str(request.get("path") or ""))
    path = _resolved_under(allowed_root, candidate)
    if not path.is_file():
        raise ValueError("attachment file does not exist")

    category = str(request.get("category") or "")
    analysis_mode = str(request.get("analysisMode") or "")
    if analysis_mode not in {"extract", "metadata"}:
        raise ValueError("invalid analysisMode")
    chunk_chars = max(500, min(int(request.get("chunkChars") or 4000), 8000))
    max_chars = max(
        chunk_chars,
        min(int(request.get("maxOutputChars") or DEFAULT_MAX_OUTPUT_CHARS), 250_000),
    )
    metadata: dict[str, Any] = {
        "sizeBytes": path.stat().st_size,
        "sha256": _sha256_path(path),
        "extension": path.suffix.lower(),
        "mimeType": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "analysisMode": analysis_mode,
        "contentExtracted": False,
        "contentKind": "unavailable" if analysis_mode == "extract" else "metadata_only",
        "extractionMethod": None if analysis_mode == "extract" else "metadata_only",
        "semanticStatus": "pending" if analysis_mode == "extract" else "not_required",
    }
    metadata.update(_media_metadata(path, category))

    if category == "zip":
        manifest = validate_zip_archive(path, limits=request.get("zipLimits"))
        metadata["zip"] = manifest
        text, extracted_members = _extract_zip_text(path, manifest)
        metadata["extractedTextMemberCount"] = extracted_members
        metadata["extractionMethod"] = "safe_zip_text"
        if extracted_members <= 0:
            metadata["semanticStatus"] = "unavailable"
            raise AttachmentExtractionError(
                "no_extractable_content",
                "ZIP contains no safely extractable text members",
                metadata=metadata,
            )
        metadata["contentExtracted"] = True
        metadata["contentKind"] = "extracted_text"
        metadata["semanticStatus"] = "available"
    elif analysis_mode == "metadata":
        if category == "apk":
            manifest = validate_zip_archive(path, limits=request.get("zipLimits"))
            metadata["apkManifest"] = {
                "memberCount": manifest["memberCount"],
                "totalUncompressedBytes": manifest["totalUncompressedBytes"],
                "entries": manifest["entries"][:200],
                "truncated": len(manifest["entries"]) > 200,
            }
            metadata["extractionMethod"] = "safe_apk_manifest"
        elif category == "archive":
            archive_limits = request.get("archiveLimits") or request.get("zipLimits")
            try:
                if path.suffix.lower() == ".7z":
                    manifest = validate_7z_archive(path, limits=archive_limits)
                elif path.suffix.lower() == ".rar":
                    manifest = validate_rar_archive(path, limits=archive_limits)
                else:
                    raise ArchiveSafetyError(
                        "unsupported_archive",
                        "archive format is unsupported",
                    )
            except ArchiveSafetyError as exc:
                metadata["extractionMethod"] = "safe_archive_manifest"
                raise AttachmentExtractionError(
                    exc.code,
                    str(exc),
                    metadata=metadata,
                ) from None
            metadata["archiveManifest"] = {
                "memberCount": manifest["memberCount"],
                "totalUncompressedBytes": manifest["totalUncompressedBytes"],
                "totalCompressedBytes": manifest["totalCompressedBytes"],
                "compressionRatio": manifest["compressionRatio"],
                "entries": manifest["entries"][:200],
                "truncated": len(manifest["entries"]) > 200,
            }
            metadata["extractionMethod"] = "safe_archive_manifest"
        text = _metadata_text(path, metadata)
    elif category in {"text", "code"}:
        text = _decode_text(path.read_bytes())
        metadata["extractionMethod"] = "direct_text"
        if not text.strip():
            metadata["semanticStatus"] = "unavailable"
            raise AttachmentExtractionError(
                "no_extractable_content",
                "text attachment contains no extractable content",
                metadata=metadata,
            )
        metadata["contentExtracted"] = True
        metadata["contentKind"] = "extracted_text"
        metadata["semanticStatus"] = "available"
    elif category == "document":
        text = _extract_with_markitdown(path)
        metadata["extractionMethod"] = "markitdown"
        if not text:
            metadata["semanticStatus"] = "unavailable"
            raise AttachmentExtractionError(
                "semantic_extraction_unavailable",
                "semantic extraction produced no content",
                metadata=metadata,
            )
        metadata["contentExtracted"] = True
        metadata["contentKind"] = "extracted_text"
        metadata["semanticStatus"] = "available"
    else:
        metadata["extractionMethod"] = "offline_semantic_extractor_unavailable"
        metadata["semanticStatus"] = "unavailable"
        raise AttachmentExtractionError(
            "semantic_extraction_unavailable",
            f"offline semantic extraction is unavailable for {category or 'this type'}",
            metadata=metadata,
        )

    return {
        "version": WORKER_CONTRACT_VERSION,
        "attachmentId": attachment_id,
        "status": "ready",
        "chunks": _chunks(text, chunk_chars, max_chars),
        "metadata": metadata,
        "truncated": len(text) > max_chars,
        "pythonVersion": ".".join(map(str, sys.version_info[:3])),
    }


def worker_error_response(
    attachment_id: str,
    exc: Exception,
) -> dict[str, Any]:
    code = str(getattr(exc, "code", "worker_failed") or "worker_failed")
    metadata = getattr(exc, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "version": WORKER_CONTRACT_VERSION,
        "attachmentId": attachment_id,
        "status": "failed",
        "chunks": [],
        "metadata": metadata,
        "error": {"code": code, "message": str(exc)[:500]},
        "pythonVersion": ".".join(map(str, sys.version_info[:3])),
    }

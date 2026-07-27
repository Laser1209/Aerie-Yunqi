from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from core.attachment_worker_runtime import DEFAULT_ARCHIVE_LIMITS, DEFAULT_ZIP_LIMITS
from core.ids import generate_id


ATTACHMENT_STATES = (
    "queued",
    "processing",
    "ready",
    "failed",
    "quarantined",
    "unsupported",
)
MAX_FILE_BYTES = 20 * 1024 * 1024
SAFE_NAME_RE = re.compile(r"[^\w .()\[\]-]+", re.UNICODE)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?<![\w])(?:[a-z]:[\\/]|\\\\)[^\r\n\"'<>|?*,;)\]]+"
)
FILE_URI_RE = re.compile(r"(?i)file:/+[^\r\n\"'<>|?*,;)\]]+")
SENSITIVE_METADATA_KEY_SUFFIXES = (
    "path",
    "root",
    "directory",
    "cwd",
    "executable",
)


def _is_sensitive_metadata_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z]", "", str(value or "").lower())
    return bool(normalized) and normalized.endswith(SENSITIVE_METADATA_KEY_SUFFIXES)


def _redact_local_paths(value: Any, *, roots: Sequence[Path] = ()) -> str:
    text = str(value or "")
    for root in roots:
        rendered = str(root.resolve())
        for variant in {rendered, rendered.replace("\\", "/")}:
            if variant:
                text = text.replace(variant, "[redacted-path]")
    text = FILE_URI_RE.sub("[redacted-path]", text)
    return WINDOWS_ABSOLUTE_PATH_RE.sub("[redacted-path]", text)


def _sanitize_public_metadata(value: Any, *, roots: Sequence[Path]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_public_metadata(nested, roots=roots)
            for key, nested in value.items()
            if not _is_sensitive_metadata_key(key)
        }
    if isinstance(value, list):
        return [
            _sanitize_public_metadata(nested, roots=roots)
            for nested in value
        ]
    if isinstance(value, tuple):
        return [
            _sanitize_public_metadata(nested, roots=roots)
            for nested in value
        ]
    if isinstance(value, str):
        return _redact_local_paths(value, roots=roots)
    return value


@dataclass(frozen=True)
class AttachmentCapability:
    category: str
    extensions: tuple[str, ...]
    analysis_mode: str
    description: str


CAPABILITIES: tuple[AttachmentCapability, ...] = (
    AttachmentCapability(
        "document",
        ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "rtf", "epub"),
        "extract",
        "Document text extraction",
    ),
    AttachmentCapability(
        "text",
        ("txt", "md", "markdown", "csv", "tsv", "json", "xml", "html", "htm"),
        "extract",
        "Text and structured text extraction",
    ),
    AttachmentCapability(
        "code",
        (
            "py", "js", "ts", "tsx", "jsx", "css", "sql", "yaml", "yml",
            "toml", "ini", "log", "sh", "ps1", "java", "c", "cpp", "h",
            "hpp", "go", "rs",
        ),
        "extract",
        "Source code extraction",
    ),
    AttachmentCapability(
        "image",
        ("jpg", "jpeg", "png", "gif", "webp"),
        "extract",
        "Image metadata; semantic extraction fails closed when unavailable",
    ),
    AttachmentCapability(
        "audio",
        ("mp3", "wav", "m4a", "opus", "ogg", "flac"),
        "extract",
        "Audio metadata; transcription fails closed when unavailable",
    ),
    AttachmentCapability(
        "video",
        ("mp4", "mov", "avi", "mkv", "webm"),
        "extract",
        "Video metadata; transcription fails closed when unavailable",
    ),
    AttachmentCapability(
        "zip",
        ("zip",),
        "extract",
        "Safe manifest and text-member extraction",
    ),
    AttachmentCapability(
        "archive",
        ("rar", "7z"),
        "metadata",
        "Metadata only; archive is never extracted",
    ),
    AttachmentCapability(
        "executable",
        ("exe",),
        "metadata",
        "Metadata only; executable is never run",
    ),
    AttachmentCapability(
        "apk",
        ("apk",),
        "metadata",
        "Safe package manifest only; APK is never run",
    ),
)
CAPABILITY_BY_EXTENSION = {
    extension: capability
    for capability in CAPABILITIES
    for extension in capability.extensions
}


def attachment_capabilities_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "states": list(ATTACHMENT_STATES),
        "maxFileBytes": MAX_FILE_BYTES,
        "uploadEndpoint": "/api/attachments",
        "statusEndpointTemplate": "/api/attachments/{attachmentId}",
        "retryEndpointTemplate": "/api/attachments/{attachmentId}/retry",
        "removeEndpointTemplate": "/api/attachments/{attachmentId}",
        "downloadEndpointTemplate": "/api/attachments/{attachmentId}/download",
        "capabilities": [
            {
                "category": capability.category,
                "extensions": list(capability.extensions),
                "analysisMode": capability.analysis_mode,
                "readyRequiresContentExtracted": capability.analysis_mode == "extract",
                "contentExtractionAvailable": capability.category
                not in {"image", "audio", "video", "archive", "executable", "apk"},
                "semanticStatus": "unavailable"
                if capability.category in {"image", "audio", "video"}
                else (
                    "available"
                    if capability.analysis_mode == "extract"
                    else "not_required"
                ),
                "description": capability.description,
            }
            for capability in CAPABILITIES
        ],
    }


class AttachmentStateConflict(RuntimeError):
    pass


class AttachmentWorkerError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
        python_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = dict(metadata or {})
        self.python_version = str(python_version or "")


class DesktopDefenderScanner:
    """Desktop-owned Defender adapter; it shares no mobile storage state."""

    def __init__(
        self,
        *,
        executable: str | Path | None = None,
        timeout_seconds: int = 120,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.executable = (
            Path(executable).expanduser() if executable is not None else self._locate()
        )
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    @staticmethod
    def _locate() -> Path | None:
        candidates: list[Path] = []
        program_files = os.getenv("ProgramFiles")
        if program_files:
            candidates.append(Path(program_files) / "Windows Defender" / "MpCmdRun.exe")
        program_data = os.getenv("ProgramData")
        if program_data:
            platform = Path(program_data) / "Microsoft" / "Windows Defender" / "Platform"
            if platform.is_dir():
                candidates.extend(sorted(platform.glob("*/MpCmdRun.exe"), reverse=True))
        located = shutil.which("MpCmdRun.exe")
        if located:
            candidates.append(Path(located))
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    def scan(self, path: str | Path) -> bool:
        target = Path(path).resolve()
        executable = self.executable
        if executable is None or not executable.is_file() or not target.is_file():
            return False
        try:
            result = self.runner(
                [
                    str(executable), "-Scan", "-ScanType", "3", "-File",
                    str(target), "-DisableRemediation",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return getattr(result, "returncode", None) == 0


class AttachmentWorkerClient:
    def __init__(
        self,
        *,
        python_command: Sequence[str] | None = None,
        worker_path: str | Path | None = None,
        timeout_seconds: int = 180,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.python_command = list(python_command or self._discover_python312())
        self.worker_path = Path(worker_path or (
            Path(__file__).resolve().parent.parent / "tools" / "attachment_worker" / "worker.py"
        )).resolve()
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    @staticmethod
    def _discover_python312() -> list[str]:
        configured = os.getenv("AERIE_ATTACHMENT_PYTHON", "").strip()
        if configured:
            candidate = Path(configured).expanduser()
            if candidate.is_file():
                return [str(candidate)]
            raise AttachmentWorkerError(
                "worker_python_missing",
                "AERIE_ATTACHMENT_PYTHON does not point to a file",
            )
        project_python = (
            Path(__file__).resolve().parent.parent
            / ".venv-attachments"
            / "Scripts"
            / "python.exe"
        )
        if project_python.is_file():
            return [str(project_python)]
        launcher = shutil.which("py") or shutil.which("py.exe")
        if launcher:
            try:
                inventory = subprocess.run(
                    [launcher, "-0p"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=False,
                    check=False,
                )
                for line in str(inventory.stdout or "").splitlines():
                    if "3.12" not in line:
                        continue
                    match = re.search(r"([A-Za-z]:\\.*python\.exe)\s*$", line, re.I)
                    if match and Path(match.group(1)).is_file():
                        return [match.group(1)]
            except (OSError, subprocess.SubprocessError):
                pass
        raise AttachmentWorkerError(
            "worker_python_missing",
            "isolated Python 3.12 is unavailable",
        )

    def process(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.runner(
                [*self.python_command, str(self.worker_path)],
                input=json.dumps(request, ensure_ascii=False) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AttachmentWorkerError("worker_unavailable", str(exc)) from exc
        raw = str(getattr(result, "stdout", "") or "").strip().splitlines()
        if not raw:
            raise AttachmentWorkerError("worker_protocol_error", "worker returned no response")
        try:
            response = json.loads(raw[-1])
        except json.JSONDecodeError:
            raise AttachmentWorkerError(
                "worker_protocol_error",
                "worker returned invalid JSON",
            ) from None
        if response.get("version") != 1 or response.get("attachmentId") != request["attachmentId"]:
            raise AttachmentWorkerError("worker_protocol_error", "worker response identity mismatch")
        if not str(response.get("pythonVersion") or "").startswith("3.12."):
            raise AttachmentWorkerError(
                "worker_python_version",
                "attachment worker must run on Python 3.12",
            )
        if response.get("status") != "ready":
            error = response.get("error") or {}
            raise AttachmentWorkerError(
                str(error.get("code") or "worker_failed"),
                str(error.get("message") or "attachment worker failed"),
                metadata=response.get("metadata")
                if isinstance(response.get("metadata"), dict)
                else None,
                python_version=str(response.get("pythonVersion") or ""),
            )
        return response


class DesktopAttachmentRepository:
    _TRANSITIONS = {
        "queued": {"processing", "unsupported", "quarantined", "failed"},
        "processing": {"ready", "failed", "quarantined"},
        "failed": {"queued"},
        "ready": set(),
        "quarantined": set(),
        "unsupported": set(),
    }

    def __init__(self, database: Any) -> None:
        self.database = database

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if isinstance(self.database, sqlite3.Connection):
            yield self.database
            return
        with self.database.connection() as conn:
            yield conn

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO desktop_attachments
                   (attachment_id, conversation_id, message_id, original_name,
                    stored_name, storage_relpath, category, extension,
                    mime_type, size_bytes, sha256, state, analysis_mode,
                    metadata_json, error_code, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["attachment_id"], record.get("conversation_id"),
                    record.get("message_id"), record["original_name"],
                    record["stored_name"], record["storage_relpath"],
                    record["category"], record["extension"],
                    record.get("mime_type") or "application/octet-stream",
                    int(record["size_bytes"]), record["sha256"], record["state"],
                    record["analysis_mode"],
                    json.dumps(record.get("metadata") or {}, ensure_ascii=False),
                    record.get("error_code"), record.get("error_message"),
                ),
            )
        result = self.get(record["attachment_id"])
        if result is None:
            raise RuntimeError("attachment insert failed")
        return result

    def get(self, attachment_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM desktop_attachments WHERE attachment_id = ?",
                (attachment_id,),
            ).fetchone()
        return self._decode_row(row) if row is not None else None

    def list_for_message(self, message_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT * FROM desktop_attachments
                   WHERE message_id = ? ORDER BY created_at, attachment_id""",
                (message_id,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def transition(
        self,
        attachment_id: str,
        target_state: str,
        *,
        metadata: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        storage_relpath: str | None = None,
        stored_name: str | None = None,
    ) -> dict[str, Any]:
        if target_state not in ATTACHMENT_STATES:
            raise ValueError("invalid attachment state")
        with self._connection() as conn:
            current = conn.execute(
                "SELECT state FROM desktop_attachments WHERE attachment_id = ?",
                (attachment_id,),
            ).fetchone()
            if current is None:
                raise KeyError(attachment_id)
            current_state = str(current["state"])
            if target_state not in self._TRANSITIONS[current_state]:
                raise AttachmentStateConflict(
                    f"cannot transition {current_state} to {target_state}"
                )
            fields = [
                "state = ?",
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                "error_code = ?",
                "error_message = ?",
            ]
            params: list[Any] = [target_state, error_code, error_message]
            if metadata is not None:
                fields.append("metadata_json = ?")
                params.append(json.dumps(metadata, ensure_ascii=False))
            if storage_relpath is not None:
                fields.append("storage_relpath = ?")
                params.append(storage_relpath)
            if stored_name is not None:
                fields.append("stored_name = ?")
                params.append(stored_name)
            if target_state == "ready":
                fields.append("ready_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
            params.extend([attachment_id, current_state])
            updated = conn.execute(
                f"UPDATE desktop_attachments SET {', '.join(fields)} "
                "WHERE attachment_id = ? AND state = ?",
                tuple(params),
            ).rowcount
            if updated != 1:
                raise AttachmentStateConflict("attachment changed concurrently")
        result = self.get(attachment_id)
        if result is None:
            raise KeyError(attachment_id)
        return result

    def replace_chunks(
        self,
        attachment_id: str,
        chunks: Sequence[dict[str, Any]],
    ) -> None:
        with self._connection() as conn:
            conn.execute("SAVEPOINT replace_attachment_chunks")
            try:
                conn.execute(
                    "DELETE FROM desktop_attachment_chunks WHERE attachment_id = ?",
                    (attachment_id,),
                )
                for ordinal, item in enumerate(chunks):
                    content = str(item.get("content") or "")
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    supplied = item.get("sha256")
                    if supplied and supplied != digest:
                        raise ValueError("attachment chunk checksum mismatch")
                    conn.execute(
                        """INSERT INTO desktop_attachment_chunks
                           (attachment_id, ordinal, content, char_count, sha256)
                           VALUES (?, ?, ?, ?, ?)""",
                        (attachment_id, ordinal, content, len(content), digest),
                    )
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT replace_attachment_chunks")
                conn.execute("RELEASE SAVEPOINT replace_attachment_chunks")
                raise
            conn.execute("RELEASE SAVEPOINT replace_attachment_chunks")

    def chunks(self, attachment_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT ordinal, content, char_count, sha256
                   FROM desktop_attachment_chunks
                   WHERE attachment_id = ? ORDER BY ordinal LIMIT ?""",
                (attachment_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def bind_message(
        self,
        attachment_ids: Sequence[str],
        *,
        message_id: str,
        conversation_id: str | None,
    ) -> None:
        unique = list(dict.fromkeys(str(value) for value in attachment_ids if value))
        if not unique:
            return
        with self._connection() as conn:
            placeholders = ",".join("?" for _ in unique)
            rows = conn.execute(
                f"SELECT attachment_id, state, message_id FROM desktop_attachments "
                f"WHERE attachment_id IN ({placeholders})",
                tuple(unique),
            ).fetchall()
            if len(rows) != len(unique):
                raise KeyError("one or more attachments do not exist")
            if any(row["state"] != "ready" for row in rows):
                raise AttachmentStateConflict("only ready attachments can be bound")
            if any(row["message_id"] not in {None, message_id} for row in rows):
                raise AttachmentStateConflict("attachment is already bound")
            conn.execute("SAVEPOINT bind_desktop_attachments")
            try:
                conn.executemany(
                    """UPDATE desktop_attachments
                       SET message_id = ?, conversation_id = ?,
                           updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                       WHERE attachment_id = ? AND state = 'ready'""",
                    [(message_id, conversation_id, value) for value in unique],
                )
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT bind_desktop_attachments")
                conn.execute("RELEASE SAVEPOINT bind_desktop_attachments")
                raise
            conn.execute("RELEASE SAVEPOINT bind_desktop_attachments")

    def delete_unbound(self, attachment_id: str) -> bool:
        with self._connection() as conn:
            deleted = conn.execute(
                """DELETE FROM desktop_attachments
                   WHERE attachment_id = ?
                     AND message_id IS NULL
                     AND state != 'processing'""",
                (attachment_id,),
            ).rowcount
        return deleted == 1

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        try:
            metadata = json.loads(result.pop("metadata_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        result["metadata"] = metadata if isinstance(metadata, dict) else {}
        return result


class DesktopAttachmentService:
    def __init__(
        self,
        database: Any,
        *,
        storage_root: str | Path,
        scanner: Any | None = None,
        worker: Any | None = None,
    ) -> None:
        self.repository = DesktopAttachmentRepository(database)
        self.storage_root = Path(storage_root).resolve()
        self.quarantine_root = self.storage_root / "quarantine"
        self.ready_root = self.storage_root / "ready"
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        self.ready_root.mkdir(parents=True, exist_ok=True)
        self.scanner = scanner or DesktopDefenderScanner()
        self.worker = worker

    def ingest(
        self,
        source_path: str | Path,
        *,
        original_name: str,
        mime_type: str = "application/octet-stream",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        source = Path(source_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        safe_name = self._safe_original_name(original_name)
        extension = Path(safe_name).suffix.lower().lstrip(".")
        capability = CAPABILITY_BY_EXTENSION.get(extension)
        attachment_id = generate_id("att")
        stored_name = attachment_id + (f".{extension}" if extension else "")
        target = self.quarantine_root / stored_name
        partial = target.with_suffix(target.suffix + ".part")
        shutil.copyfile(source, partial)
        partial.replace(target)
        size = target.stat().st_size
        digest = self._sha256(target)

        state = "queued"
        error_code = None
        error_message = None
        if capability is None:
            state = "unsupported"
            error_code = "unsupported_type"
            error_message = "file extension is not supported"
            category = "unknown"
            analysis_mode = "metadata"
        else:
            category = capability.category
            analysis_mode = capability.analysis_mode
            signature_error = self._signature_error(target, extension, category)
            if size > MAX_FILE_BYTES:
                state = "unsupported"
                error_code = "file_too_large"
                error_message = f"file exceeds {MAX_FILE_BYTES} bytes"
            elif signature_error:
                state = "quarantined"
                error_code = "signature_mismatch"
                error_message = signature_error

        return self.repository.create(
            {
                "attachment_id": attachment_id,
                "conversation_id": conversation_id,
                "message_id": None,
                "original_name": safe_name,
                "stored_name": stored_name,
                "storage_relpath": target.relative_to(self.storage_root).as_posix(),
                "category": category,
                "extension": extension,
                "mime_type": mime_type,
                "size_bytes": size,
                "sha256": digest,
                "state": state,
                "analysis_mode": analysis_mode,
                "metadata": {"originalMimeType": mime_type},
                "error_code": error_code,
                "error_message": error_message,
            }
        )

    def process(self, attachment_id: str) -> dict[str, Any]:
        record = self.repository.get(attachment_id)
        if record is None:
            raise KeyError(attachment_id)
        if record["state"] != "queued":
            raise AttachmentStateConflict("only queued attachments can be processed")
        record = self.repository.transition(attachment_id, "processing")
        path = self._record_path(record)
        if not self.scanner.scan(path):
            return self.repository.transition(
                attachment_id,
                "quarantined",
                error_code="scan_failed_or_unavailable",
                error_message="Defender did not return a clean result",
            )

        ready_path = self.ready_root / record["stored_name"]
        path.replace(ready_path)
        ready_relpath = ready_path.relative_to(self.storage_root).as_posix()
        try:
            if self.worker is None:
                self.worker = AttachmentWorkerClient()
            response = self.worker.process(
                {
                    "version": 1,
                    "attachmentId": attachment_id,
                    "path": str(ready_path),
                    "allowedRoot": str(self.storage_root),
                    "category": record["category"],
                    "analysisMode": record["analysis_mode"],
                    "chunkChars": 4000,
                    "maxOutputChars": 120000,
                    "zipLimits": DEFAULT_ZIP_LIMITS,
                    "archiveLimits": DEFAULT_ARCHIVE_LIMITS,
                }
            )
            chunks = response.get("chunks") or []
            worker_metadata = dict(response.get("metadata") or {})
            if record["analysis_mode"] == "extract" and (
                worker_metadata.get("contentExtracted") is not True or not chunks
            ):
                worker_metadata["contentExtracted"] = False
                worker_metadata["contentKind"] = "unavailable"
                worker_metadata["semanticStatus"] = "unavailable"
                raise AttachmentWorkerError(
                    "semantic_extraction_unavailable",
                    "extract-mode worker returned no verified content",
                    metadata=worker_metadata,
                    python_version=response.get("pythonVersion"),
                )
            if record["analysis_mode"] == "metadata":
                if worker_metadata.get("contentExtracted") is True:
                    raise AttachmentWorkerError(
                        "worker_contract_violation",
                        "metadata-only worker reported extracted content",
                        metadata={
                            **worker_metadata,
                            "contentExtracted": False,
                            "contentKind": "metadata_only",
                            "semanticStatus": "not_required",
                        },
                        python_version=response.get("pythonVersion"),
                    )
                worker_metadata["contentExtracted"] = False
                worker_metadata["contentKind"] = "metadata_only"
                worker_metadata["semanticStatus"] = "not_required"
            self.repository.replace_chunks(attachment_id, chunks)
            metadata = dict(record.get("metadata") or {})
            metadata.update(worker_metadata)
            metadata["workerPythonVersion"] = response.get("pythonVersion")
            metadata["truncated"] = bool(response.get("truncated"))
            return self.repository.transition(
                attachment_id,
                "ready",
                metadata=metadata,
                storage_relpath=ready_relpath,
                stored_name=ready_path.name,
            )
        except AttachmentWorkerError as exc:
            metadata = dict(record.get("metadata") or {})
            metadata.update(exc.metadata)
            if exc.python_version:
                metadata["workerPythonVersion"] = exc.python_version
            return self.repository.transition(
                attachment_id,
                "failed",
                metadata=metadata,
                error_code=exc.code,
                error_message=str(exc)[:500],
                storage_relpath=ready_relpath,
                stored_name=ready_path.name,
            )
        except Exception as exc:
            return self.repository.transition(
                attachment_id,
                "failed",
                error_code="processing_failed",
                error_message=str(exc)[:500],
                storage_relpath=ready_relpath,
                stored_name=ready_path.name,
            )

    def retry(self, attachment_id: str) -> dict[str, Any]:
        self.repository.transition(attachment_id, "queued")
        return self.process(attachment_id)

    def remove(self, attachment_id: str) -> bool:
        record = self.repository.get(attachment_id)
        if record is None:
            return False
        if record.get("message_id") is not None or record["state"] == "processing":
            raise AttachmentStateConflict("bound or processing attachment cannot be removed")
        try:
            path = self._record_path(record)
        except AttachmentStateConflict:
            path = None
        if not self.repository.delete_unbound(attachment_id):
            raise AttachmentStateConflict("attachment changed concurrently")
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass
        return True

    def public_record(self, attachment_id: str) -> dict[str, Any] | None:
        record = self.repository.get(attachment_id)
        return self._public(record) if record else None

    def public_records(self, attachment_ids: Sequence[str]) -> list[dict[str, Any]]:
        result = []
        for attachment_id in dict.fromkeys(attachment_ids):
            record = self.public_record(str(attachment_id))
            if record is not None:
                result.append(record)
        return result

    def resolve_ready_for_send(
        self,
        attachment_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        """Resolve unbound, ready attachments using server-owned metadata.

        Renderer metadata is never trusted on the send path.  Keeping this
        check next to the repository also lets both the request service and
        the pipeline enforce the same state contract without exposing local
        storage paths.
        """
        ordered: list[str] = []
        seen: set[str] = set()
        for value in attachment_ids:
            attachment_id = str(value or "").strip()
            if not attachment_id or attachment_id in seen:
                raise ValueError("attachment ids must be non-empty and unique")
            seen.add(attachment_id)
            ordered.append(attachment_id)

        resolved: list[dict[str, Any]] = []
        for attachment_id in ordered:
            record = self.repository.get(attachment_id)
            if record is None:
                raise KeyError(attachment_id)
            if record["state"] != "ready":
                raise AttachmentStateConflict("attachment is not ready")
            metadata = record.get("metadata") or {}
            if (
                record["analysis_mode"] == "extract"
                and metadata.get("contentExtracted") is not True
            ):
                raise AttachmentStateConflict(
                    "attachment has no verified extracted content"
                )
            if record.get("message_id") is not None:
                raise AttachmentStateConflict("attachment is already bound")
            resolved.append(self._public(record))
        return resolved

    def bind_message(
        self,
        attachment_ids: Sequence[str],
        *,
        message_id: str,
        conversation_id: str | None,
    ) -> None:
        self.repository.bind_message(
            attachment_ids,
            message_id=message_id,
            conversation_id=conversation_id,
        )

    def context_snippets(
        self,
        attachment_ids: Sequence[str],
        *,
        max_chars: int = 4000,
    ) -> list[str]:
        remaining = max(0, int(max_chars))
        snippets: list[str] = []
        for attachment_id in dict.fromkeys(str(value) for value in attachment_ids):
            record = self.repository.get(attachment_id)
            if not record or record["state"] != "ready":
                continue
            for chunk in self.repository.chunks(attachment_id):
                if remaining <= 0:
                    return snippets
                content = str(chunk["content"] or "")[:remaining]
                if content:
                    safe_content = _redact_local_paths(
                        content,
                        roots=(self.storage_root,),
                    )
                    snippets.append(f"[{record['original_name']}] {safe_content}")
                    remaining -= len(safe_content)
        return snippets

    def download_path(self, attachment_id: str) -> tuple[Path, str]:
        record = self.repository.get(attachment_id)
        if record is None:
            raise KeyError(attachment_id)
        if record["state"] != "ready":
            raise AttachmentStateConflict("attachment is not ready")
        return self._record_path(record), record["original_name"]

    def _record_path(self, record: dict[str, Any]) -> Path:
        candidate = (self.storage_root / record["storage_relpath"]).resolve()
        try:
            candidate.relative_to(self.storage_root)
        except ValueError:
            raise AttachmentStateConflict("attachment path escaped storage root") from None
        if not candidate.is_file():
            raise AttachmentStateConflict("attachment file is missing")
        return candidate

    def _public(self, record: dict[str, Any]) -> dict[str, Any]:
        attachment_id = record["attachment_id"]
        metadata = _sanitize_public_metadata(
            record.get("metadata") or {},
            roots=(self.storage_root,),
        )
        content_extracted = metadata.get("contentExtracted") is True
        semantic_status = metadata.get("semanticStatus")
        if semantic_status not in {"pending", "available", "unavailable", "not_required"}:
            if record["analysis_mode"] == "metadata":
                semantic_status = "not_required"
            elif record["state"] in {"queued", "processing"}:
                semantic_status = "pending"
            else:
                semantic_status = "unavailable"
        return {
            "id": attachment_id,
            "attachmentId": attachment_id,
            "name": record["original_name"],
            "size": int(record["size_bytes"]),
            "category": record["category"],
            "type": record["category"],
            "extension": record["extension"],
            "contentType": record["mime_type"],
            "sha256": record["sha256"],
            "state": record["state"],
            "analysisMode": record["analysis_mode"],
            "contentExtracted": content_extracted,
            "semanticStatus": semantic_status,
            "metadata": metadata,
            "error": (
                {
                    "code": record["error_code"],
                    "message": _redact_local_paths(
                        record["error_message"] or "",
                        roots=(self.storage_root,),
                    ),
                }
                if record.get("error_code")
                else None
            ),
            "downloadUrl": f"/api/attachments/{attachment_id}/download"
            if record["state"] == "ready"
            else None,
            "createdAt": record["created_at"],
            "updatedAt": record["updated_at"],
        }

    @staticmethod
    def _safe_original_name(value: str) -> str:
        name = Path(str(value or "")).name.strip().strip(".")
        name = SAFE_NAME_RE.sub("_", name)[:180]
        if not name or any(ord(character) < 32 for character in name):
            raise ValueError("invalid attachment filename")
        return name

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _signature_error(path: Path, extension: str, category: str) -> str | None:
        with path.open("rb") as stream:
            head = stream.read(16)
        if category in {"text", "code"} and b"\x00" in head:
            return "text-like file contains binary null bytes"
        signatures = {
            "pdf": (b"%PDF-",),
            "zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            "apk": (b"PK\x03\x04",),
            "exe": (b"MZ",),
            "rar": (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"),
            "7z": (b"7z\xbc\xaf'\x1c",),
            "png": (b"\x89PNG\r\n\x1a\n",),
            "jpg": (b"\xff\xd8\xff",),
            "jpeg": (b"\xff\xd8\xff",),
            "gif": (b"GIF87a", b"GIF89a"),
            "webp": (b"RIFF",),
            "docx": (b"PK\x03\x04",),
            "xlsx": (b"PK\x03\x04",),
            "pptx": (b"PK\x03\x04",),
            "epub": (b"PK\x03\x04",),
            "doc": (b"\xd0\xcf\x11\xe0",),
            "xls": (b"\xd0\xcf\x11\xe0",),
            "ppt": (b"\xd0\xcf\x11\xe0",),
        }
        expected = signatures.get(extension)
        if expected and not any(head.startswith(signature) for signature in expected):
            return f"file signature does not match .{extension}"
        if extension == "webp" and (len(head) < 12 or head[8:12] != b"WEBP"):
            return "file signature does not match .webp"
        return None

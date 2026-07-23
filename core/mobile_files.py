"""Account-scoped file storage for the isolated mobile gateway."""

from __future__ import annotations

import codecs
import hashlib
import math
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from core.mobile_identity import MobilePrincipal


PART_SIZE = 4 * 1024 * 1024
MAX_FILE_SIZE = 50 * 1024 * 1024
UPLOAD_LIFETIME = timedelta(hours=24)
MAX_ACTIVE_UPLOADS = 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ASCII_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

_MIME_BY_EXTENSION = {
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".gif": {"image/gif"},
    ".webp": {"image/webp"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".csv": {"text/csv"},
    ".json": {"application/json"},
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    },
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    },
    ".zip": {"application/zip"},
}


class MobileFileError(Exception):
    def __init__(
        self,
        code: str,
        *,
        status_code: int = 400,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.headers = dict(headers or {})


@dataclass(frozen=True)
class DownloadSpec:
    path: Path
    file_name: str
    mime_type: str
    sha256: str
    total_size: int
    start: int
    end: int
    partial: bool

    @property
    def content_length(self) -> int:
        if self.total_size == 0:
            return 0
        return self.end - self.start + 1

    @property
    def content_disposition(self) -> str:
        fallback = _SAFE_ASCII_NAME_RE.sub("_", self.file_name).strip("._")
        if not fallback:
            fallback = "download"
        fallback = fallback[:120]
        encoded = quote(self.file_name, safe="")
        return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


class WindowsDefenderScanner:
    """Invoke MpCmdRun without a shell and fail closed on every uncertainty."""

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
            candidates.append(
                Path(program_files) / "Windows Defender" / "MpCmdRun.exe"
            )
        program_data = os.getenv("ProgramData")
        if program_data:
            platform = (
                Path(program_data)
                / "Microsoft"
                / "Windows Defender"
                / "Platform"
            )
            if platform.is_dir():
                candidates.extend(
                    sorted(
                        platform.glob("*/MpCmdRun.exe"),
                        reverse=True,
                    )
                )
        located = shutil.which("MpCmdRun.exe")
        if located:
            candidates.append(Path(located))
        return next((path for path in candidates if path.is_file()), None)

    def scan(self, path: str | Path) -> bool:
        target = Path(path).resolve()
        executable = self.executable
        if executable is None or not executable.is_file() or not target.is_file():
            return False
        command = [
            str(executable),
            "-Scan",
            "-ScanType",
            "3",
            "-File",
            str(target),
            "-DisableRemediation",
        ]
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return getattr(result, "returncode", None) == 0


class MobileFileService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        storage_root: str | Path = "data/mobile_files",
        scanner: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_root = Path(storage_root).resolve()
        self.quarantine_root = self.storage_root / ".quarantine"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        self.scanner = scanner or WindowsDefenderScanner()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_schema(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS mobile_directory_grants (
                grant_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES mobile_accounts(account_id),
                directory_path TEXT NOT NULL,
                allow_read INTEGER NOT NULL DEFAULT 0,
                allow_upload INTEGER NOT NULL DEFAULT 0,
                allow_download INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(account_id, directory_path)
            )""",
            """CREATE TABLE IF NOT EXISTS mobile_uploads (
                upload_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES mobile_accounts(account_id),
                client_upload_id TEXT NOT NULL,
                directory_grant_id TEXT REFERENCES mobile_directory_grants(grant_id),
                file_name TEXT NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                part_size INTEGER NOT NULL,
                part_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                file_id TEXT,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(account_id, client_upload_id)
            )""",
            """CREATE INDEX IF NOT EXISTS mobile_upload_account_status
               ON mobile_uploads(account_id, status, expires_at)""",
            """CREATE TABLE IF NOT EXISTS mobile_upload_parts (
                upload_id TEXT NOT NULL REFERENCES mobile_uploads(upload_id)
                    ON DELETE CASCADE,
                part_number INTEGER NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(upload_id, part_number)
            )""",
            """CREATE TABLE IF NOT EXISTS mobile_files (
                file_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES mobile_accounts(account_id),
                upload_id TEXT UNIQUE REFERENCES mobile_uploads(upload_id),
                directory_grant_id TEXT REFERENCES mobile_directory_grants(grant_id),
                display_name TEXT NOT NULL,
                stored_path TEXT NOT NULL UNIQUE,
                size INTEGER NOT NULL,
                mime_type TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                scan_result TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS mobile_file_account_status
               ON mobile_files(account_id, status, created_at)""",
        )
        with self._lock, self._connect() as conn:
            for statement in statements:
                conn.execute(statement)
            audit_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(mobile_audit)").fetchall()
            }
            if "resource_id" not in audit_columns:
                conn.execute("ALTER TABLE mobile_audit ADD COLUMN resource_id TEXT")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _timestamp(self, value: datetime | None = None) -> str:
        return (value or self._now()).isoformat()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(16)}"

    @staticmethod
    def _normalize_client_id(value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise MobileFileError("invalid_file", status_code=422) from exc

    @staticmethod
    def _normalize_file_name(value: str) -> tuple[str, str]:
        if not isinstance(value, str):
            raise MobileFileError("invalid_file", status_code=422)
        if (
            not value
            or value != value.strip()
            or value in {".", ".."}
            or len(value) > 255
            or "/" in value
            or "\\" in value
            or "\x00" in value
            or any(ord(char) < 32 for char in value)
        ):
            raise MobileFileError("invalid_file", status_code=422)
        extension = Path(value).suffix.lower()
        if extension not in _MIME_BY_EXTENSION:
            raise MobileFileError("file_type_denied", status_code=415)
        return value, extension

    @staticmethod
    def _normalize_mime(extension: str, value: str) -> str:
        if not isinstance(value, str):
            raise MobileFileError("invalid_file", status_code=422)
        normalized = value.strip().lower()
        if normalized not in _MIME_BY_EXTENSION[extension]:
            raise MobileFileError("file_type_denied", status_code=415)
        return normalized

    @staticmethod
    def _normalize_sha256(value: str) -> str:
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise MobileFileError("invalid_file", status_code=422)
        return value

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
        except ValueError:
            return False
        return True

    def _account(self, conn: sqlite3.Connection, account_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT account_id, role FROM mobile_accounts
               WHERE account_id = ? AND enabled = 1""",
            (account_id,),
        ).fetchone()
        if row is None:
            raise MobileFileError("file_not_found", status_code=404)
        return row

    def _audit(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        outcome: str,
        *,
        account_id: str,
        device_id: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        conn.execute(
            """INSERT INTO mobile_audit
               (audit_id, account_id, device_id, event_type, outcome,
                ip_address, created_at, resource_id)
               VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                self._id("audit"),
                account_id,
                device_id,
                event_type,
                outcome,
                self._timestamp(),
                resource_id,
            ),
        )

    def _grant(
        self,
        conn: sqlite3.Connection,
        *,
        account_id: str,
        grant_id: str | None,
        permission: str,
    ) -> sqlite3.Row:
        if not grant_id or permission not in {"read", "upload", "download"}:
            raise MobileFileError("file_not_found", status_code=404)
        row = conn.execute(
            f"""SELECT * FROM mobile_directory_grants
                WHERE grant_id = ? AND account_id = ? AND enabled = 1
                  AND allow_{permission} = 1""",
            (grant_id, account_id),
        ).fetchone()
        if row is None:
            raise MobileFileError("file_not_found", status_code=404)
        return row

    def register_directory_grant(
        self,
        *,
        account_id: str,
        directory: str | Path,
        allow_read: bool,
        allow_upload: bool,
        allow_download: bool,
    ) -> str:
        raw_directory = Path(directory).expanduser()
        if not raw_directory.is_absolute():
            raise ValueError("directory grant must use an absolute path")
        normalized = raw_directory.resolve()
        normalized.mkdir(parents=True, exist_ok=True)
        if not normalized.is_dir():
            raise ValueError("directory grant target must be a directory")
        now = self._timestamp()
        with self._lock, self._connect() as conn:
            account = self._account(conn, account_id)
            if account["role"] != "owner":
                raise MobileFileError("file_not_found", status_code=404)
            existing = conn.execute(
                """SELECT grant_id FROM mobile_directory_grants
                   WHERE account_id = ? AND directory_path = ?""",
                (account_id, str(normalized)),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """UPDATE mobile_directory_grants
                       SET allow_read = ?, allow_upload = ?, allow_download = ?,
                           enabled = 1, updated_at = ? WHERE grant_id = ?""",
                    (
                        int(bool(allow_read)),
                        int(bool(allow_upload)),
                        int(bool(allow_download)),
                        now,
                        existing["grant_id"],
                    ),
                )
                return existing["grant_id"]
            grant_id = self._id("grant")
            conn.execute(
                """INSERT INTO mobile_directory_grants
                   (grant_id, account_id, directory_path, allow_read,
                    allow_upload, allow_download, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    grant_id,
                    account_id,
                    str(normalized),
                    int(bool(allow_read)),
                    int(bool(allow_upload)),
                    int(bool(allow_download)),
                    now,
                    now,
                ),
            )
            return grant_id

    def _quarantine_directory(self, upload_id: str) -> Path:
        path = (self.quarantine_root / upload_id).resolve()
        if path.parent != self.quarantine_root.resolve():
            raise MobileFileError("invalid_file", status_code=422)
        return path

    def _cleanup_quarantine(self, upload_id: str) -> None:
        try:
            path = self._quarantine_directory(upload_id)
        except MobileFileError:
            return
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def _expire_uploads(self, *, account_id: str | None = None) -> None:
        now = self._timestamp()
        clause = " AND account_id = ?" if account_id is not None else ""
        params: tuple[Any, ...] = (now, account_id) if account_id else (now,)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT upload_id FROM mobile_uploads
                   WHERE status = 'uploading' AND expires_at <= ?""" + clause,
                params,
            ).fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE mobile_uploads SET status = 'expired', updated_at = ?
                       WHERE upload_id = ? AND status = 'uploading'""",
                    (now, row["upload_id"]),
                )
        for row in rows:
            self._cleanup_quarantine(row["upload_id"])

    def _upload_response(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        uploaded_parts = [
            int(part["part_number"])
            for part in conn.execute(
                """SELECT part_number FROM mobile_upload_parts
                   WHERE upload_id = ? ORDER BY part_number""",
                (row["upload_id"],),
            ).fetchall()
        ]
        result: dict[str, Any] = {
            "uploadId": row["upload_id"],
            "partSize": int(row["part_size"]),
            "partCount": int(row["part_count"]),
            "uploadedParts": uploaded_parts,
            "expiresAt": row["expires_at"],
            "status": row["status"],
        }
        if row["file_id"]:
            result["fileId"] = row["file_id"]
        return result

    def create_upload(
        self,
        principal: MobilePrincipal,
        *,
        client_upload_id: str,
        file_name: str,
        size: int,
        sha256: str,
        mime_type: str,
        directory_grant_id: str | None,
    ) -> tuple[dict[str, Any], bool]:
        normalized_client_id = self._normalize_client_id(client_upload_id)
        normalized_name, extension = self._normalize_file_name(file_name)
        normalized_mime = self._normalize_mime(extension, mime_type)
        normalized_hash = self._normalize_sha256(sha256)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise MobileFileError("invalid_file", status_code=422)
        if size > MAX_FILE_SIZE:
            raise MobileFileError("file_too_large", status_code=413)
        if principal.role == "guest" and directory_grant_id is not None:
            raise MobileFileError("invalid_file", status_code=422)

        self._expire_uploads(account_id=principal.account_id)
        now = self._now()
        now_text = self._timestamp(now)
        with self._lock, self._connect() as conn:
            self._account(conn, principal.account_id)
            if principal.role == "owner":
                self._grant(
                    conn,
                    account_id=principal.account_id,
                    grant_id=directory_grant_id,
                    permission="upload",
                )
            existing = conn.execute(
                """SELECT * FROM mobile_uploads
                   WHERE account_id = ? AND client_upload_id = ?""",
                (principal.account_id, normalized_client_id),
            ).fetchone()
            if existing is not None:
                expected = (
                    normalized_name,
                    size,
                    normalized_hash,
                    normalized_mime,
                    directory_grant_id,
                )
                actual = (
                    existing["file_name"],
                    int(existing["size"]),
                    existing["sha256"],
                    existing["mime_type"],
                    existing["directory_grant_id"],
                )
                if expected != actual or existing["status"] in {
                    "cancelled",
                    "expired",
                    "failed",
                }:
                    raise MobileFileError("file_conflict", status_code=409)
                return self._upload_response(conn, existing), False

            active = conn.execute(
                """SELECT COUNT(*) FROM mobile_uploads
                   WHERE account_id = ? AND status = 'uploading'""",
                (principal.account_id,),
            ).fetchone()[0]
            if int(active) >= MAX_ACTIVE_UPLOADS:
                raise MobileFileError("rate_limited", status_code=429)

            upload_id = self._id("upload")
            quarantine = self._quarantine_directory(upload_id)
            quarantine.mkdir(parents=True, exist_ok=False)
            part_count = math.ceil(size / PART_SIZE) if size else 0
            try:
                conn.execute(
                    """INSERT INTO mobile_uploads
                       (upload_id, account_id, client_upload_id,
                        directory_grant_id, file_name, size, sha256, mime_type,
                        part_size, part_count, status, file_id, expires_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploading', NULL,
                               ?, ?, ?)""",
                    (
                        upload_id,
                        principal.account_id,
                        normalized_client_id,
                        directory_grant_id,
                        normalized_name,
                        size,
                        normalized_hash,
                        normalized_mime,
                        PART_SIZE,
                        part_count,
                        self._timestamp(now + UPLOAD_LIFETIME),
                        now_text,
                        now_text,
                    ),
                )
                self._audit(
                    conn,
                    "file.upload.created",
                    "success",
                    account_id=principal.account_id,
                    device_id=principal.device_id,
                    resource_id=upload_id,
                )
            except Exception:
                self._cleanup_quarantine(upload_id)
                raise
            row = conn.execute(
                "SELECT * FROM mobile_uploads WHERE upload_id = ?",
                (upload_id,),
            ).fetchone()
            return self._upload_response(conn, row), True

    def _owned_upload(
        self,
        conn: sqlite3.Connection,
        principal: MobilePrincipal,
        upload_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT * FROM mobile_uploads
               WHERE upload_id = ? AND account_id = ?""",
            (upload_id, principal.account_id),
        ).fetchone()
        if row is None or row["status"] in {"cancelled", "expired"}:
            raise MobileFileError("file_not_found", status_code=404)
        return row

    def get_upload(
        self,
        principal: MobilePrincipal,
        upload_id: str,
    ) -> dict[str, Any]:
        self._expire_uploads(account_id=principal.account_id)
        with self._lock, self._connect() as conn:
            row = self._owned_upload(conn, principal, upload_id)
            return self._upload_response(conn, row)

    def put_part(
        self,
        principal: MobilePrincipal,
        upload_id: str,
        part_number: int,
        content: bytes,
        part_sha256: str,
    ) -> None:
        self._expire_uploads(account_id=principal.account_id)
        normalized_hash = self._normalize_sha256(part_sha256)
        if isinstance(part_number, bool) or not isinstance(part_number, int):
            raise MobileFileError("invalid_file", status_code=422)
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != normalized_hash:
            raise MobileFileError("file_conflict", status_code=409)

        with self._lock, self._connect() as conn:
            row = self._owned_upload(conn, principal, upload_id)
            if row["status"] != "uploading":
                raise MobileFileError("file_conflict", status_code=409)
            part_count = int(row["part_count"])
            if not 1 <= part_number <= part_count:
                raise MobileFileError("invalid_file", status_code=422)
            expected_size = (
                PART_SIZE
                if part_number < part_count
                else int(row["size"]) - PART_SIZE * (part_count - 1)
            )
            if len(content) != expected_size:
                raise MobileFileError("file_conflict", status_code=409)
            existing = conn.execute(
                """SELECT size, sha256 FROM mobile_upload_parts
                   WHERE upload_id = ? AND part_number = ?""",
                (upload_id, part_number),
            ).fetchone()
            directory = self._quarantine_directory(upload_id)
            if not directory.is_dir():
                raise MobileFileError("file_conflict", status_code=409)
            target = directory / f"part-{part_number:08d}"
            if existing is not None:
                if (
                    int(existing["size"]) != len(content)
                    or existing["sha256"] != normalized_hash
                ):
                    raise MobileFileError("file_conflict", status_code=409)
                try:
                    stored_size, stored_hash = self._stream_hash(target)
                except OSError:
                    stored_size, stored_hash = -1, ""
                if stored_size == len(content) and stored_hash == normalized_hash:
                    return
            temporary = directory / f".{target.name}.{secrets.token_hex(8)}.tmp"
            try:
                with temporary.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
                if existing is None:
                    conn.execute(
                        """INSERT INTO mobile_upload_parts
                           (upload_id, part_number, size, sha256, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            upload_id,
                            part_number,
                            len(content),
                            normalized_hash,
                            self._timestamp(),
                        ),
                    )
            except Exception:
                temporary.unlink(missing_ok=True)
                if target.exists():
                    target.unlink(missing_ok=True)
                raise

    @staticmethod
    def _validate_text(path: Path) -> bool:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    if b"\x00" in chunk:
                        return False
                    decoder.decode(chunk)
            decoder.decode(b"", final=True)
        except (OSError, UnicodeDecodeError):
            return False
        return True

    @staticmethod
    def _validate_zip(path: Path, extension: str) -> bool:
        try:
            if not zipfile.is_zipfile(path):
                return False
            if extension == ".zip":
                return True
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
            if "[Content_Types].xml" not in names:
                return False
            required_prefix = {
                ".docx": "word/",
                ".xlsx": "xl/",
                ".pptx": "ppt/",
            }[extension]
            return any(name.startswith(required_prefix) for name in names)
        except (OSError, zipfile.BadZipFile, KeyError):
            return False

    def _validate_type(self, path: Path, file_name: str, mime_type: str) -> None:
        _, extension = self._normalize_file_name(file_name)
        self._normalize_mime(extension, mime_type)
        try:
            with path.open("rb") as handle:
                header = handle.read(16)
        except OSError as exc:
            raise MobileFileError("invalid_file", status_code=422) from exc

        valid = False
        if extension == ".png":
            valid = header.startswith(b"\x89PNG\r\n\x1a\n")
        elif extension in {".jpg", ".jpeg"}:
            valid = header.startswith(b"\xff\xd8\xff")
        elif extension == ".gif":
            valid = header.startswith((b"GIF87a", b"GIF89a"))
        elif extension == ".webp":
            valid = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
        elif extension == ".pdf":
            valid = header.startswith(b"%PDF-")
        elif extension in {".txt", ".md", ".csv", ".json"}:
            valid = self._validate_text(path)
        elif extension in {".zip", ".docx", ".xlsx", ".pptx"}:
            valid = self._validate_zip(path, extension)
        if not valid:
            raise MobileFileError("file_type_denied", status_code=415)

    @staticmethod
    def _stream_hash(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        return size, digest.hexdigest()

    def _destination_directory(
        self,
        conn: sqlite3.Connection,
        *,
        account_id: str,
        role: str,
        directory_grant_id: str | None,
        source: str,
    ) -> Path:
        if role == "owner":
            grant = self._grant(
                conn,
                account_id=account_id,
                grant_id=directory_grant_id,
                permission="upload",
            )
            destination = Path(grant["directory_path"]).resolve()
        else:
            box = "inbox" if source == "mobile_upload" else "outbox"
            destination = (self.storage_root / account_id / box).resolve()
            account_root = (self.storage_root / account_id).resolve()
            if not self._is_within(destination, account_root):
                raise MobileFileError("invalid_file", status_code=422)
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    @staticmethod
    def _copy_atomic(source: Path, destination: Path) -> None:
        temporary = destination.with_name(
            f".{destination.name}.{secrets.token_hex(8)}.tmp"
        )
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _fail_upload(self, upload_id: str) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT account_id FROM mobile_uploads WHERE upload_id = ?",
                (upload_id,),
            ).fetchone()
            conn.execute(
                """UPDATE mobile_uploads SET status = 'failed', updated_at = ?
                   WHERE upload_id = ? AND status = 'uploading'""",
                (self._timestamp(), upload_id),
            )
            if row is not None:
                self._audit(
                    conn,
                    "file.upload.failed",
                    "failure",
                    account_id=row["account_id"],
                    resource_id=upload_id,
                )
        self._cleanup_quarantine(upload_id)

    def complete_upload(
        self,
        principal: MobilePrincipal,
        upload_id: str,
    ) -> dict[str, Any]:
        self._expire_uploads(account_id=principal.account_id)
        with self._lock, self._connect() as conn:
            row = self._owned_upload(conn, principal, upload_id)
            if row["status"] == "ready" and row["file_id"]:
                file_row = self._owned_file(conn, principal.account_id, row["file_id"])
                return self._metadata(file_row)
            if row["status"] != "uploading":
                raise MobileFileError("file_conflict", status_code=409)
            parts = conn.execute(
                """SELECT * FROM mobile_upload_parts
                   WHERE upload_id = ? ORDER BY part_number""",
                (upload_id,),
            ).fetchall()
            if len(parts) != int(row["part_count"]):
                raise MobileFileError("file_conflict", status_code=409)

        quarantine = self._quarantine_directory(upload_id)
        assembled = quarantine / "assembled"
        digest = hashlib.sha256()
        assembled_size = 0
        try:
            with assembled.open("xb") as output:
                for index, part in enumerate(parts, start=1):
                    if int(part["part_number"]) != index:
                        raise MobileFileError("file_conflict", status_code=409)
                    part_path = quarantine / f"part-{index:08d}"
                    part_digest = hashlib.sha256()
                    part_size = 0
                    with part_path.open("rb") as source:
                        while chunk := source.read(1024 * 1024):
                            part_size += len(chunk)
                            assembled_size += len(chunk)
                            part_digest.update(chunk)
                            digest.update(chunk)
                            output.write(chunk)
                    if (
                        part_size != int(part["size"])
                        or part_digest.hexdigest() != part["sha256"]
                    ):
                        raise MobileFileError("file_conflict", status_code=409)
                output.flush()
                os.fsync(output.fileno())
            if assembled_size != int(row["size"]) or digest.hexdigest() != row["sha256"]:
                raise MobileFileError("file_conflict", status_code=409)
            self._validate_type(assembled, row["file_name"], row["mime_type"])
        except MobileFileError as exc:
            assembled.unlink(missing_ok=True)
            if exc.code == "file_type_denied":
                self._fail_upload(upload_id)
            raise
        except (OSError, KeyError) as exc:
            assembled.unlink(missing_ok=True)
            raise MobileFileError("file_conflict", status_code=409) from exc

        try:
            scan_allowed = bool(self.scanner.scan(assembled))
        except Exception:
            scan_allowed = False
        if not scan_allowed:
            self._fail_upload(upload_id)
            raise MobileFileError("file_scan_failed", status_code=422)

        file_id = self._id("file")
        extension = Path(row["file_name"]).suffix.lower()
        try:
            with self._lock, self._connect() as conn:
                account = self._account(conn, principal.account_id)
                destination_directory = self._destination_directory(
                    conn,
                    account_id=principal.account_id,
                    role=account["role"],
                    directory_grant_id=row["directory_grant_id"],
                    source="mobile_upload",
                )
        except MobileFileError:
            self._fail_upload(upload_id)
            raise
        destination = destination_directory / f"{file_id}{extension}"
        if destination.exists() or not self._is_within(destination, destination_directory):
            self._fail_upload(upload_id)
            raise MobileFileError("file_conflict", status_code=409)
        try:
            self._copy_atomic(assembled, destination)
            now = self._timestamp()
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    current = self._owned_upload(conn, principal, upload_id)
                    if current["status"] != "uploading":
                        raise MobileFileError("file_conflict", status_code=409)
                    conn.execute(
                        """INSERT INTO mobile_files
                           (file_id, account_id, upload_id, directory_grant_id,
                            display_name, stored_path, size, mime_type, sha256,
                            source, status, scan_result, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'mobile_upload',
                                   'ready', 'clean', ?, ?)""",
                        (
                            file_id,
                            principal.account_id,
                            upload_id,
                            row["directory_grant_id"],
                            row["file_name"],
                            str(destination.resolve()),
                            int(row["size"]),
                            row["mime_type"],
                            row["sha256"],
                            now,
                            now,
                        ),
                    )
                    conn.execute(
                        """UPDATE mobile_uploads
                           SET status = 'ready', file_id = ?, updated_at = ?
                           WHERE upload_id = ?""",
                        (file_id, now, upload_id),
                    )
                    self._audit(
                        conn,
                        "file.upload.completed",
                        "success",
                        account_id=principal.account_id,
                        device_id=principal.device_id,
                        resource_id=file_id,
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                file_row = self._owned_file(conn, principal.account_id, file_id)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            assembled.unlink(missing_ok=True)
        self._cleanup_quarantine(upload_id)
        return self._metadata(file_row)

    def cancel_upload(self, principal: MobilePrincipal, upload_id: str) -> None:
        self._expire_uploads(account_id=principal.account_id)
        with self._lock, self._connect() as conn:
            row = self._owned_upload(conn, principal, upload_id)
            if row["status"] == "ready":
                raise MobileFileError("file_conflict", status_code=409)
            conn.execute(
                """UPDATE mobile_uploads SET status = 'cancelled', updated_at = ?
                   WHERE upload_id = ?""",
                (self._timestamp(), upload_id),
            )
            self._audit(
                conn,
                "file.upload.cancelled",
                "success",
                account_id=principal.account_id,
                device_id=principal.device_id,
                resource_id=upload_id,
            )
        self._cleanup_quarantine(upload_id)

    @staticmethod
    def _metadata(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "fileId": row["file_id"],
            "fileName": row["display_name"],
            "size": int(row["size"]),
            "mimeType": row["mime_type"],
            "sha256": row["sha256"],
            "source": row["source"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _owned_file(
        conn: sqlite3.Connection,
        account_id: str,
        file_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """SELECT * FROM mobile_files
               WHERE file_id = ? AND account_id = ? AND status = 'ready'""",
            (file_id, account_id),
        ).fetchone()
        if row is None:
            raise MobileFileError("file_not_found", status_code=404)
        return row

    def list_files(
        self,
        principal: MobilePrincipal,
        *,
        before_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise MobileFileError("invalid_file", status_code=422)
        with self._lock, self._connect() as conn:
            params: list[Any] = [principal.account_id]
            cursor_clause = ""
            if before_id:
                cursor = self._owned_file(conn, principal.account_id, before_id)
                self._verify_file_permission(conn, cursor, permission="read")
                cursor_rowid = conn.execute(
                    "SELECT rowid FROM mobile_files WHERE file_id = ?",
                    (cursor["file_id"],),
                ).fetchone()[0]
                cursor_clause = " AND rowid < ?"
                params.append(cursor_rowid)
            permission_clause = ""
            if principal.role == "owner":
                permission_clause = (
                    " AND EXISTS (SELECT 1 FROM mobile_directory_grants g"
                    " WHERE g.grant_id = mobile_files.directory_grant_id"
                    " AND g.account_id = mobile_files.account_id"
                    " AND g.enabled = 1 AND g.allow_read = 1)"
                )
            params.append(limit + 1)
            rows = conn.execute(
                """SELECT * FROM mobile_files
                   WHERE account_id = ? AND status = 'ready'"""
                + permission_clause
                + cursor_clause
                + " ORDER BY rowid DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return {
            "items": [self._metadata(row) for row in rows[:limit]],
            "hasMore": len(rows) > limit,
        }

    def get_file(
        self,
        principal: MobilePrincipal,
        file_id: str,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = self._owned_file(conn, principal.account_id, file_id)
            self._verify_file_permission(conn, row, permission="read")
            return self._metadata(row)

    def _verify_file_permission(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        permission: str,
    ) -> Path:
        account = self._account(conn, row["account_id"])
        path = Path(row["stored_path"]).resolve()
        if account["role"] == "owner":
            grant = self._grant(
                conn,
                account_id=row["account_id"],
                grant_id=row["directory_grant_id"],
                permission=permission,
            )
            if not self._is_within(path, Path(grant["directory_path"])):
                raise MobileFileError("file_not_found", status_code=404)
        else:
            box = "inbox" if row["source"] == "mobile_upload" else "outbox"
            expected = self.storage_root / row["account_id"] / box
            if not self._is_within(path, expected):
                raise MobileFileError("file_not_found", status_code=404)
        if not path.is_file():
            raise MobileFileError("file_not_found", status_code=404)
        return path

    @staticmethod
    def _parse_range(value: str | None, size: int) -> tuple[int, int, bool]:
        if value is None:
            return 0, size - 1, False
        if size <= 0 or "," in value:
            raise MobileFileError(
                "range_not_satisfiable",
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
            )
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
        if match is None or (not match.group(1) and not match.group(2)):
            raise MobileFileError(
                "range_not_satisfiable",
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
            )
        if not match.group(1):
            suffix = int(match.group(2))
            if suffix <= 0:
                raise MobileFileError(
                    "range_not_satisfiable",
                    status_code=416,
                    headers={"Content-Range": f"bytes */{size}"},
                )
            start = max(size - suffix, 0)
            return start, size - 1, True
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
        if start >= size or end < start:
            raise MobileFileError(
                "range_not_satisfiable",
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
            )
        return start, min(end, size - 1), True

    def prepare_download(
        self,
        principal: MobilePrincipal,
        file_id: str,
        range_header: str | None,
    ) -> DownloadSpec:
        with self._lock, self._connect() as conn:
            row = self._owned_file(conn, principal.account_id, file_id)
            path = self._verify_file_permission(conn, row, permission="download")
            actual_size = path.stat().st_size
            if actual_size != int(row["size"]):
                raise MobileFileError("file_not_found", status_code=404)
            start, end, partial = self._parse_range(range_header, actual_size)
            self._audit(
                conn,
                "file.downloaded",
                "success",
                account_id=principal.account_id,
                device_id=principal.device_id,
                resource_id=file_id,
            )
            return DownloadSpec(
                path=path,
                file_name=row["display_name"],
                mime_type=row["mime_type"],
                sha256=row["sha256"],
                total_size=actual_size,
                start=start,
                end=end,
                partial=partial,
            )

    def resolve_request_attachments(
        self,
        principal: MobilePrincipal,
        file_ids: list[str],
    ) -> list[dict[str, Any]]:
        if len(file_ids) > 20 or len(set(file_ids)) != len(file_ids):
            raise MobileFileError("invalid_file", status_code=422)
        attachments: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            for file_id in file_ids:
                row = self._owned_file(conn, principal.account_id, file_id)
                self._verify_file_permission(conn, row, permission="read")
                attachments.append(
                    {
                        "name": row["display_name"],
                        "url": f"/api/mobile/v1/files/{row['file_id']}/content",
                        "state": "ready",
                        "size": int(row["size"]),
                        "type": row["mime_type"],
                        "mime_type": row["mime_type"],
                        "sha256": row["sha256"],
                    }
                )
        return attachments

    def register_computer_output(
        self,
        *,
        account_id: str,
        source_path: str | Path,
        file_name: str,
        mime_type: str,
        directory_grant_id: str | None = None,
    ) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise MobileFileError("file_not_found", status_code=404)
        normalized_name, extension = self._normalize_file_name(file_name)
        normalized_mime = self._normalize_mime(extension, mime_type)
        if source.stat().st_size > MAX_FILE_SIZE:
            raise MobileFileError("file_too_large", status_code=413)

        staging_id = self._id("register")
        staging_directory = self._quarantine_directory(staging_id)
        staging_directory.mkdir(parents=True, exist_ok=False)
        staging = staging_directory / "assembled"
        destination: Path | None = None
        try:
            self._copy_atomic(source, staging)
            size, sha256 = self._stream_hash(staging)
            if size > MAX_FILE_SIZE:
                raise MobileFileError("file_too_large", status_code=413)
            self._validate_type(staging, normalized_name, normalized_mime)
            try:
                scan_allowed = bool(self.scanner.scan(staging))
            except Exception:
                scan_allowed = False
            if not scan_allowed:
                raise MobileFileError("file_scan_failed", status_code=422)

            file_id = self._id("file")
            with self._lock, self._connect() as conn:
                account = self._account(conn, account_id)
                if account["role"] == "guest" and directory_grant_id is not None:
                    raise MobileFileError("invalid_file", status_code=422)
                destination_directory = self._destination_directory(
                    conn,
                    account_id=account_id,
                    role=account["role"],
                    directory_grant_id=directory_grant_id,
                    source="computer_output",
                )
                if account["role"] == "owner":
                    self._grant(
                        conn,
                        account_id=account_id,
                        grant_id=directory_grant_id,
                        permission="download",
                    )
            destination = destination_directory / f"{file_id}{extension}"
            if destination.exists() or not self._is_within(
                destination,
                destination_directory,
            ):
                raise MobileFileError("file_conflict", status_code=409)
            self._copy_atomic(staging, destination)
            copied_size, copied_hash = self._stream_hash(destination)
            if copied_size != size or copied_hash != sha256:
                raise MobileFileError("file_conflict", status_code=409)
            now = self._timestamp()
            with self._lock, self._connect() as conn:
                conn.execute(
                    """INSERT INTO mobile_files
                       (file_id, account_id, upload_id, directory_grant_id,
                        display_name, stored_path, size, mime_type, sha256,
                        source, status, scan_result, created_at, updated_at)
                       VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, 'computer_output',
                               'ready', 'clean', ?, ?)""",
                    (
                        file_id,
                        account_id,
                        directory_grant_id,
                        normalized_name,
                        str(destination.resolve()),
                        size,
                        normalized_mime,
                        sha256,
                        now,
                        now,
                    ),
                )
                self._audit(
                    conn,
                    "file.output.registered",
                    "success",
                    account_id=account_id,
                    resource_id=file_id,
                )
                row = self._owned_file(conn, account_id, file_id)
        except Exception:
            if destination is not None:
                destination.unlink(missing_ok=True)
            raise
        finally:
            self._cleanup_quarantine(staging_id)
        return self._metadata(row)


def iter_download(spec: DownloadSpec, *, block_size: int = 1024 * 1024):
    remaining = spec.content_length
    with spec.path.open("rb") as handle:
        handle.seek(spec.start)
        while remaining > 0:
            chunk = handle.read(min(block_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

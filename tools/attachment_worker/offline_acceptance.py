"""Run the redacted, synthetic-only desktop attachment acceptance matrix."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.desktop_attachments import (  # noqa: E402
    AttachmentWorkerClient,
    AttachmentWorkerError,
    DesktopAttachmentService,
    DesktopDefenderScanner,
)
from core.migrations import (  # noqa: E402
    MigrationRunner,
    desktop_chat_continuity_migrations,
)
from tools.attachment_worker.synthetic_fixtures import (  # noqa: E402
    MARKERS,
    create_fixtures,
)


CONTENT_FORMATS = {"txt", "py", "pdf", "docx", "xlsx", "pptx", "zip"}
MEDIA_FORMATS = {"png", "wav", "mp4"}
METADATA_FORMATS = {"rar", "7z", "exe", "apk"}
FORBIDDEN_PUBLIC_KEYS = {
    "path",
    "storage_path",
    "storage_relpath",
    "stored_name",
    "quarantine_path",
    "ready_path",
    "allowed_root",
    "allowedroot",
    "local_path",
    "localpath",
    "absolute_path",
    "absolutepath",
}


class SqliteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()


class RecordingDefender:
    def __init__(self) -> None:
        self.delegate = DesktopDefenderScanner()
        self.available = bool(
            self.delegate.executable and self.delegate.executable.is_file()
        )
        self.results: list[bool] = []

    def scan(self, path: Path) -> bool:
        result = self.delegate.scan(path)
        self.results.append(result)
        return result


class FailOnceWorker:
    def __init__(self, delegate: AttachmentWorkerClient) -> None:
        self.delegate = delegate
        self.calls = 0

    def process(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise AttachmentWorkerError(
                "synthetic_worker_failure",
                "synthetic retry gate",
                metadata={
                    "contentExtracted": False,
                    "contentKind": "unavailable",
                },
                python_version=".".join(map(str, sys.version_info[:3])),
            )
        return self.delegate.process(request)


class PathLeakingFailureWorker:
    def process(self, request: dict[str, Any]) -> dict[str, Any]:
        private_path = str(request["path"])
        raise AttachmentWorkerError(
            "synthetic_path_failure",
            f"failed at {private_path}",
            metadata={
                "parserPath": private_path,
                "nested": {"workingDirectory": str(Path(private_path).parent)},
                "contentExtracted": False,
            },
            python_version=".".join(map(str, sys.version_info[:3])),
        )


class PathLeakingReadyWorker:
    def process(self, request: dict[str, Any]) -> dict[str, Any]:
        private_path = str(request["path"])
        return {
            "version": 1,
            "attachmentId": request["attachmentId"],
            "status": "ready",
            "chunks": [{"content": f"synthetic path={private_path}"}],
            "metadata": {
                "sourcePath": private_path,
                "contentExtracted": True,
                "contentKind": "extracted_text",
            },
            "truncated": False,
            "pythonVersion": ".".join(map(str, sys.version_info[:3])),
        }


def _initialize_database(database: SqliteDatabase) -> None:
    with database.connection() as connection:
        MigrationRunner(connection).run(desktop_chat_continuity_migrations())
        connection.commit()


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).lower()
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _public_is_redacted(payload: dict[str, Any], private_root: Path) -> bool:
    if set(_walk_keys(payload)) & FORBIDDEN_PUBLIC_KEYS:
        return False
    serialized = json.dumps(payload, ensure_ascii=False).replace("\\\\", "/")
    return str(private_root.resolve()).replace("\\", "/") not in serialized


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _write_evidence(evidence_dir: Path, result: dict[str, Any]) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result_path = evidence_dir / "result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    (evidence_dir / "sha256sum.txt").write_text(
        f"{digest}  result.json\n",
        encoding="ascii",
    )


def run(evidence_dir: Path) -> dict[str, Any]:
    format_results: list[dict[str, Any]] = []
    lifecycle: dict[str, Any] = {}
    safety: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="aerie-attachment-qa-") as temp:
        private_root = Path(temp)
        fixture_root = private_root / "fixtures"
        storage_root = private_root / "storage"
        database = SqliteDatabase(private_root / "attachments.db")
        _initialize_database(database)
        fixtures = create_fixtures(fixture_root)
        scanner = RecordingDefender()
        worker = AttachmentWorkerClient(python_command=[sys.executable])
        service = DesktopAttachmentService(
            database,
            storage_root=storage_root,
            scanner=scanner,
            worker=worker,
        )

        retained_id = ""
        for format_name, source in fixtures.items():
            entry: dict[str, Any] = {
                "format": format_name,
                "executionAttempted": False,
            }
            try:
                queued = service.ingest(
                    source,
                    original_name=source.name,
                    mime_type="application/octet-stream",
                )
                record = (
                    service.process(queued["attachment_id"])
                    if queued["state"] == "queued"
                    else queued
                )
                chunks = service.repository.chunks(queued["attachment_id"])
                combined = "".join(
                    str(item.get("content") or "") for item in chunks
                ).replace("\\_", "_")
                marker_verified = (
                    MARKERS[format_name] in combined
                    if format_name in MARKERS
                    else False
                )
                public = service.public_record(queued["attachment_id"])
                metadata = record.get("metadata") or {}
                entry.update(
                    {
                        "state": record["state"],
                        "analysisMode": record["analysis_mode"],
                        "errorCode": record.get("error_code"),
                        "contentExtracted": bool(metadata.get("contentExtracted")),
                        "contentKind": metadata.get("contentKind"),
                        "semanticStatus": metadata.get("semanticStatus"),
                        "extractionMethod": metadata.get("extractionMethod"),
                        "chunkCount": len(chunks),
                        "contentMarkerVerified": marker_verified,
                        "publicPathRedacted": bool(
                            public and _public_is_redacted(public, private_root)
                        ),
                    }
                )
                if format_name in CONTENT_FORMATS:
                    entry["contractSafe"] = bool(
                        record["state"] == "ready"
                        and metadata.get("contentExtracted") is True
                        and marker_verified
                    )
                    entry["planRequirementMet"] = entry["contractSafe"]
                elif format_name in MEDIA_FORMATS:
                    # Media is deliberately metadata-only by default. An explicit
                    # extract request still fails closed in the worker contract.
                    entry["contractSafe"] = bool(
                        record["state"] == "ready"
                        and record.get("analysis_mode") == "metadata"
                        and metadata.get("contentExtracted") is False
                        and metadata.get("semanticStatus") == "not_required"
                        and not marker_verified
                    )
                    entry["planRequirementMet"] = entry["contractSafe"]
                    entry["blockingReason"] = "metadata_only_no_offline_semantic_extraction"
                else:
                    entry["contractSafe"] = bool(
                        record["state"] == "ready"
                        and record["analysis_mode"] == "metadata"
                        and metadata.get("contentExtracted") is False
                        and not marker_verified
                    )
                    entry["planRequirementMet"] = entry["contractSafe"]
                entry["contractSafe"] = (
                    entry["contractSafe"] and entry["publicPathRedacted"]
                )
                entry["passed"] = bool(
                    entry["contractSafe"] and entry["planRequirementMet"]
                )
                if format_name == "txt":
                    retained_id = queued["attachment_id"]
            except Exception as exc:
                entry.update(
                    {
                        "state": "audit_exception",
                        "errorCode": type(exc).__name__,
                        "contentExtracted": False,
                        "contentMarkerVerified": False,
                        "publicPathRedacted": False,
                        "contractSafe": False,
                        "planRequirementMet": False,
                        "passed": False,
                    }
                )
            format_results.append(entry)

        restarted = DesktopAttachmentService(
            SqliteDatabase(database.path),
            storage_root=storage_root,
            scanner=scanner,
            worker=worker,
        )
        restored = restarted.public_record(retained_id) if retained_id else None
        restored_chunks = (
            restarted.repository.chunks(retained_id) if retained_id else []
        )
        restored_text = "".join(
            item["content"] for item in restored_chunks
        ).replace("\\_", "_")
        download_matches = False
        deleted = False
        if restored:
            download_path, _filename = restarted.download_path(retained_id)
            download_matches = hashlib.sha256(download_path.read_bytes()).hexdigest() == (
                restored["sha256"]
            )
            deleted = restarted.remove(retained_id)
        lifecycle["restartRestored"] = bool(
            restored and MARKERS["txt"] in restored_text
        )
        lifecycle["downloadHashVerified"] = download_matches
        lifecycle["deleteRemovedRecord"] = bool(
            deleted and restarted.repository.get(retained_id) is None
        )

        retry_source = fixture_root / "retry.txt"
        retry_source.write_text(MARKERS["txt"], encoding="utf-8")
        retry_worker = FailOnceWorker(worker)
        retry_service = DesktopAttachmentService(
            database,
            storage_root=storage_root,
            scanner=scanner,
            worker=retry_worker,
        )
        retry_record = retry_service.ingest(
            retry_source,
            original_name="retry.txt",
        )
        first = retry_service.process(retry_record["attachment_id"])
        second = retry_service.retry(retry_record["attachment_id"])
        retry_text = "".join(
            item["content"]
            for item in retry_service.repository.chunks(retry_record["attachment_id"])
        ).replace("\\_", "_")
        lifecycle["failedThenRetried"] = bool(
            first["state"] == "failed"
            and first["error_code"] == "synthetic_worker_failure"
            and second["state"] == "ready"
            and MARKERS["txt"] in retry_text
        )
        retry_service.remove(retry_record["attachment_id"])

        leaking_failure_service = DesktopAttachmentService(
            database,
            storage_root=storage_root,
            scanner=scanner,
            worker=PathLeakingFailureWorker(),
        )
        leaking_failure = leaking_failure_service.ingest(
            retry_source,
            original_name="failure-path.txt",
        )
        leaking_failure_service.process(leaking_failure["attachment_id"])
        failure_public = leaking_failure_service.public_record(
            leaking_failure["attachment_id"]
        )
        safety["failureDtoPathRedacted"] = bool(
            failure_public
            and _public_is_redacted(failure_public, private_root)
            and "[redacted-path]" in (failure_public.get("error") or {}).get("message", "")
        )
        leaking_failure_service.remove(leaking_failure["attachment_id"])

        leaking_ready_service = DesktopAttachmentService(
            database,
            storage_root=storage_root,
            scanner=scanner,
            worker=PathLeakingReadyWorker(),
        )
        leaking_ready = leaking_ready_service.ingest(
            retry_source,
            original_name="ready-path.txt",
        )
        leaking_ready_service.process(leaking_ready["attachment_id"])
        ready_public = leaking_ready_service.public_record(leaking_ready["attachment_id"])
        ready_snippets = leaking_ready_service.context_snippets(
            [leaking_ready["attachment_id"]]
        )
        safety["readyDtoPathRedacted"] = bool(
            ready_public and _public_is_redacted(ready_public, private_root)
        )
        safety["contextPathRedacted"] = bool(
            ready_snippets
            and str(private_root) not in json.dumps(ready_snippets, ensure_ascii=False)
            and "[redacted-path]" in ready_snippets[0]
        )
        leaking_ready_service.remove(leaking_ready["attachment_id"])

        defender = {
            "available": scanner.available,
            "realScannerUsed": bool(scanner.results),
            "scanCount": len(scanner.results),
            "cleanCount": sum(1 for value in scanner.results if value),
            "allClean": bool(scanner.results) and all(scanner.results),
        }

    all_formats_passed = all(item.get("passed") for item in format_results)
    all_formats_contract_safe = all(
        item.get("contractSafe") for item in format_results
    )
    lifecycle_passed = all(lifecycle.values())
    safety_passed = all(safety.values())
    passed = bool(
        all_formats_passed
        and lifecycle_passed
        and safety_passed
        and defender["allClean"]
    )
    result = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "syntheticOnly": True,
        "modelCalls": 0,
        "privateContentStored": False,
        "environment": {
            "pythonVersion": ".".join(map(str, sys.version_info[:3])),
            "markitdownVersion": _package_version("markitdown"),
            "pillowVersion": _package_version("Pillow"),
            "py7zrVersion": _package_version("py7zr"),
            "rarfileVersion": _package_version("rarfile"),
        },
        "defender": defender,
        "formats": format_results,
        "lifecycle": lifecycle,
        "safety": safety,
        "summary": {
            "passed": passed,
            "planRequirementsPassed": all_formats_passed,
            "safetyContractPassed": bool(
                all_formats_contract_safe
                and lifecycle_passed
                and safety_passed
                and defender["allClean"]
            ),
            "formatCount": len(format_results),
            "formatPassedCount": sum(
                1 for item in format_results if item.get("passed")
            ),
            "contentFormats": sorted(CONTENT_FORMATS),
            "metadataOnlyFormats": sorted(METADATA_FORMATS),
            "semanticUnavailableFormats": sorted(MEDIA_FORMATS),
            "blockedFormats": sorted(
                item["format"]
                for item in format_results
                if not item.get("planRequirementMet")
            ),
        },
    }
    _write_evidence(evidence_dir, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    result = run(Path(args.evidence_dir))
    print(
        json.dumps(
            {
                "passed": result["summary"]["passed"],
                "formatCount": result["summary"]["formatCount"],
                "formatPassedCount": result["summary"]["formatPassedCount"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

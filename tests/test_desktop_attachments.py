import json
import sqlite3
import stat
import zipfile

import pytest


def _connection():
    from core.migrations import MigrationRunner, desktop_chat_continuity_migrations

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    MigrationRunner(conn).run(desktop_chat_continuity_migrations())
    return conn


class CleanScanner:
    def scan(self, path):
        return True


class RejectingScanner:
    def scan(self, path):
        return False


class RecordingWorker:
    def __init__(self):
        self.requests = []

    def process(self, request):
        self.requests.append(request)
        extracted = request["analysisMode"] == "extract"
        content = (
            "SENTINEL attachment body"
            if extracted
            else "SYNTHETIC metadata manifest"
        )
        import hashlib

        return {
            "version": 1,
            "attachmentId": request["attachmentId"],
            "status": "ready",
            "chunks": [
                {
                    "content": content,
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                }
            ],
            "metadata": {
                "parsed": True,
                "contentExtracted": extracted,
                "contentKind": "extracted_text" if extracted else "metadata_only",
                "semanticStatus": "available" if extracted else "not_required",
            },
            "pythonVersion": "3.12.12",
            "truncated": False,
        }


def test_capabilities_are_server_owned_and_dangerous_types_are_metadata_only():
    from core.desktop_attachments import attachment_capabilities_payload

    payload = attachment_capabilities_payload()
    by_extension = {
        extension: item
        for item in payload["capabilities"]
        for extension in item["extensions"]
    }
    assert by_extension["docx"]["analysisMode"] == "extract"
    assert by_extension["zip"]["analysisMode"] == "extract"
    assert by_extension["rar"]["analysisMode"] == "metadata"
    assert by_extension["7z"]["analysisMode"] == "metadata"
    assert by_extension["exe"]["analysisMode"] == "metadata"
    assert by_extension["apk"]["analysisMode"] == "metadata"
    for extension in ("png", "wav", "mp4"):
        assert by_extension[extension]["semanticStatus"] == "not_required"
        assert by_extension[extension]["contentExtractionAvailable"] is False
        assert by_extension[extension]["readyRequiresContentExtracted"] is False
    assert payload["states"] == [
        "queued", "processing", "ready", "failed", "quarantined", "unsupported"
    ]


def test_text_attachment_moves_through_quarantine_and_persists_chunks(tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    worker = RecordingWorker()
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=worker,
    )
    queued = service.ingest(source, original_name="notes.txt", mime_type="text/plain")
    assert queued["state"] == "queued"
    assert queued["storage_relpath"].startswith("quarantine/")

    ready = service.process(queued["attachment_id"])
    assert ready["state"] == "ready"
    assert ready["storage_relpath"].startswith("ready/")
    assert service.repository.chunks(queued["attachment_id"])[0]["content"] == (
        "SENTINEL attachment body"
    )
    public = service.public_record(queued["attachment_id"])
    assert "storage_relpath" not in public
    assert "stored_name" not in public
    assert public["downloadUrl"].endswith("/download")
    assert worker.requests[0]["allowedRoot"] == str((tmp_path / "desktop-only").resolve())


def test_scan_uncertainty_fails_closed_and_keeps_file_quarantined(tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=RejectingScanner(),
        worker=RecordingWorker(),
    )
    queued = service.ingest(source, original_name="notes.txt", mime_type="text/plain")
    result = service.process(queued["attachment_id"])
    assert result["state"] == "quarantined"
    assert result["error_code"] == "scan_failed_or_unavailable"
    assert result["storage_relpath"].startswith("quarantine/")


def test_executable_is_metadata_only_and_never_executed(tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    source = tmp_path / "sample.exe"
    source.write_bytes(b"MZ" + b"not executable code" * 10)
    worker = RecordingWorker()
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=worker,
    )
    queued = service.ingest(source, original_name="sample.exe")
    service.process(queued["attachment_id"])
    assert worker.requests[0]["analysisMode"] == "metadata"
    assert worker.requests[0]["category"] == "executable"


def test_signature_mismatch_is_quarantined_before_worker(tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    source = tmp_path / "fake.pdf"
    source.write_text("not a pdf", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=RecordingWorker(),
    )
    result = service.ingest(source, original_name="fake.pdf")
    assert result["state"] == "quarantined"
    assert result["error_code"] == "signature_mismatch"


@pytest.mark.parametrize("extension", ["rar", "7z"])
def test_archive_signature_mismatch_is_quarantined(tmp_path, extension):
    from core.desktop_attachments import DesktopAttachmentService

    source = tmp_path / f"fake.{extension}"
    source.write_bytes(b"not an archive")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=RecordingWorker(),
    )

    result = service.ingest(source, original_name=source.name)

    assert result["state"] == "quarantined"
    assert result["error_code"] == "signature_mismatch"


@pytest.mark.parametrize(
    ("entries", "code"),
    [
        ([{"name": "../escape.txt", "size": 1, "compressedSize": 1}], "archive_path_traversal"),
        ([{"name": "link", "size": 1, "compressedSize": 1, "symlink": True}], "archive_symlink"),
        ([{"name": "large.bin", "size": 101, "compressedSize": 2}], "archive_ratio_limit"),
    ],
)
def test_archive_manifest_guard_rejects_unsafe_entries(entries, code):
    from core.attachment_worker_runtime import (
        ArchiveSafetyError,
        _validate_archive_entries,
    )

    with pytest.raises(ArchiveSafetyError) as error:
        _validate_archive_entries(
            entries,
            limits={
                "maxMembers": 10,
                "maxUncompressedBytes": 1000,
                "maxCompressionRatio": 10,
            },
        )
    assert error.value.code == code


def test_zip_guard_rejects_path_traversal_and_symlinks(tmp_path):
    from core.attachment_worker_runtime import ZipSafetyError, validate_zip_archive

    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.txt", "no")
    with pytest.raises(ZipSafetyError, match="unsafe member path") as error:
        validate_zip_archive(traversal)
    assert error.value.code == "zip_path_traversal"

    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    with pytest.raises(ZipSafetyError, match="symbolic link") as error:
        validate_zip_archive(symlink)
    assert error.value.code == "zip_symlink"


def test_zip_worker_reads_safe_text_without_extracting_to_disk(tmp_path):
    from core.attachment_worker_runtime import process_worker_request

    archive_path = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("folder/readme.txt", "ZIP_SENTINEL")
        archive.writestr("folder/image.bin", b"\x00\x01")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    response = process_worker_request(
        {
            "version": 1,
            "attachmentId": "att_zip",
            "path": str(archive_path),
            "allowedRoot": str(tmp_path),
            "category": "zip",
            "analysisMode": "extract",
            "chunkChars": 500,
            "maxOutputChars": 5000,
        }
    )
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert response["status"] == "ready"
    assert "ZIP_SENTINEL" in "".join(chunk["content"] for chunk in response["chunks"])
    assert after == before


def test_context_snippets_require_ready_records_and_never_include_paths(tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=RecordingWorker(),
    )
    queued = service.ingest(source, original_name="notes.txt")
    assert service.context_snippets([queued["attachment_id"]]) == []
    service.process(queued["attachment_id"])
    snippets = service.context_snippets([queued["attachment_id"]])
    assert "SENTINEL attachment body" in snippets[0]
    assert str(tmp_path) not in json.dumps(snippets)


def test_send_resolution_is_server_owned_ready_unbound_and_bindable(tmp_path):
    from core.desktop_attachments import (
        AttachmentStateConflict,
        DesktopAttachmentService,
    )

    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=RecordingWorker(),
    )
    queued = service.ingest(source, original_name="notes.txt")
    with pytest.raises(AttachmentStateConflict, match="not ready"):
        service.resolve_ready_for_send([queued["attachment_id"]])

    service.process(queued["attachment_id"])
    resolved = service.resolve_ready_for_send([queued["attachment_id"]])
    assert resolved[0]["attachmentId"] == queued["attachment_id"]
    assert "storage_relpath" not in resolved[0]

    service.bind_message(
        [queued["attachment_id"]],
        message_id="msg_user_1",
        conversation_id="conv_1",
    )
    stored = service.repository.get(queued["attachment_id"])
    assert stored["message_id"] == "msg_user_1"
    assert stored["conversation_id"] == "conv_1"
    with pytest.raises(AttachmentStateConflict, match="already bound"):
        service.resolve_ready_for_send([queued["attachment_id"]])


@pytest.mark.parametrize(
    ("category", "suffix", "payload"),
    [
        ("image", ".png", b"\x89PNG\r\n\x1a\nsynthetic"),
        ("audio", ".wav", b"RIFFsynthetic"),
        ("video", ".mp4", b"\x00\x00\x00\x18ftypisomsynthetic"),
    ],
)
def test_media_extract_mode_never_calls_markitdown_or_online_speech(
    monkeypatch,
    tmp_path,
    category,
    suffix,
    payload,
):
    import builtins

    from core import attachment_worker_runtime as runtime

    source = tmp_path / f"synthetic{suffix}"
    source.write_bytes(payload)
    calls = {"markitdown": 0, "speech": 0}

    def forbidden_markitdown(_path):
        calls["markitdown"] += 1
        raise AssertionError("media must not enter MarkItDown")

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("speech_recognition"):
            calls["speech"] += 1
            raise AssertionError("online speech recognition must not be imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(runtime, "_extract_with_markitdown", forbidden_markitdown)
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(Exception) as error:
        runtime.process_worker_request(
            {
                "version": 1,
                "attachmentId": "att_semantic_failure",
                "path": str(source),
                "allowedRoot": str(tmp_path),
                "category": category,
                "analysisMode": "extract",
            }
        )

    assert getattr(error.value, "code", None) == "semantic_extraction_unavailable"
    assert error.value.metadata["contentExtracted"] is False
    assert error.value.metadata["contentKind"] == "unavailable"
    assert error.value.metadata["semanticStatus"] == "unavailable"
    assert calls == {"markitdown": 0, "speech": 0}


def test_media_metadata_mode_reaches_ready_and_can_send(tmp_path):
    """Media attachments run in metadata mode (no semantic extraction) and reach ready."""
    from core.desktop_attachments import CAPABILITY_BY_EXTENSION, DesktopAttachmentService

    assert CAPABILITY_BY_EXTENSION["png"].analysis_mode == "metadata"
    source = tmp_path / "photo.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    worker = RecordingWorker()
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=worker,
    )
    queued = service.ingest(source, original_name="photo.png", mime_type="image/png")
    assert queued["state"] == "queued"

    ready = service.process(queued["attachment_id"])
    assert worker.requests[0]["analysisMode"] == "metadata"
    assert ready["state"] == "ready"
    assert ready["metadata"]["contentExtracted"] is False
    assert ready["metadata"]["semanticStatus"] == "not_required"

    # metadata-mode attachments must be sendable without verified extracted content
    resolved = service.resolve_ready_for_send([queued["attachment_id"]])
    assert resolved[0]["attachmentId"] == queued["attachment_id"]
    public = service.public_record(queued["attachment_id"])
    assert public["semanticStatus"] == "not_required"
    assert public["contentExtracted"] is False


def test_fake_rar_fails_closed(tmp_path):
    """A RAR carrying only the file signature (garbage body) must not reach ready."""
    from core.attachment_worker_runtime import (
        AttachmentExtractionError,
        process_worker_request,
    )

    source = tmp_path / "fake.rar"
    source.write_bytes(b"Rar!\x1a\x07\x00" + b"garbage")
    with pytest.raises(AttachmentExtractionError) as error:
        process_worker_request(
            {
                "version": 1,
                "attachmentId": "att_fake_rar",
                "path": str(source),
                "allowedRoot": str(tmp_path),
                "category": "archive",
                "analysisMode": "metadata",
            }
        )
    # invalid_rar when rarfile parses (worker env); archive_parser_unavailable
    # when rarfile is missing (main env) — either way the file never becomes ready.
    assert error.value.code in {"invalid_rar", "archive_parser_unavailable"}


def test_extract_worker_without_verified_content_cannot_become_ready_or_send(tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    class MetadataOnlyWorker:
        def process(self, request):
            return {
                "version": 1,
                "attachmentId": request["attachmentId"],
                "status": "ready",
                "chunks": [{"content": "metadata only"}],
                "metadata": {
                    "contentExtracted": False,
                    "contentKind": "metadata_only",
                },
                "pythonVersion": "3.12-test",
            }

    source = tmp_path / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=MetadataOnlyWorker(),
    )
    queued = service.ingest(source, original_name="source.txt")
    failed = service.process(queued["attachment_id"])

    assert failed["state"] == "failed"
    assert failed["error_code"] == "semantic_extraction_unavailable"
    assert failed["metadata"]["contentExtracted"] is False
    assert service.repository.chunks(queued["attachment_id"]) == []
    with pytest.raises(Exception, match="not ready"):
        service.resolve_ready_for_send([queued["attachment_id"]])


def test_worker_success_metadata_distinguishes_content_from_metadata_only(tmp_path):
    from core.attachment_worker_runtime import process_worker_request

    text_path = tmp_path / "notes.txt"
    text_path.write_text("synthetic content", encoding="utf-8")
    extracted = process_worker_request(
        {
            "version": 1,
            "attachmentId": "att_text",
            "path": str(text_path),
            "allowedRoot": str(tmp_path),
            "category": "text",
            "analysisMode": "extract",
        }
    )
    assert extracted["metadata"]["contentExtracted"] is True
    assert extracted["metadata"]["contentKind"] == "extracted_text"
    assert extracted["metadata"]["extractionMethod"] == "direct_text"

    exe_path = tmp_path / "sample.exe"
    exe_path.write_bytes(b"MZ" + b"synthetic metadata only")
    metadata_only = process_worker_request(
        {
            "version": 1,
            "attachmentId": "att_exe",
            "path": str(exe_path),
            "allowedRoot": str(tmp_path),
            "category": "executable",
            "analysisMode": "metadata",
        }
    )
    assert metadata_only["metadata"]["contentExtracted"] is False
    assert metadata_only["metadata"]["contentKind"] == "metadata_only"
    assert metadata_only["metadata"]["extractionMethod"] == "metadata_only"


def test_worker_error_response_preserves_safe_extraction_metadata(tmp_path):
    from core import attachment_worker_runtime as runtime

    error = runtime.AttachmentExtractionError(
        "semantic_extraction_unavailable",
        "semantic extraction produced no content",
        metadata={
            "contentExtracted": False,
            "contentKind": "unavailable",
            "sizeBytes": 10,
        },
    )

    response = runtime.worker_error_response("att_failed", error)

    assert response["status"] == "failed"
    assert response["error"]["code"] == "semantic_extraction_unavailable"
    assert response["metadata"] == error.metadata
    assert response["chunks"] == []


def test_attachment_service_persists_worker_failure_metadata(tmp_path):
    from core.desktop_attachments import (
        AttachmentWorkerError,
        DesktopAttachmentService,
    )

    class FailingWorker:
        def process(self, _request):
            raise AttachmentWorkerError(
                "semantic_extraction_unavailable",
                "synthetic extraction failure",
                metadata={
                    "contentExtracted": False,
                    "contentKind": "unavailable",
                    "extractionMethod": "markitdown",
                },
            )

    source = tmp_path / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=FailingWorker(),
    )
    queued = service.ingest(source, original_name="notes.txt")

    failed = service.process(queued["attachment_id"])

    assert failed["state"] == "failed"
    assert failed["error_code"] == "semantic_extraction_unavailable"
    assert failed["metadata"]["contentExtracted"] is False
    assert failed["metadata"]["contentKind"] == "unavailable"
    assert service.repository.chunks(queued["attachment_id"]) == []


def test_public_failure_dto_redacts_worker_paths_and_path_metadata(tmp_path):
    from core.desktop_attachments import (
        AttachmentWorkerError,
        DesktopAttachmentService,
    )

    private_path = (tmp_path / "desktop-only" / "ready" / "private.txt").resolve()

    class PathLeakingWorker:
        def process(self, _request):
            raise AttachmentWorkerError(
                "parser_failed",
                f"parser failed while opening {private_path}",
                metadata={
                    "parserPath": str(private_path),
                    "nested": {
                        "workingDirectory": str(private_path.parent),
                        "safeValue": "retained",
                    },
                    "contentExtracted": False,
                },
            )

    source = tmp_path / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=PathLeakingWorker(),
    )
    queued = service.ingest(source, original_name="notes.txt")
    service.process(queued["attachment_id"])

    public = service.public_record(queued["attachment_id"])
    serialized = json.dumps(public, ensure_ascii=False)

    assert str(tmp_path) not in serialized
    assert "parserPath" not in public["metadata"]
    assert "workingDirectory" not in public["metadata"]["nested"]
    assert public["metadata"]["nested"]["safeValue"] == "retained"
    assert "[redacted-path]" in public["error"]["message"]


def test_context_snippets_redact_absolute_paths_from_worker_content(tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    private_path = (tmp_path / "desktop-only" / "ready" / "private.txt").resolve()

    class PathLeakingReadyWorker:
        def process(self, request):
            content = f"safe prefix; local parser path={private_path}"
            return {
                "version": 1,
                "attachmentId": request["attachmentId"],
                "status": "ready",
                "chunks": [{"content": content}],
                "metadata": {
                    "contentExtracted": True,
                    "contentKind": "extracted_text",
                    "sourcePath": str(private_path),
                },
                "pythonVersion": "3.12.12",
                "truncated": False,
            }

    source = tmp_path / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=PathLeakingReadyWorker(),
    )
    queued = service.ingest(source, original_name="notes.txt")
    service.process(queued["attachment_id"])

    public = service.public_record(queued["attachment_id"])
    snippets = service.context_snippets([queued["attachment_id"]])

    assert "sourcePath" not in public["metadata"]
    assert str(tmp_path) not in json.dumps(public, ensure_ascii=False)
    assert str(tmp_path) not in json.dumps(snippets, ensure_ascii=False)
    assert "[redacted-path]" in snippets[0]

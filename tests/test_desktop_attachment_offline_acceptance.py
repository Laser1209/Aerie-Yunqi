from __future__ import annotations

import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON312 = PROJECT_ROOT / ".venv-attachments" / "Scripts" / "python.exe"
GENERATOR = PROJECT_ROOT / "tools" / "attachment_worker" / "synthetic_fixtures.py"


@pytest.fixture(scope="module")
def synthetic_fixtures(tmp_path_factory):
    if not PYTHON312.is_file():
        pytest.skip("isolated Python 3.12 attachment worker is not installed")
    root = tmp_path_factory.mktemp("desktop-attachment-formats")
    result = subprocess.run(
        [str(PYTHON312), str(GENERATOR), str(root)],
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return root


def _connection():
    from core.migrations import MigrationRunner, desktop_chat_continuity_migrations

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    MigrationRunner(connection).run(desktop_chat_continuity_migrations())
    return connection


class CleanScanner:
    def scan(self, path):
        return Path(path).is_file()


def test_isolated_worker_environment_has_required_versions():
    if not PYTHON312.is_file():
        pytest.skip("isolated Python 3.12 attachment worker is not installed")
    probe = subprocess.run(
        [
            str(PYTHON312),
            "-c",
            (
                "import importlib.metadata,sys;"
                "print('.'.join(map(str,sys.version_info[:3])));"
                "print(importlib.metadata.version('markitdown'));"
                "print(importlib.metadata.version('Pillow'));"
                "print(importlib.metadata.version('py7zr'));"
                "print(importlib.metadata.version('rarfile'))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
        check=False,
    )
    assert probe.returncode == 0
    assert probe.stdout.splitlines() == [
        "3.12.12", "0.1.6", "12.2.0", "1.1.0", "4.2"
    ]


def test_real_worker_offline_format_truth_matrix(synthetic_fixtures, tmp_path):
    from core.desktop_attachments import AttachmentWorkerClient, DesktopAttachmentService
    from tools.attachment_worker.synthetic_fixtures import MARKERS

    content_formats = {"txt", "py", "pdf", "docx", "xlsx", "pptx", "zip"}
    metadata_formats = {"png", "wav", "mp4", "rar", "7z", "exe", "apk"}
    worker = AttachmentWorkerClient(python_command=[str(PYTHON312)])
    service = DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "storage",
        scanner=CleanScanner(),
        worker=worker,
    )

    for source in sorted(synthetic_fixtures.iterdir()):
        format_name = source.suffix.lower().lstrip(".")
        queued = service.ingest(source, original_name=source.name)
        record = service.process(queued["attachment_id"])
        chunks = service.repository.chunks(queued["attachment_id"])
        content = "".join(item["content"] for item in chunks).replace("\\_", "_")
        metadata = record["metadata"]

        if format_name in content_formats:
            assert record["state"] == "ready", format_name
            assert metadata["contentExtracted"] is True, format_name
            assert metadata["contentKind"] == "extracted_text", format_name
            assert MARKERS[format_name] in content, format_name
        else:
            assert format_name in metadata_formats
            assert record["state"] == "ready", format_name
            assert record["analysis_mode"] == "metadata"
            assert metadata["contentExtracted"] is False
            assert metadata["contentKind"] == "metadata_only"
            assert metadata["semanticStatus"] == "not_required"
            if format_name in {"rar", "7z"}:
                manifest = metadata["archiveManifest"]
                assert manifest["memberCount"] == 1
                assert manifest["entries"][0]["name"] == "folder/metadata.txt"
                assert metadata["extractionMethod"] == "safe_archive_manifest"


def test_file_backed_records_survive_restart_download_and_delete(
    synthetic_fixtures,
    tmp_path,
):
    from core.desktop_attachments import AttachmentWorkerClient, DesktopAttachmentService
    from core.migrations import MigrationRunner, desktop_chat_continuity_migrations
    from tools.attachment_worker.synthetic_fixtures import MARKERS

    class Database:
        def __init__(self, path):
            self.path = path

        @contextmanager
        def connection(self):
            connection = sqlite3.connect(str(self.path), isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                yield connection
            finally:
                connection.close()

    database = Database(tmp_path / "restart.db")
    with database.connection() as connection:
        MigrationRunner(connection).run(desktop_chat_continuity_migrations())
        connection.commit()
    storage_root = tmp_path / "restart-storage"
    worker = AttachmentWorkerClient(python_command=[str(PYTHON312)])
    first = DesktopAttachmentService(
        database,
        storage_root=storage_root,
        scanner=CleanScanner(),
        worker=worker,
    )
    source = synthetic_fixtures / "synthetic.txt"
    queued = first.ingest(source, original_name="synthetic.txt")
    ready = first.process(queued["attachment_id"])
    assert ready["state"] == "ready"

    restarted = DesktopAttachmentService(
        database,
        storage_root=storage_root,
        scanner=CleanScanner(),
        worker=worker,
    )
    public = restarted.public_record(queued["attachment_id"])
    chunks = restarted.repository.chunks(queued["attachment_id"])
    assert public["state"] == "ready"
    assert MARKERS["txt"] in "".join(item["content"] for item in chunks)
    assert "storage_relpath" not in public
    download_path, filename = restarted.download_path(queued["attachment_id"])
    assert filename == "synthetic.txt"
    assert download_path.read_bytes() == source.read_bytes()
    assert restarted.remove(queued["attachment_id"]) is True
    assert restarted.repository.get(queued["attachment_id"]) is None

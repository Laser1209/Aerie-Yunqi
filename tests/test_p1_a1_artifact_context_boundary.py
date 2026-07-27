"""TDD RED tests for P1-A.1: C3.5 AI 上下文 Artifact 边界.

验证附件进入 AI 上下文时携带结构化边界信息：
- attachment_id: 附件唯一 ID
- trusted_boundary: 可信边界标记（desktop/local/unknown）
- part_id: 分部分 ID（页/sheet/slide）
- page_range / sheet_range / slide_range: 范围标识
- parser_warning: 解析器警告信息
- parser_status: 解析器状态
- sheet_names / cell_ranges: 表格专属字段
"""

import hashlib
import sqlite3

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


class MultiPagePdfWorker:
    """Mock worker returning multi-page PDF metadata with parser warning."""

    def process(self, request):
        chunks = [
            {
                "content": "Page 1 sentinel",
                "sha256": hashlib.sha256(b"Page 1 sentinel").hexdigest(),
            },
            {
                "content": "Page 2 sentinel",
                "sha256": hashlib.sha256(b"Page 2 sentinel").hexdigest(),
            },
        ]
        return {
            "version": 1,
            "attachmentId": request["attachmentId"],
            "status": "ready",
            "chunks": chunks,
            "metadata": {
                "contentExtracted": True,
                "contentKind": "extracted_text",
                "semanticStatus": "available",
                "pageCount": 2,
                "pageRanges": ["1-1", "2-2"],
                "parserWarning": "partial_ocr_fallback_on_page_2",
            },
            "pythonVersion": "3.12.12",
            "truncated": False,
        }


class MultiSheetExcelWorker:
    """Mock worker returning multi-sheet Excel metadata."""

    def process(self, request):
        chunks = [
            {
                "content": "Summary sheet data",
                "sha256": hashlib.sha256(b"Summary sheet data").hexdigest(),
            },
            {
                "content": "Details sheet data",
                "sha256": hashlib.sha256(b"Details sheet data").hexdigest(),
            },
        ]
        return {
            "version": 1,
            "attachmentId": request["attachmentId"],
            "status": "ready",
            "chunks": chunks,
            "metadata": {
                "contentExtracted": True,
                "contentKind": "extracted_text",
                "semanticStatus": "available",
                "sheetNames": ["Summary", "Details"],
                "cellRanges": ["A1:C10", "A1:E20"],
                "parserStatus": "ok",
            },
            "pythonVersion": "3.12.12",
            "truncated": False,
        }


class WarningWorker:
    """Mock worker returning parser warnings."""

    def process(self, request):
        content = "warning sentinel content"
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
                "contentExtracted": True,
                "contentKind": "extracted_text",
                "semanticStatus": "available",
                "parserWarning": "encoding_fallback_utf8_lossy",
            },
            "pythonVersion": "3.12.12",
            "truncated": False,
        }


def _make_service(tmp_path, worker):
    from core.desktop_attachments import DesktopAttachmentService

    return DesktopAttachmentService(
        _connection(),
        storage_root=tmp_path / "desktop-only",
        scanner=CleanScanner(),
        worker=worker,
    )


def test_multipage_pdf_artifact_contains_boundary_fields(tmp_path):
    """多页 PDF 附件进入上下文时包含 attachment_id、trusted_boundary、part_id、page_range、parser_warning"""
    service = _make_service(tmp_path, MultiPagePdfWorker())
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4\n%binary test content")
    queued = service.ingest(source, original_name="report.pdf")
    service.process(queued["attachment_id"])

    artifacts = service.context_artifacts([queued["attachment_id"]])

    assert len(artifacts) == 2
    first = artifacts[0]
    assert first["attachment_id"] == queued["attachment_id"]
    assert first["trusted_boundary"] == "desktop"
    assert first["part_id"]
    assert "page_range" in first
    assert first["page_range"]
    assert "parser_warning" in first
    assert first["parser_warning"]


def test_multisheet_excel_artifact_contains_sheet_and_cell_fields(tmp_path):
    """多 sheet Excel 附件进入上下文时包含 sheet_names、cell_ranges、parser_status"""
    service = _make_service(tmp_path, MultiSheetExcelWorker())
    source = tmp_path / "data.xlsx"
    source.write_bytes(b"PK\x03\x04" + b"\x00" * 20)
    queued = service.ingest(source, original_name="data.xlsx")
    service.process(queued["attachment_id"])

    artifacts = service.context_artifacts([queued["attachment_id"]])

    assert len(artifacts) == 2
    first = artifacts[0]
    assert first["attachment_id"] == queued["attachment_id"]
    assert first["trusted_boundary"] == "desktop"
    assert first["sheet_names"] == ["Summary", "Details"]
    assert first["cell_ranges"] == ["A1:C10", "A1:E20"]
    assert "parser_status" in first


def test_parser_warning_appears_in_artifact(tmp_path):
    """带解析警告的附件进入上下文时包含 warning 信息"""
    service = _make_service(tmp_path, WarningWorker())
    source = tmp_path / "warn.txt"
    source.write_text("hello", encoding="utf-8")
    queued = service.ingest(source, original_name="warn.txt")
    service.process(queued["attachment_id"])

    artifacts = service.context_artifacts([queued["attachment_id"]])

    assert len(artifacts) >= 1
    assert artifacts[0]["parser_warning"]
    assert "encoding_fallback" in artifacts[0]["parser_warning"]


def test_no_attachments_returns_empty_artifacts(tmp_path):
    """无附件时上下文不受影响"""
    service = _make_service(tmp_path, MultiPagePdfWorker())

    assert service.context_artifacts([]) == []
    assert service.context_artifacts(["nonexistent-id"]) == []


def test_trusted_boundary_marks_attachment_source(tmp_path):
    """trusted_boundary 字段标记附件来源可信度"""
    service = _make_service(tmp_path, MultiPagePdfWorker())
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4\n%test")
    queued = service.ingest(source, original_name="doc.pdf")
    service.process(queued["attachment_id"])

    artifacts = service.context_artifacts([queued["attachment_id"]])

    assert len(artifacts) >= 1
    for art in artifacts:
        assert art["trusted_boundary"] == "desktop"

"""Vector-index integration for desktop attachment chunks.

Verifies the chain: process() persists worker chunks -> index_attachment()
writes them to the vector store -> search_chunks()/context_snippets(query)
semantically retrieve the relevant chunk and inject it for the model.
"""
import hashlib
import os
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


class ChunkedWorker:
    def __init__(self, chunks):
        self._chunks = chunks

    def process(self, request):
        return {
            "version": 1,
            "attachmentId": request["attachmentId"],
            "status": "ready",
            "chunks": self._chunks,
            "metadata": {
                "parsed": True,
                "contentExtracted": True,
                "contentKind": "extracted_text",
                "semanticStatus": "available",
            },
            "pythonVersion": "3.12.12",
            "truncated": False,
        }


def _chunks():
    def chunk(ordinal, text):
        return {
            "ordinal": ordinal,
            "content": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    return [
        chunk(0, "季度营收报告开篇 市场概览 竞争对手分析 行业背景介绍 数据来源说明"),
        chunk(
            1,
            "核心结论: 2025年营收同比增长 23%, 毛利率提升至 41%, 主要受海外市场驱动。"
            "北美与欧洲销售强劲, 新客户占比显著提升。",
        ),
        chunk(
            2,
            "风险提示: 汇率波动 供应链成本上升 政策监管趋严 可能影响下半年业绩表现。",
        ),
    ]


def _service(tmp_path, conn, chunks):
    from core.desktop_attachments import DesktopAttachmentService
    from core.knowledge_indexer import _hash_embedding

    os.environ["AERIE_CHROMA_ATTACHMENTS_DIR"] = str(tmp_path / "chroma")
    return DesktopAttachmentService(
        conn,
        storage_root=tmp_path / "store",
        scanner=CleanScanner(),
        worker=ChunkedWorker(chunks),
        embedding_fn=_hash_embedding,
    )


def _ingest_and_process(tmp_path, conn, chunks):
    svc = _service(tmp_path, conn, chunks)
    src = tmp_path / "report.txt"
    src.write_text("source body", encoding="utf-8")
    record = svc.ingest(str(src), original_name="report.txt", mime_type="text/plain")
    attachment_id = record["attachment_id"]
    ready = svc.process(attachment_id)
    return svc, attachment_id, ready


def test_process_indexes_chunks_into_vector_store(tmp_path):
    conn = _connection()
    svc, attachment_id, ready = _ingest_and_process(tmp_path, conn, _chunks())
    assert ready["state"] == "ready"

    # process() already indexed the chunks; an explicit re-index is a no-op
    # (all chunks dedupe), which proves the process -> vector chain ran.
    result = svc.index_attachment(attachment_id, _chunks())
    assert result["indexed"] == 0
    assert result["deduped"] == 3


def test_reindex_is_idempotent(tmp_path):
    conn = _connection()
    svc, attachment_id, _ = _ingest_and_process(tmp_path, conn, _chunks())
    svc.index_attachment(attachment_id, _chunks())
    second = svc.index_attachment(attachment_id, _chunks())
    assert second["indexed"] == 0
    assert second["deduped"] == 3


def test_search_chunks_scoped_to_attachment(tmp_path):
    conn = _connection()
    svc, attachment_id, _ = _ingest_and_process(tmp_path, conn, _chunks())
    hits = svc.search_chunks([attachment_id], "海外市场增长", k=3)
    assert hits
    assert all(h["attachment_id"] == attachment_id for h in hits)
    assert any("海外市场" in h["content"] for h in hits)


def test_search_chunks_ignores_other_attachments(tmp_path):
    conn = _connection()
    svc, attachment_id, _ = _ingest_and_process(tmp_path, conn, _chunks())

    # A second attachment with unrelated content must not leak into scope.
    weather_text = "天气预报 多云转晴 最高气温 28 度"
    other_chunks = [
        {
            "ordinal": 0,
            "content": weather_text,
            "sha256": hashlib.sha256(weather_text.encode("utf-8")).hexdigest(),
        }
    ]
    src2 = tmp_path / "weather.txt"
    src2.write_text("source body", encoding="utf-8")
    rec2 = svc.ingest(str(src2), original_name="weather.txt", mime_type="text/plain")
    svc.process(rec2["attachment_id"])

    hits = svc.search_chunks([attachment_id], "海外市场增长", k=3)
    assert hits
    assert all(h["attachment_id"] == attachment_id for h in hits)


def test_context_snippets_with_query_includes_semantic_hit(tmp_path):
    conn = _connection()
    svc, attachment_id, _ = _ingest_and_process(tmp_path, conn, _chunks())

    flat = svc.context_snippets([attachment_id])
    assert flat and all("语义检索命中" not in s for s in flat)

    with_query = svc.context_snippets([attachment_id], query="海外市场增长")
    assert any("语义检索命中" in s and "海外市场" in s for s in with_query)

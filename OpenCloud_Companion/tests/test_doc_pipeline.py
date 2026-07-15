"""文档管道测试"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tools.doc_pipeline import DocumentPipeline


@pytest.fixture
def pipeline():
    return DocumentPipeline(brain=None)


class TestDocumentPipeline:
    """文档管道测试"""

    def test_available_without_markitdown(self, pipeline):
        """markitdown 可能不可用但不应崩溃"""
        # 只验证属性存在
        assert hasattr(pipeline, 'available')

    @pytest.mark.asyncio
    async def test_fallback_read_txt(self, pipeline):
        """纯文本文件回退读取"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Hello World 测试")
            tmp_path = f.name

        try:
            result = await pipeline.to_markdown(tmp_path)
            assert result is not None
            assert "Hello World" in result
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_fallback_read_md(self, pipeline):
        """Markdown 文件回退读取"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# 标题\n内容")
            tmp_path = f.name

        try:
            result = await pipeline.to_markdown(tmp_path)
            assert result is not None
            assert "标题" in result
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, pipeline):
        """不存在的文件返回 None"""
        result = await pipeline.to_markdown("nonexistent_file.xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_process_document_without_brain(self, pipeline):
        """无 brain 时 process_document 返回转换内容"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("测试文档内容")
            tmp_path = f.name

        try:
            result = await pipeline.process_document(tmp_path, "分析这个文档")
            assert result["result"]
            assert result["file"] is None
            assert result["token_saved_pct"] >= 0
        finally:
            os.unlink(tmp_path)

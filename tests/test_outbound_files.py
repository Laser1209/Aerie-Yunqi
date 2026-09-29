"""外发文件发布到 uploads（桌面端收文件的落地环节）。

背景（§十四 #72 / 开放例外 E6）：桌面端没有原生"收文件"通道，`SendQueue` 只注册了
qq / ilink。桌面端展示文件的成熟机制是生成图那条 `/uploads/<rel>` + 结构化附件卡片，
本模块把"把文件发布进去并造出卡片描述"这件事独立出来，便于单测与复用。
"""

from __future__ import annotations

import pytest

from core import outbound_files


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr(outbound_files, "_uploads_dir", lambda: root)
    return root


def test_publish_copies_file_and_rewrites_name(uploads, tmp_path):
    """复制进 uploads 且**用 uuid 重写文件名**（避免同名覆盖与目录结构外泄）。"""
    source = tmp_path / "我的报告.txt"
    source.write_text("内容", encoding="utf-8")

    rel = outbound_files.publish_to_uploads(source)

    assert rel is not None
    assert rel.endswith(".txt")
    assert "我的报告" not in rel            # uuid 名，不含原名
    assert (uploads / rel).read_text(encoding="utf-8") == "内容"
    assert source.is_file()                 # 原文件不动


def test_publish_creates_missing_uploads_dir(uploads, tmp_path):
    assert not uploads.exists()
    source = tmp_path / "a.md"
    source.write_text("x", encoding="utf-8")

    assert outbound_files.publish_to_uploads(source) is not None
    assert uploads.is_dir()


def test_publish_returns_none_for_missing_source(uploads, tmp_path):
    """源文件不存在 → None（调用方据此如实报失败，不得静默当成功）。"""
    assert outbound_files.publish_to_uploads(tmp_path / "ghost.txt") is None


def test_publish_returns_none_when_copy_fails(uploads, tmp_path, monkeypatch):
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(outbound_files.shutil, "copyfile", boom)
    assert outbound_files.publish_to_uploads(source) is None


def test_build_file_attachment_keeps_display_name_and_marks_ready():
    attachment = outbound_files.build_file_attachment(
        "abc123.docx", display_name="季度报告.docx", size_bytes=2048,
    )

    assert attachment is not None
    assert attachment["category"] == "file"
    assert attachment["state"] == "ready"      # ready 才会渲染「打开」按钮
    assert attachment["name"] == "季度报告.docx"
    assert attachment["extension"] == "docx"
    assert attachment["size"] == 2048
    assert attachment["url"] == "/uploads/abc123.docx"
    assert attachment["content_type"].endswith("wordprocessingml.document")


def test_build_file_attachment_falls_back_to_stored_name():
    attachment = outbound_files.build_file_attachment("abc.txt")
    assert attachment is not None
    assert attachment["name"] == "abc.txt"
    assert "size" not in attachment            # 未给大小就不编一个


def test_build_file_attachment_rejects_blank_relative_path():
    assert outbound_files.build_file_attachment("") is None
    assert outbound_files.build_file_attachment("   ") is None


def test_build_file_attachment_strips_leading_slash():
    """容忍带前导 / 的写法，避免拼出 //uploads。"""
    attachment = outbound_files.build_file_attachment("/abc.txt")
    assert attachment is not None
    assert attachment["url"] == "/uploads/abc.txt"

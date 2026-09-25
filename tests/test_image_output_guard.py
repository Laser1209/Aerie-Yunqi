"""image_output_guard: LLM 图片伪标记剥离 + 历史消息重写测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"e:\Agent_reply")

from core.image_output_guard import (  # noqa: E402
    build_image_attachment,
    rewrite_image_content,
    strip_llm_image_artifacts,
    uploads_relative_path,
)


class TestStripLlmImageArtifacts:
    def test_removes_fabricated_markdown_image(self):
        text = "既然你要看照片：![图片](http://127.0.0.1:7890/uploads/abc123.png)"
        out = strip_llm_image_artifacts(text)
        assert "![" not in out
        assert "abc123" not in out
        assert "既然你要看照片" in out

    def test_removes_relative_markdown_image(self):
        out = strip_llm_image_artifacts("看图 ![图片](/uploads/x.png) 怎么样")
        assert "![" not in out
        assert "/uploads/x.png" not in out
        assert "看图" in out and "怎么样" in out

    def test_removes_image_content_description_line(self):
        text = "发你了\n[图片内容] 她坐在窗边微笑，午后阳光"
        out = strip_llm_image_artifacts(text)
        assert "[图片内容]" not in out
        assert "窗边" not in out
        assert "发你了" in out

    def test_removes_bare_image_placeholder(self):
        assert strip_llm_image_artifacts("好的[图片]") == "好的"
        assert strip_llm_image_artifacts("[图片:自拍]给你") == "给你"

    def test_keeps_emoji_sticker_marker(self):
        # [表情包] 是另一套交付机制，不能被图片守卫误伤
        out = strip_llm_image_artifacts("哼 [表情包] 不理你了")
        assert "[表情包]" in out
        assert "不理你了" in out

    def test_plain_text_unchanged(self):
        text = "今天天气不错，我们出去走走吧。"
        assert strip_llm_image_artifacts(text) == text

    def test_empty_and_none(self):
        assert strip_llm_image_artifacts("") == ""
        assert strip_llm_image_artifacts(None) == ""  # type: ignore[arg-type]

    def test_collapses_blank_lines(self):
        out = strip_llm_image_artifacts("第一句\n![图片](http://x/a.png)\n\n\n第二句")
        assert out == "第一句\n\n第二句"


class TestUploadsRelativePath:
    def test_absolute_localhost_url(self):
        assert uploads_relative_path(
            "http://127.0.0.1:7890/uploads/abc.png",
        ) == "abc.png"

    def test_relative_url_with_nested_asset_dir(self):
        assert uploads_relative_path(
            "/uploads/.image_assets/thumbs/abc.png",
        ) == ".image_assets/thumbs/abc.png"

    def test_rejects_non_uploads_url(self):
        assert uploads_relative_path("http://evil.example.com/x.png") == ""
        assert uploads_relative_path("/static/x.png") == ""

    def test_rejects_data_uri(self):
        assert uploads_relative_path("data:image/png;base64,AAAA") == ""

    def test_rejects_path_traversal(self):
        assert uploads_relative_path("/uploads/../etc/passwd") == ""
        assert uploads_relative_path("/uploads/a\\..\\b.png") == ""


class TestBuildImageAttachment:
    def test_fields_match_qq_channel_contract(self):
        att = build_image_attachment("abc.png")
        assert att is not None
        assert att["category"] == "image"
        assert att["name"] == "abc.png"
        assert att["url"] == "/uploads/abc.png"
        assert att["thumbnail_url"] == "/uploads/abc.png"
        assert att["content_type"] == "image/png"

    def test_nested_path_content_type(self):
        att = build_image_attachment(".image_assets/thumbs/x.jpg")
        assert att is not None
        assert att["name"] == "x.jpg"
        assert att["content_type"] == "image/jpeg"

    def test_empty_path_returns_none(self):
        assert build_image_attachment("") is None


class TestRewriteImageContent:
    def test_no_markdown_image_is_noop(self, tmp_path: Path):
        content, attachments, changed = rewrite_image_content("纯文本", tmp_path)
        assert content == "纯文本"
        assert attachments == []
        assert changed is False

    def test_fake_url_is_stripped_without_attachment(self, tmp_path: Path):
        text = "给你看：![图片](http://127.0.0.1:7890/uploads/deadbeef.png)"
        content, attachments, changed = rewrite_image_content(text, tmp_path)
        assert changed is True
        assert attachments == []
        assert "![" not in content
        assert "deadbeef" not in content
        assert "给你看" in content

    def test_real_file_becomes_structured_attachment(self, tmp_path: Path):
        asset = tmp_path / "realfile.png"
        asset.write_bytes(b"fake-png-bytes")
        text = (
            "![图片](http://127.0.0.1:7890/uploads/realfile.png)\n"
            "[图片内容] 一张她的自拍"
        )
        content, attachments, changed = rewrite_image_content(text, tmp_path)
        assert changed is True
        assert len(attachments) == 1
        assert attachments[0]["url"] == "/uploads/realfile.png"
        # 正文没有剩余文字时用 [图片] 描述兜底，保留给 LLM 上下文的语义
        assert content == "[图片] 一张她的自拍"

    def test_real_file_with_remaining_text_keeps_text(self, tmp_path: Path):
        asset = tmp_path / "r.png"
        asset.write_bytes(b"x")
        text = "先说好哦：![图片](/uploads/r.png)\n这张怎么样？"
        content, attachments, changed = rewrite_image_content(text, tmp_path)
        assert changed is True
        assert len(attachments) == 1
        assert "先说好哦" in content
        assert "这张怎么样" in content
        assert "![" not in content

    def test_duplicate_url_produces_single_attachment(self, tmp_path: Path):
        asset = tmp_path / "dup.png"
        asset.write_bytes(b"x")
        text = (
            "![图片](/uploads/dup.png)![图片](http://127.0.0.1:7890/uploads/dup.png)"
        )
        _, attachments, changed = rewrite_image_content(text, tmp_path)
        assert changed is True
        assert len(attachments) == 1

    def test_mixed_real_and_fake_keeps_only_real(self, tmp_path: Path):
        (tmp_path / "real.png").write_bytes(b"x")
        text = "![图片](/uploads/real.png)![图片](/uploads/ghost.png)"
        content, attachments, changed = rewrite_image_content(text, tmp_path)
        assert changed is True
        assert [a["name"] for a in attachments] == ["real.png"]
        assert "ghost" not in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

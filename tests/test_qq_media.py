"""Tests for core.qq_media — QQ voice / sticker multimodal preprocessing.

Covers CQ 段解析、face 映射、语音转写、图片/表情包视觉解析、以及整体
preprocess 的降级回退，确保原始 CQ 码/JSON 永不泄漏给 AI 或前端。
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from core import qq_media
from core.qq_media import QQMediaPreprocessor, face_text


# ── face_text 映射 ───────────────────────────────
def test_face_text_known_id():
    assert face_text("14") == "微笑"
    assert face_text(14) == "微笑"
    assert face_text("0") == "惊讶"


def test_face_text_unknown_id_falls_back():
    assert face_text("99999") == "[QQ表情 99999]"


def test_face_text_empty_falls_back():
    assert face_text("") == "[QQ表情]"
    assert face_text(None) == "[QQ表情]"


# ── CQ 码解析 ─────────────────────────────────────
def test_parse_cq_preserves_order_and_text():
    pre = QQMediaPreprocessor()
    segs = pre._parse_cq("hello[CQ:face,id=14]world[CQ:record,file=x.silk]")
    types = [s["type"] for s in segs]
    assert types == ["text", "face", "text", "record"]
    assert segs[0]["data"]["text"] == "hello"
    assert segs[2]["data"]["text"] == "world"
    assert segs[1]["data"]["id"] == "14"


def test_parse_cq_no_code_single_text():
    pre = QQMediaPreprocessor()
    segs = pre._parse_cq("纯文本消息")
    assert segs == [{"type": "text", "data": {"text": "纯文本消息"}}]


# ── 本地文件路径 / base64 解析 ─────────────────────
def test_resolve_local_file_base64(tmp_path):
    payload = b"fake-audio-bytes"
    b64 = "base64://" + base64.b64encode(payload).decode("ascii")
    pre = QQMediaPreprocessor(media_dir=tmp_path)
    path = qq_media._resolve_local_file({"file": b64})
    assert path is not None
    assert _read_bytes(path) == payload


def test_resolve_local_file_absolute(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    assert qq_media._resolve_local_file({"file": str(f)}) == str(f)


# ── 语音：转写 + 附件结构 ─────────────────────────
@pytest.mark.asyncio
async def test_voice_transcribed(tmp_path):
    fake_audio = base64.b64encode(b"audio-bytes").decode("ascii")
    qq = MagicMock()
    qq.get_record = AsyncMock(return_value={"status": "ok", "data": {"file": fake_audio}})

    sf = MagicMock()
    sf.transcribe = AsyncMock(return_value="我好想你")
    sf.describe = AsyncMock(return_value="")

    pre = QQMediaPreprocessor(qq_client=qq, sf_client=sf, media_dir=tmp_path)
    msg = _msg_with_segments([{"type": "record", "data": {"file": "x.silk"}}])

    content, atts = await pre.preprocess(msg)

    assert "我好想你" in content
    assert atts[0]["category"] == "audio"
    assert atts[0]["transcript"] == "我好想你"
    qq.get_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_no_transcript_falls_back_to_label(tmp_path):
    qq = MagicMock()
    qq.get_record = AsyncMock(return_value={"status": "ok", "data": {"file": "some-local-path"}})
    sf = MagicMock()
    sf.transcribe = AsyncMock(return_value="")
    sf.describe = AsyncMock(return_value="")

    pre = QQMediaPreprocessor(qq_client=qq, sf_client=sf, media_dir=tmp_path)
    msg = _msg_with_segments([{"type": "record", "data": {"file": "x.silk"}}])

    content, atts = await pre.preprocess(msg)
    assert "[语音]" in content
    assert atts[0]["category"] == "audio"
    assert atts[0]["transcript"] == ""


# ── 图片 / 表情包：视觉分类 + 描述 + 缩略图落库 ──────────
@pytest.mark.asyncio
async def test_image_photo_described_and_persisted(tmp_path, monkeypatch):
    fake_img = base64.b64encode(b"image-bytes").decode("ascii")
    qq = MagicMock()
    qq.get_image = AsyncMock(return_value={"status": "ok", "data": {"file": fake_img}})

    sf = MagicMock()
    sf.classify_and_describe = AsyncMock(return_value=("photo", "一张阳光下的猫猫照片"))
    sf.transcribe = AsyncMock(return_value="")

    saved = {
        "status": "ok",
        "url": "/uploads/q.png",
        "thumbnail_url": "/uploads/.image_assets/thumbs/t.png",
        "size": 10,
        "saved_as": "q.png",
    }
    monkeypatch.setattr(
        "core.attachment_handler.process_image_upload",
        lambda **kw: dict(saved),
    )

    pre = QQMediaPreprocessor(qq_client=qq, sf_client=sf, media_dir=tmp_path)
    msg = _msg_with_segments([{"type": "image", "data": {"file": "f.png"}}])

    content, atts = await pre.preprocess(msg)

    assert "[图片:" in content
    assert "猫猫" in content
    assert atts[0]["category"] == "image"
    assert atts[0]["name"] == "图片"
    assert atts[0]["url"] == "/uploads/q.png"
    assert atts[0]["thumbnail_url"]
    qq.get_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_image_sticker_labeled_as_sticker(tmp_path, monkeypatch):
    fake_img = base64.b64encode(b"image-bytes").decode("ascii")
    qq = MagicMock()
    qq.get_image = AsyncMock(return_value={"status": "ok", "data": {"file": fake_img}})

    sf = MagicMock()
    sf.classify_and_describe = AsyncMock(return_value=("sticker", "一个搞笑的表情包"))
    sf.transcribe = AsyncMock(return_value="")

    saved = {
        "status": "ok",
        "url": "/uploads/q.png",
        "thumbnail_url": "/uploads/.image_assets/thumbs/t.png",
        "size": 10,
        "saved_as": "q.png",
    }
    monkeypatch.setattr(
        "core.attachment_handler.process_image_upload",
        lambda **kw: dict(saved),
    )

    pre = QQMediaPreprocessor(qq_client=qq, sf_client=sf, media_dir=tmp_path)
    msg = _msg_with_segments([{"type": "image", "data": {"file": "f.png"}}])

    content, atts = await pre.preprocess(msg)

    assert "[表情包:" in content
    assert atts[0]["name"] == "表情包"


@pytest.mark.asyncio
async def test_image_vision_fail_falls_back_to_label(tmp_path):
    qq = MagicMock()
    qq.get_image = AsyncMock(return_value={"status": "ok", "data": {"file": "some-local-path"}})
    sf = MagicMock()
    sf.classify_and_describe = AsyncMock(return_value=("unknown", ""))
    sf.transcribe = AsyncMock(return_value="")

    pre = QQMediaPreprocessor(qq_client=qq, sf_client=sf, media_dir=tmp_path)
    msg = _msg_with_segments([{"type": "image", "data": {"file": "f.png"}}])

    content, atts = await pre.preprocess(msg)
    assert "[图片]" in content
    assert atts[0]["name"] == "图片"


# ── 视觉分类解析（type/desc 两行结构）────────────────
def test_parse_classify_photo():
    assert qq_media._SFClient._parse_classify("type: photo\ndesc: 一张海边的照片") == ("photo", "一张海边的照片")


def test_parse_classify_sticker():
    assert qq_media._SFClient._parse_classify("type: sticker\ndesc: 一个搞笑表情包") == ("sticker", "一个搞笑表情包")


def test_parse_classify_no_format_falls_back_to_desc():
    kind, desc = qq_media._SFClient._parse_classify("type: sticker\n一个卡通猫猫")
    assert kind == "sticker"
    assert "卡通猫猫" in desc


def test_parse_classify_empty():
    assert qq_media._SFClient._parse_classify("") == ("unknown", "")


# ── face 表情 + 文本混合 ──────────────────────────
@pytest.mark.asyncio
async def test_face_and_text_mix(tmp_path):
    pre = QQMediaPreprocessor(media_dir=tmp_path)
    msg = _msg_with_segments([
        {"type": "text", "data": {"text": "你猜"}},
        {"type": "face", "data": {"id": "14"}},
    ])
    content, atts = await pre.preprocess(msg)
    assert "你猜" in content
    assert "微笑" in content
    assert atts == []


# ── 空/全失败 → 占位，不泄漏 CQ ───────────────────
@pytest.mark.asyncio
async def test_no_segments_returns_raw_content():
    pre = QQMediaPreprocessor()
    msg = _msg_with_segments([])
    msg.content = "只有文本"
    content, atts = await pre.preprocess(msg)
    assert content == "只有文本"
    assert atts == []


@pytest.mark.asyncio
async def test_all_segments_fail_falls_back_to_placeholder(tmp_path):
    qq = MagicMock()
    qq.get_record = AsyncMock(return_value=None)
    sf = MagicMock()
    sf.transcribe = AsyncMock(return_value="")
    sf.describe = AsyncMock(return_value="")

    pre = QQMediaPreprocessor(qq_client=qq, sf_client=sf, media_dir=tmp_path)
    msg = _msg_with_segments([{"type": "record", "data": {"file": ""}}])
    content, atts = await pre.preprocess(msg)
    assert content == "[语音]"
    assert atts[0]["category"] == "audio"


# ── helpers ───────────────────────────────────────
def _msg_with_segments(segments):
    from communication.message import IncomingMessage

    msg = IncomingMessage.from_onebot_event({
        "sender": {"user_id": 123},
        "message_type": "private",
        "message": segments,
        "raw_message": "",
    })
    return msg


def _read_bytes(path: str) -> bytes:
    from pathlib import Path

    return Path(path).read_bytes()

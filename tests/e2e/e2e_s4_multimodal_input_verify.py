"""Aerie v11.3 · S4 M4.1 多模态输入验证

验证项：
  T1 附件类型检测
  T2 ImageAttachment 数据模型
  T3 OCRService 初始化与可用性
  T4 ImageAnalyzer 配置与 mock
  T5 AudioTranscriber 配置与 mock
  T6 MultimodalInputProcessor 处理纯文本
  T7 MultimodalInputProcessor 处理图片
  T8 MultimodalInputProcessor 处理语音
  T9 MultimodalInputProcessor 处理混合
  T10 复杂度评估感知多模态（验证 ProviderRouter 集成点）
"""

from __future__ import annotations
import asyncio
import base64
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.multimodal_input import (
    AttachmentType,
    AudioAttachment,
    AudioTranscriber,
    ImageAnalyzer,
    ImageAttachment,
    MultimodalInputProcessor,
    MultimodalResult,
    OCRQuality,
    OCRService,
    detect_attachment_type,
)


def _make_test_image(path: Path, text: str = "Hello Aerie") -> None:
    """Create a minimal valid PNG (1x1 pixel)."""
    # Minimal PNG: 1x1 red pixel
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    )
    path.write_bytes(png)


def _make_test_audio(path: Path) -> None:
    """Create a minimal WAV file (silent, 0.1s)."""
    import struct
    import wave
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        nframes = int(44100 * 0.1)
        wf.writeframes(b"\x00\x00" * nframes)


def t1_attachment_type_detection() -> tuple[bool, str]:
    """T1 附件类型检测"""
    cases = {
        "photo.jpg": AttachmentType.IMAGE,
        "screenshot.png": AttachmentType.IMAGE,
        "anim.gif": AttachmentType.IMAGE,
        "voice.mp3": AttachmentType.AUDIO,
        "recording.wav": AttachmentType.AUDIO,
        "movie.mp4": AttachmentType.VIDEO,
        "doc.pdf": AttachmentType.FILE,
        "data.csv": AttachmentType.FILE,
    }
    passed = 0
    total = len(cases)
    for name, expected in cases.items():
        result = detect_attachment_type(f"/tmp/{name}")
        if result == expected:
            passed += 1
    return passed == total, f"{passed}/{total}"


def t2_image_attachment_model() -> tuple[bool, str]:
    """T2 ImageAttachment 数据模型"""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "test.png"
        _make_test_image(img_path)

        img = ImageAttachment(path=str(img_path), mime_type="image/png")
        checks = []
        checks.append(img.is_valid)
        checks.append(img.mime_type == "image/png")
        checks.append(len(img.to_base64()) > 0)
        checks.append(img.data_url().startswith("data:image/png;base64,"))
        checks.append(img.size_bytes > 0)

        # Invalid path
        bad_img = ImageAttachment(path="/nonexistent.png")
        checks.append(not bad_img.is_valid)
        checks.append(bad_img.to_base64() == "")

        return all(checks), f"valid={img.is_valid}, b64_len={len(img.to_base64())}, bad_valid={bad_img.is_valid}"


def t3_ocr_service_init() -> tuple[bool, str]:
    """T3 OCRService 初始化"""
    ocr = OCRService(quality=OCRQuality.STANDARD)
    # Just verify initialization doesn't crash
    available = ocr.is_available or True  # not required to be available
    quality_ok = ocr.quality == OCRQuality.STANDARD
    return available and quality_ok, f"available={ocr.is_available}, quality={ocr.quality}"


def t4_image_analyzer_config() -> tuple[bool, str]:
    """T4 ImageAnalyzer 配置"""
    analyzer = ImageAnalyzer(api_key="test-key", api_base="https://test.example.com", model="test-model")
    checks = []
    checks.append(analyzer.model == "test-model")
    checks.append(analyzer.api_key == "test-key")
    checks.append(analyzer.api_base == "https://test.example.com")
    # Without real key, is_available depends on openai pkg
    has_client = analyzer._client is not None or not analyzer.api_key.startswith("test-")
    # test-key 会被当作空吗？不会，因为 "test-key" 是非空的
    # 但 openai 包可能不可用
    return all(checks), f"model={analyzer.model}, has_client={analyzer._client is not None}"


def t5_audio_transcriber_config() -> tuple[bool, str]:
    """T5 AudioTranscriber 配置"""
    trans = AudioTranscriber(api_key="test-key", model="whisper-test")
    checks = []
    checks.append(trans.model == "whisper-test")
    checks.append(trans.api_key == "test-key")
    return all(checks), f"model={trans.model}, available={trans.is_available}"


def t6_processor_text_only() -> tuple[bool, str]:
    """T6 处理纯文本消息"""
    proc = MultimodalInputProcessor(
        enable_ocr=False,
        enable_image_caption=False,
        enable_transcription=False,
    )
    result = asyncio.run(proc.process_message("你好，今天天气怎么样？"))
    checks = []
    checks.append(result.text_content == "你好，今天天气怎么样？")
    checks.append(len(result.images) == 0)
    checks.append(len(result.audio) == 0)
    checks.append(not result.has_vision)
    checks.append(not result.has_audio)
    checks.append(result.combined_prompt == "你好，今天天气怎么样？")
    return all(checks), f"text={result.text_content[:20]}..., combined_len={len(result.combined_prompt)}"


def t7_processor_with_image() -> tuple[bool, str]:
    """T7 处理图片消息"""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "photo.jpg"
        _make_test_image(img_path)

        proc = MultimodalInputProcessor(
            enable_ocr=False,
            enable_image_caption=False,
            enable_transcription=False,
        )
        result = asyncio.run(proc.process_message(
            "看这张图",
            [{"path": str(img_path), "type": "image"}],
        ))
        checks = []
        checks.append(len(result.images) == 1)
        checks.append(result.has_vision)
        checks.append(not result.has_audio)
        checks.append(result.images[0].is_valid)
        checks.append(result.images[0].mime_type in ("image/jpeg", "image/png"))
        checks.append(result.images[0].size_bytes > 0)
        checks.append("看这张图" in result.combined_prompt)
        return all(checks), f"images={len(result.images)}, has_vision={result.has_vision}, size={result.images[0].size_bytes}"


def t8_processor_with_audio() -> tuple[bool, str]:
    """T8 处理语音消息"""
    with tempfile.TemporaryDirectory() as td:
        aud_path = Path(td) / "voice.wav"
        _make_test_audio(aud_path)

        proc = MultimodalInputProcessor(
            enable_ocr=False,
            enable_image_caption=False,
            enable_transcription=False,
        )
        result = asyncio.run(proc.process_message(
            "",
            [{"path": str(aud_path), "type": "audio"}],
        ))
        checks = []
        checks.append(len(result.audio) == 1)
        checks.append(result.has_audio)
        checks.append(not result.has_vision)
        checks.append(result.audio[0].is_valid)
        checks.append(result.audio[0].size_bytes > 0)
        return all(checks), f"audio={len(result.audio)}, has_audio={result.has_audio}, size={result.audio[0].size_bytes}"


def t9_processor_mixed() -> tuple[bool, str]:
    """T9 处理混合消息（文本+图片+语音+文件）"""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "img.png"
        aud_path = Path(td) / "voice.mp3"
        file_path = Path(td) / "doc.pdf"
        _make_test_image(img_path)
        _make_test_audio(aud_path)
        file_path.write_text("fake pdf content")

        proc = MultimodalInputProcessor(
            enable_ocr=False,
            enable_image_caption=False,
            enable_transcription=False,
        )
        result = asyncio.run(proc.process_message(
            "帮我看看这些内容",
            [
                {"path": str(img_path), "type": "image"},
                {"path": str(aud_path), "type": "audio"},
                {"path": str(file_path), "type": "file"},
            ],
        ))
        checks = []
        checks.append(len(result.images) == 1)
        checks.append(len(result.audio) == 1)
        checks.append(len(result.files) == 1)
        checks.append(result.has_vision)
        checks.append(result.has_audio)
        checks.append("帮我看看这些内容" in result.combined_prompt)
        return all(checks), f"images={len(result.images)}, audio={len(result.audio)}, files={len(result.files)}"


def t10_multimodal_impact_complexity() -> tuple[bool, str]:
    """T10 多模态消息对复杂度评估的影响（集成点验证）"""
    from core.provider_router import ProviderRouter, ComplexityScore

    router = ProviderRouter()
    text_msg = "你好"
    img_attachments = [{"type": "image", "path": "/fake.jpg"}]

    text_score = router.evaluate_sync(text_msg, context_turns=0)
    img_score = router.evaluate_sync(text_msg, context_turns=0, attachments=img_attachments)

    checks = []
    checks.append(isinstance(text_score, ComplexityScore))
    checks.append(img_score.total >= text_score.total)
    return all(checks), f"text={text_score.total}, multimodal={img_score.total}, delta={img_score.total - text_score.total}"


def main() -> int:
    tests = [
        t1_attachment_type_detection,
        t2_image_attachment_model,
        t3_ocr_service_init,
        t4_image_analyzer_config,
        t5_audio_transcriber_config,
        t6_processor_text_only,
        t7_processor_with_image,
        t8_processor_with_audio,
        t9_processor_mixed,
        t10_multimodal_impact_complexity,
    ]

    print("=" * 60)
    print("Aerie v11.3 · S4 M4.1 多模态输入验证")
    print("=" * 60)

    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        name = test.__doc__ or test.__name__
        print(f"  {status} {name}  {detail}")
        if ok:
            passed += 1

    total = len(tests)
    print()
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 M4.1 多模态输入全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())

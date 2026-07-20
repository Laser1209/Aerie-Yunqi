import base64
import io

import pytest
from PIL import Image

from core.brain import Brain


def test_load_providers_puts_grok_before_openai(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "grok-key")
    monkeypatch.setenv("GROK_BASE_URL", "https://mysubapi.com/v1")
    monkeypatch.setenv("GROK_MODEL", "grok-4.5")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_FREE_MODEL", raising=False)

    brain = Brain()

    assert brain._providers[0] == {
        "name": "grok",
        "url": "https://mysubapi.com/v1",
        "key": "grok-key",
        "model": "grok-4.5",
        "supports_tools": False,
    }
    assert brain._providers[1]["name"] == "openai"


@pytest.mark.asyncio
async def test_compose_brief_keeps_openai_for_article_generation(monkeypatch):
    brain = Brain()
    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["preferred_provider"] = kwargs.get("preferred_provider")
        from core.brain import BrainResponse
        return BrainResponse(text="### 大模型 & AI Agent\n测试摘要")

    monkeypatch.setattr(brain, "chat", fake_chat)

    result = await brain.compose_brief({"date": "2026-07-19", "ai_news": []})

    assert captured["preferred_provider"] == "openai"
    assert "测试摘要" in result


@pytest.mark.asyncio
async def test_disable_model_calls_returns_local_stub_without_provider_call(
    monkeypatch,
):
    monkeypatch.setenv("AERIE_DISABLE_MODEL_CALLS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    brain = Brain()

    async def fail_provider_call(*args, **kwargs):
        raise AssertionError("provider should not be called")

    monkeypatch.setattr(brain, "_call_provider", fail_provider_call)

    result = await brain.chat([{"role": "user", "content": "smoke"}])

    assert result.provider == "disabled"
    assert result.model == "aerie-local-smoke-stub"
    assert result.text


@pytest.mark.asyncio
async def test_summarize_news_batch_keeps_openai_for_article_generation(monkeypatch):
    brain = Brain()
    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["preferred_provider"] = kwargs.get("preferred_provider")
        from core.brain import BrainResponse
        return BrainResponse(text='[{"id": 0, "summary": "生成摘要"}]')

    monkeypatch.setattr(brain, "chat", fake_chat)

    items = [{"title": "标题", "summary": "短", "url": "https://example.com", "source": "x"}]
    result = await brain.summarize_news_batch(items)

    assert captured["preferred_provider"] == "openai"
    assert result[0]["summary"] == "生成摘要"


def _png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (4, 3), color=(120, 160, 210)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_generate_image_uses_explicit_openai_compatible_provider(monkeypatch):
    monkeypatch.setenv("AERIE_IMAGE_API_KEY", "image-provider-key")
    monkeypatch.setenv("AERIE_IMAGE_BASE_URL", "https://image.example/v1")
    monkeypatch.setenv("AERIE_IMAGE_MODEL", "image-test-model")
    brain = Brain()
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": _png_b64()}]}

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("core.brain.httpx.post", fake_post)

    result = brain.generate_image("draw a calm lake")

    assert result["status"] == "ok"
    assert result["provider"] == "openai_compatible_image"
    assert result["model"] == "image-test-model"
    assert result["mime_type"] == "image/png"
    assert result["image_bytes_b64"]
    assert calls[0]["url"] == "https://image.example/v1/images/generations"
    assert calls[0]["headers"]["Authorization"] == "Bearer image-provider-key"
    assert calls[0]["json"]["prompt"] == "draw a calm lake"
    assert calls[0]["json"]["response_format"] == "b64_json"


def test_generate_image_without_explicit_provider_keeps_stub(monkeypatch):
    monkeypatch.delenv("AERIE_IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_API_KEY", raising=False)
    brain = Brain()

    def fail_post(*args, **kwargs):
        raise AssertionError("image provider should not be called without explicit image key")

    monkeypatch.setattr("core.brain.httpx.post", fail_post)

    result = brain.generate_image("draw a calm lake")

    assert result["status"] == "stub"
    assert result["output_path"] is None


def test_speak_text_uses_explicit_openai_compatible_tts_provider(monkeypatch):
    monkeypatch.setenv("AERIE_TTS_API_KEY", "tts-provider-key")
    monkeypatch.setenv("AERIE_TTS_BASE_URL", "https://tts.example/v1")
    monkeypatch.setenv("AERIE_TTS_MODEL", "tts-test-model")
    monkeypatch.setenv("AERIE_TTS_VOICE", "verse")
    monkeypatch.setenv("AERIE_TTS_FORMAT", "wav")
    brain = Brain()
    calls = []

    class Response:
        content = b"RIFFfake-wav"

        def raise_for_status(self):
            return None

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("core.brain.httpx.post", fake_post)

    result = brain.speak_text("给我一句短语音")

    assert result["status"] == "ok"
    assert result["provider"] == "openai_compatible_tts"
    assert result["model"] == "tts-test-model"
    assert result["voice"] == "verse"
    assert result["mime_type"] == "audio/wav"
    assert base64.b64decode(result["audio_bytes_b64"]) == b"RIFFfake-wav"
    assert result["wav_path"] is None
    assert calls[0]["url"] == "https://tts.example/v1/audio/speech"
    assert calls[0]["headers"]["Authorization"] == "Bearer tts-provider-key"
    assert calls[0]["json"] == {
        "model": "tts-test-model",
        "input": "给我一句短语音",
        "voice": "verse",
        "response_format": "wav",
    }


def test_speak_text_without_explicit_provider_keeps_stub(monkeypatch):
    monkeypatch.delenv("AERIE_TTS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_TTS_API_KEY", raising=False)
    brain = Brain()

    def fail_post(*args, **kwargs):
        raise AssertionError("TTS provider should not be called without explicit TTS key")

    monkeypatch.setattr("core.brain.httpx.post", fail_post)

    result = brain.speak_text("给我一句短语音")

    assert result["status"] == "stub"
    assert result["wav_path"] is None


def test_see_image_uses_explicit_openai_compatible_vision_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIE_VISION_API_KEY", "vision-provider-key")
    monkeypatch.setenv("AERIE_VISION_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("AERIE_VISION_MODEL", "vision-test-model")
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(base64.b64decode(_png_b64()))
    brain = Brain()
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "a quiet blue test image"}}]}

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("core.brain.httpx.post", fake_post)

    result = brain.see_image(str(image_path), "describe")

    assert result["status"] == "ok"
    assert result["answer"] == "a quiet blue test image"
    assert result["provider"] == "openai_compatible_vision"
    assert result["model"] == "vision-test-model"
    assert calls[0]["url"] == "https://vision.example/v1/chat/completions"
    content = calls[0]["json"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

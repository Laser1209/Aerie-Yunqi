from __future__ import annotations

import sys
import types

import pytest

from voice.multimodal_output import EnhancedTTSEngine, TTSProvider, VoiceStyle


@pytest.mark.asyncio
async def test_enhanced_tts_openai_provider_writes_audio_without_real_network(
    tmp_path,
    monkeypatch,
):
    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        content = b"RIFFfake-openai-tts"
        text = ""

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def post(self, url, *, headers, json):
            calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "timeout": self.timeout,
                }
            )
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))
    monkeypatch.chdir(tmp_path)

    engine = EnhancedTTSEngine(
        api_key="tts-provider-key",
        provider=TTSProvider.OPENAI,
        default_style=VoiceStyle.NIGHT,
    )

    result = await engine.synthesize(
        "晚安，测试语音",
        style=VoiceStyle.NIGHT,
        output_name="night-test",
        use_cache=False,
    )

    assert result.success is True
    assert result.provider == "openai"
    assert result.style == VoiceStyle.NIGHT.value
    assert result.audio_path is not None
    assert (tmp_path / "data" / "tts" / "night-test.mp3").read_bytes() == b"RIFFfake-openai-tts"
    assert calls == [
        {
            "url": "https://api.openai.com/v1/audio/speech",
            "headers": {
                "Authorization": "Bearer tts-provider-key",
                "Content-Type": "application/json",
            },
            "json": {
                "model": "gpt-4o-mini-tts",
                "input": "晚安，测试语音",
                "voice": "alloy",
                "response_format": "mp3",
            },
            "timeout": 30.0,
        }
    ]


@pytest.mark.asyncio
async def test_enhanced_tts_openai_provider_requires_explicit_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AERIE_TTS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_TTS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    engine = EnhancedTTSEngine(api_key="", provider=TTSProvider.OPENAI)

    result = await engine.synthesize(
        "不会外呼",
        output_name="no-key",
        use_cache=False,
    )

    assert result.success is False
    assert "no API key" in result.error
    assert not (tmp_path / "data" / "tts" / "no-key.mp3").exists()

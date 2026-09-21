"""core/relay_headers 单测。

覆盖三件事：
1. 版本头取值与 core.version.APP_VERSION 一致（改版本号时若漏同步，这里会红）；
2. 中转地址识别对 etta.top 系列返回真、对官方直连与空值返回假；
3. 关键客户端构造点确实带上了该头（走中转注入、直连不注入）。
"""

from __future__ import annotations

import pytest

from core.relay_headers import is_relay_base_url, relay_headers
from core.version import APP_VERSION


def test_version_header_matches_app_version():
    assert relay_headers()["X-Aerie-Version"] == APP_VERSION


@pytest.mark.parametrize(
    "url",
    [
        "https://api.etta.top",
        "https://api.etta.top/v1",
        "https://etta.top",
    ],
)
def test_is_relay_base_url_true_for_relay(url):
    assert is_relay_base_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://api.deepseek.com/v1",
        "",
        None,
    ],
)
def test_is_relay_base_url_false_for_direct(url):
    assert is_relay_base_url(url) is False


class _CaptureClient:
    """替身客户端：记录构造时传入的 kwargs，供断言 default_headers。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _patch_async_openai(monkeypatch):
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _CaptureClient)


def test_image_analyzer_injects_header_for_relay(monkeypatch):
    _patch_async_openai(monkeypatch)
    from core.multimodal_input import ImageAnalyzer

    analyzer = ImageAnalyzer(api_key="k", api_base="https://api.etta.top/v1")
    assert analyzer._client.kwargs["default_headers"] == relay_headers()


def test_image_analyzer_skips_header_for_direct(monkeypatch):
    _patch_async_openai(monkeypatch)
    from core.multimodal_input import ImageAnalyzer

    analyzer = ImageAnalyzer(
        api_key="k",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    assert "default_headers" not in analyzer._client.kwargs


def test_self_evolve_proposer_injects_header_for_relay(monkeypatch):
    _patch_async_openai(monkeypatch)
    from core.self_evolve_proposer import SelfEvolveProposer

    client = SelfEvolveProposer._client_for("k", "https://api.etta.top/v1")
    assert client.kwargs["default_headers"] == relay_headers()


def test_qq_media_sf_client_injects_header_for_relay(monkeypatch):
    _patch_async_openai(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "k")
    monkeypatch.setenv("SILICONFLOW_BASE_URL", "https://api.etta.top/v1")
    from core.qq_media import _SFClient

    sf = _SFClient()
    assert sf._client.kwargs["base_url"] == "https://api.etta.top/v1"
    assert sf._client.kwargs["default_headers"] == relay_headers()


@pytest.mark.asyncio
async def test_llm_caller_sends_version_header_for_relay(monkeypatch):
    from core import llm_caller

    captured: dict = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "hi"}}], "usage": {}}

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(llm_caller.httpx, "AsyncClient", _FakeAsyncClient)

    brain = llm_caller.LLMCaller()
    provider = {"name": "relay", "url": "https://api.etta.top/v1", "model": "m", "key": "k"}
    await brain._call_provider_once(
        provider, "k", [{"role": "user", "content": "hi"}], None, None
    )

    assert captured["headers"]["X-Aerie-Version"] == APP_VERSION

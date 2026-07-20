import pytest

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

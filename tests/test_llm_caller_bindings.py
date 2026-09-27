"""LLMCaller：自定义厂商注入链 + 功能点绑定（主对话/子Agent/轻量）。"""
import pytest

import core.ai_services as ai_services
from core.ai_services import AiServicesStore
from core.llm_caller import LLMCaller, LLMCallerResponse


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    store = AiServicesStore(tmp_path / "data" / "ai_services.json")
    monkeypatch.setattr(ai_services, "get_store", lambda: store)
    return store


def _custom(store, *, supports_tools=False, model="gpt-bound"):
    return store.commit_custom_provider(store.prepare_custom_provider({
        "name": "RelayOne",
        "base_url": "https://relay.example.com/v1",
        "api_key": "sk-relay-123456",
        "model": model,
        "supports_tools": supports_tools,
        "max_tool_calls": 8,
    }))


def test_custom_provider_enters_chain(monkeypatch, isolated_store):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    _custom(isolated_store)
    brain = LLMCaller()
    names = [p["name"] for p in brain._providers]
    assert any(n.startswith("custom:") for n in names)


def test_main_chat_binding_promotes_custom_with_bound_model(monkeypatch, isolated_store):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    cp = _custom(isolated_store)
    isolated_store.set_binding("main_chat", cp["id"], "bound-model-x")

    brain = LLMCaller()
    first = brain._providers[0]
    assert first["name"] == f"custom:{cp['id']}"
    assert first["model"] == "bound-model-x"


def test_light_binding_model_used_for_siliconflow_light(monkeypatch, isolated_store):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    monkeypatch.setenv("SILICONFLOW_LIGHT_MODEL", "env-light-model")
    isolated_store.set_binding("light_assist", "siliconflow-light", "bound-light-model")

    brain = LLMCaller()
    light = next(p for p in brain._providers if p["name"] == "siliconflow-light")
    assert light["model"] == "bound-light-model"


@pytest.mark.asyncio
async def test_chat_model_override_applies_to_preferred(monkeypatch, isolated_store):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    cp = _custom(isolated_store)
    brain = LLMCaller()
    captured = {}

    async def fake_call(provider, messages, tools, temperature):
        captured["name"] = provider["name"]
        captured["model"] = provider["model"]
        return LLMCallerResponse(text="ok", provider=provider["name"], model=provider["model"])

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    await brain.chat(
        [{"role": "user", "content": "hi"}],
        preferred_provider=f"custom:{cp['id']}",
        model_override="per-call-model",
    )
    assert captured == {"name": f"custom:{cp['id']}", "model": "per-call-model"}


@pytest.mark.asyncio
async def test_subagent_binding_promotes_tool_capable_custom(monkeypatch, isolated_store):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    cp = _custom(isolated_store, supports_tools=True)
    isolated_store.set_binding("subagent", cp["id"], "tool-model")

    brain = LLMCaller()
    captured = {}

    async def fake_call(provider, messages, tools, temperature):
        captured.setdefault("order", []).append((provider["name"], provider["model"]))
        return LLMCallerResponse(text="ok", provider=provider["name"], model=provider["model"])

    monkeypatch.setattr(brain, "_call_provider", fake_call)

    class _Registry:
        pass

    await brain.chat(
        [{"role": "user", "content": "do"}],
        tools=[{"type": "function", "function": {"name": "f"}}],
        tool_registry=_Registry(),
    )
    assert captured["order"][0] == (f"custom:{cp['id']}", "tool-model")

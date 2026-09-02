import pytest

from core.llm_caller import LLMCaller


@pytest.mark.asyncio
async def test_llm_entitlement_gate_blocks_before_provider_call(tmp_path, monkeypatch):
    path = tmp_path / "entitlement.json"
    monkeypatch.setenv("AERIE_ENFORCE_ENTITLEMENTS", "1")
    monkeypatch.setenv("AERIE_ENTITLEMENT_PATH", str(path))
    caller = LLMCaller()
    caller._max_tokens = 200_000
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be called when quota is exceeded")

    caller._call_provider = fail_if_called
    result = await caller.chat([{"role": "user", "content": "hello"}])
    assert result.provider == "entitlement"
    assert called is False

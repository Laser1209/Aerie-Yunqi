"""P2 写入校验门（ConsistencyGate）测试（§3.7-2 / memory_write_validation_v1）。"""

from types import SimpleNamespace

import pytest

from core.memory_validation import (
    IMPORTANCE_THRESHOLD,
    MemoryFactValidator,
)


class FakeLightLLM:
    def __init__(self, text: str = '{"explicit": true, "reason": "ok"}') -> None:
        self.text = text
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            text=self.text,
            provider="siliconflow-light",
            model="light-test",
            tokens_prompt=120,
            tokens_completion=30,
        )


def _validator(llm, **kwargs):
    return MemoryFactValidator(llm=llm, **kwargs)


@pytest.mark.asyncio
async def test_low_importance_skips_llm():
    llm = FakeLightLLM()
    v = _validator(llm)
    result = await v.validate(text="任意内容", importance=IMPORTANCE_THRESHOLD - 1)
    assert result["status"] == "skip"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_disabled_returns_unchecked():
    llm = FakeLightLLM()
    v = _validator(llm, enabled=False)
    result = await v.validate(text="任意内容", importance=8)
    assert result["status"] == "unchecked"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_explicit_fact_confirmed():
    llm = FakeLightLLM('{"explicit": true, "reason": "用户明确说出地址"}')
    v = _validator(llm)
    result = await v.validate(
        text="用户说住在XX小区3栋",
        channel="qq",
        source="knowledge_add",
        importance=8,
    )
    assert result["status"] == "confirmed"
    assert result["channel"] == "qq"
    assert result["source"] == "knowledge_add"
    assert result["tokens_prompt"] == 120
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_inferred_fact_low_confidence():
    llm = FakeLightLLM('{"explicit": false, "reason": "AI 推断"}')
    v = _validator(llm)
    result = await v.validate(text="AI 猜测用户喜欢红色", importance=9)
    assert result["status"] == "low_confidence"


@pytest.mark.asyncio
async def test_llm_failure_fails_open_to_unavailable():
    class FailingLLM:
        async def chat(self, messages, **kwargs):
            raise RuntimeError("provider down")

    v = _validator(FailingLLM(), max_retries=0)
    result = await v.validate(text="任意内容", importance=8)
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
async def test_unparsable_response_retries_then_unavailable():
    class GarbageLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return SimpleNamespace(text="我不理解", provider="p", model="m")

    v = _validator(GarbageLLM(), max_retries=1)
    result = await v.validate(text="任意内容", importance=8)
    assert result["status"] == "unavailable"
    assert v.llm.calls == 2


def test_parse_raw_json_variants():
    assert MemoryFactValidator._parse_response('{"explicit":true,"reason":"r"}')["explicit"] is True
    assert MemoryFactValidator._parse_response('{"explicit": false, "reason": "r"}')["explicit"] is False
    assert MemoryFactValidator._parse_response("true")["explicit"] is True
    assert MemoryFactValidator._parse_response("no")["explicit"] is False
    assert MemoryFactValidator._parse_response("garbage")["explicit"] is None


def test_validation_flag_default_on():
    from core.feature_flags import FeatureFlags

    assert FeatureFlags().is_enabled("memory_write_validation_v1") is True

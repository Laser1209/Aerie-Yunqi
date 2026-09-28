"""TypeSafe noul 解策通道 + 记忆写入校验接线测试。

全部离线：HTTP 用假 AsyncClient 替换，不触网。
"""

import json
from types import SimpleNamespace

import pytest

from core import typesafe_decision


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """替换 httpx.AsyncClient：记录最近请求体，按队列返回预设响应。"""

    responses: list = []
    last_json: dict | None = None
    last_url: str = ""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, headers=None, json=None):
        _FakeAsyncClient.last_json = json
        _FakeAsyncClient.last_url = url
        item = _FakeAsyncClient.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def configured(monkeypatch):
    """配好凭证 + 假 HTTP 客户端。"""
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.last_json = None
    _FakeAsyncClient.last_url = ""
    monkeypatch.setenv("AERIE_TYPESAFE_API_KEY", "sk-test")
    monkeypatch.setenv("AERIE_TYPESAFE_BASE_URL", "https://example.test/gateway/typesafe/v1")
    monkeypatch.setenv("AERIE_TYPESAFE_MODEL", "bocha-jev-v1")
    monkeypatch.setattr(typesafe_decision.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _answer(value: float) -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "model": "bocha-jev-v1",
            "answers": {"q": {"type": "noul", "noul": value}},
            "usage": {"input_tokens": 41, "output_tokens": 0},
        },
    )


# ── 通道本身 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_noul_returns_probability_and_body_shape(configured):
    configured.responses = [_answer(0.87)]
    score = await typesafe_decision.noul("看看你长什么样子", "用户是否想看具体画面？")
    assert score == pytest.approx(0.87)
    assert configured.last_json == {
        "model": "bocha-jev-v1",
        "state": "看看你长什么样子",
        "questions": {"q": {"type": "noul", "instructions": "用户是否想看具体画面？"}},
    }
    assert configured.last_url == "https://example.test/gateway/typesafe/v1/systemone"


@pytest.mark.asyncio
async def test_noul_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("AERIE_TYPESAFE_API_KEY", raising=False)
    assert await typesafe_decision.noul("state", "question") is None


@pytest.mark.asyncio
async def test_noul_http_error_returns_none(configured):
    configured.responses = [_FakeResponse(422, {"detail": "bad schema"})]
    assert await typesafe_decision.noul("state", "question") is None


@pytest.mark.asyncio
async def test_noul_malformed_payload_returns_none(configured):
    configured.responses = [_FakeResponse(200, {"answers": {"q": {"type": "noul"}}})]
    assert await typesafe_decision.noul("state", "question") is None


@pytest.mark.asyncio
async def test_noul_network_error_returns_none(configured):
    configured.responses = [RuntimeError("boom")]
    assert await typesafe_decision.noul("state", "question") is None


@pytest.mark.asyncio
async def test_noul_respects_global_model_gate(configured, monkeypatch):
    monkeypatch.setenv("AERIE_DISABLE_MODEL_CALLS", "1")
    configured.responses = [_answer(0.9)]
    assert await typesafe_decision.noul("state", "question") is None
    assert configured.last_json is None


@pytest.mark.asyncio
async def test_noul_blank_input_returns_none(configured):
    assert await typesafe_decision.noul("", "question") is None
    assert await typesafe_decision.noul("state", "   ") is None
    assert configured.last_json is None


@pytest.mark.asyncio
async def test_noul_clamps_out_of_range(configured):
    configured.responses = [_answer(1.4)]
    assert await typesafe_decision.noul("state", "question") == 1.0


# ── 记忆写入校验接线 ─────────────────────────────────


class _FakeLightLLM:
    def __init__(self, text: str = '{"explicit": true, "reason": "ok"}') -> None:
        self.text = text
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            text=self.text, provider="siliconflow-light", model="light-test",
            tokens_prompt=120, tokens_completion=30,
        )


def _patch_noul(monkeypatch, value):
    """把 TypeSafe 判定固定为 value（None = 通道不可用），并记录调用参数。"""
    seen: dict = {}

    async def fake_noul(state, instructions, *, timeout=None):
        seen["state"] = state
        seen["instructions"] = instructions
        return value

    monkeypatch.setattr("core.typesafe_decision.noul", fake_noul)
    return seen


@pytest.mark.asyncio
async def test_memory_validation_high_confidence_short_circuits(monkeypatch):
    from core import memory_validation as mv

    seen = _patch_noul(monkeypatch, 0.93)
    llm = _FakeLightLLM()
    result = await mv.MemoryFactValidator(llm=llm).validate(
        text="用户说：我住在济南历下区", channel="qq", importance=8
    )
    assert result["status"] == "confirmed"
    assert result["provider"] == "typesafe"
    assert llm.calls == 0  # 轻量 LLM 被短路
    assert seen["state"] == "用户说：我住在济南历下区"
    assert "确定的事实" in seen["instructions"]


@pytest.mark.asyncio
async def test_memory_validation_low_confidence_short_circuits(monkeypatch):
    from core import memory_validation as mv

    _patch_noul(monkeypatch, 0.12)
    llm = _FakeLightLLM()
    result = await mv.MemoryFactValidator(llm=llm).validate(
        text="或许更喜欢待在家里", importance=9
    )
    assert result["status"] == "low_confidence"
    assert result["provider"] == "typesafe"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_memory_validation_defers_middle_band_to_light_llm(monkeypatch):
    """模糊区间（既不 ≥0.90 也不 ≤0.30）不得短路，必须交给轻量 LLM。"""
    from core import memory_validation as mv

    _patch_noul(monkeypatch, 0.62)
    llm = _FakeLightLLM('{"explicit": false, "reason": "AI 推断"}')
    result = await mv.MemoryFactValidator(llm=llm).validate(text="也许最近工作压力挺大", importance=8)
    assert result["status"] == "low_confidence"
    assert result["provider"] == "siliconflow-light"
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_memory_validation_falls_back_when_typesafe_unavailable(monkeypatch):
    from core import memory_validation as mv

    _patch_noul(monkeypatch, None)
    llm = _FakeLightLLM('{"explicit": true, "reason": "用户明确"}')
    result = await mv.MemoryFactValidator(llm=llm).validate(text="任意内容", importance=8)
    assert result["status"] == "confirmed"
    assert result["provider"] == "siliconflow-light"
    assert llm.calls == 1

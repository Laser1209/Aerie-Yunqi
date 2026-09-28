"""ReAct 工具回执配对不变量 + 工具结果成功判定。

**为什么这是 P0**

``working_msgs`` 是**跨供应商复用**的（`core/llm_caller.py` 中一行注释已写明
"已产生的 assistant tool_calls 消息与对应 tool 结果消息必须完整携带"）。

历史上 ``json.dumps(result)`` 抛 ``TypeError`` 时，异常发生在"append tool 消息"
**之前**，于是历史里出现一条**只声明了 tool_calls、却没有配对 tool 回执的
assistant 消息**。OpenAI 兼容接口对此是硬约束：

    "An assistant message with 'tool_calls' must be followed by tool messages
     responding to each tool_call_id"

→ 一个工具出错会让本轮**所有**剩余供应商以 400 拒收。本测试锁定"配对必然完整"。
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from core.llm_caller import LLMCaller, LLMCallerResponse
from core.tool_registry import ToolRegistry
from core.tool_result import tool_result_success

_STUB_PROVIDER = {
    "name": "stub",
    "url": "http://stub.invalid/v1",
    "key": "sk-stub",
    "model": "stub-model",
    "supports_tools": True,
    "max_tool_calls": 8,
}

_TOOLS_SCHEMA = [{
    "type": "function",
    "function": {"name": "anything", "parameters": {"type": "object"}},
}]


@dataclasses.dataclass
class _ControlResultLike:
    """与 ``core.computer_control.ControlResult`` 同形：@dataclass + 恒带 error 键。"""

    success: bool = True
    action: str = "shell_execute"
    data: dict = dataclasses.field(default_factory=lambda: {"stdout": "hi"})
    error: str = ""
    timestamp: float = 1.0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "action": self.action,
            "data": self.data,
            "error": self.error,
            "timestamp": self.timestamp,
        }


def _tool_calls(*names: str) -> list[dict]:
    return [
        {
            "id": f"call_{i}",
            "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }
        for i, name in enumerate(names)
    ]


def _single_provider_brain(monkeypatch) -> LLMCaller:
    brain = LLMCaller()
    monkeypatch.setattr(brain, "_providers", [dict(_STUB_PROVIDER)])
    return brain


def _assert_pairing_invariant(messages: list[dict]) -> None:
    """核心断言：每个 assistant tool_call id 都有且仅有一条 tool 消息配对。"""
    declared: list[str] = []
    answered: list[str] = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            declared.extend(str(tc.get("id")) for tc in msg["tool_calls"])
        elif msg.get("role") == "tool":
            answered.append(str(msg.get("tool_call_id")))
    assert sorted(declared) == sorted(answered), (
        f"tool_calls/tool 消息未配对：declared={declared} answered={answered}"
    )
    # 整个历史必须可序列化 —— 否则下一个供应商拿到就会炸。
    json.dumps(messages, ensure_ascii=False)


@pytest.mark.asyncio
async def test_pairing_survives_exploding_tool(monkeypatch):
    """工具抛异常时，仍必须为它 append 一条 tool 回执。"""
    brain = _single_provider_brain(monkeypatch)
    registry = ToolRegistry()

    def boom(**kwargs):
        raise RuntimeError("kaboom")

    registry.register("boom", boom, schema={"description": "x"})

    rounds = {"n": 0}
    captured: dict[str, Any] = {}

    async def fake_call(provider, messages, tools, temperature):
        rounds["n"] += 1
        captured[f"round{rounds['n']}"] = [dict(m) for m in messages]
        if rounds["n"] == 1:
            return LLMCallerResponse(
                text="", provider="stub", model="m",
                _raw_tool_calls=_tool_calls("boom"),
            )
        return LLMCallerResponse(text="done", provider="stub", model="m")

    monkeypatch.setattr(brain, "_call_provider", fake_call)

    resp = await brain.chat(
        [{"role": "user", "content": "hi"}],
        tools=_TOOLS_SCHEMA,
        tool_registry=registry,
    )

    assert resp.text == "done"
    _assert_pairing_invariant(captured["round2"])


@pytest.mark.asyncio
async def test_pairing_survives_non_serializable_tool_result(monkeypatch):
    """回归 P0：工具返回 @dataclass 时，历史必须仍然可序列化且配对完整。"""
    brain = _single_provider_brain(monkeypatch)
    registry = ToolRegistry()
    registry.register("obj", lambda **kw: _ControlResultLike(), schema={"description": "x"})

    rounds = {"n": 0}
    captured: dict[str, Any] = {}

    async def fake_call(provider, messages, tools, temperature):
        rounds["n"] += 1
        captured[f"round{rounds['n']}"] = [dict(m) for m in messages]
        if rounds["n"] == 1:
            return LLMCallerResponse(
                text="", provider="stub", model="m",
                _raw_tool_calls=_tool_calls("obj"),
            )
        return LLMCallerResponse(text="done", provider="stub", model="m")

    monkeypatch.setattr(brain, "_call_provider", fake_call)

    resp = await brain.chat(
        [{"role": "user", "content": "hi"}],
        tools=_TOOLS_SCHEMA,
        tool_registry=registry,
    )

    assert resp.text == "done"
    messages = captured["round2"]
    _assert_pairing_invariant(messages)
    # 回执里应能看到 @dataclass 的真实字段，而不是一句"不可序列化"。
    tool_replies = [m for m in messages if m.get("role") == "tool"]
    assert any("shell_execute" in m["content"] for m in tool_replies)


@pytest.mark.asyncio
async def test_multiple_tool_calls_all_paired(monkeypatch):
    """一条 assistant 消息里多个 tool_call 时，逐条都要配对（不能只兜第一个）。"""
    brain = _single_provider_brain(monkeypatch)
    registry = ToolRegistry()
    registry.register("ok_tool", lambda **kw: {"fine": True}, schema={"description": "x"})

    def boom(**kwargs):
        raise RuntimeError("nope")

    registry.register("boom", boom, schema={"description": "x"})

    rounds = {"n": 0}
    captured: dict[str, Any] = {}

    async def fake_call(provider, messages, tools, temperature):
        rounds["n"] += 1
        captured[f"round{rounds['n']}"] = [dict(m) for m in messages]
        if rounds["n"] == 1:
            return LLMCallerResponse(
                text="", provider="stub", model="m",
                _raw_tool_calls=_tool_calls("ok_tool", "boom", "ok_tool"),
            )
        return LLMCallerResponse(text="done", provider="stub", model="m")

    monkeypatch.setattr(brain, "_call_provider", fake_call)

    await brain.chat(
        [{"role": "user", "content": "hi"}],
        tools=_TOOLS_SCHEMA,
        tool_registry=registry,
    )

    messages = captured["round2"]
    _assert_pairing_invariant(messages)
    assert len([m for m in messages if m.get("role") == "tool"]) == 3


@pytest.mark.asyncio
async def test_tool_results_expose_success_and_duration(monkeypatch):
    """工具结果为聚合结果，成功态与耗时必须如实上报（供 tool_call_log 落库）。"""
    brain = _single_provider_brain(monkeypatch)
    registry = ToolRegistry()
    registry.register("obj", lambda **kw: _ControlResultLike(), schema={"description": "x"})

    rounds = {"n": 0}

    async def fake_call(provider, messages, tools, temperature):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return LLMCallerResponse(
                text="", provider="stub", model="m",
                _raw_tool_calls=_tool_calls("obj"),
            )
        return LLMCallerResponse(text="done", provider="stub", model="m")

    monkeypatch.setattr(brain, "_call_provider", fake_call)

    resp = await brain.chat(
        [{"role": "user", "content": "hi"}],
        tools=_TOOLS_SCHEMA,
        tool_registry=registry,
    )

    entry = resp.tool_results[0]
    assert entry["name"] == "obj"
    # ControlResult 成功时 error 为空串：必须按 success 判定为成功，
    # 否则每一次成功的系统操控都会被误报为失败。
    assert entry["success"] is True
    json.dumps(entry["result"], ensure_ascii=False)


# ── 成功判定（归一化引入的耦合点）────────────────────────────────────────


def test_control_result_is_success_despite_empty_error_key():
    """耦合回归：to_dict() 恒带 error 键，空串不得被判为失败。"""
    payload = _ControlResultLike().to_dict()
    assert "error" in payload and payload["error"] == ""
    assert tool_result_success(payload) is True


def test_explicit_success_false_wins():
    assert tool_result_success({"success": False, "error": "boom"}) is False


def test_error_without_success_key_is_failure():
    assert tool_result_success({"error": "boom"}) is False


def test_non_dict_result_is_success():
    assert tool_result_success(None) is True
    assert tool_result_success([1, 2]) is True

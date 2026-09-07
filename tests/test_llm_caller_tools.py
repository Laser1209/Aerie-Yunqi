import json

import pytest

from core.llm_caller import LLMCaller, LLMCallerResponse
from core.tool_registry import ToolRegistry


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        "data_stats",
        lambda data: {"success": True, "rows": len(data)},
        {
            "type": "function",
            "function": {
                "name": "data_stats",
                "description": "count rows",
                "parameters": {"type": "object", "properties": {"data": {"type": "array"}}},
            },
        },
        category="office",
    )
    return registry


def _call(name: str, arguments: object, call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    }


@pytest.mark.asyncio
async def test_chat_executes_tool_and_feeds_result_back():
    brain = LLMCaller()
    registry = _registry()
    offered = registry.get_openai_schema()
    seen = []
    responses = [
        LLMCallerResponse(
            text="[]",
            provider="fake",
            model="fake-tools",
            _raw_tool_calls=[_call("data_stats", {"data": [{"value": 1}, {"value": 2}]})],
        ),
        LLMCallerResponse(text="统计完成：共 2 行。", provider="fake", model="fake-tools"),
    ]

    async def fake_call(provider, messages, tools, temperature=None):
        seen.append({"messages": messages, "tools": tools})
        return responses.pop(0)

    brain._providers = [{"name": "fake", "key": "test", "model": "fake-tools", "url": "http://invalid", "supports_tools": True}]
    brain._call_provider = fake_call

    result = await brain.chat(
        [{"role": "user", "content": "统计数据"}],
        tools=offered,
        tool_registry=registry,
    )

    assert result.text == "统计完成：共 2 行。"
    assert result.tool_results and len(result.tool_results) == 1
    assert result.tool_results[0]["name"] == "data_stats"
    assert result.tool_results[0]["success"] is True
    assert result.tool_results[0]["result"] == {"success": True, "rows": 2}
    assert len(seen) == 2
    assert seen[1]["messages"][-1]["role"] == "tool"
    assert json.loads(seen[1]["messages"][-1]["content"]) == {"success": True, "rows": 2}


@pytest.mark.asyncio
async def test_chat_surfaces_unknown_tool_without_crashing():
    brain = LLMCaller()
    registry = _registry()
    responses = [
        LLMCallerResponse(
            text="[]",
            provider="fake",
            model="fake-tools",
            _raw_tool_calls=[_call("missing_tool", {})],
        ),
        LLMCallerResponse(text="工具不可用。", provider="fake", model="fake-tools"),
    ]

    async def fake_call(provider, messages, tools, temperature=None):
        return responses.pop(0)

    brain._providers = [{"name": "fake", "key": "test", "model": "fake-tools", "url": "http://invalid", "supports_tools": True}]
    brain._call_provider = fake_call

    result = await brain.chat(
        [{"role": "user", "content": "执行未知工具"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
    )

    assert result.text == "工具不可用。"
    assert result.tool_results[0]["success"] is False
    assert result.tool_results[0]["result"]["error"] == "unknown tool: missing_tool"


@pytest.mark.asyncio
async def test_chat_malformed_tool_arguments_become_auditable_error():
    brain = LLMCaller()
    registry = _registry()
    responses = [
        LLMCallerResponse(
            text="[]",
            provider="fake",
            model="fake-tools",
            _raw_tool_calls=[_call("data_stats", "{not-json")],
        ),
        LLMCallerResponse(text="参数错误。", provider="fake", model="fake-tools"),
    ]

    async def fake_call(provider, messages, tools, temperature=None):
        return responses.pop(0)

    brain._providers = [{"name": "fake", "key": "test", "model": "fake-tools", "url": "http://invalid", "supports_tools": True}]
    brain._call_provider = fake_call

    result = await brain.chat(
        [{"role": "user", "content": "使用错误参数"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
    )

    assert result.text == "参数错误。"
    assert result.tool_results[0]["success"] is False
    assert "tool_signature" in result.tool_results[0]["result"]["error"]

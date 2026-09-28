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


# ── 跨 provider 回退：工具不重复执行、消息历史完整携带 ──────────────

def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    }


def _side_effect_registry() -> tuple[ToolRegistry, list]:
    """注册两个带副作用的工具，返回值刻意不是 dict（None / int）。"""
    registry = ToolRegistry()
    calls: list = []

    async def make_dir(path=None):
        calls.append(("make_dir", path))
        return None  # 刻意返回 None：曾触发 "error" not in result 的 TypeError

    async def other_step(path=None):
        calls.append(("other_step", path))
        return 42  # 刻意返回标量

    registry.register("make_dir", make_dir, _schema("make_dir"), category="file")
    registry.register("other_step", other_step, _schema("other_step"), category="file")
    return registry, calls


def _scripted_brain(scripts: dict) -> tuple[LLMCaller, list]:
    """按 provider 名依次吐出脚本响应（Exception 实例表示该次调用抛错）。"""
    brain = LLMCaller()
    brain._providers = [
        {
            "name": name,
            "key": "test",
            "model": f"{name}-model",
            "url": "http://invalid",
            "supports_tools": True,
        }
        for name in scripts
    ]
    # 杜绝宿主环境真实 key 触发最后的 env 兜底扫描，保证用例确定性
    brain._discover_env_providers = lambda exclude_names=None: []
    seen: list = []

    async def fake_call(provider, messages, tools, temperature=None):
        item = scripts[provider["name"]].pop(0)
        seen.append({"provider": provider["name"], "messages": messages})
        if isinstance(item, Exception):
            raise item
        return item

    brain._call_provider = fake_call
    return brain, seen


@pytest.mark.asyncio
async def test_chat_carries_tool_history_across_providers_and_executes_once():
    """缺陷1：provider 回退后，已执行工具的 assistant/tool 消息必须完整带给下一个 provider，
    且同一 tool_call 绝不执行第二次。"""
    registry, calls = _side_effect_registry()
    scripts = {
        "p1": [
            LLMCallerResponse(
                text="[]",
                provider="p1",
                model="p1-model",
                _raw_tool_calls=[_call("make_dir", {"path": r"D:\test"}, call_id="c1")],
            ),
            RuntimeError("p1 第二次调用炸了"),
        ],
        "p2": [
            LLMCallerResponse(text="建好了。", provider="p2", model="p2-model"),
        ],
    }
    brain, seen = _scripted_brain(scripts)

    result = await brain.chat(
        [{"role": "user", "content": "在 D 盘建文件夹"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
    )

    # 有副作用的工具只执行了一次（曾被两个 provider 各执行一次）
    assert calls == [("make_dir", r"D:\test")]
    assert result.text == "建好了。"
    assert result.provider == "p2"
    assert result.tool_results and len(result.tool_results) == 1

    # p2 的首次调用看到了 p1 留下的完整 assistant tool_calls + tool 结果消息
    p2_seen = next(s for s in seen if s["provider"] == "p2")
    assistant_tools = [
        m for m in p2_seen["messages"]
        if m["role"] == "assistant" and m.get("tool_calls")
    ]
    tool_msgs = [m for m in p2_seen["messages"] if m["role"] == "tool"]
    assert assistant_tools and assistant_tools[-1]["tool_calls"][0]["id"] == "c1"
    assert tool_msgs and tool_msgs[-1]["tool_call_id"] == "c1"
    # 契约：execute 出口统一归一化为 dict（None 包在 result 键下），保证可序列化。
    assert json.loads(tool_msgs[-1]["content"]) == {"result": None}


@pytest.mark.asyncio
async def test_chat_dedupes_repeated_tool_call_id_across_providers():
    """缺陷1：下一个 provider 若重复返回已执行过的 tool_call id，必须直接跳过，不再执行。"""
    registry, calls = _side_effect_registry()
    scripts = {
        "p1": [
            LLMCallerResponse(
                text="[]",
                provider="p1",
                model="p1-model",
                _raw_tool_calls=[_call("make_dir", {"path": "D:\\test"}, call_id="c1")],
            ),
            RuntimeError("p1 boom"),
        ],
        "p2": [
            # p2 没带脑子地重复了同一个 id
            LLMCallerResponse(
                text="[]",
                provider="p2",
                model="p2-model",
                _raw_tool_calls=[_call("make_dir", {"path": "D:\\test"}, call_id="c1")],
            ),
            LLMCallerResponse(text="都搞定了。", provider="p2", model="p2-model"),
        ],
    }
    brain, seen = _scripted_brain(scripts)

    result = await brain.chat(
        [{"role": "user", "content": "建文件夹"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
    )

    assert result.text == "都搞定了。"
    assert calls == [("make_dir", r"D:\test")]  # 仍然只有一次
    assert len(result.tool_results) == 1
    # p2 被调用了两次（重复 id 被跳过后再答一次），每次都没有追加重复消息
    assert [s["provider"] for s in seen] == ["p1", "p1", "p2", "p2"]


@pytest.mark.asyncio
async def test_chat_aggregates_tool_results_across_providers():
    """缺陷1：all_tool_results 必须聚合所有 provider 的结果，而不是只留最后一个。"""
    registry, calls = _side_effect_registry()
    scripts = {
        "p1": [
            LLMCallerResponse(
                text="[]",
                provider="p1",
                model="p1-model",
                _raw_tool_calls=[_call("make_dir", {"path": "D:\\a"}, call_id="c1")],
            ),
            RuntimeError("p1 boom"),
        ],
        "p2": [
            LLMCallerResponse(
                text="[]",
                provider="p2",
                model="p2-model",
                _raw_tool_calls=[_call("other_step", {"path": "D:\\b"}, call_id="c2")],
            ),
            LLMCallerResponse(text="全部完成。", provider="p2", model="p2-model"),
        ],
    }
    brain, _ = _scripted_brain(scripts)

    result = await brain.chat(
        [{"role": "user", "content": "连续做两步"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
    )

    assert result.text == "全部完成。"
    assert len(calls) == 2
    assert [r["name"] for r in result.tool_results] == ["make_dir", "other_step"]


@pytest.mark.asyncio
async def test_chat_none_and_scalar_tool_results_count_as_success():
    """缺陷2：工具返回 None/int 等非 dict 时视为成功，不再抛 TypeError 把真结果换成错误。"""
    registry, calls = _side_effect_registry()
    scripts = {
        "fake": [
            LLMCallerResponse(
                text="[]",
                provider="fake",
                model="fake-tools",
                _raw_tool_calls=[_call("make_dir", {}, call_id="n1")],
            ),
            LLMCallerResponse(
                text="[]",
                provider="fake",
                model="fake-tools",
                _raw_tool_calls=[_call("other_step", {}, call_id="n2")],
            ),
            LLMCallerResponse(text="好了。", provider="fake", model="fake-tools"),
        ],
    }
    brain, _ = _scripted_brain(scripts)

    result = await brain.chat(
        [{"role": "user", "content": "干活"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
    )

    assert result.text == "好了。"
    assert [r["success"] for r in result.tool_results] == [True, True]
    # 非 dict 结果照样算成功，且原值保留（只是按契约包在 result 键下）。
    assert result.tool_results[0]["result"] == {"result": None}
    assert result.tool_results[1]["result"] == {"result": 42}


@pytest.mark.asyncio
async def test_chat_zero_rounds_still_allows_one_plain_response():
    """缺陷3：max_react_rounds=0 时健康 provider 至少有一次普通调用机会，不直接整体失败。"""
    registry, calls = _side_effect_registry()
    scripts = {
        "fake": [
            LLMCallerResponse(text="你好呀。", provider="fake", model="fake-tools"),
        ],
    }
    brain, seen = _scripted_brain(scripts)

    result = await brain.chat(
        [{"role": "user", "content": "在吗"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
        max_react_rounds=0,
    )

    assert result.text == "你好呀。"
    assert len(seen) == 1
    assert calls == []


@pytest.mark.asyncio
async def test_chat_zero_rounds_never_executes_tools_but_walks_providers():
    """缺陷3补充：rounds=0 时模型即便要求调工具也不执行，且每个 provider 各拿到一次调用机会。"""
    registry, calls = _side_effect_registry()
    scripts = {
        "p1": [
            LLMCallerResponse(
                text="[]",
                provider="p1",
                model="p1-model",
                _raw_tool_calls=[_call("make_dir", {"path": "D:\\test"}, call_id="c1")],
            ),
        ],
        "p2": [
            LLMCallerResponse(
                text="[]",
                provider="p2",
                model="p2-model",
                _raw_tool_calls=[_call("make_dir", {"path": "D:\\test"}, call_id="c2")],
            ),
        ],
    }
    brain, seen = _scripted_brain(scripts)

    result = await brain.chat(
        [{"role": "user", "content": "建文件夹"}],
        tools=registry.get_openai_schema(),
        tool_registry=registry,
        max_react_rounds=0,
    )

    # 没有任何工具被执行
    assert calls == []
    # 两个 provider 都各被调用一次（调用机会不被轮数上限吞掉）
    assert [s["provider"] for s in seen] == ["p1", "p2"]
    # 全部没能给出最终文本 → 兜底文案
    assert "暂时无法连接模型" in result.text


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

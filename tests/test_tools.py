"""Tests for tool registry v9.0."""

import pytest

from core.tool_registry import ToolRegistry


class TestToolRegistry:
    """Test tool registration and execution."""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    def test_register_and_get_openai_schema(self, registry):
        def dummy_tool(**kwargs):
            return {"result": "ok"}
        registry.register("dummy_tool", dummy_tool, schema={
            "description": "A test tool",
            "parameters": {"type": "object", "properties": {}},
        })
        schema = registry.get_openai_schema()
        names = [s["function"]["name"] for s in schema]
        assert "dummy_tool" in names

    def test_register_multiple_tools(self, registry):
        def a(**kw): return {"result": "a"}
        def b(**kw): return {"result": "b"}
        registry.register("a", a, schema={"description": "A"})
        registry.register("b", b, schema={"description": "B"})
        schema = registry.get_openai_schema()
        names = {s["function"]["name"] for s in schema}
        assert names == {"a", "b"}

    @pytest.mark.asyncio
    async def test_execute_calls_function(self, registry):
        def my_tool(value=42, **kwargs):
            return f"got {value}"
        registry.register("my_tool", my_tool, schema={"description": "test"})
        # 契约：execute 恒返回 dict（标量包在 result 键下），保证可 JSON 序列化。
        result = await registry.execute("my_tool", {"value": 99})
        assert result == {"result": "got 99"}

    @pytest.mark.asyncio
    async def test_execute_normalizes_non_serializable_object(self, registry):
        """回归：工具返回 @dataclass（如 ControlResult）时不得让下游 json.dumps 炸。"""
        import dataclasses
        import json

        @dataclasses.dataclass
        class _ControlResult:
            success: bool = True
            action: str = "shell_execute"
            error: str = ""

        registry.register("shell_like", lambda **kw: _ControlResult(), schema={"description": "x"})
        result = await registry.execute("shell_like", {})
        assert result["action"] == "shell_execute"
        json.dumps(result, ensure_ascii=False)  # 不得抛 TypeError

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self, registry):
        result = await registry.execute("missing_tool", {})
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_register_overwrites(self, registry):
        def v1(**kw): return "v1"
        def v2(**kw): return "v2"
        registry.register("overwrite", v1, schema={"description": "v1"})
        registry.register("overwrite", v2, schema={"description": "v2"})
        result = await registry.execute("overwrite", {})
        assert result == {"result": "v2"}

    def test_get_openai_schema_format(self, registry):
        registry.register("test_tool", lambda **kw: "ok", schema={
            "description": "Test desc",
            "parameters": {"type": "object"},
        })
        schema = registry.get_openai_schema()
        assert len(schema) == 1
        assert schema[0]["type"] == "function"
        assert schema[0]["function"]["name"] == "test_tool"
        assert schema[0]["function"]["description"] == "Test desc"

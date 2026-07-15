"""Tests for tool registry and tool registration."""

import pytest

from core.tool_registry import ToolRegistry


class TestToolRegistry:
    """Test tool registration and retrieval (some async methods)."""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    def test_register_and_get(self, registry):
        def dummy_tool(**kwargs):
            return "ok"
        registry.register("dummy_tool", dummy_tool, schema={}, category="test", description="A test tool")
        tool = registry.get("dummy_tool")
        assert tool is not None
        assert tool.func is dummy_tool

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None

    def test_usage_increments(self, registry):
        import uuid
        unique_name = f"foo_{uuid.uuid4().hex[:8]}"
        registry.register(unique_name, lambda **kw: "bar", schema={}, category="test")
        registry.increment_usage(unique_name)
        registry.increment_usage(unique_name)
        stats = registry.usage_stats()
        found = [s for s in stats if s.get("tool_name") == unique_name]
        assert len(found) >= 1
        assert found[0]["calls"] == 2

    def test_list_tools_returns_dicts(self, registry):
        def a(**kw): pass
        def b(**kw): pass
        registry.register("a", a, schema={}, category="x")
        registry.register("b", b, schema={}, category="y")
        tools = registry.list_tools()
        names = {t["name"] for t in tools}
        assert "a" in names
        assert "b" in names

    @pytest.mark.asyncio
    async def test_execute_calls_function(self, registry):
        def my_tool(value=42, **kwargs):
            return f"got {value}"
        registry.register("my_tool", my_tool, schema={}, category="test")
        result = await registry.execute("my_tool", value=99)
        assert result == "got 99"

    @pytest.mark.asyncio
    async def test_execute_nonexistent(self, registry):
        with pytest.raises(ValueError, match="tool not found"):
            await registry.execute("missing_tool")

    @pytest.mark.asyncio
    async def test_register_overwrites(self, registry):
        def v1(**kw): return "v1"
        def v2(**kw): return "v2"
        registry.register("overwrite", v1, schema={}, category="test")
        registry.register("overwrite", v2, schema={}, category="test")
        result = await registry.execute("overwrite")
        assert result == "v2"

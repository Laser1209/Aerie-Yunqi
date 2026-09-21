"""A / C 部分：把 MCP 客户端接进 companion 运行链路的接线测试。

覆盖：
  - 默认关闭：不建连、不注册任何工具（启动行为与未接线时一致）
  - 启用（桩 MCP server）：工具按 ``mcp__<server>__<tool>`` 注册进 registry 且可调用
  - 启动失败降级：握手失败 / 配置损坏 / 构造异常都不阻断、不抛错
  - companion.start()/stop() 生命周期里真的走了接线点
  - 只读状态端点 /api/background/status 如实反映启用与否

桩 MCP server 复用 tests/test_mcp_client.py 里的实现。
"""

from __future__ import annotations

import pytest

from core import companion as companion_module
from core.companion import Companion
from core.mcp_client import MCPClientManager
from core.tool_registry import ToolRegistry
from tests.test_mcp_client import _servers, _write_stub


def _companion_shell() -> Companion:
    """绕过重量级 __init__，只装配接线所需的最小状态（真实方法照常调用）。"""
    comp = object.__new__(Companion)
    comp.settings = {}
    comp.tool_registry = ToolRegistry()
    comp.mcp_manager = None
    comp.thinking_loop = None
    comp._thinking_ticks = 0
    return comp


def _inject_stub_manager(monkeypatch, stub, **overrides) -> None:
    monkeypatch.setattr(
        companion_module,
        "MCPClientManager",
        lambda registry: MCPClientManager(registry, servers=_servers(stub, **overrides)),
    )


# ── 默认关闭 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_mcp_disabled_by_default_touches_nothing():
    """仓库默认配置（enabled: false）下不建连、不注册工具。"""
    comp = _companion_shell()

    await comp._start_mcp()
    try:
        assert comp.mcp_manager is not None
        assert comp.mcp_manager.client_names() == []
        assert comp.tool_registry.list_names() == []
        assert comp.mcp_manager.summary()["enabled"] is False
    finally:
        await comp._stop_mcp()


# ── 启用：注册 + 可调用 ───────────────────────────────

@pytest.mark.asyncio
async def test_start_mcp_enabled_registers_prefixed_tools(monkeypatch, tmp_path):
    stub = _write_stub(tmp_path)
    _inject_stub_manager(monkeypatch, stub)
    comp = _companion_shell()

    await comp._start_mcp()
    try:
        assert comp.mcp_manager.client_names() == ["stub"]
        names = comp.tool_registry.list_names()
        assert "mcp__stub__echo" in names
        assert all(name.startswith("mcp__stub__") for name in names)
        entry = comp.tool_registry.get("mcp__stub__echo")
        assert entry is not None
        assert entry["category"] == "mcp"

        # ReAct 工具循环通过 registry.execute 调用，必须能拿到归一化结果
        result = await comp.tool_registry.execute("mcp__stub__echo", {"text": "hi"})
        assert result["status"] == "ok"
        assert result["text"] == "echo: hi"
        assert "error" not in result
    finally:
        await comp._stop_mcp()


# ── 失败降级 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_mcp_handshake_failure_degrades_without_blocking(monkeypatch, tmp_path):
    stub = _write_stub(tmp_path)
    _inject_stub_manager(monkeypatch, stub, mode="die")
    comp = _companion_shell()

    await comp._start_mcp()  # 不得抛错

    assert comp.mcp_manager is not None
    summary = comp.mcp_manager.summary()
    assert summary["enabled"] is True
    assert summary["started"] == []
    assert "stub" in summary["failed"]
    assert comp.tool_registry.list_names() == []
    await comp._stop_mcp()


@pytest.mark.asyncio
async def test_start_mcp_corrupted_config_keeps_disabled(monkeypatch, tmp_path):
    broken = tmp_path / "mcp_servers.yaml"
    broken.write_text("enabled: [unclosed\n", encoding="utf-8")
    monkeypatch.setattr(
        companion_module,
        "MCPClientManager",
        lambda registry: MCPClientManager(registry, config_path=broken),
    )
    comp = _companion_shell()

    await comp._start_mcp()

    assert comp.mcp_manager is not None
    assert comp.mcp_manager.summary()["enabled"] is False
    assert comp.tool_registry.list_names() == []
    await comp._stop_mcp()


@pytest.mark.asyncio
async def test_start_mcp_construction_crash_is_contained(monkeypatch):
    comp = _companion_shell()

    def _boom(_registry):
        raise RuntimeError("corrupted mcp config")

    monkeypatch.setattr(companion_module, "MCPClientManager", _boom)

    await comp._start_mcp()  # 不得抛错

    assert comp.mcp_manager is None
    await comp._stop_mcp()  # manager 为 None 时也必须安全


# ── companion 生命周期接线 ────────────────────────────

@pytest.mark.asyncio
async def test_companion_start_and_stop_wire_mcp_manager(monkeypatch, phase4_db):
    from tests.test_phase4_integration import _feature_env, _patch_companion

    _feature_env(monkeypatch, queue=False)
    companion_module = _patch_companion(monkeypatch)
    companion = companion_module.Companion(
        {"qq": {"self_qq": 0, "friends_qq": [], "startup_wait_timeout": 0}},
        database=phase4_db,
    )

    await companion.start()
    try:
        assert companion.mcp_manager is not None
        assert companion.mcp_manager.client_names() == []
        assert companion.tool_registry.list_names() == []
    finally:
        await companion.stop()

    assert companion.mcp_manager is not None
    assert companion.mcp_manager.client_names() == []


# ── 只读状态端点 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_background_status_reports_disabled(monkeypatch):
    import httpx

    from core import api_server

    comp = _companion_shell()
    await comp._start_mcp()
    monkeypatch.setattr(api_server, "get_companion", lambda: comp)

    transport = httpx.ASGITransport(app=api_server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/background/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp"] == {
        "enabled": False,
        "connected": 0,
        "tools_registered": 0,
        "servers": [],
        "failed": {},
    }
    await comp._stop_mcp()


@pytest.mark.asyncio
async def test_background_status_reports_connected_servers(monkeypatch, tmp_path):
    import httpx

    from core import api_server

    stub = _write_stub(tmp_path)
    _inject_stub_manager(monkeypatch, stub)
    comp = _companion_shell()
    await comp._start_mcp()
    monkeypatch.setattr(api_server, "get_companion", lambda: comp)

    transport = httpx.ASGITransport(app=api_server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/background/status")

    assert response.status_code == 200
    mcp = response.json()["mcp"]
    assert mcp["enabled"] is True
    assert mcp["connected"] == 1
    assert mcp["tools_registered"] == 4
    assert mcp["servers"] == ["stub"]
    await comp._stop_mcp()

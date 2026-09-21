"""B 部分：通用 MCP 客户端测试。

全部使用本地桩（stub）stdio MCP server，不依赖网络或真实远端服务。
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

from core import mcp_client
from core.mcp_client import (
    DEFAULT_CONFIG_PATH,
    MCPClientManager,
    MCPError,
    MCPServerConfig,
    load_servers_config,
    local_tool_name,
)
from core.tool_registry import ToolRegistry

# 最小 MCP server：行分隔 JSON-RPC over stdio，只实现本客户端用到的方法。
STUB_SOURCE = """
import json
import os
import sys
import time

MODE = os.environ.get("STUB_MODE", "normal")

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

if MODE == "die":
    sys.stderr.write("stub: boom during startup\\n")
    sys.stderr.flush()
    sys.exit(3)

sys.stderr.write("stub: ready\\n")
sys.stderr.flush()

TOOLS = [
    {"name": "echo", "description": "echo back text",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "boom", "description": "always fails", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "slow", "description": "sleeps then returns", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "weird name!", "description": "illegal chars", "inputSchema": {"type": "object", "properties": {}}},
]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "stub", "version": "0.1"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "echo: %s" % args.get("text", "")}],
                "structuredContent": {"echoed": args.get("text", "")},
            }})
        elif name == "boom":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "isError": True,
                "content": [{"type": "text", "text": "kaboom"}],
            }})
        elif name == "slow":
            time.sleep(1.0)
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "slow done"}],
            }})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32601, "message": "Unknown tool: %s" % name,
            }})
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {
            "code": -32601, "message": "Method not found: %s" % method,
        }})
"""


def _write_stub(tmp_path: Path) -> Path:
    stub = tmp_path / "stub_mcp_server.py"
    stub.write_text(textwrap.dedent(STUB_SOURCE), encoding="utf-8")
    return stub


def _servers(stub: Path, mode: str = "normal", **overrides) -> dict:
    cfg = {
        "enabled": True,
        "command": sys.executable,
        "args": [str(stub)],
        "env": {"STUB_MODE": mode},
        "timeout_seconds": 5,
        "call_timeout_seconds": 5,
    }
    cfg.update(overrides)
    return {"stub": cfg}


# ── 默认关闭 ──────────────────────────────────────────

def test_repo_config_is_disabled_by_default():
    """仓库自带配置必须默认关闭（不改变现有启动行为）。"""
    enabled, servers = load_servers_config(DEFAULT_CONFIG_PATH)
    assert enabled is False
    assert "justoneapi" in servers
    assert servers["justoneapi"]["enabled"] is False


def test_missing_config_file_stays_disabled(tmp_path):
    enabled, servers = load_servers_config(tmp_path / "nope.yaml")
    assert enabled is False
    assert servers == {}


@pytest.mark.asyncio
async def test_manager_disabled_does_not_touch_registry(tmp_path):
    registry = ToolRegistry()
    manager = MCPClientManager(registry, config_path=tmp_path / "nope.yaml")
    summary = await manager.start()
    assert summary == {"enabled": False, "started": [], "failed": {}, "tools_registered": 0}
    assert registry.list_names() == []
    await manager.aclose()


# ── tools/list 注册 ───────────────────────────────────

@pytest.mark.asyncio
async def test_tools_list_registers_with_expected_names(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    try:
        summary = await manager.start()
        assert summary["enabled"] is True
        assert summary["started"] == ["stub"]
        assert summary["failed"] == {}
        assert summary["tools_registered"] == 4

        entry = registry.get("mcp__stub__echo")
        assert entry is not None
        assert entry["category"] == "mcp"
        assert entry["provider_hint"] == "text"
        fn = entry["schema"]["function"]
        assert fn["name"] == "mcp__stub__echo"
        assert "[MCP:stub/echo]" in fn["description"]
        assert fn["parameters"]["properties"]["text"]["type"] == "string"

        # 非法字符的工具名被归一化
        assert registry.get("mcp__stub__weird_name_") is not None
    finally:
        await manager.aclose()


# ── 调用与结果归一化 ──────────────────────────────────

@pytest.mark.asyncio
async def test_call_tool_success_is_normalized(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    try:
        await manager.start()
        result = await registry.execute("mcp__stub__echo", {"text": "hi"})
        assert result["status"] == "ok"
        assert result["text"] == "echo: hi"
        assert result["server"] == "stub"
        assert result["tool"] == "echo"
        assert result["is_error"] is False
        assert result["structured"] == {"echoed": "hi"}
        assert "error" not in result
    finally:
        await manager.aclose()


@pytest.mark.asyncio
async def test_remote_iserror_becomes_error_dict(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    try:
        await manager.start()
        result = await registry.execute("mcp__stub__boom", {})
        assert "error" in result  # llm_caller 用 "error" not in result 判定失败
        assert result["status"] == "error"
        assert result["is_error"] is True
        assert "kaboom" in result["error"]
    finally:
        await manager.aclose()


@pytest.mark.asyncio
async def test_unknown_tool_is_diagnosable(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    try:
        await manager.start()
        client = manager.get_client("stub")
        out = await client.invoke("no_such_tool")
        assert out["kind"] == "method_not_found"
        assert out["error"].startswith("mcp_method_not_found:")
        assert "Unknown tool" in out["error"]
    finally:
        await manager.aclose()


@pytest.mark.asyncio
async def test_call_timeout_is_diagnosable(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub, call_timeout_seconds=0.1))
    proc = None
    try:
        await manager.start()
        client = manager.get_client("stub")
        proc = client._proc
        out = await client.invoke("slow")
        assert out["kind"] == "timeout"
        assert "超时" in out["error"]
    finally:
        await manager.aclose()
    assert proc.returncode is not None  # 超时路径同样要回收子进程


# ── 失败诊断 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_failure_is_diagnosable(tmp_path):
    registry = ToolRegistry()
    servers = {"stub": {
        "enabled": True,
        "command": "definitely-not-a-real-mcp-command",
        "args": [],
    }}
    manager = MCPClientManager(registry, servers=servers)
    try:
        summary = await manager.start()
        assert summary["started"] == []
        assert summary["failed"]["stub"].startswith("connect:")
        assert "命令不存在" in summary["failed"]["stub"]
        assert registry.list_names() == []
    finally:
        await manager.aclose()


@pytest.mark.asyncio
async def test_handshake_failure_reports_stderr(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub, mode="die"))
    try:
        summary = await manager.start()
        reason = summary["failed"]["stub"]
        assert reason.startswith("handshake:")
        assert "boom during startup" in reason  # stderr 尾巴带进错误信息
    finally:
        await manager.aclose()


@pytest.mark.asyncio
async def test_bad_config_does_not_block_other_servers(tmp_path):
    stub = _write_stub(tmp_path)
    servers = _servers(stub)
    servers["bad"] = {"enabled": True, "transport": "sse", "command": "npx"}
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=servers)
    try:
        summary = await manager.start()
        assert summary["started"] == ["stub"]
        assert summary["failed"]["bad"].startswith("config:")
    finally:
        await manager.aclose()


def test_from_dict_rejects_bad_config():
    with pytest.raises(MCPError) as info:
        MCPServerConfig.from_dict("x", {"transport": "sse", "command": "npx"})
    assert info.value.kind == "config"

    with pytest.raises(MCPError) as info2:
        MCPServerConfig.from_dict("x", {"command": ""})
    assert info2.value.kind == "config"


# ── 生命周期 / 清理 ───────────────────────────────────

@pytest.mark.asyncio
async def test_close_reaps_child_process(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    await manager.start()
    client = manager.get_client("stub")
    proc = client._proc
    assert proc is not None and proc.returncode is None

    await manager.aclose()
    assert proc.returncode is not None  # 子进程已被回收
    assert manager.client_names() == []
    assert client.connected is False
    assert client not in mcp_client._ACTIVE_CLIENTS  # 退出兜底清单里不留残项

    await manager.aclose()  # 幂等
    assert manager.client_names() == []


@pytest.mark.asyncio
async def test_sync_reaper_terminates_live_child(tmp_path):
    """进程退出兜底（atexit 路径）：同步回收必须能杀掉仍存活的子进程。"""
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    await manager.start()
    client = manager.get_client("stub")
    proc = client._proc
    assert proc.returncode is None

    mcp_client._reap_all_nowait()  # 模拟进程退出时的同步清理
    assert client not in mcp_client._ACTIVE_CLIENTS
    await asyncio.wait_for(proc.wait(), timeout=5)
    assert proc.returncode is not None

    await manager.aclose()  # 之后再走正常关闭也不能报错


@pytest.mark.asyncio
async def test_after_close_calls_fail_cleanly(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    await manager.start()
    client = manager.get_client("stub")
    await manager.aclose()
    out = await client.invoke("echo", {"text": "x"})
    assert out["kind"] in {"closed", "process_exit"}
    assert out["error"].startswith("mcp_")


# ── 命名与去重规则 ────────────────────────────────────

def test_local_tool_name_sanitizes_illegal_chars():
    assert local_tool_name("my server", "weird name!") == "mcp__my_server__weird_name_"


def test_local_tool_name_is_bounded_and_distinct():
    long_a = local_tool_name("srv", "a" * 200)
    long_b = local_tool_name("srv", "b" * 200)
    assert len(long_a) <= 64 and len(long_b) <= 64
    assert long_a != long_b


@pytest.mark.asyncio
async def test_name_conflict_never_overwrites_existing_tool(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()

    def existing() -> dict:
        return {"origin": "builtin"}

    registry.register("mcp__stub__echo", existing, {"description": "builtin"})

    manager = MCPClientManager(registry, servers=_servers(stub))
    try:
        summary = await manager.start()
        assert summary["tools_registered"] == 3  # echo 被跳过
        assert registry.get("mcp__stub__echo")["func"] is existing
        client = manager.get_client("stub")
        assert client.registered_tools.get("mcp__stub__echo") is None
    finally:
        await manager.aclose()


@pytest.mark.asyncio
async def test_register_tools_is_idempotent(tmp_path):
    stub = _write_stub(tmp_path)
    registry = ToolRegistry()
    manager = MCPClientManager(registry, servers=_servers(stub))
    try:
        await manager.start()
        client = manager.get_client("stub")
        again = client.register_tools(registry, client.tools)
        assert again["registered"] == {}
        assert set(again["skipped"].values()) == {"already_registered"}
    finally:
        await manager.aclose()

"""MCP HTTP transport：远端 MCP server（Notion / 天眼查这类）的接入。

为什么需要它：`core/mcp_client.py` 原本只支持 stdio 子进程，而 Notion 官方
（`https://mcp.notion.com/mcp`）与天眼查（`https://mcp.tianyancha.com/v1`）
都是 **Streamable HTTP** 端点。没有这条 transport，"优先接现成 MCP"就落不了地。

规范要点（modelcontextprotocol.io/specification 的 Streamable HTTP）：
  - 每个 JSON-RPC 消息是一次独立的 HTTP POST；
  - 请求头必须同时声明可接受的 `application/json` 与 `text/event-stream`；
  - 响应可能是单个 JSON 对象，也可能是一条 SSE 流（流里先有通知、最后是响应）；
  - 服务端可在 initialize 响应头下发 `Mcp-Session-Id`，后续请求须带回；
  - 鉴权走标准 HTTP 头（本项目用 `Authorization: Bearer <token>`）。

全程 mock `requests.post`，不碰网络。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from core.mcp_client import (
    MCPServerClient,
    MCPServerConfig,
    MCPError,
    _iter_sse_events,
    _response_from_sse,
)


class _Resp:
    def __init__(self, status_code=200, body="", headers=None):
        self.status_code = status_code
        self.text = body
        self.headers = headers or {}


def _install_post(monkeypatch, *responses):
    """把 requests.post 换成按顺序返回给定响应的桩，并记录每次调用。"""
    calls: list[dict] = []
    queue = list(responses)

    def _post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return queue.pop(0) if queue else _Resp(200, "{}")

    monkeypatch.setattr("requests.post", _post)
    return calls


# ── 配置解析 ──────────────────────────────────────────


def test_http_config_parses_url_and_headers():
    cfg = MCPServerConfig.from_dict("notion", {
        "transport": "http",
        "url": "https://mcp.notion.com/mcp",
        "headers": {"Authorization": "Bearer ntn_x"},
    })
    assert cfg.is_http is True
    assert cfg.url == "https://mcp.notion.com/mcp"
    assert cfg.headers["Authorization"] == "Bearer ntn_x"
    assert cfg.command == ""


def test_config_expands_env_placeholders(monkeypatch):
    """凭据走 ${VAR} 引用，避免把密钥抄进会被提交的 YAML。"""
    monkeypatch.setenv("NOTION_TOKEN", "ntn_secret")
    cfg = MCPServerConfig.from_dict("notion", {
        "transport": "http",
        "url": "https://mcp.notion.com/mcp",
        "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"},
    })
    assert cfg.headers["Authorization"] == "Bearer ntn_secret"


def test_stdio_env_also_expands(monkeypatch):
    monkeypatch.setenv("SOME_TOKEN", "abc")
    cfg = MCPServerConfig.from_dict("s", {
        "command": "npx", "args": ["-y", "x"],
        "env": {"TOKEN": "${SOME_TOKEN}"},
    })
    assert cfg.env["TOKEN"] == "abc"


def test_http_config_requires_url():
    with pytest.raises(MCPError) as ei:
        MCPServerConfig.from_dict("bad", {"transport": "http"})
    assert "url" in ei.value.message


def test_http_config_rejects_non_http_scheme():
    with pytest.raises(MCPError):
        MCPServerConfig.from_dict("bad", {"transport": "http", "url": "file:///etc/passwd"})


def test_unknown_transport_rejected():
    with pytest.raises(MCPError) as ei:
        MCPServerConfig.from_dict("bad", {"transport": "carrier-pigeon", "url": "https://x"})
    assert "transport" in ei.value.message


# ── SSE 解析 ──────────────────────────────────────────


def test_iter_sse_events_ignores_comments_and_joins_multiline():
    text = (
        ": keep-alive\n"
        "event: message\n"
        "data: {\"a\": 1}\n"
        "\n"
        "data: {\"b\":\n"
        "data:  2}\n"
        "\n"
    )
    assert _iter_sse_events(text) == ['{"a": 1}', '{"b":\n 2}']


def test_response_from_sse_picks_matching_id():
    """流里前面可能有通知，只有 id 对得上的那条才是本次结果。"""
    text = (
        "data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\"}\n\n"
        "data: {\"jsonrpc\":\"2.0\",\"id\":0,\"result\":{\"protocolVersion\":\"2025-06-18\"}}\n\n"
    )
    msg = _response_from_sse(text, 0)
    assert msg["result"]["protocolVersion"] == "2025-06-18"


def test_response_from_sse_returns_none_when_absent():
    assert _response_from_sse("data: {\"id\": 99}\n\n", 0) is None


# ── 请求装配与响应处理 ────────────────────────────────


def _call_headers(calls: list[dict]) -> dict:
    return calls[0]["headers"]


def test_http_request_sends_required_headers(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer tok-123"},
    })
    client = MCPServerClient(config)
    calls = _install_post(
        monkeypatch, _Resp(200, json.dumps({"jsonrpc": "2.0", "id": 0, "result": {}}))
    )

    asyncio.run(client._request_http("tools/list", {}, timeout=5))

    headers = _call_headers(calls)
    # 规范强制：两种响应类型都要声明
    assert "application/json" in headers["Accept"]
    assert "text/event-stream" in headers["Accept"]
    assert headers["Content-Type"] == "application/json"
    assert headers["MCP-Protocol-Version"]
    # 配置里的鉴权头原样带上
    assert headers["Authorization"] == "Bearer tok-123"
    assert calls[0]["url"] == "https://mcp.example.com/mcp"


def test_http_request_parses_sse_response(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    _install_post(monkeypatch, _Resp(
        200,
        "data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\"}\n\n"
        "data: {\"jsonrpc\":\"2.0\",\"id\":0,\"result\":{\"tools\":[]}}\n\n",
        headers={"Content-Type": "text/event-stream"},
    ))

    assert asyncio.run(client._request_http("tools/list", {}, timeout=5)) == {"tools": []}


def test_session_id_is_captured_and_replayed(monkeypatch):
    """initialize 响应头下发的会话 id，后续请求必须带回去。"""
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    calls = _install_post(
        monkeypatch,
        _Resp(200, json.dumps({"jsonrpc": "2.0", "id": 0, "result": {}}),
              headers={"Mcp-Session-Id": "sess-42"}),
        _Resp(200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})),
    )

    asyncio.run(client._request_http("initialize", {}, timeout=5))
    assert client._http_session_id == "sess-42"

    asyncio.run(client._request_http("tools/list", {}, timeout=5))
    assert calls[1]["headers"]["Mcp-Session-Id"] == "sess-42"


def test_http_401_is_reported_as_auth_error(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    _install_post(monkeypatch, _Resp(401, "unauthorized"))

    with pytest.raises(MCPError) as ei:
        asyncio.run(client._request_http("tools/list", {}, timeout=5))
    assert ei.value.kind == "auth"
    assert "凭据" in ei.value.message


def test_http_500_is_reported_as_http_error(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    _install_post(monkeypatch, _Resp(503, "upstream down"))

    with pytest.raises(MCPError) as ei:
        asyncio.run(client._request_http("tools/list", {}, timeout=5))
    assert ei.value.kind == "http_error"
    assert "503" in ei.value.message


def test_remote_jsonrpc_error_is_raised(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    _install_post(monkeypatch, _Resp(200, json.dumps({
        "jsonrpc": "2.0", "id": 0,
        "error": {"code": -32601, "message": "Method not found"},
    })))

    with pytest.raises(MCPError) as ei:
        asyncio.run(client._request_http("tools/list", {}, timeout=5))
    assert "Method not found" in ei.value.message


def test_2xx_without_matching_id_is_not_treated_as_success(monkeypatch):
    """拿到 200 但没有我们那条 id 的结果 → 如实报错，不能当成功返回空。"""
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    _install_post(monkeypatch, _Resp(200, json.dumps({"jsonrpc": "2.0", "id": 99, "result": {}})))

    with pytest.raises(MCPError) as ei:
        asyncio.run(client._request_http("tools/list", {}, timeout=5))
    assert ei.value.kind == "protocol"


def test_connection_error_is_reported(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)

    def _boom(url, **kwargs):
        raise ConnectionError("dns fail")

    monkeypatch.setattr("requests.post", _boom)

    with pytest.raises(MCPError) as ei:
        asyncio.run(client._request_http("tools/list", {}, timeout=5))
    assert ei.value.kind == "http_error"


# ── 握手 ──────────────────────────────────────────────


def test_connect_over_http_completes_handshake(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer t"},
    })
    client = MCPServerClient(config)
    _install_post(
        monkeypatch,
        _Resp(200, json.dumps({
            "jsonrpc": "2.0", "id": 0,
            "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "demo-server", "version": "1"},
            },
        })),
        _Resp(202, ""),  # notifications/initialized
    )

    info = asyncio.run(client.connect())

    assert info["name"] == "demo-server"
    assert client.connected is True
    assert client.server_info["name"] == "demo-server"


def test_connect_over_http_failure_closes_connection(monkeypatch):
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    _install_post(monkeypatch, _Resp(403, "forbidden"))

    with pytest.raises(MCPError) as ei:
        asyncio.run(client.connect())
    assert ei.value.kind == "handshake"
    assert client.connected is False


def test_http_client_close_is_safe_without_subprocess(monkeypatch):
    """HTTP 没有子进程，close() 必须安全幂等。"""
    config = MCPServerConfig.from_dict("demo", {
        "transport": "http", "url": "https://mcp.example.com/mcp",
    })
    client = MCPServerClient(config)
    _install_post(monkeypatch, _Resp(202, ""))
    asyncio.run(client.close())
    asyncio.run(client.close())
    client.terminate_nowait()  # 不应抛错

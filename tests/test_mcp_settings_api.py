"""MCP 服务器管理端点：设置页开关与凭据 → .env → 配置加载，整条链路。

界面上的开关如果不真的影响配置加载，就只是装饰。这里专门覆盖那条回环：
写进 .env 的开关名，必须被 core/mcp_client.py 认出来。
"""

from __future__ import annotations

import asyncio

import pytest

from core import api_server, env_file
from core.mcp_client import MCPServerConfig, load_servers_config
from tests._http_helpers import make_request as _request


@pytest.fixture(autouse=True)
def isolated_env_file(tmp_path, monkeypatch):
    """钉住 .env：测试密钥绝不能写进仓库根的真实 .env。"""
    monkeypatch.setattr(env_file, "env_file_path", lambda: tmp_path / ".env")
    # 环境变量覆盖也要清干净，否则受宿主机影响
    for name in (
        "AERIE_MCP_ENABLED",
        "AERIE_MCP_SERVER_NOTION",
        "AERIE_MCP_SERVER_TIANYANCHA",
        "AERIE_MCP_SERVER_JUSTONEAPI",
        "NOTION_TOKEN",
        "TIANYAN_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / ".env"


# ── 读取 ──────────────────────────────────────────────


def test_lists_presets_with_transport_and_endpoint():
    data = asyncio.run(api_server.env_mcp_servers_get())

    by_key = {s["key"]: s for s in data["servers"]}
    assert {"notion", "tianyancha", "justoneapi"} <= set(by_key)

    notion = by_key["notion"]
    assert notion["transport"] == "stdio"
    assert notion["endpoint"] == "npx"
    assert notion["enabled"] is False
    assert notion["restart_required"] is True

    tyc = by_key["tianyancha"]
    assert tyc["transport"] == "http"
    assert tyc["endpoint"].startswith("https://")


def test_required_credential_fields_are_derived_from_config():
    """字段来自配置里的 ${VAR} 引用 —— 单一事实来源，不在两处各写一份。"""
    data = asyncio.run(api_server.env_mcp_servers_get())
    by_key = {s["key"]: s for s in data["servers"]}

    assert [f["env_key"] for f in by_key["notion"]["fields"]] == ["NOTION_TOKEN"]
    assert [f["env_key"] for f in by_key["tianyancha"]["fields"]] == ["TIANYAN_TOKEN"]
    # 没有 ${VAR} 引用的 server 不该凭空长出字段
    assert by_key["justoneapi"]["fields"] == []


def test_credential_label_reuses_platform_credentials_declaration():
    """同一个环境变量在两处（平台凭证 / MCP）不该各写一套标签。"""
    data = asyncio.run(api_server.env_mcp_servers_get())
    notion = next(s for s in data["servers"] if s["key"] == "notion")
    field = notion["fields"][0]
    assert field["label"] == "Personal Access Token"
    assert field["secret"] is True


def test_configured_flag_reflects_env_file():
    assert asyncio.run(api_server.env_mcp_servers_get())["servers"][1]["configured"] is False

    env_file.write_env_file({"TIANYAN_TOKEN": "tyc-12345678"})

    data = asyncio.run(api_server.env_mcp_servers_get())
    tyc = next(s for s in data["servers"] if s["key"] == "tianyancha")
    assert tyc["configured"] is True
    # 明文不得出现在响应里
    assert "tyc-12345678" not in str(data)
    assert tyc["fields"][0]["masked"].endswith("5678")


# ── 写入 ──────────────────────────────────────────────


def test_toggling_master_writes_env_flag():
    result = asyncio.run(api_server.env_mcp_servers_save(
        _request({"master_enabled": True})
    ))
    assert result["status"] == "ok"
    assert result["restart_required"] is True
    assert env_file.read_env_file()["AERIE_MCP_ENABLED"] == "1"


def test_toggling_one_server_writes_its_own_flag():
    asyncio.run(api_server.env_mcp_servers_save(
        _request({"server_key": "notion", "enabled": True})
    ))
    env = env_file.read_env_file()
    assert env["AERIE_MCP_SERVER_NOTION"] == "1"
    # 不能顺手把别的 server 也打开
    assert "AERIE_MCP_SERVER_TIANYANCHA" not in env


def test_saving_credentials_writes_env_and_hot_reloads():
    asyncio.run(api_server.env_mcp_servers_save(_request({
        "server_key": "notion",
        "fields": {"NOTION_TOKEN": "ntn_secret_value"},
    })))
    assert env_file.read_env_file()["NOTION_TOKEN"] == "ntn_secret_value"


def test_masked_placeholder_is_never_written_back():
    """回归：前端回显的是脱敏串，用户没改那一格就点保存时不得覆盖真实密钥。"""
    env_file.write_env_file({"NOTION_TOKEN": "ntn_real_key"})

    asyncio.run(api_server.env_mcp_servers_save(_request({
        "server_key": "notion",
        "fields": {"NOTION_TOKEN": "••••••••_key"},
    })))

    assert env_file.read_env_file()["NOTION_TOKEN"] == "ntn_real_key"


def test_unknown_server_is_rejected():
    resp = asyncio.run(api_server.env_mcp_servers_save(
        _request({"server_key": "no-such-mcp", "enabled": True})
    ))
    assert resp.status_code == 400


def test_env_key_not_declared_by_that_server_is_ignored():
    """不能借某台 server 的名字往 .env 里塞任意键。"""
    asyncio.run(api_server.env_mcp_servers_save(_request({
        "server_key": "notion",
        "fields": {"DEEPSEEK_API_KEY": "injected"},
    })))
    assert "DEEPSEEK_API_KEY" not in env_file.read_env_file()


# ── 回环：写进去的开关，配置加载必须认 ──────────────────


def test_env_flag_overrides_yaml_default(monkeypatch):
    """这条是整个界面存在的理由：开关必须真的影响加载结果。"""
    monkeypatch.setenv("AERIE_MCP_SERVER_NOTION", "1")
    enabled_map, raw = load_servers_config()
    assert enabled_map is False  # 总闸仍是 YAML 默认的 false
    cfg = MCPServerConfig.from_dict("notion", raw["notion"])
    assert cfg.enabled is True


def test_master_env_flag_overrides_yaml(monkeypatch):
    monkeypatch.setenv("AERIE_MCP_ENABLED", "1")
    master, _ = load_servers_config()
    assert master is True


def test_yaml_default_applies_when_env_absent():
    master, raw = load_servers_config()
    assert master is False
    assert MCPServerConfig.from_dict("notion", raw["notion"]).enabled is False


def test_round_trip_through_the_endpoint(monkeypatch):
    """端到端：调保存接口 → 配置加载真的认这个开关。"""
    asyncio.run(api_server.env_mcp_servers_save(
        _request({"server_key": "notion", "enabled": True})
    ))
    # 端点已把变更同步进 os.environ
    _, raw = load_servers_config()
    assert MCPServerConfig.from_dict("notion", raw["notion"]).enabled is True

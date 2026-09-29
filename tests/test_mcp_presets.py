"""MCP server 预设：Notion（stdio + 令牌）与 天眼查（远程 HTTP + 令牌）。

两条通道的形态不同，都是查证过实际配置后定的：

* **Notion** —— 官方的托管 MCP（`mcp.notion.com/mcp`）**只支持 OAuth 2.0 + PKCE，
  无法在无人工点击的后端里跑**；官方那个开源 stdio server 又会一次性灌进
  17,163 tokens 的工具 schema。因此选社区维护的 `notion-mcp-server`：静态
  Personal Access Token，工具 schema 仅约 1,005 tokens。

* **天眼查** —— 官方远程 MCP，`Authorization: Bearer <token>`，
  走 core/mcp_client.py 的 HTTP transport。

两条都默认 `enabled: false`：MCP 会拉起子进程/建立外连，必须是用户显式开启的动作。
"""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "mcp_servers.yaml"


def _cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_top_level_switch_defaults_off():
    """总闸默认关：没配好就绝不建立任何连接。"""
    assert _cfg()["enabled"] is False


def test_notion_preset_is_stdio_with_token():
    servers = _cfg()["servers"]
    assert "notion" in servers, "缺少 notion 预设"
    notion = servers["notion"]
    assert notion["enabled"] is False
    assert notion["transport"] == "stdio"
    assert notion["command"] == "npx"
    assert "-y" in notion["args"]
    # 令牌走 ${VAR} 引用：密钥只存在 .env，不进会被提交的 YAML
    assert notion["env"]["NOTION_TOKEN"] == "${NOTION_TOKEN}"


def test_tianyancha_preset_is_http_with_bearer_token():
    servers = _cfg()["servers"]
    assert "tianyancha" in servers, "缺少 天眼查 预设"
    tyc = servers["tianyancha"]
    assert tyc["enabled"] is False
    assert tyc["transport"] == "http"
    assert tyc["url"].startswith("https://")
    assert tyc["headers"]["Authorization"] == "Bearer ${TIANYAN_TOKEN}"


def test_presets_load_through_the_client_config_parser():
    """预设必须能被 MCPServerConfig 解析 —— 否则只是看着像配置的文本。"""
    from core.mcp_client import MCPServerConfig

    for name, raw in _cfg()["servers"].items():
        cfg = MCPServerConfig.from_dict(name, raw)
        assert cfg.enabled is False
        if cfg.is_http:
            assert cfg.url
        else:
            assert cfg.command


def test_preset_token_names_match_platform_credentials():
    """MCP 预设引用的密钥名，必须与设置页「平台凭证」写进 .env 的名字一致。

    不一致的话，用户在设置页填完密钥，MCP 这边仍然是空的 —— 界面显示"已配置"、
    实际用不了，是最难排查的一类假成功。
    """
    from core.api_server import _PLATFORM_CREDENTIALS

    declared = {
        f["env_key"]
        for entry in _PLATFORM_CREDENTIALS
        for f in entry.get("fields", [])
    }
    servers = _cfg()["servers"]
    for token in ("NOTION_TOKEN", "TIANYAN_TOKEN"):
        assert token in declared, f"{token} 未在设置页平台凭证里声明"

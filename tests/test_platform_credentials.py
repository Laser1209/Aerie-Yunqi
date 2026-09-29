"""平台凭证：设置页填写 -> .env -> os.environ -> skill 可用性，整条链路的回归。

这些凭据由用户自备（Notion / 天眼查 / 火山系 / 支付 / 部署），因此保存后
**必须当场生效** —— 模型可见的工具清单是启动时定下的，不重扫就等于没保存，
而界面上还会显示「已保存」，是最难排查的一类假成功。
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from core import api_server, env_file
from core import skill_loader as skill_loader_module
from core.skill_loader import SkillLoader
from core.skill_router import SkillRouter
from core.tool_registry import ToolRegistry
from tests._http_helpers import make_request as _request


@pytest.fixture(autouse=True)
def isolated_env_file(tmp_path, monkeypatch):
    """把 .env 钉到临时目录 —— 测试密钥绝不能写进仓库根的真实 .env。"""
    monkeypatch.setattr(env_file, "env_file_path", lambda: tmp_path / ".env")
    return tmp_path / ".env"


def test_platform_credentials_are_exposed_alongside_feature_apis():
    data = asyncio.run(api_server.env_feature_apis_get())

    # 功能 API 那一组不能被这次改动挤掉
    assert {f["key"] for f in data["features"]} >= {
        "bocha_search", "baidu_map", "dailyhot", "open_meteo",
    }

    creds = data["platform_credentials"]
    assert {c["key"] for c in creds} == {
        "notion", "tianyancha", "seedream", "seedance", "mediakit",
        "volcengine_tos", "byteplus_pages", "iga_pages",
        "alipay", "douyinpay", "douyin_interactive",
    }
    for c in creds:
        assert c["configured"] is False
        assert c["status"] == "unconfigured"
        assert c["tutorial"] is not None  # 无教程留空串，但键必须存在
        for f in c["fields"]:
            assert f["masked"] == ""


def test_secret_field_is_masked_in_response():
    env_file.write_env_file({"TIANYAN_TOKEN": "abcdefgh1234"})

    data = asyncio.run(api_server.env_feature_apis_get())
    tianyan = next(c for c in data["platform_credentials"] if c["key"] == "tianyancha")
    assert tianyan["configured"] is True
    assert tianyan["status"] == "configured"

    field = tianyan["fields"][0]
    assert field["secret"] is True
    assert field["masked"] == "•" * 8 + "1234"
    # 明文绝不能出现在响应里
    assert "abcdefgh1234" not in json.dumps(data)


def test_save_writes_env_and_hot_reloads(monkeypatch):
    monkeypatch.delenv("TIANYAN_TOKEN", raising=False)

    result = asyncio.run(api_server.env_feature_apis_save(
        _request({"feature_key": "tianyancha", "fields": {"TIANYAN_TOKEN": "ty-secret-1234"}})
    ))

    assert result["status"] == "ok"
    assert result["hot_reloaded"] == ["TIANYAN_TOKEN"]
    assert env_file.read_env_file()["TIANYAN_TOKEN"] == "ty-secret-1234"
    # 进程内环境必须同步刷新，否则 run.py 的 os.getenv 读不到
    assert os.environ["TIANYAN_TOKEN"] == "ty-secret-1234"


def test_masked_placeholder_is_never_written_back(monkeypatch):
    """回归：前端回显的是脱敏串，用户没改那一格就点保存时不得覆盖真实密钥。"""
    monkeypatch.delenv("TIANYAN_TOKEN", raising=False)

    asyncio.run(api_server.env_feature_apis_save(
        _request({"feature_key": "tianyancha", "fields": {"TIANYAN_TOKEN": "ty-real-key"}})
    ))
    result = asyncio.run(api_server.env_feature_apis_save(
        _request({"feature_key": "tianyancha", "fields": {"TIANYAN_TOKEN": "•" * 8 + "-key"}})
    ))

    assert result["hot_reloaded"] == []  # 没有真的改动
    assert env_file.read_env_file()["TIANYAN_TOKEN"] == "ty-real-key"
    assert os.environ["TIANYAN_TOKEN"] == "ty-real-key"


def test_clearing_a_credential_is_allowed(monkeypatch):
    """空串是「清空」，与脱敏占位不同，必须真的写进去。"""
    monkeypatch.delenv("NOTION_TOKEN", raising=False)

    asyncio.run(api_server.env_feature_apis_save(
        _request({"feature_key": "notion", "fields": {"NOTION_TOKEN": "ntn_realkey"}})
    ))
    result = asyncio.run(api_server.env_feature_apis_save(
        _request({"feature_key": "notion", "fields": {"NOTION_TOKEN": ""}})
    ))

    assert result["hot_reloaded"] == ["NOTION_TOKEN"]
    assert env_file.read_env_file()["NOTION_TOKEN"] == ""


def test_unknown_feature_key_is_rejected():
    resp = asyncio.run(api_server.env_feature_apis_save(
        _request({"feature_key": "no-such-platform", "fields": {}})
    ))
    assert resp.status_code == 400


def test_save_reports_newly_activated_skills(monkeypatch):
    """保存接口要把「本次刚点亮的技能」透出来，前端据此给用户反馈。"""
    monkeypatch.setattr(api_server, "_resync_skills", lambda: ["tianyan"])
    result = asyncio.run(api_server.env_feature_apis_save(
        _request({"feature_key": "tianyancha", "fields": {"TIANYAN_TOKEN": "k"}})
    ))
    assert result["activated_skills"] == ["tianyan"]


# ── SkillLoader.resync()：凭证到位后 skill 从「不可用」变「已注册」 ──────


def _write_cred_skill(root, name: str, env_key: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: needs {env_key}\n"
        "provider_hint: text\n"
        "read_only: true\n"
        f"requires_env: {env_key}\n"
        "---\n\n正文。\n",
        encoding="utf-8",
    )
    (d / "run.py").write_text(
        "def run(args):\n    return {'status': 'ok'}\n", encoding="utf-8"
    )


def test_resync_activates_skill_once_credential_appears(tmp_path, monkeypatch):
    root = tmp_path / "cloud"
    _write_cred_skill(root, "cred-skill", "AERIE_TEST_CRED")
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((root, "cloud"),))
    monkeypatch.setattr(skill_loader_module, "_ALLOWED_BASES", (root.resolve(),))
    monkeypatch.delenv("AERIE_TEST_CRED", raising=False)

    registry = ToolRegistry()
    loader = SkillLoader(registry, SkillRouter({}))
    loader.discover()
    assert loader.register_all() == 0  # 缺凭据 -> 不注册
    assert registry.get("cred-skill") is None

    assert loader.resync() == []  # 仍然缺凭据 -> 没有新注册

    monkeypatch.setenv("AERIE_TEST_CRED", "now-present")
    assert loader.resync() == ["cred-skill"]  # 凭据到位 -> 当场可用
    assert registry.get("cred-skill") is not None
    # 幂等：再扫一次不会重复计入
    assert loader.resync() == []

"""API：厂商增删改查（含启用停用）、保存即测、功能点绑定先测后存。"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from core import api_server
from core.ai_services import AiServicesStore
from core.api_server import app
from core.database import Database

client = TestClient(app)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    Database.reset_instance()
    store = AiServicesStore(Database(tmp_path / "provider-api.db"))
    monkeypatch.setattr(api_server, "_ai_store", lambda: store)
    monkeypatch.setattr(api_server, "_hot_reload_brain", lambda: None)
    yield store
    Database.reset_instance()


def _ok_check(**over):
    base = {"ok": True, "detail": "", "http_status": 200, "latency_ms": 12, "mode": "chat"}
    base.update(over)
    return base


@pytest.fixture
def check_ok(monkeypatch):
    mock = AsyncMock(return_value=_ok_check())
    monkeypatch.setattr(api_server, "run_provider_check", mock)
    return mock


@pytest.fixture
def check_fail(monkeypatch):
    mock = AsyncMock(return_value=_ok_check(ok=False, http_status=401, detail="Unauthorized"))
    monkeypatch.setattr(api_server, "run_provider_check", mock)
    return mock


def _body(**over):
    base = {
        "kind": "custom",
        "name": "TokenDance",
        "base_url": "https://td.example.com/v1",
        "api_key": "sk-td-123456",
        "model": "td-4o",
        "supports_tools": False,
        "max_tool_calls": 8,
    }
    base.update(over)
    return base


def _custom_rows(store):
    return [p for p in store.list_providers(include_key=True) if p["kind"] != "builtin"]


def test_list_returns_builtins_with_masked_keys(isolated_store):
    r = client.get("/api/ai/providers")
    assert r.status_code == 200
    data = r.json()
    ids = [p["id"] for p in data["providers"]]
    assert "deepseek" in ids
    assert all(not p["api_key_masked"] or "•" in p["api_key_masked"] for p in data["providers"])
    assert any(s["key"] == "image" for s in data["special_services"])
    # 已被 seed 的内置厂商不再出现在「可添加」清单里
    assert "deepseek" not in [m["key"] for m in data["available_builtins"]]


def test_put_creates_provider_after_ok_check(isolated_store, check_ok):
    r = client.put("/api/ai/providers", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert data["provider"]["name"] == "TokenDance"
    assert data["provider"]["api_key_masked"].startswith("•")
    assert data["check"]["ok"] is True
    rows = _custom_rows(isolated_store)
    assert len(rows) == 1 and rows[0]["api_key"] == "sk-td-123456"
    assert isolated_store.get_checks()[rows[0]["id"]]["ok"] is True


def test_put_failed_check_does_not_persist(isolated_store, check_fail):
    r = client.put("/api/ai/providers", json=_body())
    assert r.status_code == 422
    assert _custom_rows(isolated_store) == []


def test_put_force_saves_despite_failed_check(isolated_store, check_fail):
    r = client.put("/api/ai/providers", json=_body(force=True))
    assert r.status_code == 200
    assert len(_custom_rows(isolated_store)) == 1


def test_put_update_keeps_key_when_blank(isolated_store, check_ok):
    created = client.put("/api/ai/providers", json=_body()).json()["provider"]
    r = client.put("/api/ai/providers", json=_body(
        id=created["id"], name="TokenDance Pro", api_key="", model="td-4o-mini"))
    assert r.status_code == 200
    record = isolated_store.get_provider(created["id"])
    assert record["name"] == "TokenDance Pro"
    assert record["api_key"] == "sk-td-123456"
    assert record["model"] == "td-4o-mini"


def test_put_rejects_masked_key(isolated_store, check_ok):
    r = client.put("/api/ai/providers", json=_body(api_key="••••4567"))
    assert r.status_code == 400
    assert _custom_rows(isolated_store) == []


def test_put_local_cli_skips_network_check(isolated_store, monkeypatch):
    """本地 CLI 厂商不走网络探测，也不要求 Base URL / API Key。"""
    mock = AsyncMock(return_value=_ok_check())
    monkeypatch.setattr(api_server, "run_provider_check", mock)
    r = client.put("/api/ai/providers", json={
        "kind": "local_cli",
        "name": "即梦 Seedream",
        "model": "seedream_5.0_pro",
    })
    assert r.status_code == 200
    assert r.json()["check"]["mode"] == "local"
    mock.assert_not_called()


def test_enabled_toggle_keeps_key_and_clears_env(tmp_path, monkeypatch, check_ok):
    """停用只清 .env 凭据，库里的 Key 保留；重新启用后原样恢复。

    凭据显式声明：seed 读的是 `os.environ`，此前"能读到"只是因为宿主 `.env`
    被别的模块顺手灌进了环境（见 conftest::isolate_host_dotenv）——
    测试不该依赖这种偶发污染，否则 .env 一改结果就变。
    """
    import os

    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-seed-key")

    Database.reset_instance()
    store = AiServicesStore(Database(tmp_path / "provider-api.db"))
    monkeypatch.setattr(api_server, "_ai_store", lambda: store)
    monkeypatch.setattr(api_server, "_hot_reload_brain", lambda: None)
    try:
        stored_key = store.get_provider("deepseek")["api_key"]
        assert stored_key == "ds-seed-key", "内置厂商 seed 应带上 os.environ 里的既有凭据"

        r = client.post("/api/ai/providers/deepseek/enabled", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["provider"]["enabled"] is False
        assert store.get_provider("deepseek")["api_key"] == stored_key
        assert os.environ["DEEPSEEK_API_KEY"] == ""

        r = client.post("/api/ai/providers/deepseek/enabled", json={"enabled": True})
        assert r.status_code == 200
        assert os.environ["DEEPSEEK_API_KEY"] == stored_key
    finally:
        Database.reset_instance()


def test_delete_clears_row_and_resets_binding(isolated_store, check_ok, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    created = client.put("/api/ai/providers", json=_body()).json()["provider"]
    isolated_store.set_binding("main_chat", created["id"], "td-4o")

    r = client.delete(f"/api/ai/providers/{created['id']}")
    assert r.status_code == 200
    binding = isolated_store.get_bindings()["main_chat"]
    assert binding["provider"] == "deepseek"
    assert binding["model"] == "deepseek-chat"


def test_deleted_builtin_becomes_re_addable(isolated_store):
    """删掉内置厂商后必须在「可添加」清单里重新出现，否则用户无法恢复。"""
    assert client.delete("/api/ai/providers/deepseek").status_code == 200
    assert client.delete("/api/ai/providers/deepseek").status_code == 404
    available = [m["key"] for m in client.get("/api/ai/providers").json()["available_builtins"]]
    assert "deepseek" in available


def test_check_endpoint_records_result(isolated_store, monkeypatch):
    async def fake_check(*, base_url, api_key, model, mode):
        return {"ok": True, "detail": "", "http_status": 200,
                "latency_ms": 5, "mode": mode, "checked_at": "t"}
    monkeypatch.setattr(api_server, "run_provider_check", AsyncMock(side_effect=fake_check))
    r = client.post("/api/ai/providers/deepseek/check")
    assert r.status_code == 200
    assert r.json()["check"]["ok"] is True
    assert isolated_store.get_checks()["deepseek"]["latency_ms"] == 5


def test_model_roles_failed_check_blocks_save(isolated_store, check_fail, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    roles = [{"key": "main_chat", "provider": "deepseek", "model": "deepseek-chat"}]
    r = client.post("/api/env/model-roles", json={"roles": roles})
    assert r.status_code == 422
    assert isolated_store.get_bindings()["main_chat"]["provider"] == "deepseek"
    assert "binding:main_chat" not in isolated_store.get_checks()


def test_model_roles_force_saves_and_records_checks(isolated_store, check_fail, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    roles = [{"key": "main_chat", "provider": "deepseek", "model": "deepseek-reasoner"}]
    r = client.post("/api/env/model-roles", json={"roles": roles, "force": True})
    assert r.status_code == 200
    assert isolated_store.get_bindings()["main_chat"]["model"] == "deepseek-reasoner"
    assert isolated_store.get_checks()["binding:main_chat"]["ok"] is False


def test_model_roles_unknown_provider_rejected(isolated_store, check_ok):
    roles = [{"key": "main_chat", "provider": "cp_ghost", "model": "x"}]
    r = client.post("/api/env/model-roles", json={"roles": roles})
    assert r.status_code == 400


def test_bindable_providers_lists_configured(isolated_store, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    r = client.get("/api/env/bindable-providers")
    keys = [p["key"] for p in r.json()["providers"]]
    assert "deepseek" in keys

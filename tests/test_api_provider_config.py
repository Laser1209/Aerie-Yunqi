"""API：自定义厂商增改删、保存即测、功能点绑定先测后存。"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from core import api_server
from core.api_server import app
from core.ai_services import AiServicesStore

client = TestClient(app)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    store = AiServicesStore(tmp_path / "data" / "ai_services.json")
    monkeypatch.setattr(api_server, "_ai_store", lambda: store)
    monkeypatch.setattr(api_server, "_hot_reload_brain", lambda: None)
    return store


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
        "name": "TokenDance",
        "base_url": "https://td.example.com/v1",
        "api_key": "sk-td-123456",
        "model": "td-4o",
        "supports_tools": False,
        "max_tool_calls": 8,
    }
    base.update(over)
    return base


def test_put_custom_tests_before_commit(isolated_store, check_ok):
    r = client.put("/api/env/custom-providers", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert data["provider"]["name"] == "TokenDance"
    assert data["provider"]["api_key_masked"].startswith("•")
    assert data["check"]["ok"] is True
    records = isolated_store.list_custom_providers(include_key=True)
    assert len(records) == 1 and records[0]["api_key"] == "sk-td-123456"
    # 连通性结果落盘
    assert isolated_store.get_checks()[records[0]["id"]]["ok"] is True


def test_put_custom_failed_check_does_not_persist(isolated_store, check_fail):
    r = client.put("/api/env/custom-providers", json=_body())
    assert r.status_code == 422
    assert isolated_store.list_custom_providers() == []


def test_put_custom_force_saves_despite_failed_check(isolated_store, check_fail):
    r = client.put("/api/env/custom-providers", json=_body(force=True))
    assert r.status_code == 200
    assert len(isolated_store.list_custom_providers()) == 1


def test_put_custom_update_keeps_key_when_blank(isolated_store, check_ok):
    created = client.put("/api/env/custom-providers", json=_body()).json()["provider"]
    r = client.put("/api/env/custom-providers", json=_body(
        id=created["id"], name="TokenDance Pro", api_key="", model="td-4o-mini"))
    assert r.status_code == 200
    record = isolated_store.get_custom_provider(created["id"])
    assert record["name"] == "TokenDance Pro"
    assert record["api_key"] == "sk-td-123456"
    assert record["model"] == "td-4o-mini"


def test_put_custom_rejects_masked_key(isolated_store, check_ok):
    r = client.put("/api/env/custom-providers", json=_body(api_key="••••4567"))
    assert r.status_code == 400
    assert isolated_store.list_custom_providers() == []


def test_delete_custom_resets_referencing_binding(isolated_store, check_ok, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    created = client.put("/api/env/custom-providers", json=_body()).json()["provider"]
    isolated_store.set_binding("main_chat", created["id"], "td-4o")

    r = client.delete(f"/api/env/custom-providers/{created['id']}")
    assert r.status_code == 200
    binding = isolated_store.get_bindings()["main_chat"]
    assert binding["provider"] == "deepseek"
    assert binding["model"] == "deepseek-chat"


def test_model_roles_failed_check_blocks_save(isolated_store, check_fail, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    roles = [{"key": "main_chat", "provider": "deepseek", "model": "deepseek-chat"}]
    r = client.post("/api/env/model-roles", json={"roles": roles})
    assert r.status_code == 422
    assert isolated_store.get_bindings()["main_chat"]["provider"] == "deepseek"
    # 默认值未被污染：model 仍是默认 deepseek-chat（此处绑定本来就解析成功），
    # 关键是 checks 之外没有产生部分写入。
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


def test_env_save_rejects_masked_key(isolated_store):
    r = client.post("/api/env/save", json={
        "provider_key": "deepseek", "api_key": "••••••••1234",
    })
    assert r.status_code == 400


def test_bindable_providers_lists_configured(isolated_store, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    r = client.get("/api/env/bindable-providers")
    keys = [p["key"] for p in r.json()["providers"]]
    assert "deepseek" in keys


def test_provider_check_only_endpoint_custom(isolated_store):
    async def fake_check(*, base_url, api_key, model, mode):
        return {"ok": True, "detail": "", "http_status": 200,
                "latency_ms": 5, "mode": mode, "base_url": base_url, "model": model}
    api_server.run_provider_check = AsyncMock(side_effect=fake_check)
    r = client.post("/api/env/provider-check", json={
        "custom": {"base_url": "https://x.example/v1", "api_key": "sk-x", "model": "m-1"},
        "mode": "models",
    })
    assert r.status_code == 200
    assert r.json()["check"]["model"] == "m-1"

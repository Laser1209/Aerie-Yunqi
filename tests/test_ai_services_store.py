"""AiServicesStore：SQLite 存储、校验、启用停用、功能点绑定与 check 审计。"""
import json
import os

import pytest

import core.ai_services as ai_services
from core.ai_services import (
    AiServicesError,
    AiServicesStore,
    DEFAULT_BINDINGS,
    KIND_BUILTIN,
    KIND_CUSTOM,
    resolve_provider,
    resolve_role,
)
from core.database import Database


@pytest.fixture
def store(tmp_path, monkeypatch):
    Database.reset_instance()
    s = AiServicesStore(Database(tmp_path / "ai_services.db"))
    monkeypatch.setattr(ai_services, "get_store", lambda: s)
    yield s
    Database.reset_instance()


def _custom_records(store):
    """只看自定义行——内置厂商由 seed 写入，不属于本测试的关注点。"""
    return [p for p in store.list_providers() if p["kind"] != KIND_BUILTIN]


def _record(**over):
    base = {
        "kind": KIND_CUSTOM,
        "name": "MyRelay",
        "base_url": "https://relay.example.com/v1",
        "api_key": "sk-secret-1234",
        "model": "gpt-test",
        "supports_tools": True,
        "max_tool_calls": 8,
    }
    base.update(over)
    return base


def test_builtin_providers_seeded_once(store):
    ids = [p["id"] for p in store.list_providers()]
    assert "deepseek" in ids
    # 虚拟组合型（多 Key 轮询池 / 轻量）不进表，只由运行时解析。
    assert "aerie-ws" not in ids
    assert "siliconflow-light" not in ids

    again = AiServicesStore(store._db)
    assert [p["id"] for p in again.list_providers()].count("deepseek") == 1


def test_prepare_does_not_persist_but_commit_does(store):
    prepared = store.prepare_provider(_record())
    assert prepared["id"].startswith("cp_")
    assert _custom_records(store) == []

    saved = store.commit_provider(prepared)
    assert saved["name"] == "MyRelay"
    assert store.get_provider(saved["id"])["api_key"] == "sk-secret-1234"


def test_update_with_empty_key_keeps_stored_key(store):
    saved = store.commit_provider(store.prepare_provider(_record()))
    prepared = store.prepare_provider(
        _record(id=saved["id"], name="MyRelay2", api_key="", model="gpt-test-2")
    )
    assert prepared["api_key"] == "sk-secret-1234"
    updated = store.commit_provider(prepared)
    assert updated["name"] == "MyRelay2"
    assert updated["model"] == "gpt-test-2"
    assert len(_custom_records(store)) == 1


def test_masked_placeholder_and_bad_url_rejected(store):
    with pytest.raises(AiServicesError, match="脱敏"):
        store.prepare_provider(_record(api_key="••••1234"))
    with pytest.raises(AiServicesError, match="http"):
        store.prepare_provider(_record(base_url="ftp://relay.example.com"))


def test_duplicate_name_rejected_case_insensitive(store):
    store.commit_provider(store.prepare_provider(_record()))
    with pytest.raises(AiServicesError, match="重复|存在"):
        store.prepare_provider(_record(name=" myrelay ", api_key="sk-other"))


def test_max_tool_calls_clamped(store):
    prepared = store.prepare_provider(_record(max_tool_calls=999))
    assert prepared["max_tool_calls"] == 50


def test_builtin_credentials_written_through_to_env(store, monkeypatch):
    """内置厂商保存必须回写 .env 与 os.environ —— llm_caller 等旁路靠它取凭据。"""
    import core.env_file as env_file

    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-placeholder")
    store.commit_provider(store.prepare_provider({
        "id": "deepseek",
        "kind": KIND_BUILTIN,
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "ds-real-key",
        "model": "deepseek-reasoner",
    }))
    assert os.environ["DEEPSEEK_API_KEY"] == "ds-real-key"
    assert env_file.read_env_file()["DEEPSEEK_API_KEY"] == "ds-real-key"
    assert env_file.read_env_file()["DEEPSEEK_MODEL"] == "deepseek-reasoner"


def test_disable_keeps_key_but_clears_env(store, monkeypatch):
    """停用只清 .env 凭据，库里的 Key 保留，随时可恢复。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    store.commit_provider(store.prepare_provider({
        "id": "deepseek",
        "kind": KIND_BUILTIN,
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "ds-key",
        "model": "deepseek-chat",
    }))

    store.set_enabled("deepseek", False)
    assert os.environ["DEEPSEEK_API_KEY"] == ""
    assert store.get_provider("deepseek")["api_key"] == "ds-key"
    assert resolve_provider("deepseek") is None

    store.set_enabled("deepseek", True)
    assert os.environ["DEEPSEEK_API_KEY"] == "ds-key"
    assert resolve_provider("deepseek") is not None


def test_delete_removes_row_and_clears_env(store, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    assert store.delete_provider("deepseek") is True
    assert store.get_provider("deepseek") is None
    assert os.environ["DEEPSEEK_API_KEY"] == ""
    assert store.delete_provider("deepseek") is False


def test_binding_validation_and_persistence(store):
    saved = store.commit_provider(store.prepare_provider(_record()))
    store.set_binding("main_chat", saved["id"], "gpt-test")
    assert store.get_bindings()["main_chat"] == {
        "provider": saved["id"],
        "model": "gpt-test",
    }

    with pytest.raises(AiServicesError):
        store.validate_binding("main_chat", "cp_missing", "x")
    with pytest.raises(AiServicesError):
        store.validate_binding("not_a_role", saved["id"], "x")
    with pytest.raises(AiServicesError):
        store.set_binding("subagent", saved["id"], "")


def test_checks_recorded_and_audited(store):
    store.record_check("deepseek", {"ok": True, "latency_ms": 42, "mode": "models"})
    assert store.get_checks()["deepseek"]["latency_ms"] == 42
    lines = store._log_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["target"] == "deepseek"
    assert payload["ok"] is True


def test_resolve_custom_binding(monkeypatch, store):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    saved = store.commit_provider(store.prepare_provider(_record()))
    store.set_binding("main_chat", saved["id"], "bound-model")

    ep = resolve_role("main_chat")
    assert ep is not None
    assert ep.name == f"custom:{saved['id']}"
    assert ep.model == "bound-model"
    assert ep.api_key == "sk-secret-1234"
    assert ep.available

    direct = resolve_provider(saved["id"])
    assert direct is not None and direct.base_url == "https://relay.example.com/v1"


def test_resolve_default_binding_uses_env(monkeypatch, store):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    ep = resolve_role("main_chat")
    assert ep is not None and ep.name == "deepseek" and ep.model == "deepseek-chat"
    assert DEFAULT_BINDINGS["main_chat"]["provider"] == "deepseek"

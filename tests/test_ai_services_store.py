"""AiServicesStore：结构化存储、校验、功能点绑定与 check 审计。"""
import json

import pytest

import core.ai_services as ai_services
from core.ai_services import (
    AiServicesError,
    AiServicesStore,
    DEFAULT_BINDINGS,
    resolve_provider,
    resolve_role,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = AiServicesStore(tmp_path / "data" / "ai_services.json")
    monkeypatch.setattr(ai_services, "get_store", lambda: s)
    return s


def _record(**over):
    base = {
        "name": "MyRelay",
        "base_url": "https://relay.example.com/v1",
        "api_key": "sk-secret-1234",
        "model": "gpt-test",
        "supports_tools": True,
        "max_tool_calls": 8,
    }
    base.update(over)
    return base


def test_prepare_does_not_persist_but_commit_does(store):
    prepared = store.prepare_custom_provider(_record())
    assert prepared["id"].startswith("cp_")
    assert store.list_custom_providers() == []

    saved = store.commit_custom_provider(prepared)
    assert saved["name"] == "MyRelay"
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert on_disk["custom_providers"][0]["api_key"] == "sk-secret-1234"


def test_update_with_empty_key_keeps_stored_key(store):
    saved = store.commit_custom_provider(store.prepare_custom_provider(_record()))
    prepared = store.prepare_custom_provider(
        _record(id=saved["id"], name="MyRelay2", api_key="", model="gpt-test-2")
    )
    assert prepared["api_key"] == "sk-secret-1234"
    updated = store.commit_custom_provider(prepared)
    assert updated["name"] == "MyRelay2"
    assert updated["model"] == "gpt-test-2"
    assert len(store.list_custom_providers()) == 1


def test_masked_placeholder_and_bad_url_rejected(store):
    with pytest.raises(AiServicesError, match="脱敏"):
        store.prepare_custom_provider(_record(api_key="••••1234"))
    with pytest.raises(AiServicesError, match="http"):
        store.prepare_custom_provider(_record(base_url="ftp://relay.example.com"))


def test_duplicate_name_rejected_case_insensitive(store):
    store.commit_custom_provider(store.prepare_custom_provider(_record()))
    with pytest.raises(AiServicesError, match="重复|存在"):
        store.prepare_custom_provider(_record(name=" myrelay ", api_key="sk-other"))


def test_max_tool_calls_clamped(store):
    prepared = store.prepare_custom_provider(_record(max_tool_calls=999))
    assert prepared["max_tool_calls"] == 50


def test_binding_validation_and_persistence(store):
    saved = store.commit_custom_provider(store.prepare_custom_provider(_record()))
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


def test_checks_recorded_in_json_and_jsonl(store):
    store.record_check("deepseek", {"ok": True, "latency_ms": 42, "mode": "models"})
    assert store.get_checks()["deepseek"]["latency_ms"] == 42
    lines = store._log_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["target"] == "deepseek"
    assert payload["ok"] is True


def test_resolve_custom_binding(monkeypatch, store):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    saved = store.commit_custom_provider(store.prepare_custom_provider(_record()))
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

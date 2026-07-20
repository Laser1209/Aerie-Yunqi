from copy import deepcopy

import pytest

from tests.test_persona_hub import VALID_PERSONA


def test_hub_persona_projects_to_legacy_shape():
    from core.persona_hub.legacy_projector import project_persona_to_legacy

    persona = deepcopy(VALID_PERSONA)
    persona["personality"]["archetype"] = "温柔守护者"
    persona["relationship"]["user_intimate_terms"] = ["宝贝"]

    projected = project_persona_to_legacy(persona)

    legacy = projected["persona"]
    assert legacy["name"] == "测试"
    assert legacy["english_name"] == "Test"
    assert legacy["profile"]["age"] == 25
    assert legacy["profile"]["personality_archetype"] == "温柔守护者"
    assert legacy["personality_cores"] == persona["personality"]["cores"]
    assert legacy["speech"]["style"] == "温柔大方"
    assert legacy["address"]["user_intimate"] == ["宝贝"]


def test_load_persona_uses_active_hub_projection_when_flag_enabled(monkeypatch, tmp_path):
    from config import persona_loader
    from core.persona_hub.persona_manager import PersonaManager

    manager = PersonaManager(data_dir=str(tmp_path))
    manager.update_persona(
        "yita_default",
        {"basic": {"name": "Hub 伊塔", "english_name": "Hub Ita"}},
    )

    monkeypatch.setattr(persona_loader, "get_persona_manager", lambda: manager)
    monkeypatch.setattr(
        persona_loader.FeatureFlags,
        "is_enabled",
        lambda _self, name: name == "persona_hub_source_v1",
    )

    loaded = persona_loader.load_persona()

    assert loaded["persona"]["name"] == "Hub 伊塔"
    assert loaded["persona"]["english_name"] == "Hub Ita"


def test_load_persona_preserves_legacy_yaml_when_flag_disabled(monkeypatch):
    from config import persona_loader

    monkeypatch.setattr(
        persona_loader.FeatureFlags,
        "is_enabled",
        lambda _self, _name: False,
    )
    monkeypatch.setattr(
        persona_loader,
        "_load_yaml",
        lambda filename: {"persona": {"name": "Legacy"}},
    )

    assert persona_loader.load_persona()["persona"]["name"] == "Legacy"


def test_save_persona_updates_active_hub_when_flag_enabled(monkeypatch, tmp_path):
    from config import persona_loader
    from core.persona_hub.persona_manager import PersonaManager

    manager = PersonaManager(data_dir=str(tmp_path))
    monkeypatch.setattr(persona_loader, "get_persona_manager", lambda: manager)
    monkeypatch.setattr(
        persona_loader.FeatureFlags,
        "is_enabled",
        lambda _self, name: name == "persona_hub_source_v1",
    )

    saved = persona_loader.save_persona({"name": "新伊塔", "english_name": "New Ita"})

    assert saved["name"] == "新伊塔"
    assert manager.get_active()["basic"]["name"] == "新伊塔"
    assert manager.get_active()["basic"]["english_name"] == "New Ita"


def test_persona_manager_reports_exact_existence(tmp_path):
    from core.persona_hub.persona_manager import PersonaManager

    manager = PersonaManager(data_dir=str(tmp_path))

    assert manager.has_persona("yita_default") is True
    assert manager.has_persona("missing") is False


def test_persona_update_keeps_memory_unchanged_when_persistence_fails(
    monkeypatch,
    tmp_path,
):
    from core.persona_hub.persona_manager import PersonaManager

    manager = PersonaManager(data_dir=str(tmp_path))
    original_name = manager.get_name()
    monkeypatch.setattr(
        manager,
        "_save_persona",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        manager.update_persona(
            "yita_default",
            {"basic": {"name": "不应留在内存"}},
        )

    assert manager.get_name() == original_name


def test_persona_switch_keeps_active_id_when_persistence_fails(
    monkeypatch,
    tmp_path,
):
    from core.persona_hub.persona_manager import PersonaManager

    manager = PersonaManager(data_dir=str(tmp_path))
    ok, _ = manager.create_persona(deepcopy(VALID_PERSONA))
    assert ok is True
    monkeypatch.setattr(
        manager,
        "_write_json_atomic",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )

    ok, error = manager.switch_persona("test_persona")

    assert ok is False
    assert "disk full" in error
    assert manager.get_active_id() == "yita_default"


@pytest.mark.asyncio
async def test_persona_yaml_put_is_read_only():
    from core.api_server import config_yaml_put

    response = await config_yaml_put(file="persona.yaml", request=None)

    assert response.status_code == 409
    assert b"read-only" in response.body


@pytest.mark.asyncio
async def test_persona_hub_get_returns_404_for_unknown_id(monkeypatch, tmp_path):
    from core import api_server
    from core.persona_hub.persona_manager import PersonaManager

    manager = PersonaManager(data_dir=str(tmp_path))
    monkeypatch.setattr(api_server, "_persona_mgr", manager)

    response = await api_server.persona_hub_get("missing")

    assert response.status_code == 404
    assert b"persona not found" in response.body


@pytest.mark.asyncio
async def test_persona_hub_import_keeps_available_id(monkeypatch, tmp_path):
    import json

    from core import api_server
    from core.persona_hub.persona_manager import PersonaManager

    class Upload:
        async def read(self):
            return json.dumps(VALID_PERSONA, ensure_ascii=False).encode("utf-8")

    manager = PersonaManager(data_dir=str(tmp_path))
    monkeypatch.setattr(api_server, "_persona_mgr", manager)

    response = await api_server.persona_hub_import(Upload())

    assert response == {"status": "ok", "persona_id": "test_persona"}
    assert manager.has_persona("test_persona") is True
    assert manager.has_persona("test_persona_imported") is False

from pathlib import Path


def test_desktop_data_environment_overrides_legacy_yaml_path(tmp_path, monkeypatch):
    from core.companion import _resolve_companion_data_path

    isolated = tmp_path / "electron-data"
    monkeypatch.setenv("AERIE_DATA_DIR", str(isolated))

    resolved = _resolve_companion_data_path(
        {"paths": {"data": "./data-that-must-not-be-used"}}
    )

    assert resolved == isolated


def test_legacy_yaml_data_path_remains_compatible(monkeypatch):
    from core.companion import _resolve_companion_data_path

    monkeypatch.delenv("AERIE_DATA_DIR", raising=False)

    assert _resolve_companion_data_path({"paths": {"data": "custom-data"}}) == Path(
        "custom-data"
    )

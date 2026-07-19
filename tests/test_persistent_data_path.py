from pathlib import Path

from core.database import Database


def test_database_uses_aerie_db_path(monkeypatch, tmp_path):
    db_path = tmp_path / "persistent" / "aerie.db"
    monkeypatch.setenv("AERIE_DB_PATH", str(db_path))
    Database._instance = None

    db = Database()

    assert db.db_path == db_path
    assert db_path.exists()
    Database._instance = None


def test_electron_backend_uses_persistent_user_data():
    main_js = Path(__file__).resolve().parents[1] / "electron" / "src" / "main.js"
    source = main_js.read_text(encoding="utf-8")

    assert 'app.getPath("userData")' in source
    assert "AERIE_DB_PATH" in source
    assert "legacyDbPath" in source

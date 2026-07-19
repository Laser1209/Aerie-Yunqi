from pathlib import Path

from core.database import Database
from knowledge.kb import KnowledgeBase


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


def test_chat_and_knowledge_survive_database_recreation(tmp_path):
    db_path = tmp_path / "persistent" / "aerie.db"
    Database._instance = None
    db = Database(db_path)
    chat_id = db.insert("chat_log", {"user_id": 7, "role": "user", "content": "persist me"})
    knowledge_id = KnowledgeBase(db).add("world", "Persistent", "knowledge body", "saved")

    Database._instance = None
    restored = Database(db_path)

    assert restored.query_one("SELECT * FROM chat_log WHERE id = ?", (chat_id,))["content"] == "persist me"
    assert KnowledgeBase(restored).get(knowledge_id)["title"] == "Persistent"
    assert restored.db_path.resolve() == db_path.resolve()
    Database._instance = None

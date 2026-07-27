from pathlib import Path


def test_desire_state_uses_configured_data_directory(tmp_path, monkeypatch):
    from core.desire_engine import DesireEngine

    isolated_data = tmp_path / "runtime-data"
    monkeypatch.setenv("AERIE_DATA_DIR", str(isolated_data))

    repository_state = (
        Path(__file__).resolve().parent.parent / "data" / "desire_state.json"
    )
    before = repository_state.read_bytes()

    engine = DesireEngine(None, {"desire": {"tick_seconds": 300}})
    engine.mark_rejected()

    assert engine.state_path == isolated_data / "desire_state.json"
    assert engine.state_path.is_file()
    assert repository_state.read_bytes() == before

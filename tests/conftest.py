"""Shared pytest fixtures for Aerie · 云栖 v9.0 tests."""

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Collection imports core.api_server, which initializes Database eagerly.
# Pin that import-time singleton to a disposable database before test modules load.
_PYTEST_DB_ROOT = Path(tempfile.mkdtemp(prefix="aerie-pytest-db-"))
os.environ["AERIE_DB_PATH"] = str(_PYTEST_DB_ROOT / "aerie.db")


def pytest_sessionfinish(session, exitstatus):
    del session, exitstatus
    shutil.rmtree(_PYTEST_DB_ROOT, ignore_errors=True)


@pytest.fixture
def temp_data_dir():
    """Temporary data directory that cleans up after test."""
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        Path("data").mkdir(exist_ok=True)
        yield Path(td)
        os.chdir(old_cwd)


@pytest.fixture
def mock_qq_client():
    """Mock QQClient with no real WebSocket."""
    client = MagicMock()
    client.send_message = AsyncMock(return_value=True)
    client.send_poke = AsyncMock(return_value=True)
    client.send_voice = AsyncMock(return_value=True)
    client.send_image = AsyncMock(return_value=True)
    client.recall_message = AsyncMock(return_value=True)
    client.close = AsyncMock()
    return client


@pytest.fixture
def sample_config():
    """Minimal settings dict for testing."""
    return {
        "qq": {"self_qq": 3998874040, "friends": [12345678]},
    }


@pytest.fixture
def frozen_utc_clock():
    current = datetime(
        2026,
        7,
        20,
        0,
        0,
        tzinfo=timezone.utc,
    )

    def now() -> datetime:
        return current

    def advance(seconds: int) -> None:
        nonlocal current
        current += timedelta(seconds=seconds)

    return SimpleNamespace(now=now, advance=advance)


@pytest.fixture
def phase4_db(tmp_path, monkeypatch):
    from core.database import Database

    monkeypatch.setenv(
        "AERIE_FEATURE_MIGRATION_FRAMEWORK_V1",
        "true",
    )
    Database.reset_instance()
    db = Database(tmp_path / "phase4.db")
    try:
        yield db
    finally:
        Database.reset_instance()


@pytest.fixture
def ready_attachment():
    return {
        "name": "phase4-attachment.txt",
        "url": (
            "/uploads/"
            "00000000-0000-4000-8000-000000000004.txt"
        ),
        "state": "ready",
        "size": 128,
        "type": "text/plain",
    }


@pytest.fixture
def phase4_pipeline_double():
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()
    cancel_seen = asyncio.Event()

    async def handle(*args, **kwargs):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancel_seen.set()
            raise
        return {
            "reply": "fixture reply",
            "persisted": True,
        }

    return SimpleNamespace(
        handle=handle,
        started=started,
        release=release,
        cancel_seen=cancel_seen,
    )

"""Shared pytest fixtures for Aerie · 云栖 v9.0 tests."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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

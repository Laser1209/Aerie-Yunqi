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


@pytest.fixture(autouse=True)
def isolate_optional_provider_credentials(monkeypatch):
    """Prevent host .env credentials from changing call-count contracts."""
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_LIGHT_MODEL", raising=False)
    monkeypatch.delenv("AERIE_TYPESAFE_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def isolate_host_dotenv(monkeypatch):
    """宿主 .env 不得流进测试进程。

    某些模块在**运行期**调 `load_dotenv(<真实 .env>)`（如
    `scripts/mobile_accounts.py::_store()`），把 .env 里**全部键**灌进
    `os.environ`。于是开发者往 .env 加一个运维开关，就会静默改写一批无关
    测试的前置条件 —— 2026-09-29 实测：新增 `AERIE_PHOTO_PROMPT_DRYRUN=1` 后，
    `test_phase14_world_image_candidates.py` 等 17 个生图用例从 completed 变
    成 dry_run 而集体失败（测试没坏，是环境被污染）。

    只 patch `dotenv.load_dotenv` 属性**挡不住**：这些模块用的是
    `from dotenv import load_dotenv`，收集期 import 时就把真实函数绑定到了自己
    的命名空间。因此这里直接按"宿主 .env 里出现了哪些键"逐个隔离 —— 无论注入
    来自哪条路径都拦得住。测试若真需要某个变量，自己 `monkeypatch.setenv`。
    """
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False, raising=False)
    for key in _host_dotenv_keys():
        monkeypatch.delenv(key, raising=False)


_HOST_DOTENV_KEYS: list[str] | None = None


def _host_dotenv_keys() -> list[str]:
    """读取宿主 .env 的键名（只读文件，不写环境）；进程内缓存一次。"""
    global _HOST_DOTENV_KEYS
    if _HOST_DOTENV_KEYS is None:
        import dotenv

        env_path = Path(__file__).resolve().parent.parent / ".env"
        try:
            _HOST_DOTENV_KEYS = (
                list(dotenv.dotenv_values(env_path).keys()) if env_path.exists() else []
            )
        except Exception:
            _HOST_DOTENV_KEYS = []
    return _HOST_DOTENV_KEYS


@pytest.fixture(autouse=True)
def isolate_dotenv_file(tmp_path, monkeypatch):
    """厂商保存会把凭据回写 .env —— 测试里指向临时文件，绝不碰仓库真 .env。"""
    import core.env_file as env_file

    target = tmp_path / ".env.test"
    monkeypatch.setattr(env_file, "env_file_path", lambda: target)
    return target


@pytest.fixture
def mock_qq_client():
    """Mock QQClient with no real WebSocket."""
    client = MagicMock()
    client.send_message = AsyncMock(return_value=True)
    client.send_poke = AsyncMock(return_value=True)
    client.send_voice = AsyncMock(return_value=True)
    client.send_image = AsyncMock(return_value=True)
    client.send_file = AsyncMock(return_value=True)
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

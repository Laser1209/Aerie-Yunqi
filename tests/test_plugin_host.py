"""P0 插件宿主适应度测试（fitness functions）。

守卫的不变量（对应计划文档第 10 章验证清单）：
  - 空目录零装配：插件目录不存在/为空时，启动行为与接线前完全一致；
  - 装/用/删闭环：hello-pack 能注册工具、挂载 API，reset 后回滚 sys.path；
  - 契约拒绝：api_level 不匹配、min_core 不达标 → incompatible，不注入路径；
  - 准入标记：打包态缺 .aerie-installed → broken，补齐后可加载；
  - 失败隔离：单个包 register/start 抛异常不影响其他包与核心；
  - 多版本选择：同 id 多版本只加载最高版本；
  - 依赖方向：core/ 任何文件不得引用具体功能包模块名。
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from core import paths, plugin_host
from core.plugin_host import (
    API_LEVEL,
    INSTALL_MARKER,
    STATE_BROKEN,
    STATE_INCOMPATIBLE,
    STATE_LOADED,
    LoadedPlugin,
    PluginContext,
)

FIXTURE_PACK = Path(__file__).parent / "fixtures" / "hello_pack"


class FakeRegistry:
    """与 ToolRegistry.register/list_names 同签名的最小双工。"""

    def __init__(self) -> None:
        self._tools: dict[str, tuple] = {}

    def register(self, name, func, schema, provider_hint="text", category="utility"):
        self._tools[name] = (func, schema, provider_hint, category)

    def list_names(self):
        return list(self._tools)

    def call(self, name):
        return self._tools[name][0]()


@pytest.fixture(autouse=True)
def clean_host():
    host = plugin_host.get_host()
    host.reset()
    yield host
    host.reset()


def _copy_pack(plugins_root: Path, dirname: str = "hello") -> Path:
    target = plugins_root / dirname
    shutil.copytree(FIXTURE_PACK, target)
    return target


def _edit_manifest(pack_dir: Path, **updates) -> dict:
    manifest_path = pack_dir / "pack.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(updates)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest


def _write_pack(plugins_root: Path, dirname: str, pack_id: str, module_name: str,
                module_code: str, **manifest_updates) -> Path:
    pack_dir = plugins_root / dirname
    py_dir = pack_dir / "py"
    py_dir.mkdir(parents=True)
    (py_dir / f"{module_name}.py").write_text(module_code, encoding="utf-8")
    manifest = {
        "id": pack_id,
        "version": "1.0.0",
        "api_level": API_LEVEL,
        "min_core": "0.0.0",
        "entry": f"{module_name}:register",
    }
    manifest.update(manifest_updates)
    (pack_dir / "pack.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return pack_dir


# ── 空目录基线 / 默认路径 ───────────────────────────────────────────────


class TestEmptyBaseline:
    def test_missing_dir_loads_nothing(self, tmp_path):
        registry = FakeRegistry()
        result = plugin_host.discover_and_register(registry, tmp_path / "no-plugins")
        assert result == []
        assert registry.list_names() == []
        assert plugin_host.list_status() == []

    def test_empty_dir_loads_nothing(self, tmp_path):
        root = tmp_path / "plugins"
        root.mkdir()
        registry = FakeRegistry()
        plugin_host.discover_and_register(registry, root)
        assert registry.list_names() == []

    def test_staging_and_hidden_dirs_ignored(self, tmp_path):
        root = tmp_path / "plugins"
        root.mkdir()
        (root / ".staging").mkdir()
        (root / "loose-file.txt").write_text("x", encoding="utf-8")
        registry = FakeRegistry()
        plugin_host.discover_and_register(registry, root)
        assert plugin_host.list_status() == []


# ── 装/用/删 闭环 ────────────────────────────────────────────────────────


class TestHelloPackLifecycle:
    def test_loaded_status_tool_and_api(self, tmp_path, clean_host):
        root = tmp_path / "plugins"
        _copy_pack(root)
        registry = FakeRegistry()
        plugins = plugin_host.discover_and_register(registry, root)

        assert len(plugins) == 1
        status = plugins[0].to_status()
        assert status["id"] == "hello"
        assert status["state"] == STATE_LOADED
        assert status["tools"] == ["plugin_ping"]
        assert plugin_host.is_installed("hello")

        # 工具真实可调
        assert registry.call("plugin_ping") == {"pong": True, "pack": "hello"}

        # API 已挂：/api/plugins + /api/plugins/hello/pong
        app = FastAPI()
        app.include_router(clean_host.router)
        client = TestClient(app)

        listing = client.get("/api/plugins").json()["plugins"]
        assert [p["id"] for p in listing] == ["hello"]

        response = client.get("/api/plugins/hello/pong")
        assert response.status_code == 200
        assert response.json() == {"ok": "true"}

        assert client.get("/api/plugins/not-here").status_code == 404

    def test_start_stop_callbacks_receive_companion(self, tmp_path):
        root = tmp_path / "plugins"
        _copy_pack(root)
        registry = FakeRegistry()
        plugin_host.discover_and_register(registry, root)

        import hello_pack_ping

        sentinel = object()
        asyncio.run(plugin_host.start_all(sentinel))
        assert hello_pack_ping._started_with is sentinel

        asyncio.run(plugin_host.stop_all())
        assert hello_pack_ping._started_with is None

    def test_reset_rolls_back_sys_path(self, tmp_path):
        root = tmp_path / "plugins"
        _copy_pack(root)
        before = list(__import__("sys").path)
        registry = FakeRegistry()
        plugin_host.discover_and_register(registry, root)
        added = [p for p in __import__("sys").path if p not in before]
        assert any(str(p).endswith(str(Path("hello") / "py")) for p in added)

        import sys
        plugin_host.reset_for_tests()
        # 判据：所有发现期新增条目都已从 sys.path 摘除
        assert not any(entry in sys.path for entry in added)
        assert plugin_host.list_status() == []

    def test_duplicate_discovery_is_guarded(self, tmp_path):
        root = tmp_path / "plugins"
        _copy_pack(root)
        registry = FakeRegistry()
        plugin_host.discover_and_register(registry, root)
        # 第二次调用必须是 no-op，不能重复装配
        plugin_host.discover_and_register(registry, root)
        assert len(plugin_host.list_status()) == 1


# ── 契约拒绝 ─────────────────────────────────────────────────────────────


class TestContractRejection:
    def test_api_level_mismatch_rejected(self, tmp_path):
        root = tmp_path / "plugins"
        pack_dir = _copy_pack(root)
        _edit_manifest(pack_dir, api_level=API_LEVEL + 999)

        registry = FakeRegistry()
        plugins = plugin_host.discover_and_register(registry, root)
        assert plugins[0].state == STATE_INCOMPATIBLE
        assert "api_level" in plugins[0].error
        assert registry.list_names() == []
        # 契约不符不得注入 sys.path
        assert not any(
            str(pack_dir) in entry for entry in __import__("sys").path
        )

    def test_min_core_rejected(self, tmp_path):
        root = tmp_path / "plugins"
        pack_dir = _copy_pack(root)
        _edit_manifest(pack_dir, min_core="99.0.0")

        registry = FakeRegistry()
        plugins = plugin_host.discover_and_register(registry, root)
        assert plugins[0].state == STATE_INCOMPATIBLE
        assert "core version" in plugins[0].error

    def test_bad_entry_marked_broken(self, tmp_path):
        root = tmp_path / "plugins"
        _write_pack(
            root, "broken", "broken", "hello_pack_broken",
            "def register(ctx):\n    raise RuntimeError('boom from pack')\n",
        )
        registry = FakeRegistry()
        plugins = plugin_host.discover_and_register(registry, root)
        assert plugins[0].state == STATE_BROKEN
        assert "boom from pack" in plugins[0].error
        assert registry.list_names() == []

    def test_malformed_manifest_marked_broken(self, tmp_path):
        root = tmp_path / "plugins"
        pack_dir = root / "bad-json"
        (pack_dir / "py").mkdir(parents=True)
        (pack_dir / "pack.json").write_text("{ not json", encoding="utf-8")

        plugins = plugin_host.discover_and_register(FakeRegistry(), root)
        assert plugins[0].state == STATE_BROKEN
        assert "pack.json parse failed" in plugins[0].error


# ── 安装准入标记（打包态） ───────────────────────────────────────────────


class TestInstallMarker:
    def test_packaged_mode_requires_marker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plugin_host, "_running_from_source", lambda: False)
        root = tmp_path / "plugins"
        pack_dir = _copy_pack(root)

        registry = FakeRegistry()
        plugins = plugin_host.discover_and_register(registry, root)
        assert plugins[0].state == STATE_BROKEN
        assert "install marker" in plugins[0].error

        # 模拟模块中心完成准入：写入标记后重装即可加载
        plugin_host.reset_for_tests()
        (pack_dir / INSTALL_MARKER).write_text(
            json.dumps({"sha256": "x", "source": "test"}), encoding="utf-8"
        )
        plugins = plugin_host.discover_and_register(registry, root)
        assert plugins[0].state == STATE_LOADED


# ── 失败隔离 / 多版本 ─────────────────────────────────────────────────────


class TestIsolationAndSelection:
    def test_register_failure_does_not_block_other_packs(self, tmp_path):
        root = tmp_path / "plugins"
        _write_pack(
            root, "aaa-explode", "explode", "hello_pack_explode",
            "def register(ctx):\n    raise RuntimeError('detonate')\n",
        )
        _copy_pack(root, "zzz-hello")

        registry = FakeRegistry()
        plugins = plugin_host.discover_and_register(registry, root)
        states = {p.pack_id: p.state for p in plugins}
        assert states == {"explode": STATE_BROKEN, "hello": STATE_LOADED}
        assert registry.list_names() == ["plugin_ping"]

    def test_start_failure_isolates_pack(self, tmp_path):
        root = tmp_path / "plugins"
        _write_pack(
            root, "bad-start", "badstart", "hello_pack_badstart",
            "def register(ctx):\n    pass\n"
            "async def start(companion):\n    raise RuntimeError('start boom')\n",
            lifecycle={"start": "hello_pack_badstart:start"},
        )
        _copy_pack(root, "hello")
        registry = FakeRegistry()
        plugin_host.discover_and_register(registry, root)

        asyncio.run(plugin_host.start_all(object()))
        states = {p["id"]: p["state"] for p in plugin_host.list_status()}
        assert states["badstart"] == STATE_BROKEN
        assert states["hello"] == STATE_LOADED

    def test_duplicate_id_picks_highest_version(self, tmp_path):
        root = tmp_path / "plugins"
        old_dir = _copy_pack(root, "hello-v1")
        new_dir = _copy_pack(root, "hello-v2")
        _edit_manifest(new_dir, version="2.0.0")

        registry = FakeRegistry()
        plugins = plugin_host.discover_and_register(registry, root)
        assert len(plugins) == 1
        assert plugins[0].version == "2.0.0"
        # 败选版本不得注入 sys.path
        import sys
        assert not any(str(old_dir) in entry for entry in sys.path)
        assert any(str(new_dir) in entry for entry in sys.path)


# ── ctx 能力面 ──────────────────────────────────────────────────────────


class TestPluginContext:
    def test_pack_path_and_escape_guard(self, tmp_path):
        plugin = LoadedPlugin(
            pack_id="hello", version="1.0.0", root=tmp_path,
            manifest={}, state=STATE_LOADED,
        )
        ctx = PluginContext(plugin, FakeRegistry(), APIRouter())

        target = ctx.pack_path("models", "a.bin")
        assert target == (tmp_path / "models" / "a.bin").resolve()

        with pytest.raises(ValueError, match="escapes pack root"):
            ctx.pack_path("..", "evil.bin")

    def test_get_config_reads_plugins_section(self, tmp_path, monkeypatch):
        fake_root = tmp_path / "proj"
        config_dir = fake_root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "settings.yaml").write_text(
            "plugins:\n  hello:\n    greeting: '你好'\n", encoding="utf-8"
        )
        monkeypatch.setattr(paths, "project_root", lambda: fake_root)

        plugin = LoadedPlugin(
            pack_id="hello", version="1.0.0", root=tmp_path,
            manifest={}, state=STATE_LOADED,
        )
        ctx = PluginContext(plugin, FakeRegistry(), APIRouter())
        assert ctx.get_config() == {"greeting": "你好"}

    def test_emit_namespaced_on_event_bus(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(
            plugin_host.chat_events, "emit",
            lambda event_type, **payload: seen.append((event_type, payload)),
        )
        plugin = LoadedPlugin(
            pack_id="hello", version="1.0.0", root=tmp_path,
            manifest={}, state=STATE_LOADED,
        )
        ctx = PluginContext(plugin, FakeRegistry(), APIRouter())
        ctx.emit("ready", ok=True)
        assert seen == [("plugin_hello_ready", {"ok": True})]


# ── 依赖方向守卫 ────────────────────────────────────────────────────────


def test_core_never_imports_concrete_pack_modules():
    """核心代码不得出现任何功能包夹具/真实包模块名（依赖只能 core ← pack）。"""
    forbidden = ("hello_pack_ping", "hello_pack_broken", "browser_pack", "voice_asr_pack")
    core_dir = paths.project_root() / "core"
    offenders = []
    for py_file in core_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                offenders.append(f"{py_file.name}:{token}")
    assert offenders == [], f"核心反向依赖具体功能包: {offenders}"

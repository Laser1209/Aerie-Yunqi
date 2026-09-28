"""Aerie · 云栖 — 进程内一方功能包宿主（plugin host）。

为什么存在：
    核心安装包必须保持精简，而 Playwright 内核、torch、语音模型等重型资产
    以 ``.aeriepack`` 形式按需下载到 ``userData/plugins``。宿主在后端启动
    早期发现已安装的包、校验契约、注入 ``sys.path``、调用包的 ``register``
    入口，把工具 / API 路由挂进既有体系——核心代码不认识任何具体功能包。

设计约束（ADR-1，见 .trae/documents/能力扩展落地计划_*.md）：
    - 契约面极小：包只能通过 ``register(ctx)`` 拿到注册表、配置、事件总线、
      API 挂点与路径这五件套，不允许反向 import 核心内部模块形成新耦合；
    - 失败隔离：任何单个包的清单错误 / import 异常都不得阻断核心启动；
    - 发现阶段零重活：只扫目录 + 读清单，严禁在此 import 重型库
      （重库只能在包的 start 生命周期里惰性加载）；
    - 完整性在"安装准入"时由 Electron 下载器校验（SHA256 + 原子落盘），
      启动时只认安装标记，避免每次开机对 GB 级模型重复哈希；
    - 依赖方向由 tests/test_plugin_host.py 守卫：核心不得 import 具体包。
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from core import chat_events, paths
from core.version import APP_VERSION

logger = logging.getLogger(__name__)

# 契约版本：register(ctx) / pack.json 字段发生破坏性变化时 +1。
# 宿主一期只接受精确相等的 level，不匹配直接拒绝加载。
API_LEVEL = 1

PACK_MANIFEST = "pack.json"
INSTALL_MARKER = ".aerie-installed"

# 状态：loaded=已装配；incompatible=契约/核心版本不符；broken=加载异常。
STATE_LOADED = "loaded"
STATE_INCOMPATIBLE = "incompatible"
STATE_BROKEN = "broken"


@dataclass
class LoadedPlugin:
    """一个已发现功能包的运行期记录（含失败状态）。"""

    pack_id: str
    version: str
    root: Path
    manifest: dict[str, Any]
    state: str
    error: str = ""
    tools: list[str] = field(default_factory=list)
    sys_path_entries: list[str] = field(default_factory=list)
    module: Any = None
    start_fn_name: str = ""
    stop_fn_name: str = ""

    def to_status(self) -> dict[str, Any]:
        return {
            "id": self.pack_id,
            "version": self.version,
            "api_level": self.manifest.get("api_level"),
            "state": self.state,
            "error": self.error,
            "tools": self.tools,
            "path": str(self.root),
        }


class PluginContext:
    """暴露给功能包 register(ctx) 的唯一能力面（五件套，克制不扩张）。"""

    def __init__(self, plugin: LoadedPlugin, tool_registry: Any, host_router: APIRouter) -> None:
        self._plugin = plugin
        self.tool_registry = tool_registry
        self._host_router = host_router
        # 后端子系统实例，在 start_all 时补入；register 阶段刻意为 None，
        # 防止包在装配期触碰尚未初始化完成的 Companion。
        self.companion: Any = None

    @property
    def pack_id(self) -> str:
        return self._plugin.pack_id

    @property
    def root(self) -> Path:
        return self._plugin.root

    def emit(self, event_type: str, **payload: Any) -> None:
        """经进程内事件总线上报（转写条/状态灯等），与 chat_events 同源。"""
        chat_events.emit(f"plugin_{self.pack_id}_{event_type}", **payload)

    def add_api_router(self, router: APIRouter, prefix: str = "") -> None:
        """挂载包自带 API。最终路径：/api/plugins/<pack_id><prefix>。"""
        full_prefix = f"/{self.pack_id}"
        if prefix:
            full_prefix += prefix if prefix.startswith("/") else f"/{prefix}"
        self._host_router.include_router(router, prefix=full_prefix)

    def pack_path(self, *parts: str) -> Path:
        """包内资源绝对路径（models/bin 等），不允许逃逸出包目录。"""
        target = (self._plugin.root.joinpath(*parts)).resolve()
        root = self._plugin.root.resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"plugin path escapes pack root: {target}")
        return target

    def get_config(self) -> dict[str, Any]:
        """读取 settings.yaml 中 plugins.<pack_id> 段（每次现读，天然跟随热重载）。"""
        settings_path = paths.project_root() / "config" / "settings.yaml"
        try:
            data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            section = (data.get("plugins") or {}).get(self.pack_id) or {}
            return section if isinstance(section, dict) else {}
        except Exception:
            logger.warning("plugin %s: read plugins config failed", self.pack_id, exc_info=True)
            return {}


class PluginHost:
    def __init__(self) -> None:
        self._plugins: list[LoadedPlugin] = []
        self._discovered = False
        # 包路由统一挂在 /api/plugins 下；本路由在 start_api 时被 include 一次。
        self.router = APIRouter(prefix="/api/plugins", tags=["plugins"])
        self.router.add_api_route("", self._list_plugins, methods=["GET"])
        self.router.add_api_route("/{plugin_id}", self._get_plugin, methods=["GET"])

    # ── API ────────────────────────────────────────────────────────────

    async def _list_plugins(self) -> dict[str, Any]:
        return {"plugins": [p.to_status() for p in self._plugins]}

    async def _get_plugin(self, plugin_id: str) -> dict[str, Any]:
        for plugin in self._plugins:
            if plugin.pack_id == plugin_id:
                return plugin.to_status()
        raise HTTPException(status_code=404, detail=f"plugin not installed: {plugin_id}")

    # ── 发现与装配 ─────────────────────────────────────────────────────

    def discover_and_register(self, tool_registry: Any, plugins_root: Path | None = None) -> list[LoadedPlugin]:
        """扫描插件目录并完成装配。正常在 Companion 建注册表后调用一次。"""
        if self._discovered:
            logger.warning("plugin host already discovered; ignoring duplicate call")
            return self._plugins
        self._discovered = True

        root = Path(plugins_root) if plugins_root else paths.plugins_dir()
        if not root.exists():
            logger.info("plugin dir not exist (%s); no feature packs loaded", root)
            return self._plugins

        candidates = self._collect_candidates(root)
        for plugin in candidates:
            self._load_one(plugin, tool_registry)

        loaded = [p for p in self._plugins if p.state == STATE_LOADED]
        logger.info(
            "plugin host: %d pack(s) discovered, %d loaded, %d broken, %d incompatible",
            len(candidates),
            len(loaded),
            sum(p.state == STATE_BROKEN for p in self._plugins),
            sum(p.state == STATE_INCOMPATIBLE for p in self._plugins),
        )
        return self._plugins

    def _collect_candidates(self, root: Path) -> list[LoadedPlugin]:
        """枚举各包目录，读清单做基础校验；同 id 多版本只保留最高版本。"""
        raw: list[LoadedPlugin] = []
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            manifest_path = entry / PACK_MANIFEST
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raw.append(LoadedPlugin(
                    pack_id=entry.name, version="?", root=entry, manifest={},
                    state=STATE_BROKEN, error=f"pack.json parse failed: {exc}",
                ))
                continue
            pack_id = str(manifest.get("id") or "").strip()
            version = str(manifest.get("version") or "0.0.0").strip()
            if not pack_id:
                raw.append(LoadedPlugin(
                    pack_id=entry.name, version=version, root=entry, manifest=manifest,
                    state=STATE_BROKEN, error="pack.json missing 'id'",
                ))
                continue
            raw.append(LoadedPlugin(
                pack_id=pack_id, version=version, root=entry, manifest=manifest,
                state=STATE_BROKEN,  # 占位，后续 _load_one 改判
            ))

        # 同 id 多版本：最高版本胜出，其余不加载（避免 sys.path 双注入）。
        latest: dict[str, LoadedPlugin] = {}
        for plugin in raw:
            current = latest.get(plugin.pack_id)
            if current is None or _version_tuple(plugin.version) > _version_tuple(current.version):
                latest[plugin.pack_id] = plugin
        return [latest[key] for key in sorted(latest.keys())]

    def _load_one(self, plugin: LoadedPlugin, tool_registry: Any) -> None:
        manifest = plugin.manifest
        if not manifest or not str(manifest.get("id") or "").strip():
            # 清单解析失败 / 缺 id 的结论在枚举阶段已定，不再改判。
            self._register_failed(plugin)
            return

        # 1) 契约版本：一期精确匹配，不猜测向前/向后兼容。
        level = manifest.get("api_level")
        if level != API_LEVEL:
            plugin.state = STATE_INCOMPATIBLE
            plugin.error = f"api_level mismatch: pack={level!r}, host={API_LEVEL}"
            self._register_failed(plugin)
            return

        # 2) 核心最低版本。
        min_core = str(manifest.get("min_core") or "0.0.0")
        if _version_tuple(APP_VERSION) < _version_tuple(min_core):
            plugin.state = STATE_INCOMPATIBLE
            plugin.error = f"core version {APP_VERSION} < required {min_core}"
            self._register_failed(plugin)
            return

        # 3) 安装准入标记（开发态从源码运行可豁免）。
        if not _running_from_source() and not (plugin.root / INSTALL_MARKER).is_file():
            plugin.state = STATE_BROKEN
            plugin.error = "install marker missing; pack was not admitted by module center"
            self._register_failed(plugin)
            return

        entry_ref = str(manifest.get("entry") or "").strip()
        if not entry_ref or ":" not in entry_ref:
            plugin.state = STATE_BROKEN
            plugin.error = "pack.json missing valid 'entry' (module:callable)"
            self._register_failed(plugin)
            return

        # 4) sys.path 注入：vendor（独占三方库）先追加，py 后追加，
        #    使包自身代码在 vendor 之前被命中；两者均在末尾，核心依赖永远优先，
        #    包无法用 vendor 里的同名库覆盖核心版本（R1 共享库治理）。
        for sub in ("vendor", "py"):
            candidate = (plugin.root / sub).resolve()
            if candidate.is_dir():
                plugin.sys_path_entries.append(str(candidate))
                sys.path.append(str(candidate))

        # 5) import + register，全程隔离。
        try:
            module_name, attr_name = entry_ref.split(":", 1)
            module = importlib.import_module(module_name)
            register_fn = getattr(module, attr_name)
            plugin.module = module
            lifecycle = manifest.get("lifecycle") or {}
            plugin.start_fn_name = str(lifecycle.get("start") or "")
            plugin.stop_fn_name = str(lifecycle.get("stop") or "")

            before = set(tool_registry.list_names())
            context = PluginContext(plugin, tool_registry, self.router)
            register_fn(context)
            after = set(tool_registry.list_names())
            plugin.tools = sorted(after - before)
            plugin.state = STATE_LOADED
            plugin.error = ""
            self._plugins.append(plugin)
            logger.info("plugin loaded: %s@%s (tools=%s)", plugin.pack_id, plugin.version, plugin.tools)
        except Exception as exc:
            plugin.state = STATE_BROKEN
            plugin.error = f"{type(exc).__name__}: {exc}"
            self._register_failed(plugin)
            logger.warning("plugin %s load failed: %s", plugin.pack_id, plugin.error, exc_info=True)

    def _register_failed(self, plugin: LoadedPlugin) -> None:
        self._plugins.append(plugin)
        logger.warning("plugin rejected: %s (%s)", plugin.pack_id, plugin.error)

    # ── 生命周期 ───────────────────────────────────────────────────────

    async def start_all(self, companion: Any) -> None:
        for plugin in self._plugins:
            if plugin.state != STATE_LOADED or not plugin.start_fn_name:
                continue
            try:
                fn = _resolve_ref(plugin.start_fn_name)
                # register 阶段构造的 ctx 是局部变量，这里通过 contextVar 取不到，
                # 故直接以 companion 为参数；包需要 ctx 其余能力时自行闭包持有。
                result = fn(companion)
                if hasattr(result, "__await__"):
                    await result
                logger.info("plugin started: %s", plugin.pack_id)
            except Exception:
                # start 失败按 broken 处理，但不二次影响已注册工具之外的核心。
                plugin.state = STATE_BROKEN
                plugin.error = "start lifecycle failed"
                logger.warning("plugin %s start failed", plugin.pack_id, exc_info=True)

    async def stop_all(self) -> None:
        for plugin in self._plugins:
            if plugin.state != STATE_LOADED or not plugin.stop_fn_name:
                continue
            try:
                fn = _resolve_ref(plugin.stop_fn_name)
                result = fn()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                logger.warning("plugin %s stop failed", plugin.pack_id, exc_info=True)

    # ── 查询 ───────────────────────────────────────────────────────────

    def list_status(self) -> list[dict[str, Any]]:
        return [p.to_status() for p in self._plugins]

    def is_installed(self, pack_id: str) -> bool:
        return any(p.pack_id == pack_id and p.state == STATE_LOADED for p in self._plugins)

    def reset(self) -> None:
        """测试专用：清空装配记录、回滚 sys.path 注入并重建路由树。"""
        for plugin in self._plugins:
            for entry in plugin.sys_path_entries:
                try:
                    sys.path.remove(entry)
                except ValueError:
                    pass
        self._plugins.clear()
        self._discovered = False
        # 重建路由树：include_router 会把上一轮包路由合并进同一对象。
        self.router = APIRouter(prefix="/api/plugins", tags=["plugins"])
        self.router.add_api_route("", self._list_plugins, methods=["GET"])
        self.router.add_api_route("/{plugin_id}", self._get_plugin, methods=["GET"])


# ── 模块级单例 ──────────────────────────────────────────────────────────

_host = PluginHost()


def get_host() -> PluginHost:
    return _host


def discover_and_register(tool_registry: Any, plugins_root: Path | None = None) -> list[LoadedPlugin]:
    return _host.discover_and_register(tool_registry, plugins_root)


async def start_all(companion: Any) -> None:
    await _host.start_all(companion)


async def stop_all() -> None:
    await _host.stop_all()


def is_installed(pack_id: str) -> bool:
    return _host.is_installed(pack_id)


def list_status() -> list[dict[str, Any]]:
    return _host.list_status()


def reset_for_tests() -> None:
    _host.reset()


# ── 工具函数 ────────────────────────────────────────────────────────────

_VERSION_RE = re.compile(r"\d+")


def _version_tuple(text: str) -> tuple[int, ...]:
    """取版本号前导数字段（0.3.2-beta.0904 → (0,3,2)）；缺失位补 0。"""
    numbers = [int(n) for n in _VERSION_RE.findall(str(text))[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def _running_from_source() -> bool:
    """从源码目录运行（含 .git）视为开发态，豁免安装标记；打包态必验。"""
    if (os.environ.get("AERIE_PLUGIN_DEV") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return (paths.project_root() / ".git").is_dir()


def _resolve_ref(ref: str) -> Any:
    module_name, attr_name = ref.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)

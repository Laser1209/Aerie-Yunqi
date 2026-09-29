"""浏览器工具的来源必须按配置与"包是否已装"决定。

为什么这条不能省：`ToolRegistry.register()` 是**直接赋值覆盖**（不做冲突拒绝），
而 `core/companion.py` 的注册顺序是「功能包先、核心工具后」。于是核心无条件注册的
`browser_*`（Kimi WebBridge）会把 browser 功能包注册的同名工具**整个顶掉** ——
用户装了 170MB 的 Playwright 内核，实际仍在调外部 WebBridge，而且毫无报错。

同时不能走另一个极端：核心瘦身不能以"没装包的用户静默失去浏览器能力"为代价。
所以默认 `auto`：装了包让位，没装维持现状。
"""

from __future__ import annotations

import pytest

from core import plugin_host
from core.tool_registry import ToolRegistry
from tools import register_all_tools


def _names(monkeypatch, backend: str, pack_installed: bool) -> set[str]:
    import tools as tools_pkg

    monkeypatch.setattr(tools_pkg, "_browser_backend", lambda: backend)
    monkeypatch.setattr(
        plugin_host, "is_installed", lambda pack_id: pack_installed and pack_id == "browser"
    )
    reg = ToolRegistry()
    register_all_tools(reg)
    return set(reg.list_names())


@pytest.mark.parametrize("installed", [False, True])
def test_explicit_playwright_never_registers_webbridge(monkeypatch, installed):
    """显式选 playwright：无论包装没装，核心都不碰 browser_*。"""
    names = _names(monkeypatch, "playwright", installed)
    assert "browser_navigate" not in names
    assert "browser_snapshot" not in names


@pytest.mark.parametrize("installed", [False, True])
def test_explicit_webbridge_always_registers(monkeypatch, installed):
    """显式选 webbridge：无视包状态，始终注册内置通道。"""
    names = _names(monkeypatch, "webbridge", installed)
    assert "browser_navigate" in names


def test_auto_yields_to_pack_when_installed(monkeypatch):
    """auto + 已装包：核心让位，包的 browser_* 才不会被顶掉。"""
    names = _names(monkeypatch, "auto", pack_installed=True)
    assert "browser_navigate" not in names


def test_auto_keeps_webbridge_when_pack_absent(monkeypatch):
    """auto + 未装包：维持内置通道 —— 不让现有用户静默失去浏览器能力。"""
    names = _names(monkeypatch, "auto", pack_installed=False)
    assert "browser_navigate" in names


def test_settings_yaml_declares_browser_backend():
    """配置项本身要存在，否则"能按配置切"只是空话。"""
    import yaml

    from core.paths import project_root

    cfg = yaml.safe_load(
        (project_root() / "config" / "settings.yaml").read_text(encoding="utf-8")
    )
    assert cfg["browser"]["backend"] in ("auto", "playwright", "webbridge")


def test_missing_config_falls_back_to_auto(monkeypatch):
    """配置读不到时不得抛异常，且按 auto 处理（维持现状优先）。"""
    import tools as tools_pkg

    monkeypatch.setattr(
        "core.paths.project_root", lambda: __import__("pathlib").Path("/nonexistent")
    )
    assert tools_pkg._browser_backend() == "auto"

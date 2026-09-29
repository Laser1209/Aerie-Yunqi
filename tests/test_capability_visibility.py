"""Part C 能力可见性 —— 失败文案（C2）/ 自省工具（C3）/ 按需注入（C4）契约测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import capability_catalog as cc


@pytest.fixture(autouse=True)
def _isolate_catalog(monkeypatch):
    """把目录换成受控的两条 skill，避免受本机 plugin / MCP / 真实 skill 影响。"""
    from core.skill_loader import SkillLoader

    loader = SkillLoader(None, None)
    loader.discovered = {
        "byted-seedream": {
            "desc": "Seedream 文生图",
            "available": False,
            "unavailable_reason": "missing env: SEEDREAM_KEY",
            "setup_hint": "",
        },
        "byted-mediakit": {
            "desc": "AI MediaKit",
            "available": False,
            "unavailable_reason": "missing cli: mediakit-cli",
            "setup_hint": "本机执行：npm install -g @volcengine/mediakit-cli",
        },
        "doc-page": {
            "desc": "可打印文档页",
            "available": True,
            "unavailable_reason": "",
            "setup_hint": "",
        },
    }
    monkeypatch.setattr(cc, "_plugin_entries", lambda: [])
    monkeypatch.setattr(cc, "_mcp_entries", lambda: [])
    cc.set_loader(loader)
    yield
    cc.set_loader(None)


# ── C2 失败文案 ─────────────────────────────────────────

def test_failure_text_points_to_settings_for_missing_env():
    from core.progress_reporter import chat_failure_text

    text = chat_failure_text("credential_missing: env 'SEEDREAM_KEY' not set")

    assert "SEEDREAM_KEY" in text
    assert "平台凭证" in text


def test_failure_text_points_to_install_for_missing_module():
    from core.progress_reporter import chat_failure_text

    text = chat_failure_text("missing cli: mediakit-cli")

    assert "mediakit-cli" in text
    assert "npm install" in text


def test_failure_text_falls_back_when_not_reverse_lookupable():
    """反查不到就回落原兜底文案 —— 不瞎指路。"""
    from core.progress_reporter import _CHAT_FAILURE_BY_REASON, chat_failure_text

    text = chat_failure_text("ModuleNotFoundError: No module named 'ghost_module'")

    assert "ghost_module" not in text
    assert any(text == fallback for _kws, fallback in _CHAT_FAILURE_BY_REASON)


def test_failure_text_keeps_timeout_bucket():
    from core.progress_reporter import chat_failure_text

    assert chat_failure_text("request timed out") == "刚才那一步卡住了，我再试一次。"


# ── C3 自省工具 ─────────────────────────────────────────

def test_system_status_overview_reports_counts():
    from tools.system_tools import system_status

    result = system_status()

    assert result["status"] == "ok"
    assert result["total"] == 3
    assert result["ready_count"] == 1
    assert result["unavailable_count"] == 2


def test_system_status_single_lookup_returns_where():
    from tools.system_tools import system_status

    result = system_status(name="byted-seedream")

    assert result["status"] == "ok"
    cap = result["capability"]
    assert cap["ready"] is False
    assert cap["missing"] == ["SEEDREAM_KEY"]
    assert "平台凭证" in cap["where"]


def test_system_status_unknown_name_errors_instead_of_empty():
    from tools.system_tools import system_status

    result = system_status(name="no-such-thing")

    assert "unknown capability" in result["error"]
    assert "byted-seedream" in result["known_sample"]


def test_system_health_returns_uptime_fields():
    from tools.system_tools import system_health

    result = system_health()

    assert result["status"] == "ok"
    assert "uptime_seconds" in result
    assert "uptime_text" in result


def test_system_tools_register_into_registry():
    from core.tool_registry import ToolRegistry
    from tools.system_tools import register_system_tools

    registry = ToolRegistry()
    register_system_tools(registry)

    names = set(registry.list_names()) if hasattr(registry, "list_names") else set(registry._tools)
    assert {"system_status", "system_health"} <= names


# ── C4 按需注入 ─────────────────────────────────────────

@pytest.fixture
def builder():
    from core.context_builder import ContextBuilder

    return ContextBuilder()


def _system(builder, msg: str) -> str:
    return builder.build(3998874040, msg, "FULL")[0]["content"]


def test_capability_block_injected_when_message_names_it(builder):
    system = _system(builder, "我要用 seedream 画张图")

    assert "能力可见性" in system
    assert "SEEDREAM_KEY" in system
    assert "平台凭证" in system


def test_capability_block_absent_for_smalltalk(builder):
    system = _system(builder, "今天有点累，随便聊聊")

    assert "能力可见性" not in system


def test_capability_block_injected_from_history_failure(builder):
    """上一轮失败文案里带了 SEEDREAM_KEY → 下一轮要能"记得"该去哪儿配。"""
    history = [{"role": "assistant", "content": "这个能力还缺 SEEDREAM_KEY 没配好。"}]

    system = builder._build_system_prompt(
        {"basic": {"name": "伊塔"}, "behavior": {}},
        "FULL",
        current_msg="那我怎么办",
        history_msgs=history,
    )

    assert "能力可见性" in system


def test_capability_block_absent_in_basic_mode(builder):
    """BASIC 模式不注入能力可见性（省预算）。"""
    system = builder.build(99999, "我要用 seedream", "BASIC")[0]["content"]

    assert "能力可见性" not in system

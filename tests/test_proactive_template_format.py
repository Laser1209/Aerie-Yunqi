"""主动消息模板格式化：缺占位符必须降级、绝不抛异常。

背景（真机事故 2026-09-28）：`boot_greeting` 的模板含 `{todo_count}`，而
`Companion._dispatch_push` 的 kwargs 未提供该键 → `template.format(**kwargs)`
抛 `KeyError` → 整条主动推送失败（用户一条消息都收不到）。
且当时**主路径裸调 format、兜底反而有 except** —— 防御只写在一处。

本组测试钉住两件事：
1. `_format_template_tolerant` 对缺键/非法模板一律降级，永不抛异常；
2. `generate_push` 的模板通道不再因缺键中断。
"""

from __future__ import annotations

import string

from core.llm_caller import _format_template_tolerant


def test_formats_when_all_placeholders_provided():
    out = _format_template_tolerant("你好宝贝，今天{date}，{weather}。", {
        "date": "2026年09月28日", "weather": "晴",
    })
    assert out == "你好宝贝，今天2026年09月28日，晴。"


def test_missing_placeholder_degrades_to_empty_without_raising():
    """实测事故的核心：缺键必须降级，不能抛 KeyError 让整条推送死掉。"""
    out = _format_template_tolerant("今天{date}，你还有{todo_count}件事要做，{weather}。", {
        "date": "2026年09月28日",
    })
    assert out == "今天2026年09月28日，你还有件事要做，。"
    assert "{todo_count}" not in out
    assert "{weather}" not in out


def test_missing_placeholder_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        _format_template_tolerant("你还有{todo_count}件事", {"date": "x"})
    assert "todo_count" in caplog.text


def test_empty_template_returns_empty_string():
    assert _format_template_tolerant("", {"date": "x"}) == ""
    assert _format_template_tolerant(None, {"date": "x"}) == ""


def test_malformed_template_is_returned_as_is():
    """模板本身语法坏掉（未闭合花括号）时原样返回，不把异常抛给调用方。"""
    broken = "早安 {date 你好"
    out = _format_template_tolerant(broken, {"date": "x"})
    assert out == broken


def test_no_placeholders_passes_through():
    assert _format_template_tolerant("早安宝贝。", {}) == "早安宝贝。"


def test_all_configured_scene_templates_render_with_date_only():
    """配置里所有场景模板，即使只给 date 也必须能渲染出来（不漏占位符、不抛错）。

    这是对"模板来自配置、取值来自代码"不同源这一结构性风险的直接回归。
    """
    from config.persona_loader import load_proactive_config

    scenes = (load_proactive_config() or {}).get("scenes") or {}
    assert scenes, "proactive scenes must be configured"

    for name, cfg in scenes.items():
        template = str((cfg or {}).get("template") or "")
        out = _format_template_tolerant(template, {"date": "2026年09月28日"})
        assert isinstance(out, str)
        # 渲染结果里不应残留任何未替换的占位符
        remaining = [
            field
            for _, field, _, _ in string.Formatter().parse(out)
            if field
        ]
        assert not remaining, f"scene {name} left placeholders: {remaining}"

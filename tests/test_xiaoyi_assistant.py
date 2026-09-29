"""小伊（系统管家）契约测试。

三条不能破的底线：
1. 小伊**不走 persona 机制**（不写 `_active.json`，不与人设中心耦合）；
2. 上下文是**自然语言摘要**，不是把 JSON 堆给模型；
3. 快照与上下文**绝不携带密钥明文**。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from core import xiaoyi_assistant as xy


def test_snapshot_has_expected_sections_and_no_secrets():
    snap = xy.snapshot()

    assert snap["status"] == "ok"
    for key in ("health", "tokens", "capabilities", "tasks"):
        assert key in snap

    blob = json.dumps(snap, ensure_ascii=False)
    for marker in ("sk-", "ntn_", "Bearer "):
        assert marker not in blob, "快照里绝不能出现密钥形态的串"


def test_context_is_natural_language_not_json_dump():
    snap = {
        "health": {"uptime_text": "3 小时 20 分", "providers_banned": ["x"]},
        "tokens": {"calls": 12, "total_tokens": 3456},
        "capabilities": {
            "total": 70,
            "ready_count": 60,
            "unavailable": [
                {
                    "name": "byted-seedream",
                    "unavailable_reason": "missing env: SEEDREAM_KEY",
                    "where": "设置页 → 平台凭证 → 火山 Seedream 文生图",
                }
            ],
        },
        "tasks": {},
        "pending_proposals": 2,
    }

    text = xy.build_context(snap)

    assert "已经连续运行 3 小时 20 分" in text
    assert "设置页 → 平台凭证" in text
    assert "2 条自我改进提案" in text
    assert "{" not in text and "}" not in text, "不该把 JSON 丢给模型"


def test_context_with_nothing_to_report_says_all_normal():
    text = xy.build_context({"health": {}, "tokens": {}, "capabilities": {}, "tasks": {}})

    assert "一切正常" in text


def test_empty_message_is_rejected():
    assert asyncio.run(xy.answer("   "))["error"] == "empty_message"


def test_answer_uses_xiaoyi_prompt_and_not_persona(monkeypatch):
    captured: dict = {}

    class _FakeBrain:
        def __init__(self, *_a, **_kw):
            pass

        async def chat(self, messages, **_kw):
            captured["messages"] = messages
            return SimpleNamespace(text="好呀，我看看。", provider="main_llm")

    import core.llm_caller as llm_caller

    monkeypatch.setattr(llm_caller, "LLMCaller", _FakeBrain)

    result = asyncio.run(xy.answer("我要用 seedream，怎么装？", history=[
        {"role": "user", "content": "在吗"},
        {"role": "assistant", "content": "在的"},
        {"role": "user", "content": "？？"},
        {"role": "user", "content": "？？"},
        {"role": "user", "content": "？？"},
        {"role": "user", "content": "？？"},
        {"role": "user", "content": "？？"},
        {"role": "user", "content": "？？"},
    ]))

    assert result["status"] == "ok"
    assert result["reply"] == "好呀，我看看。"
    assert result["conversation_id"] == xy.CONVERSATION_ID

    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert "小伊" in messages[0]["content"]
    assert messages[1]["role"] == "system" and "当前状态" in messages[1]["content"]
    # 历史只保留最后 MAX_HISTORY_TURNS 条非空消息
    history = [m for m in messages if m["role"] in ("user", "assistant")]
    assert len(history) <= xy.MAX_HISTORY_TURNS + 1


def test_conversation_id_is_not_a_persona():
    """独立会话标识：不该长得像 persona id，也不该出现在人设目录里。"""
    from core.paths import data_dir

    assert xy.CONVERSATION_ID == "xiaoyi"
    personas_dir = data_dir() / "personas"
    if personas_dir.exists():
        assert not (personas_dir / xy.CONVERSATION_ID).exists(), "小伊不得是人设目录里的角色"


def test_snapshot_survives_missing_companion(monkeypatch):
    """companion 未就绪时不能抛错（侧栏轮询会反复打这个接口）。"""
    import core.companion as companion_mod

    monkeypatch.setattr(companion_mod, "get_companion", lambda: None)

    snap = xy.snapshot()

    assert snap["tasks"] == {}
    assert snap["pending_proposals"] == 0

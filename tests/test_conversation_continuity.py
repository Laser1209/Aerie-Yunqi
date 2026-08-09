"""Tests for ContextAssembler time-perception fix (history timestamps + budget)."""

from unittest.mock import MagicMock

from core.conversation_continuity import ContextAssembler


def _assembler(max_total_chars=16_000):
    return ContextAssembler(
        conversations=MagicMock(),
        summaries=MagicMock(),
        max_total_chars=max_total_chars,
        recent_message_limit=24,
    )


def _page(*items):
    return {"items": list(items)}


def test_history_messages_get_timestamp_prefix():
    asm = _assembler()
    asm.conversations.history_page.return_value = _page(
        {"role": "user", "content": "我睡觉去了", "ts": "2026-08-09 04:06:47"},
        {"role": "assistant", "content": "晚安", "ts": "2026-08-09 04:06:47"},
    )
    asm.summaries.get.return_value = None

    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="看看腿我就去",
        actor_id="actor_primary",
        channel="qq",
        channel_account_id="3489352115",
        user_id=3489352115,
    )
    contents = [m["content"] for m in result.messages[1:-1]]
    assert "[08-09 04:06] 我睡觉去了" in contents
    assert "[08-09 04:06] 晚安" in contents


def test_history_without_timestamp_unchanged():
    asm = _assembler()
    asm.conversations.history_page.return_value = _page(
        {"role": "user", "content": "没有时间戳的消息"},
    )
    asm.summaries.get.return_value = None

    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="看看腿我就去",
        actor_id="actor_primary",
        channel="qq",
        channel_account_id="3489352115",
        user_id=3489352115,
    )
    contents = [m["content"] for m in result.messages[1:-1]]
    assert "没有时间戳的消息" in contents


def test_history_prefix_counts_toward_char_budget():
    """加时间前缀后，预算边界不应丢弃本可容纳的消息。"""
    asm = _assembler(max_total_chars=2000)
    # 每条内容 100 字符，前缀 ~11 字符。若预算不含前缀，会多装一条而超预算。
    items = [
        {"role": "user", "content": "x" * 100, "ts": "2026-08-09 04:06:47"}
        for _ in range(20)
    ]
    asm.conversations.history_page.return_value = _page(*items)
    asm.summaries.get.return_value = None

    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="看看腿我就去",
        actor_id="actor_primary",
        channel="qq",
        channel_account_id="3489352115",
        user_id=3489352115,
    )
    # 所有消息(含前缀)总字符数不得超过预算
    total = sum(len(m["content"]) for m in result.messages)
    assert total <= 2000
    # 至少装入一条带前缀的消息
    assert any(m["content"].startswith("[08-09 04:06] ") for m in result.messages[1:-1])
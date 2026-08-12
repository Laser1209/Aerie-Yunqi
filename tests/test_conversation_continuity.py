"""Tests for ContextAssembler time-perception fix (history timestamps + budget)."""

from unittest.mock import MagicMock

from core.conversation_continuity import ContextAssembler


def _assembler(max_total_chars=16_000, max_turn_chars=6_000):
    return ContextAssembler(
        conversations=MagicMock(),
        summaries=MagicMock(),
        max_total_chars=max_total_chars,
        recent_turn_limit=8,
        max_turn_chars=max_turn_chars,
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


def test_turn_grouping_keeps_recent_turns_complete():
    """同一 turn 的多条子消息（分句）全量保留，热窗口按最近 8 轮截取。"""
    asm = _assembler()
    items = []
    for t in range(10):
        tid = f"turn-{t}"
        ts = "2026-08-09 10:00:00"
        items.append({"role": "user", "content": f"第{t}轮问题", "ts": ts, "turn_id": tid})
        items.append({"role": "assistant", "content": f"第{t}轮回复-1", "ts": ts, "turn_id": tid})
        items.append({"role": "assistant", "content": f"第{t}轮回复-2", "ts": ts, "turn_id": tid})
    asm.conversations.history_page.return_value = _page(*items)
    asm.summaries.get.return_value = None

    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="接着聊",
        actor_id="actor_primary",
        channel="qq",
        channel_account_id="3489352115",
        user_id=3489352115,
    )
    contents = [m["content"] for m in result.messages[1:-1]]
    # 最近 8 轮（turn-2 ~ turn-9）完整保留，含每条分句
    assert any("第9轮回复-2" in c for c in contents)
    assert any("第2轮回复-2" in c for c in contents)
    # 更早轮次（turn-0 / turn-1）被窗口截掉
    assert not any("第1轮" in c for c in contents)
    assert not any("第0轮" in c for c in contents)
    assert result.audit["l0_turns_included"] == 8
    assert result.audit["l0_turns_requested"] == 8
    assert result.audit["l0_truncated"] is False


def test_turn_window_elasticity_truncates_oldest():
    """超 max_turn_chars 上限时从最远轮次截断，l0_truncated=True（§4 #11 用例②）。"""
    asm = _assembler(max_turn_chars=6_000)
    items = []
    for t in range(3):
        tid = f"turn-{t}"
        items.append({"role": "user", "content": "u" * 1400, "ts": "2026-08-09 10:00:00", "turn_id": tid})
        items.append({"role": "assistant", "content": "a" * 1400, "ts": "2026-08-09 10:00:01", "turn_id": tid})
    asm.conversations.history_page.return_value = _page(*items)
    asm.summaries.get.return_value = None

    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor_primary",
        channel="qq",
        channel_account_id="3489352115",
        user_id=3489352115,
    )
    contents = [m["content"] for m in result.messages[1:-1]]
    # 每轮 ~2800 字符，6000 上限只装得下最近 2 轮（turn-2 + turn-1），turn-0 被截断
    assert any("a" * 1400 in c for c in contents)
    assert result.audit["l0_truncated"] is True
    assert result.audit["l0_turns_included"] == 2


def test_channel_awareness_injected_into_system_prompt():
    """system prompt 头部注入【当前通道】（§3.4 / §4 #11 用例③）。"""
    asm = _assembler()
    asm.conversations.history_page.return_value = _page(
        {"role": "user", "content": "早上好", "ts": "2026-08-09 04:06:47", "channel": "qq"},
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
    assert "【当前通道】你正在通过「QQ 私聊」与用户聊天。" in result.messages[0]["content"]

    result_desktop = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="看看腿我就去",
        actor_id="actor_primary",
        channel="desktop",
        channel_account_id="3489352115",
        user_id=3489352115,
    )
    assert "【当前通道】你正在通过「云栖桌面 App」与用户聊天。" in result_desktop.messages[0]["content"]


def test_cross_channel_history_gets_source_tag():
    """跨通道来源的历史消息追加 [QQ]/[桌面] 标记；同通道消息不标注。"""
    asm = _assembler()
    asm.conversations.history_page.return_value = _page(
        # 同通道（desktop）历史：不标注
        {"role": "user", "content": "桌面端说的", "ts": "2026-08-09 04:06:47", "channel": "desktop"},
        # 跨通道来源（qq）：标注 [QQ]
        {"role": "user", "content": "QQ端说的", "ts": "2026-08-09 04:06:48", "channel": "qq"},
    )
    asm.summaries.get.return_value = None

    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor_primary",
        channel="desktop",
        channel_account_id="3489352115",
        user_id=3489352115,
    )
    contents = [m["content"] for m in result.messages[1:-1]]
    assert any("[QQ] QQ端说的" in c for c in contents)
    assert any("桌面端说的" in c and "[桌面]" not in c for c in contents)
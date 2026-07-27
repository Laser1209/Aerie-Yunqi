"""TDD tests for Task P1-B.2: OfficeContext 系统上下文采集与脱敏.

覆盖:
  - 字段齐全: active_window / focused_task / clipboard_candidate / network_state /
              battery_state / calendar_due / notification_budget
  - update_context 部分更新
  - clipboard_candidate 30 秒过期
  - calendar_due 到期提醒
  - 敏感字段脱敏 (password/token/secret/key/credential/authorization)
  - per-user 上下文隔离
"""

from __future__ import annotations

import time

import pytest


# ── 字段齐全 ────────────────────────────────────────
def test_office_context_has_all_fields():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    # 初始化应为安全默认值 (None/空/默认)
    assert hasattr(ctx, "active_window")
    assert hasattr(ctx, "focused_task")
    assert hasattr(ctx, "clipboard_candidate")
    assert hasattr(ctx, "network_state")
    assert hasattr(ctx, "battery_state")
    assert hasattr(ctx, "calendar_due")
    assert hasattr(ctx, "notification_budget")
    assert ctx.notification_budget == 0  # 默认预算为 0, 禁止主动消息


# ── update_context ─────────────────────────────────
def test_update_context_partial_fields():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    ctx.update_context(active_window="Chrome - Gmail", battery_state=87)
    assert ctx.active_window == "Chrome - Gmail"
    assert ctx.battery_state == 87
    # 未更新字段保持默认
    assert ctx.focused_task is None
    assert ctx.network_state is None


def test_update_context_overwrites_previous():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    ctx.update_context(active_window="VSCode")
    ctx.update_context(active_window="Notepad")
    assert ctx.active_window == "Notepad"


# ── clipboard_candidate 30s 过期 ──────────────────
def test_clipboard_candidate_expires_after_30s():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    now = time.time()
    ctx.update_context(
        clipboard_candidate={"text": "hello world", "captured_at": now - 31}
    )
    assert ctx.clipboard_candidate is None  # 已过期被清掉


def test_clipboard_candidate_fresh_within_window():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    now = time.time()
    ctx.update_context(
        clipboard_candidate={"text": "fresh text", "captured_at": now - 5}
    )
    assert ctx.clipboard_candidate is not None
    assert ctx.clipboard_candidate["text"] == "fresh text"


# ── calendar_due 到期提醒 ─────────────────────────
def test_calendar_due_returns_when_event_is_due():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    now = time.time()
    ctx.update_context(
        calendar_due={
            "title": "周会",
            "start_at": now - 60,  # 1 分钟前开始
            "remind_advance": 300,
        }
    )
    due = ctx.get_due_calendar_events()
    assert len(due) == 1
    assert due[0]["title"] == "周会"


def test_calendar_due_filters_future_events():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    now = time.time()
    ctx.update_context(
        calendar_due={
            "title": "未来会议",
            "start_at": now + 3600,
            "remind_advance": 300,
        }
    )
    assert ctx.get_due_calendar_events() == []


# ── 敏感字段脱敏 ──────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected_hint",
    [
        ("password=abc123", "***"),
        ("my_token=sk-1234567890abcdef", "***"),
        ("secret_key: supersecret", "***"),
        ("Authorization: Bearer xyz789", "***"),
        ("credentials: admin:pass", "***"),
        ("api_key=ABCDEF123456", "***"),
    ],
)
def test_clipboard_redacts_sensitive_patterns(raw, expected_hint):
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    ctx.update_context(clipboard_candidate={"text": raw, "captured_at": time.time()})
    # 敏感模式必须被屏蔽, 原文不应出现
    redacted = ctx.clipboard_candidate["text"]
    assert raw not in redacted
    assert "***" in redacted


def test_clipboard_keeps_normal_text_untouched():
    from core.office_context import OfficeContext

    ctx = OfficeContext()
    ctx.update_context(
        clipboard_candidate={
            "text": "meeting notes: discuss Q3 roadmap",
            "captured_at": time.time(),
        }
    )
    assert ctx.clipboard_candidate["text"] == "meeting notes: discuss Q3 roadmap"


# ── per-user 隔离 ─────────────────────────────────
def test_context_isolated_per_user():
    from core.office_context import OfficeContext

    alice = OfficeContext(user_id="alice")
    bob = OfficeContext(user_id="bob")
    alice.update_context(active_window="Alice's IDE")
    bob.update_context(active_window="Bob's Terminal")
    assert alice.active_window == "Alice's IDE"
    assert bob.active_window == "Bob's Terminal"
    assert alice.user_id == "alice"
    assert bob.user_id == "bob"


def test_notification_budget_decrement():
    from core.office_context import OfficeContext

    ctx = OfficeContext(notification_budget=3)
    assert ctx.consume_notification_budget() is True
    assert ctx.notification_budget == 2
    ctx.consume_notification_budget()
    ctx.consume_notification_budget()
    assert ctx.notification_budget == 0
    # 预算耗尽后不应再允许主动通知
    assert ctx.consume_notification_budget() is False

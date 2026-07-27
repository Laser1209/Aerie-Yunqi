"""TDD tests for Task P1-B.5: companion_mode / office_mode 模式切换.

覆盖:
  - companion_mode → office_mode 切换
  - office_mode → companion_mode 切换
  - 切换写入 trace (timestamp / from_mode / to_mode / reason)
  - office_mode 下 is_proactive_allowed() 返回 False
  - companion_mode 下 is_proactive_allowed() 返回 True (默认)
  - 重复切换到同一模式被忽略或允许 (幂等行为)
"""

from __future__ import annotations

import time

import pytest


# ── 默认模式 ──────────────────────────────────────
def test_default_mode_is_companion():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    assert sw.get_current_mode() == CompanionMode.COMPANION


# ── companion → office ────────────────────────────
def test_switch_companion_to_office():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    ok = sw.switch_mode(CompanionMode.OFFICE, reason="user_toggled")
    assert ok is True
    assert sw.get_current_mode() == CompanionMode.OFFICE


# ── office → companion ────────────────────────────
def test_switch_office_to_companion():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch(initial=CompanionMode.OFFICE)
    ok = sw.switch_mode(CompanionMode.COMPANION, reason="task_done")
    assert ok is True
    assert sw.get_current_mode() == CompanionMode.COMPANION


# ── trace 记录 ────────────────────────────────────
def test_switch_writes_trace_entry():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    sw.switch_mode(CompanionMode.OFFICE, reason="enter_meeting")
    assert len(sw.trace) == 1
    entry = sw.trace[0]
    assert entry["from_mode"] == CompanionMode.COMPANION
    assert entry["to_mode"] == CompanionMode.OFFICE
    assert entry["reason"] == "enter_meeting"
    assert entry["timestamp"] > 0


def test_trace_accumulates_multiple_switches():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    sw.switch_mode(CompanionMode.OFFICE, reason="a")
    time.sleep(0.01)
    sw.switch_mode(CompanionMode.COMPANION, reason="b")
    assert len(sw.trace) == 2
    assert sw.trace[0]["to_mode"] == CompanionMode.OFFICE
    assert sw.trace[1]["to_mode"] == CompanionMode.COMPANION
    assert sw.trace[1]["timestamp"] >= sw.trace[0]["timestamp"]


# ── proactive allowed ─────────────────────────────
def test_office_mode_disables_proactive():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch(initial=CompanionMode.OFFICE)
    assert sw.is_proactive_allowed() is False


def test_companion_mode_allows_proactive():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    assert sw.is_proactive_allowed() is True


def test_proactive_flips_with_switch():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    assert sw.is_proactive_allowed() is True
    sw.switch_mode(CompanionMode.OFFICE, reason="focus")
    assert sw.is_proactive_allowed() is False
    sw.switch_mode(CompanionMode.COMPANION, reason="relax")
    assert sw.is_proactive_allowed() is True


# ── 幂等 ─────────────────────────────────────────
def test_switch_to_same_mode_is_idempotent():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    first = sw.switch_mode(CompanionMode.COMPANION, reason="noop")
    # 切到相同模式: 返回 False / True 均可接受, 但 mode 必须不变
    assert sw.get_current_mode() == CompanionMode.COMPANION
    # 不应当重复记录 trace (避免噪音)
    assert len(sw.trace) == 0


# ── 字符串模式名也可切换 ──────────────────────────
def test_switch_accepts_string_mode():
    from core.mode_switch import CompanionMode, ModeSwitch

    sw = ModeSwitch()
    sw.switch_mode("office", reason="hotkey")
    assert sw.get_current_mode() == CompanionMode.OFFICE

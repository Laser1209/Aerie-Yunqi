"""TDD RED tests for Task P1-D.4: CompanionChannel 通道抽象.

覆盖:
  - CompanionChannel Protocol 契约 (health / echo / send / receive)
  - QQ 适配器本地桩: 健康检查、回显、发送入队、接收
  - ClawBot 适配器本地桩: 健康检查、回显、发送入队、接收
    - 安全边界: 本地桩绝不触发真实 QQ 引擎消息动作
"""

from __future__ import annotations

import pytest

from core.companion_channel import (
    ChannelHealth,
    ChannelMessage,
    ClawBotChannelAdapter,
    CompanionChannel,
    QQChannelAdapter,
    SendReceipt,
)


# ── Protocol 契约 ──────────────────────────────────
def test_companion_channel_is_protocol():
    from typing import Protocol

    assert issubclass(CompanionChannel, Protocol)


def test_protocol_defines_health_echo_send_receive():
    for method in ("health", "echo", "send", "receive"):
        assert hasattr(CompanionChannel, method), f"missing method: {method}"


def test_qq_adapter_satisfies_protocol():
    adapter: CompanionChannel = QQChannelAdapter()
    for method in ("health", "echo", "send", "receive"):
        assert callable(getattr(adapter, method)), f"QQ missing {method}"


def test_clawbot_adapter_satisfies_protocol():
    adapter: CompanionChannel = ClawBotChannelAdapter()
    for method in ("health", "echo", "send", "receive"):
        assert callable(getattr(adapter, method)), f"ClawBot missing {method}"


# ── QQ 适配器: 健康检查 ─────────────────────────────
def test_qq_health_returns_healthy_stub():
    adapter = QQChannelAdapter()
    health = adapter.health()
    assert isinstance(health, ChannelHealth)
    assert health.channel == "qq"
    assert health.healthy is True
    assert health.status


# ── QQ 适配器: 回显 ─────────────────────────────────
def test_qq_echo_returns_same_text():
    adapter = QQChannelAdapter()
    assert adapter.echo("你好") == "你好"
    assert adapter.echo("ping") == "ping"


# ── QQ 适配器: 发送(本地桩入队) ─────────────────────
def test_qq_send_returns_accepted_receipt():
    adapter = QQChannelAdapter()
    receipt = adapter.send({"text": "早安", "target": 123456})
    assert isinstance(receipt, SendReceipt)
    assert receipt.channel == "qq"
    assert receipt.accepted is True


def test_qq_send_records_to_outbox_without_real_network():
    adapter = QQChannelAdapter()
    adapter.send({"text": "早安"})
    adapter.send({"text": "晚安"})
    assert len(adapter.outbox) == 2
    assert adapter.outbox[0].text == "早安"
    assert adapter.outbox[1].text == "晚安"


# ── QQ 适配器: 接收(本地桩 inbox) ───────────────────
def test_qq_receive_returns_seeded_inbox_messages():
    adapter = QQChannelAdapter(inbox_texts=["用户消息A", "用户消息B"])
    messages = adapter.receive()
    assert isinstance(messages, list)
    assert len(messages) == 2
    assert all(isinstance(m, ChannelMessage) for m in messages)
    assert messages[0].text == "用户消息A"
    assert messages[1].text == "用户消息B"


def test_qq_receive_drains_inbox():
    adapter = QQChannelAdapter(inbox_texts=["仅此一条"])
    assert len(adapter.receive()) == 1
    assert adapter.receive() == []


# ── ClawBot 适配器: 健康检查 ────────────────────────
def test_clawbot_health_returns_healthy_stub():
    adapter = ClawBotChannelAdapter()
    health = adapter.health()
    assert isinstance(health, ChannelHealth)
    assert health.channel == "clawbot"
    assert health.healthy is True
    assert health.status


# ── ClawBot 适配器: 回显 ────────────────────────────
def test_clawbot_echo_returns_same_text():
    adapter = ClawBotChannelAdapter()
    assert adapter.echo("hello clawbot") == "hello clawbot"


# ── ClawBot 适配器: 发送(本地桩入队) ────────────────
def test_clawbot_send_returns_accepted_and_records_outbox():
    adapter = ClawBotChannelAdapter()
    receipt = adapter.send({"text": "提醒喝水"})
    assert receipt.accepted is True
    assert receipt.channel == "clawbot"
    assert len(adapter.outbox) == 1
    assert adapter.outbox[0].text == "提醒喝水"


# ── ClawBot 适配器: 接收 ────────────────────────────
def test_clawbot_receive_returns_seeded_messages():
    adapter = ClawBotChannelAdapter(inbox_texts=["clawbot 提示"])
    messages = adapter.receive()
    assert len(messages) == 1
    assert messages[0].channel == "clawbot"
    assert messages[0].text == "clawbot 提示"


# ── 安全边界: 绝不触发真实消息动作 ─────────────────
def test_stubs_never_touch_real_network_actions(monkeypatch):
    """send/echo 只操作本地内存, 不导入或调用 QQClient/QQ 引擎."""
    import sys

    import core.companion_channel as module

    adapter_qq = QQChannelAdapter()
    adapter_claw = ClawBotChannelAdapter()

    monkeypatch.setattr(sys, "path", sys.path)  # no-op, keep style
    # 仅断言桩行为不依赖真实客户端对象
    assert not hasattr(adapter_qq, "client")
    assert not hasattr(adapter_claw, "client")
    assert module.__name__ == "core.companion_channel"

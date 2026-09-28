"""§九-b 请求级投递上下文（DeliveryContext）与主动消息端口策略测试。

覆盖计划 §9.6 的验收项：
  1/2/3. 微信 / QQ / **桌面端** 要文件 → 各自回到自己的端口
  4.     交错进行（先微信、后桌面）→ 两次分别回到各自端口（不是全局状态）
  5.     主动推送：投最近活跃端口；窗口内无记录 → 落桌面端
  + 无来源端口时不静默丢件（落未决回执，供 P0-2 回报模型）
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from communication.message import IncomingMessage, OutgoingReply
from core import delivery_routing as dr
from core.companion import Companion
from core.delivery_routing import DeliveryContext


# ── 归一与构造 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("qq", "qq"),
        ("ilink", "ilink"),
        ("local", "local_chat"),
        ("local_chat", "local_chat"),
        ("QQ", "qq"),
        ("", "local_chat"),
        (None, "local_chat"),
        ("wechat", "local_chat"),  # 未知来源一律按桌面处理（最保守）
    ],
)
def test_normalize_channel(value, expected):
    assert dr.normalize_channel(value) == expected


def test_context_from_message_prefers_channel_then_source():
    msg = IncomingMessage(user_id=42, content="hi", source="ilink", channel="ilink",
                          channel_account_id="acc-1")
    ctx = dr.context_from_message(msg)
    assert ctx == DeliveryContext(channel="ilink", user_id=42, channel_account_id="acc-1")


def test_context_from_message_desktop_has_no_account_id():
    """桌面端不需要 channel_account_id（它按 user_id 定点投递）。"""
    msg = IncomingMessage(user_id=7, content="hi", source="local", channel="local_chat",
                          channel_account_id="should-be-dropped")
    ctx = dr.context_from_message(msg)
    assert ctx is not None
    assert ctx.channel == "local_chat"
    assert ctx.channel_account_id == ""


def test_context_from_message_without_user_id_is_none():
    assert dr.context_from_message(IncomingMessage(user_id=0, content="hi")) is None


# ── ContextVar 绑定 ───────────────────────────────────────────────────


def test_bind_and_unbind_restores_previous():
    assert dr.current() is None
    outer = dr.bind(DeliveryContext(channel="qq", user_id=1))
    inner = dr.bind(DeliveryContext(channel="local_chat", user_id=1))
    assert dr.current().channel == "local_chat"
    dr.unbind(inner)
    assert dr.current().channel == "qq"
    dr.unbind(outer)
    assert dr.current() is None


# ── 主动消息端口策略 ───────────────────────────────────────────────────


def test_proactive_config_defaults_and_overrides():
    assert dr.proactive_channel_config({}) == ("auto", dr.DEFAULT_RECENT_WINDOW_MIN)
    assert dr.proactive_channel_config(None) == ("auto", dr.DEFAULT_RECENT_WINDOW_MIN)
    mode, window = dr.proactive_channel_config(
        {"proactive": {"delivery_channel": "ilink", "auto_recent_window_min": 10}}
    )
    assert (mode, window) == ("ilink", 10.0)


def test_proactive_explicit_channel_wins():
    assert dr.resolve_proactive_channel(configured="ilink") == "ilink"


def test_proactive_auto_uses_fresh_recent_channel():
    recent = DeliveryContext(channel="qq", user_id=1)
    assert dr.resolve_proactive_channel(configured="auto", recent=recent, recent_fresh=True) == "qq"


def test_proactive_auto_stale_or_missing_recent_falls_back_to_desktop():
    recent = DeliveryContext(channel="qq", user_id=1)
    assert dr.resolve_proactive_channel(configured="auto", recent=recent, recent_fresh=False) == "local_chat"
    assert dr.resolve_proactive_channel(configured="auto") == "local_chat"


# ── Companion：最近活跃端口记录（含桌面） ──────────────────────────────


def _bare_companion(*, settings=None) -> Companion:
    comp = Companion.__new__(Companion)
    comp.queue = SimpleNamespace(enqueue=lambda reply: comp.queue.sent.append(reply))
    comp.queue.sent = []
    comp.settings = settings or {}
    comp._recent_inbound = None
    comp.message_batcher = None
    comp.pipeline = None
    return comp


def test_submit_incoming_records_desktop_too():
    """旧实现只在 qq/ilink 入站时记录 —— 桌面端发起的请求在投递侧完全不可见。"""
    comp = _bare_companion()
    asyncio.run(comp._submit_incoming_message(
        IncomingMessage(user_id=7, content="hi", source="local", channel="local_chat")
    ))
    assert comp._recent_inbound is not None
    assert comp._recent_inbound[0].channel == "local_chat"


def test_proactive_channel_prefers_fresh_recent_then_desktop():
    comp = _bare_companion(settings={"proactive": {"delivery_channel": "auto"}})
    # 无记录 → 桌面端
    assert comp._proactive_delivery_channel() == "local_chat"
    # 30 分钟窗口内刚在 QQ 活跃 → 投 QQ
    comp._recent_inbound = (DeliveryContext(channel="qq", user_id=1), time.time())
    assert comp._proactive_delivery_channel() == "qq"
    # 超出窗口 → 落桌面
    comp._recent_inbound = (
        DeliveryContext(channel="qq", user_id=1),
        time.time() - 31 * 60,
    )
    assert comp._proactive_delivery_channel() == "local_chat"


def test_proactive_channel_honours_explicit_config():
    comp = _bare_companion(settings={"proactive": {"delivery_channel": "ilink"}})
    comp._recent_inbound = (DeliveryContext(channel="qq", user_id=1), time.time())
    assert comp._proactive_delivery_channel() == "ilink"


# ── 文件投递回到来源端口（验收 1/2/3/4） ──────────────────────────────


def _deliver_with_origin(comp, channel, *, user_id=7, account="", path="x.docx"):
    token = dr.bind(DeliveryContext(channel=channel, user_id=user_id, channel_account_id=account))
    try:
        comp._notify_file_delivery({"path": path, "note": "给你"})
    finally:
        dr.unbind(token)


def test_wechat_request_delivers_back_to_wechat():
    comp = _bare_companion()
    _deliver_with_origin(comp, "ilink", account="acc-9")
    assert len(comp.queue.sent) == 1
    assert comp.queue.sent[0].channel == "ilink"
    assert comp.queue.sent[0].channel_account_id == "acc-9"


def test_qq_request_delivers_back_to_qq():
    comp = _bare_companion()
    _deliver_with_origin(comp, "qq")
    assert comp.queue.sent[0].channel == "qq"


def test_desktop_request_delivers_back_to_desktop():
    """桌面端要文件 → 桌面端收到（旧实现会投到上次的 QQ/微信，或静默丢件）。"""
    comp = _bare_companion()
    _deliver_with_origin(comp, "local_chat")
    assert comp.queue.sent[0].channel == "local_chat"


def test_interleaved_requests_go_to_their_own_ports():
    """先微信、后桌面各要一次 → 两次分别回到各自端口（证明不是全局状态）。"""
    comp = _bare_companion()
    _deliver_with_origin(comp, "ilink", account="acc-1", path="a.docx")
    _deliver_with_origin(comp, "local_chat", path="b.docx")

    assert [r.channel for r in comp.queue.sent] == ["ilink", "local_chat"]
    assert [r.file_paths[0] for r in comp.queue.sent] == ["a.docx", "b.docx"]


def test_no_origin_records_pending_receipt():
    """无来源端口 → 不静默丢件：落一条未决回执（P0-2 会把它回报给模型）。"""
    from core.delivery_ledger import get_ledger

    ledger = get_ledger()
    ledger.clear()
    comp = _bare_companion()
    comp._notify_file_delivery({"path": "c.docx", "note": ""})

    assert comp.queue.sent == []
    assert ledger.has_pending(0) is True
    ledger.clear()


def test_approval_notice_goes_to_origin_port():
    comp = _bare_companion()
    token = dr.bind(DeliveryContext(channel="local_chat", user_id=7))
    try:
        comp._notify_pending_approval({"call_id": "c1", "action": "shell_execute"})
    finally:
        dr.unbind(token)

    assert len(comp.queue.sent) == 1
    assert comp.queue.sent[0].channel == "local_chat"
    assert isinstance(comp.queue.sent[0], OutgoingReply)

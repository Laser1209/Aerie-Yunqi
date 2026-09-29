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
        {"proactive": {"primary_channel": "ilink", "auto_recent_window_min": 10}}
    )
    assert (mode, window) == ("ilink", 10.0)


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("auto", "auto"),
        ("qq", "qq"),
        ("ilink", "ilink"),
        # electron「外部连接」面板写的是 desktop / wechat 这类别名，要能认出来
        ("desktop", "local_chat"),
        ("wechat", "ilink"),
        # 写错一个词不该把主动消息投到没人看的端口 → 按 auto 处理
        ("telegram", "auto"),
        ("", "auto"),
    ],
)
def test_proactive_config_normalizes_aliases(configured, expected):
    mode, _ = dr.proactive_channel_config({"proactive": {"primary_channel": configured}})
    assert mode == expected


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
    comp = _bare_companion(settings={"proactive": {"primary_channel": "auto"}})
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
    comp = _bare_companion(settings={"proactive": {"primary_channel": "ilink"}})
    comp._recent_inbound = (DeliveryContext(channel="qq", user_id=1), time.time())
    assert comp._proactive_delivery_channel() == "ilink"


def test_proactive_channel_accepts_electron_panel_desktop_alias():
    """electron「外部连接」面板写 desktop → 归一为桌面端（此前 Python 侧根本没读）。"""
    comp = _bare_companion(settings={"proactive": {"primary_channel": "desktop"}})
    comp._recent_inbound = (DeliveryContext(channel="qq", user_id=1), time.time())
    assert comp._proactive_delivery_channel() == "local_chat"


# ── 主动发图的投递集合：所有已连接端 + 桌面（用户 2026-09-28 拍板） ────────


def _image_channel_companion(*, qq_online: bool, ilink_target: str) -> Companion:
    comp = _bare_companion()
    comp.qq = SimpleNamespace(is_logged_in=qq_online)
    comp.ilink_gateway = SimpleNamespace(
        get_status=lambda: {"connected": bool(ilink_target)},
        bound_user_id=lambda: ilink_target,
    )
    return comp


def test_proactive_image_channels_fan_out_to_all_connected_ports():
    comp = _image_channel_companion(qq_online=True, ilink_target="wx-owner")
    assert comp._proactive_image_channels() == ["qq", "ilink", "local_chat"]


def test_proactive_image_channels_keeps_desktop_when_only_one_port_is_live():
    qq_only = _image_channel_companion(qq_online=True, ilink_target="")
    assert qq_only._proactive_image_channels() == ["qq", "local_chat"]

    wechat_only = _image_channel_companion(qq_online=False, ilink_target="wx-owner")
    assert wechat_only._proactive_image_channels() == ["ilink", "local_chat"]


def test_proactive_image_channels_falls_back_to_desktop_alone():
    """两端都不在线时仍要投桌面端：它是这张图的唯一历史记录。"""
    comp = _image_channel_companion(qq_online=False, ilink_target="")
    assert comp._proactive_image_channels() == ["local_chat"]


# ── 文件投递回到来源端口（验收 1/2/3/4） ──────────────────────────────


def _deliver_with_origin(comp, channel, *, user_id=7, account="", path="x.docx"):
    token = dr.bind(DeliveryContext(channel=channel, user_id=user_id, channel_account_id=account))
    try:
        return comp._notify_file_delivery({"path": path, "note": "给你"})
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


def test_desktop_request_delivers_file_into_local_chat(tmp_path, monkeypatch):
    """桌面端要文件 → 真的变成一张可打开的卡片（§十四 #72 / 开放例外 E6）。

    桌面端没有原生收文件通道（`SendQueue` 只有 qq / ilink），但复用了生成图那条
    成熟链路：文件发布到 uploads + 落一条带 attachments 的 assistant 聊天记录。
    旧实现在这里是**静默丢件**（入队后取 `channel_senders["local_chat"]` 直接
    KeyError），所以这条用例锁定"不再丢件"。
    """
    from core import chat_events, outbound_files
    from core.delivery_ledger import get_ledger

    ledger = get_ledger()
    ledger.clear()
    monkeypatch.setattr(outbound_files, "_uploads_dir", lambda: tmp_path / "uploads")
    doc = tmp_path / "报告.txt"
    doc.write_text("hello", encoding="utf-8")

    emitted: list[dict] = []
    monkeypatch.setattr(chat_events, "emit", lambda *a, **k: emitted.append(k))

    comp = _bare_companion()
    delivery_id = _deliver_with_origin(comp, "local_chat", path=str(doc))

    assert delivery_id, "桌面端投递必须返回回执 id，调用方才等得到真实结局"
    assert comp.queue.sent == [], "桌面端不走发送队列（队列里没有它的发送器）"

    receipt = ledger.get(delivery_id)
    assert receipt is not None and receipt.ok is True

    assert emitted, "必须推一条 SSE，前端才会渲染卡片"
    attachments = emitted[0].get("attachments") or []
    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment["category"] == "file"
    assert attachment["state"] == "ready"          # 前端据此渲染「打开」
    assert attachment["name"] == "报告.txt"          # 用户看到原名，不是 uuid
    assert attachment["url"].startswith("/uploads/")

    # 文件必须真的躺在 uploads 里（否则卡片上的「打开」是死链）
    stored = tmp_path / "uploads" / attachment["url"].removeprefix("/uploads/")
    assert stored.is_file()
    assert stored.read_text(encoding="utf-8") == "hello"

    ledger.clear()


def test_desktop_delivery_reports_failure_when_publish_fails(monkeypatch):
    """发布到 uploads 失败 → 回执必须是失败，不能谎报送达。"""
    from core import outbound_files
    from core.delivery_ledger import get_ledger

    ledger = get_ledger()
    ledger.clear()
    monkeypatch.setattr(outbound_files, "publish_to_uploads", lambda _p: None)

    comp = _bare_companion()
    delivery_id = _deliver_with_origin(comp, "local_chat", path=__file__)

    receipt = ledger.get(delivery_id)
    assert receipt is not None
    assert receipt.ok is False
    assert "uploads" in receipt.detail

    ledger.clear()


def test_interleaved_requests_go_to_their_own_ports(tmp_path, monkeypatch):
    """先微信、后桌面各要一次 → 两次分别回到各自端口（证明不是全局状态）。"""
    from core import chat_events, outbound_files
    from core.delivery_ledger import get_ledger

    ledger = get_ledger()
    ledger.clear()
    monkeypatch.setattr(chat_events, "emit", lambda *a, **k: None)
    monkeypatch.setattr(outbound_files, "_uploads_dir", lambda: tmp_path / "uploads")
    doc = tmp_path / "b.docx"
    doc.write_text("x", encoding="utf-8")

    comp = _bare_companion()
    _deliver_with_origin(comp, "ilink", account="acc-1", path="a.docx")
    desktop_id = _deliver_with_origin(comp, "local_chat", path=str(doc))

    # 微信那次走队列；桌面那次走 uploads 链路，两边互不干扰。
    assert [r.channel for r in comp.queue.sent] == ["ilink"]
    assert [r.file_paths[0] for r in comp.queue.sent] == ["a.docx"]

    # 桌面端的回执当场落定（微信那条仍在队列里等 worker，测试环境没有 worker）。
    desktop_receipt = ledger.get(desktop_id)
    assert desktop_receipt is not None and desktop_receipt.ok is True

    ledger.clear()


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

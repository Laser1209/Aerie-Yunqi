"""投递失败回灌模型（P0-2）。

**背景**

文件投递是异步入队的：工具返回 ``status="queued"``，真正的发送发生在发送队列
worker 里。历史上失败只进日志，不回写模型 —— 模型没有渠道知道失败，下一轮
照旧宣称"已经发给你了"（实测 2026-09-28 三端一致的假成功）。

本测试锁定：失败必须落成回执，并在**下一轮**注入系统提示。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from core.delivery_ledger import (
    PENDING_GRACE_SECONDS,
    DeliveryLedger,
    build_feedback_note,
    describe_failure,
)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """隔离台账单例，避免跨测试污染。"""
    import core.delivery_ledger as mod

    fresh = DeliveryLedger()
    monkeypatch.setattr(mod, "_LEDGER", fresh)
    return fresh


# ── 台账基本语义 ─────────────────────────────────────────────────────────


def test_failure_is_reported_once(ledger):
    did = ledger.record_pending(user_id=7, channel="ilink", path=r"D:\a\报告.pptx")
    ledger.record_outcome(did, ok=False, detail="上传超时")

    first = ledger.drain_unreported(7)
    assert len(first) == 1
    assert first[0].ok is False
    assert "报告.pptx" in first[0].to_prompt_line()
    assert "上传超时" in first[0].to_prompt_line()

    # 已上报的不再重复打扰
    assert ledger.drain_unreported(7) == []


def test_success_is_not_reported(ledger):
    """成功无需打扰模型 —— 它已经说过"我发过去了"。"""
    did = ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\ok.pdf")
    ledger.record_outcome(did, ok=True)

    assert ledger.drain_unreported(7) == []


def test_pending_within_grace_is_held_back(ledger):
    """刚入队还没到能下结论的时间：留到下一轮再看，别急着说失败。"""
    ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\x.pdf")

    assert ledger.drain_unreported(7) == []
    assert ledger.pending_count(7) == 1


def test_pending_beyond_grace_reports_uncertainty(ledger):
    """长时间未决必须如实说"不确定"，而不是沉默、也不是替它断言成功。"""
    did = ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\slow.pdf")
    ledger.record_outcome(did, ok=False, detail="")  # 先落定，再改回未决
    receipt = ledger._index[did]
    receipt.ok = None
    receipt.created_at = time.time() - PENDING_GRACE_SECONDS - 1

    out = ledger.drain_unreported(7)
    assert len(out) == 1
    line = out[0].to_prompt_line()
    assert "结果未知" in line
    assert "不要断言已送达" in line


def test_users_are_isolated(ledger):
    did = ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\x.pdf")
    ledger.record_outcome(did, ok=False, detail="失败")

    assert ledger.drain_unreported(8) == []
    assert len(ledger.drain_unreported(7)) == 1


def test_unknown_target_bucket_is_surfaced(ledger):
    """入队时无法定位接收方（user_id=0）同样意味着没发出去，必须说出来。"""
    did = ledger.record_pending(user_id=0, channel="", path=r"D:\a\orphan.pdf")
    ledger.record_outcome(did, ok=False, detail="无可用会话通道")

    out = ledger.drain_unreported(7)
    assert len(out) == 1
    assert "orphan.pdf" in out[0].to_prompt_line()


def test_unknown_delivery_id_is_ignored(ledger):
    ledger.record_outcome("dlv_nope", ok=False, detail="x")  # 不应抛异常
    assert ledger.pending_count() == 0


def test_bucket_is_bounded(ledger):
    """长期运行不得无界增长。"""
    for i in range(40):
        ledger.record_pending(user_id=7, channel="qq", path=f"D:\\a\\{i}.pdf")
    assert ledger.pending_count(7) <= 20


def test_channel_is_rendered_in_chinese(ledger):
    for channel, expected in (("qq", "QQ"), ("ilink", "微信"), ("local_chat", "桌面端")):
        did = ledger.record_pending(user_id=1, channel=channel, path=r"D:\a\f.pdf")
        ledger.record_outcome(did, ok=False, detail="x")
        line = ledger.drain_unreported(1)[0].to_prompt_line()
        assert expected in line


# ── 提示词片段 ───────────────────────────────────────────────────────────


def test_build_feedback_note_empty_when_nothing_to_report(ledger):
    assert build_feedback_note(7) == ""


def test_build_feedback_note_prefix_and_content(ledger):
    did = ledger.record_pending(user_id=7, channel="ilink", path=r"D:\a\报告.pptx")
    ledger.record_outcome(did, ok=False, detail="上传读超时")

    note = build_feedback_note(7)
    assert note.startswith("[投递回执] ")
    assert "报告.pptx" in note
    assert "上传读超时" in note
    # 明确要求别再说已送达
    assert "不要再说已经发过去了" in note


def test_build_feedback_note_never_raises(monkeypatch):
    import core.delivery_ledger as mod

    class _Boom:
        def drain_unreported(self, user_id):  # noqa: ARG002
            raise RuntimeError("boom")

    monkeypatch.setattr(mod, "_LEDGER", _Boom())
    assert build_feedback_note(7) == ""


# ── 异常收敛 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc,expected",
    [
        (TimeoutError("read timed out"), "上传超时"),
        (RuntimeError("httpx.ReadTimeout: "), "上传读超时"),
        (RuntimeError("HTTP 401 unauthorized"), "鉴权失败"),
        (RuntimeError("connection reset by peer"), "网络不可达"),
        (RuntimeError(""), "原因未知"),
    ],
)
def test_describe_failure_maps_to_readable_reason(exc, expected):
    assert describe_failure(exc) == expected


# ── 端到端：失败经发送路径回灌到下一轮上下文 ─────────────────────────────


@pytest.mark.asyncio
async def test_ilink_failure_records_receipt(ledger):
    """微信发文件抛异常 → 必须落失败回执（此前只进日志）。"""
    from core.companion import Companion

    class _Gateway:
        async def send_text(self, account, content):  # noqa: ARG002
            return True

        async def send_file(self, account, path):  # noqa: ARG002
            raise RuntimeError("httpx.ReadTimeout: upload")

    comp = object.__new__(Companion)
    comp.ilink_gateway = _Gateway()

    delivery_id = ledger.record_pending(
        user_id=7, channel="ilink", path=r"D:\a\报告.pptx",
    )
    reply = SimpleNamespace(
        user_id=7,
        content="给你",
        channel="ilink",
        channel_account_id="wx-1",
        file_paths=[r"D:\a\报告.pptx"],
        context={"deliveries": [{"delivery_id": delivery_id, "path": r"D:\a\报告.pptx"}]},
    )

    await Companion._send_to_ilink(comp, reply)

    out = ledger.drain_unreported(7)
    assert len(out) == 1
    assert out[0].ok is False
    assert "上传读超时" in out[0].detail


@pytest.mark.asyncio
async def test_qq_success_records_ok_receipt(ledger):
    from core.companion import Companion

    class _QQ:
        async def send_message(self, user_id, content):  # noqa: ARG002
            return True

        async def send_file(self, user_id, path):  # noqa: ARG002
            return True

    comp = object.__new__(Companion)
    comp.qq = _QQ()

    delivery_id = ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\ok.pdf")
    reply = SimpleNamespace(
        user_id=7,
        content="给你",
        channel="qq",
        channel_account_id="",
        file_paths=[r"D:\a\ok.pdf"],
        context={"deliveries": [{"delivery_id": delivery_id, "path": r"D:\a\ok.pdf"}]},
    )

    await Companion._send_to_qq(comp, reply)

    # 成功：不回执给模型
    assert ledger.drain_unreported(7) == []
    assert ledger._index[delivery_id].ok is True


@pytest.mark.asyncio
async def test_qq_platform_negative_records_failure(ledger):
    """平台返回 False（未确认送达）也算失败，不能当成功。"""
    from core.companion import Companion

    class _QQ:
        async def send_message(self, user_id, content):  # noqa: ARG002
            return True

        async def send_file(self, user_id, path):  # noqa: ARG002
            return False

    comp = object.__new__(Companion)
    comp.qq = _QQ()

    delivery_id = ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\x.pdf")
    reply = SimpleNamespace(
        user_id=7, content="", channel="qq", channel_account_id="",
        file_paths=[r"D:\a\x.pdf"],
        context={"deliveries": [{"delivery_id": delivery_id, "path": r"D:\a\x.pdf"}]},
    )

    await Companion._send_to_qq(comp, reply)

    out = ledger.drain_unreported(7)
    assert len(out) == 1 and out[0].ok is False

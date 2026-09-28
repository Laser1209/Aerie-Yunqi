"""完成态措辞守卫（P1-3）。

**背景（实测 2026-09-28 桌面端）**

工具只调了 ``directory_list``（**没有任何投递动作**），Agent 却回复
"找到了…"、"刚才可能没发过去 这次应该好了"、"喏 给你" —— 用户什么都没收到。

这不是话题审查（``response_validator`` 的内容解放策略仍然有效），
而是**助手对自己行为的陈述是否属实**。
"""
from __future__ import annotations

import pytest

from core.completion_claim_guard import (
    find_completion_claims,
    guard_completion_claims,
    had_delivery_action,
    rewrite_completion_claims,
)


@pytest.fixture(autouse=True)
def _fresh_ledger(monkeypatch):
    """隔离台账，避免其他测试留下的成功回执让守卫放行。"""
    import core.delivery_ledger as mod

    monkeypatch.setattr(mod, "_LEDGER", mod.DeliveryLedger())


# ── 实测现场的原始三句 ───────────────────────────────────────────────────


def test_real_incident_texts_are_rewritten():
    """复现 2026-09-28 桌面端那三句：本轮无投递动作，全部应被改写。"""
    for text in ("喏 给你", "刚才可能没发过去 这次应该好了", "已经发给你了"):
        out, audit = guard_completion_claims(text, tool_results=[], user_id=7)
        assert audit.get("claims"), f"应命中完成态措辞: {text}"
        assert out != text
        assert audit["reason"] == "no_delivery_action_this_turn"


def test_rewrite_keeps_meaning_and_gives_no_false_promise():
    out, _ = guard_completion_claims("喏 给你", tool_results=[], user_id=7)
    # 不能说"给你了"，但也不能反向承诺"已发送"
    assert "给你" in out or "怎么给" in out
    assert out == "我看看怎么给你"


# ── 不误伤 ───────────────────────────────────────────────────────────────


def test_question_is_not_a_claim():
    """"你收到了吗？" 是询问，不是声称。"""
    out, audit = guard_completion_claims("你收到了吗？", tool_results=[], user_id=7)
    assert out == "你收到了吗？"
    assert not audit.get("claims")


def test_plain_chat_is_untouched():
    for text in ("我给你讲个事", "今天天气不错", "我这就发给你", "我先看看怎么弄"):
        out, audit = guard_completion_claims(text, tool_results=[], user_id=7)
        assert out == text, f"不该改写下述文本: {text}"
        assert not audit.get("claims")


def test_empty_text_is_safe():
    assert guard_completion_claims("", tool_results=[], user_id=7)[0] == ""


# ── 本轮确实投递过 → 放行 ────────────────────────────────────────────────


def test_queued_delivery_action_allows_claim():
    """工具返回 queued 表示"确实在发"，此时"我发过去了"是诚实的。"""
    tool_results = [{"name": "send_file_to_user", "result": {"status": "queued"}}]
    out, audit = guard_completion_claims("已经发给你了", tool_results=tool_results, user_id=7)
    assert out == "已经发给你了"
    assert audit["allowed"] == "turn_had_delivery_action"


def test_failed_delivery_action_does_not_allow_claim():
    """投递失败不算"发得出去"——更不该据此宣称已送达。"""
    tool_results = [{
        "name": "send_file_to_user",
        "result": {"success": False, "error": "路径越界"},
    }]
    out, audit = guard_completion_claims("已经发给你了", tool_results=tool_results, user_id=7)
    assert out != "已经发给你了"
    assert audit.get("claims")


def test_unrelated_tool_does_not_allow_claim():
    """只调了 directory_list（实测现场）→ 不构成投递动作。"""
    tool_results = [{"name": "directory_list", "result": {"files": ["a.pptx"]}}]
    out, _ = guard_completion_claims("喏 给你", tool_results=tool_results, user_id=7)
    assert out == "我看看怎么给你"


def test_legacy_queued_flag_is_recognized():
    tool_results = [{"name": "send_file_to_user", "result": {"success": True, "queued": True}}]
    assert had_delivery_action(tool_results) is True


def test_had_delivery_action_handles_garbage():
    assert had_delivery_action(None) is False
    assert had_delivery_action([None, "x", 1]) is False
    assert had_delivery_action([{"name": "send_file_to_user"}]) is False


# ── 台账状态也参与判据 ───────────────────────────────────────────────────


def test_in_flight_delivery_allows_claim():
    """台账里有在途投递 → 放行（确实发了，只是还没结果）。"""
    from core.delivery_ledger import get_ledger

    get_ledger().record_pending(user_id=7, channel="qq", path=r"D:\a\x.pdf")
    out, audit = guard_completion_claims("已经发给你了", tool_results=[], user_id=7)
    assert out == "已经发给你了"
    assert audit["allowed"] == "delivery_in_flight"


def test_recent_success_allows_claim():
    from core.delivery_ledger import get_ledger

    ledger = get_ledger()
    did = ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\x.pdf")
    ledger.record_outcome(did, ok=True)
    out, audit = guard_completion_claims("喏 给你", tool_results=[], user_id=7)
    assert out == "喏 给你"
    assert audit["allowed"] == "recent_delivery_succeeded"


def test_failed_delivery_does_not_allow_claim_in_ledger():
    from core.delivery_ledger import get_ledger

    ledger = get_ledger()
    did = ledger.record_pending(user_id=7, channel="qq", path=r"D:\a\x.pdf")
    ledger.record_outcome(did, ok=False, detail="上传超时")
    out, audit = guard_completion_claims("已经发给你了", tool_results=[], user_id=7)
    assert out != "已经发给你了"
    assert audit.get("claims")


# ── 改写质量 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("已经发给你了", "我这就发给你"),
        ("已经发过去了", "我这就发过去"),
        ("发你了，看看", "我这就发给你，看看"),
        ("你应该收到了吧", "你那边能收到吗"),
        ("刚才可能没发过去 这次应该好了", "我确认一下发出去没"),
        ("喏 给你", "我看看怎么给你"),
    ],
)
def test_rewrite_outputs_are_natural(text, expected):
    """改写必须吃掉整段措辞（含尾随 了/吧），否则拼出"能收到吗吧"这类语病。"""
    assert rewrite_completion_claims(text)[0] == expected


def test_rewrite_preserves_surrounding_text():
    out, hits = rewrite_completion_claims("文件已经发过去了，你看看")
    assert out == "文件我这就发过去，你看看"
    assert hits


def test_rewrite_does_not_compound():
    """多模式串行替换不得互相吃掉产生乱码。"""
    out, _ = rewrite_completion_claims("已经发给你了")
    assert out == "我这就发给你"
    assert "已经" not in out


def test_multiline_question_line_is_exempt():
    """逐行处理：问句行豁免，同一段里的声称行仍改写。"""
    text = "你收到了吗？\n已经发给你了"
    out, audit = guard_completion_claims(text, tool_results=[], user_id=7)
    assert "你收到了吗？" in out
    assert "已经发给你了" not in out


def test_find_claims_reports_matches():
    assert find_completion_claims("喏 给你") == ["喏 给你"]
    assert find_completion_claims("你收到了吗？") == []


def test_guard_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AERIE_COMPLETION_CLAIM_GUARD", "false")
    out, audit = guard_completion_claims("喏 给你", tool_results=[], user_id=7)
    assert out == "喏 给你"
    assert audit["skipped"] == "disabled"


def test_guard_never_raises_on_ledger_failure(monkeypatch):
    import core.delivery_ledger as mod

    class _Boom:
        def has_pending(self, user_id):  # noqa: ARG002
            raise RuntimeError("boom")

        def has_recent_success(self, user_id, **kw):  # noqa: ARG002
            raise RuntimeError("boom")

    monkeypatch.setattr(mod, "get_ledger", lambda: _Boom())
    out, audit = guard_completion_claims("喏 给你", tool_results=[], user_id=7)
    # 台账读不到不该阻断守卫本身
    assert out == "我看看怎么给你"

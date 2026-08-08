"""Tests for RecallJudge (Gate 5): 撤回判断联动三分支."""

import pytest

from core.message_orchestrator import RecallDecision, RecallJudge


class _FakeRecallManager:
    """Stub recall_manager exposing can_recall / try_recall."""

    def __init__(self, can: bool = True, why: str = "ok") -> None:
        self.can = can
        self.why = why
        self.try_recall_calls: list[dict] = []

    def can_recall(self, user_id, *, channel="qq", channel_account_id=None):
        return self.can, self.why

    async def try_recall(self, user_id, reason="manual", *, channel="qq", channel_account_id=None):
        self.try_recall_calls.append(
            {"user_id": user_id, "reason": reason, "channel": channel}
        )
        return {"status": "ok"}


class TestRecallJudge:
    def _judge(self, rm) -> RecallJudge:
        return RecallJudge(rm)

    def test_correction_message_recalls_prev(self):
        rm = _FakeRecallManager(can=True)
        judge = self._judge(rm)
        d = judge.should_recall_prev(
            prev_reply="好的",
            new_msg="不对，我说错了",
            channel="qq",
            channel_account_id="1",
            user_id=1,
        )
        assert isinstance(d, RecallDecision)
        assert d.recall is True
        assert d.reason == "user_correction"

    def test_normal_message_does_not_recall(self):
        rm = _FakeRecallManager(can=True)
        judge = self._judge(rm)
        d = judge.should_recall_prev(
            prev_reply="好的",
            new_msg="继续聊啊",
            channel="qq",
            channel_account_id="1",
            user_id=1,
        )
        assert d.recall is False
        assert d.reason == "no_op"

    def test_budget_exhausted_no_recall(self):
        rm = _FakeRecallManager(can=False, why="session_limit")
        judge = self._judge(rm)
        d = judge.should_recall_prev(
            prev_reply="好的",
            new_msg="不对，重说",
            channel="qq",
            channel_account_id="1",
            user_id=1,
        )
        assert d.recall is False
        assert d.reason == "session_limit"

    def test_window_expired_no_recall(self):
        rm = _FakeRecallManager(can=False, why="window_expired")
        judge = self._judge(rm)
        d = judge.should_recall_prev(
            prev_reply="好的",
            new_msg="说错了，撤回",
            channel="qq",
            channel_account_id="1",
            user_id=1,
        )
        assert d.recall is False
        assert d.reason == "window_expired"

    def test_no_manager_no_recall(self):
        judge = RecallJudge(None)
        d = judge.should_recall_prev(
            prev_reply="好的",
            new_msg="不对",
            channel="qq",
            channel_account_id="1",
            user_id=1,
        )
        assert d.recall is False
        assert d.reason == "no_manager"

    def test_custom_correction_keywords(self):
        rm = _FakeRecallManager(can=True)
        judge = RecallJudge(rm, correction_keywords=("打住",))
        # 默认关键词不含 "打住", 但自定义后应命中
        d = judge.should_recall_prev(
            prev_reply="好的",
            new_msg="打住",
            channel="qq",
            channel_account_id="1",
            user_id=1,
        )
        assert d.recall is True

    def test_keyword_not_in_default_does_not_recall(self):
        rm = _FakeRecallManager(can=True)
        judge = self._judge(rm)
        d = judge.should_recall_prev(
            prev_reply="好的",
            new_msg="打住",
            channel="qq",
            channel_account_id="1",
            user_id=1,
        )
        assert d.recall is False

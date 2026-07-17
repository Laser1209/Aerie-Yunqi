"""Aerie · 云栖 v9.0 — Phase 4 Recall tests."""
import asyncio
import time
from communication.recall_manager import RecallManager, RecallConfig


class TestRecallManagerBasics:
    def test_record_and_can_recall(self):
        rm = RecallManager(config=RecallConfig(window_seconds=120, min_recall_gap_seconds=60, max_recalls_per_session=5))
        rm.record_sent(1, "hello", msg_id=100)
        can, why = rm.can_recall(1)
        assert can is True
        assert why == "ok"

    def test_cannot_recall_when_disabled(self):
        rm = RecallManager(config=RecallConfig(enabled=False, window_seconds=120))
        rm.record_sent(1, "hi")
        can, why = rm.can_recall(1)
        assert can is False
        assert why == "disabled"

    def test_cannot_recall_no_message(self):
        rm = RecallManager(config=RecallConfig())
        can, why = rm.can_recall(999)
        assert can is False
        assert why == "no_recent_message"

    def test_cannot_recall_outside_window(self):
        rm = RecallManager(config=RecallConfig(window_seconds=10))
        rm.record_sent(1, "hi")
        time.sleep(0.05)
        # force old timestamp
        rm._last_sent[1].timestamp -= 30
        can, why = rm.can_recall(1)
        assert can is False
        assert why == "window_expired"

    def test_session_limit_enforced(self):
        rm = RecallManager(config=RecallConfig(window_seconds=120, min_recall_gap_seconds=0, max_recalls_per_session=2))
        rm.record_sent(1, "hi")
        rm._session_recall_count[1] = 2
        can, why = rm.can_recall(1)
        assert can is False
        assert why == "session_limit"

    def test_min_gap_cooldown(self):
        rm = RecallManager(config=RecallConfig(window_seconds=120, min_recall_gap_seconds=60, max_recalls_per_session=5))
        rm.record_sent(1, "hi")
        rm._last_recall_at[1] = time.time()
        can, why = rm.can_recall(1)
        assert can is False
        assert why == "cooldown"

    def test_reset_session_clears_count(self):
        rm = RecallManager(config=RecallConfig())
        rm._session_recall_count[1] = 3
        rm.reset_session(1)
        assert rm._session_recall_count[1] == 0


class TestRecallManagerAsync:
    def test_try_recall_skipped_no_message(self):
        rm = RecallManager(config=RecallConfig())
        result = asyncio.run(rm.try_recall(1))
        assert result["status"] == "skipped"
        assert result["reason"] == "no_recent_message"

    def test_try_recall_ok(self):
        rm = RecallManager(config=RecallConfig(window_seconds=120, min_recall_gap_seconds=0, max_recalls_per_session=5))
        rm.record_sent(1, "hi", msg_id=42)
        result = asyncio.run(rm.try_recall(1, reason="manual"))
        assert result["status"] == "ok"
        assert result["msg_id"] == 42
        assert result["reason"] == "manual"

    def test_handle_user_negative_keywords(self):
        rm = RecallManager(config=RecallConfig(window_seconds=120, min_recall_gap_seconds=0, max_recalls_per_session=5))
        rm.record_sent(1, "test")
        triggered = asyncio.run(rm.handle_user_negative(1, "别说了"))
        assert triggered is True

    def test_handle_user_negative_no_match(self):
        rm = RecallManager(config=RecallConfig())
        rm.record_sent(1, "test")
        triggered = asyncio.run(rm.handle_user_negative(1, "继续说"))
        assert triggered is False

    def test_attach_qq_message_id(self):
        rm = RecallManager(config=RecallConfig())
        rm.record_sent(1, "hi")
        rm.attach_qq_message_id(1, 99999)
        assert rm._last_sent[1].qq_message_id == 99999

    def test_record_sent_with_segments(self):
        rm = RecallManager(config=RecallConfig())
        rm.record_sent(1, "x", msg_id=1, segments=["x", "y", "z"])
        assert rm._last_sent[1].segments == ["x", "y", "z"]
        assert rm._last_sent[1].msg_id == 1

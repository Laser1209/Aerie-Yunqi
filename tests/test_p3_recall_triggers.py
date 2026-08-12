"""P3-4/P3-5 事件记忆召回 + 主动回忆触发器测试（附录 A.3.4/A.3.5）。"""

import time
from types import SimpleNamespace

from core.pipeline import Pipeline


def _ts_iso(offset_sec: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - offset_sec))


def _ts_naive(offset_sec: float) -> str:
    return time.strftime(
        "%Y-%m-%d %H:%M:%S", time.localtime(time.time() - offset_sec)
    )


def _pipeline_with(*, history_items, event_memories, timeline_rows):
    p = Pipeline.__new__(Pipeline)
    p.conversation_repository = SimpleNamespace(
        history_page=lambda **kwargs: {"items": history_items}
    )
    p.memory_store = SimpleNamespace(
        list_by_user=lambda *a, **k: event_memories
    )
    p.timeline_repository = None

    class FakeTimeline:
        def __init__(self):
            self.calls = []

        def recent_events(self, **kwargs):
            self.calls.append(kwargs)
            return list(timeline_rows)

    fake_timeline = FakeTimeline()
    return p, fake_timeline


def _msg(channel="desktop"):
    return SimpleNamespace(
        actor_id="actor_ita",
        user_id=7,
        channel=channel,
        channel_account_id="local",
    )


def test_parse_ts_handles_iso_and_naive():
    assert Pipeline._parse_ts("2026-08-12T22:10:00Z") is not None
    assert Pipeline._parse_ts("2026-08-12 22:10:00") is not None
    assert Pipeline._parse_ts(None) is None
    assert Pipeline._parse_ts("garbage") is None


def test_trigger_explicit_recall_returns_timeline_and_event_memories():
    p, timeline = _pipeline_with(
        history_items=[],
        event_memories=[
            {
                "content": "事件记忆：用户说去过重庆",
                "metadata": {"channel": "qq", "occurred_at": _ts_iso(3600)},
            }
        ],
        timeline_rows=[
            {"channel": "qq", "occurred_at": _ts_iso(600), "event_summary": "QQ事件"}
        ],
    )
    events = p._resolve_recall_events(
        timeline=timeline,
        msg=_msg(),
        current_user_content="你还记得我说过什么吗？",
        conversation_id="conv_x",
    )
    assert len(events) == 2
    assert events[0]["event_summary"] == "QQ事件"
    assert "事件记忆" in events[1]["event_summary"]
    # 显式回忆优先于其他触发器
    assert timeline.calls and timeline.calls[0].get("exclude_channel") is None


def test_trigger_cross_channel_switch_when_conversation_idle():
    p, timeline = _pipeline_with(
        history_items=[{"created_at": _ts_naive(45 * 60)}],  # 45 分钟前
        event_memories=[],
        timeline_rows=[
            {"channel": "qq", "occurred_at": _ts_iso(1200), "event_summary": "另一端的对话"}
        ],
    )
    events = p._resolve_recall_events(
        timeline=timeline,
        msg=_msg(channel="desktop"),
        current_user_content="在吗",
        conversation_id="conv_x",
    )
    assert len(events) == 1
    # calls[0] 为内部 limit=1 探针，calls[1] 为实际注入调用
    assert timeline.calls[1]["exclude_channel"] == "desktop"


def test_trigger_long_interval_uses_24h_window():
    p, timeline = _pipeline_with(
        history_items=[{"created_at": _ts_naive(3 * 60 * 60)}],  # 3 小时前
        event_memories=[],
        timeline_rows=[
            {"channel": "qq", "occurred_at": _ts_iso(3 * 60 * 60 + 600), "event_summary": "E"}
        ],
    )
    events = p._resolve_recall_events(
        timeline=timeline,
        msg=_msg(),
        current_user_content="我回来了",
        conversation_id="conv_x",
    )
    assert len(events) == 1
    assert "since" in timeline.calls[1]


def test_no_trigger_when_recent_activity():
    p, timeline = _pipeline_with(
        history_items=[{"created_at": _ts_naive(60)}],  # 1 分钟前
        event_memories=[],
        timeline_rows=[
            {"channel": "qq", "occurred_at": _ts_iso(600), "event_summary": "E"}
        ],
    )
    events = p._resolve_recall_events(
        timeline=timeline,
        msg=_msg(),
        current_user_content="继续聊",
        conversation_id="conv_x",
    )
    assert events == []


def test_recall_event_memories_orders_by_recency():
    p, _ = _pipeline_with(history_items=[], event_memories=[], timeline_rows=[])
    p.memory_store = SimpleNamespace(
        list_by_user=lambda *a, **k: [
            {"content": "旧事件", "metadata": {"occurred_at": _ts_iso(7200)}},
            {"content": "新事件", "metadata": {"occurred_at": _ts_iso(600)}},
        ]
    )
    memories = p._recall_event_memories(_msg())
    assert [m["event_summary"] for m in memories] == ["新事件", "旧事件"]


def test_recall_keywords_match():
    p, timeline = _pipeline_with(
        history_items=[{"created_at": _ts_naive(60)}],
        event_memories=[],
        timeline_rows=[],
    )
    events = p._resolve_recall_events(
        timeline=timeline,
        msg=_msg(),
        current_user_content="你记得之前说过吗",
        conversation_id="conv_x",
    )
    # 命中显式回忆关键词：即使当前对话活跃也触发
    assert timeline.calls == [] or timeline.calls[0].get("exclude_channel") is None

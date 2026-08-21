"""P4a stats service tests — 数据统计看板聚合."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.stats_service import StatsService


def _fake_db(rows):
    return SimpleNamespace(query=lambda sql, params=(): list(rows))


def _fake_db_by_query(message_rows=None, token_rows=None):
    def query(sql, params=()):
        if "FROM messages" in sql:
            return list(message_rows or [])
        return list(token_rows or [])

    return SimpleNamespace(query=query)


class TestStatsService:
    def test_daily_token_series(self):
        db = _fake_db(
            [
                {"d": "2026-08-12", "tokens": 1200, "calls": 3},
                {"d": "2026-08-13", "tokens": 800, "calls": 2},
            ]
        )
        svc = StatsService(db=db)
        series = svc.daily_token_series(days=7)
        assert len(series) == 2
        assert series[0]["date"] == "2026-08-12"
        assert series[0]["total_tokens"] == 1200

    def test_token_by_provider(self):
        db = _fake_db(
            [
                {"provider": "deepseek", "tokens": 5000},
                {"provider": "siliconflow", "tokens": 3000},
            ]
        )
        svc = StatsService(db=db)
        by = svc.token_by_provider(days=7)
        assert by[0]["provider"] == "deepseek"

    def test_daily_message_series_counts_user_ai_and_total_messages(self):
        db = _fake_db_by_query(
            message_rows=[
                {"d": "2026-08-12", "user_messages": 4, "ai_messages": 6, "total_messages": 10},
                {"d": "2026-08-13", "user_messages": 2, "ai_messages": 3, "total_messages": 5},
            ]
        )
        svc = StatsService(db=db)
        series = svc.daily_message_series(days=365)
        assert series == [
            {"date": "2026-08-12", "user_messages": 4, "ai_messages": 6, "total_messages": 10},
            {"date": "2026-08-13", "user_messages": 2, "ai_messages": 3, "total_messages": 5},
        ]

    def test_top_topics_matches_categories(self):
        db = _fake_db(
            [
                {"content": "今天上班好累，项目又延期了"},
                {"content": "想你了，好久没见到你"},
                {"content": "周末去看了部电影很好看"},
                {"content": "今天天气下雨，记得带伞"},
            ]
        )
        svc = StatsService(db=db)
        top = svc.top_topics(limit=5)
        assert any(t["topic"] == "工作" for t in top)
        assert any(t["topic"] == "情感" for t in top)
        assert any(t["topic"] == "娱乐" for t in top)

    def test_decision_stats_from_log(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        path = log_dir / "decision_log_20260813.jsonl"
        entries = [
            {"event_id": "a", "ts": "2026-08-13T01:00:00", "kind": "topic_motive", "chosen": {}, "fallback": False},
            {"event_id": "b", "ts": "2026-08-13T02:00:00", "kind": "behavior", "chosen": {}, "fallback": False},
            {"event_id": "c", "ts": "2026-08-13T03:00:00", "kind": "movement", "chosen": {}, "fallback": True},
        ]
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        svc = StatsService(decision_log_dir=log_dir)
        stats = svc.decision_stats()
        assert stats["total"] == 3
        assert stats["fallback_count"] == 1
        assert stats["by_kind"]["behavior"] == 1
        assert stats["chosen_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_dashboard_assembles(self, tmp_path):
        db = _fake_db([])
        log_dir = tmp_path / "logs"
        svc = StatsService(db=db, decision_log_dir=log_dir)
        dash = svc.dashboard(window="7d")
        assert "tokens" in dash and "topics" in dash and "decisions" in dash
        assert "messages" in dash
        assert dash["decisions"]["total"] == 0

    def test_empty_db_safe(self):
        svc = StatsService(db=None)
        assert svc.daily_token_series() == []
        assert svc.daily_message_series() == []
        assert svc.top_topics() == []
        assert svc.decision_stats()["total"] == 0

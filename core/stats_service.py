"""Aerie · stats_service — 数据统计看板（P4 管理平台）.

- token 统计唯一真源 = token_usage 表（GROUP BY date，SQLite 直查）。
- 高频话题 = 类目词表匹配（复用 evolution_manager 类目），不引入分词库。
- 决策统计 = decision_log.jsonl（append-only）聚合。
所有查询 SQLite 直查毫秒级，不做服务端实时聚合表。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TOPIC_CATEGORIES: dict[str, tuple[str, ...]] = {
    "工作": ("工作", "上班", "加班", "项目", "会议", "汇报", "deadline", "任务", "同事", "老板"),
    "学习": ("学习", "读书", "看书", "课程", "考试", "研究", "论文", "知识", "技能"),
    "生活": ("生活", "日常", "吃饭", "睡觉", "休息", "周末", "旅行", "逛街", "做饭"),
    "情感": ("想你", "喜欢", "爱", "开心", "难过", "生气", "委屈", "感动", "温暖", "想念"),
    "健康": ("健康", "身体", "生病", "感冒", "失眠", "运动", "健身", "减肥", "饮食"),
    "技术": ("代码", "编程", "开发", "bug", "程序", "软件", "算法", "架构", "AI", "模型"),
    "娱乐": ("游戏", "电影", "剧", "音乐", "综艺", "小说", "动漫", "追剧", "直播"),
    "家庭": ("家人", "爸妈", "父母", "家里", "亲戚", "家庭", "孩子", "宠物"),
    "天气": ("天气", "下雨", "晴天", "热", "冷", "降温", "台风", "下雪"),
}


class StatsService:
    def __init__(self, db: Any = None, decision_log_dir: Optional[Path] = None) -> None:
        self._db = db
        self._decision_log_dir = Path(decision_log_dir) if decision_log_dir else None

    # ── token 日趋势（唯一真源 token_usage）────────────────
    def daily_token_series(self, days: int = 30) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        try:
            rows = self._db.query(
                "SELECT date(created_at) AS d, SUM(total_tokens) AS tokens, "
                "COUNT(*) AS calls FROM token_usage "
                "WHERE created_at >= date('now', ?) GROUP BY date(created_at) "
                "ORDER BY d",
                (f"-{int(days)} days",),
            )
            return [
                {
                    "date": str(r.get("d") or ""),
                    "total_tokens": int(r.get("tokens") or 0),
                    "calls": int(r.get("calls") or 0),
                }
                for r in (rows or [])
            ]
        except Exception:
            logger.debug("token daily series failed", exc_info=True)
            return []

    def token_by_provider(self, days: int = 30) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        try:
            rows = self._db.query(
                "SELECT provider, SUM(total_tokens) AS tokens FROM token_usage "
                "WHERE created_at >= date('now', ?) GROUP BY provider ORDER BY tokens DESC",
                (f"-{int(days)} days",),
            )
            return [
                {"provider": str(r.get("provider") or "unknown"), "total_tokens": int(r.get("tokens") or 0)}
                for r in (rows or [])
            ]
        except Exception:
            logger.debug("token by provider failed", exc_info=True)
            return []

    # ── 高频话题（类目词表匹配）─────────────────────────────
    def top_topics(self, limit: int = 5) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        try:
            rows = self._db.query(
                "SELECT content FROM messages WHERE role='user' ORDER BY id DESC LIMIT 2000"
            ) or self._db.query(
                "SELECT content FROM chat_log WHERE role='user' ORDER BY id DESC LIMIT 2000"
            )
            counts: dict[str, int] = {}
            for r in (rows or []):
                text = str(r.get("content") or "").lower()
                for cat, keywords in _TOPIC_CATEGORIES.items():
                    if any(kw in text for kw in keywords):
                        counts[cat] = counts.get(cat, 0) + 1
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
            return [{"topic": k, "count": v} for k, v in top]
        except Exception:
            logger.debug("top topics failed", exc_info=True)
            return []

    # ── 决策统计（decision_log）────────────────────────────
    def decision_stats(self) -> dict[str, Any]:
        entries = self._read_decision_log()
        if not entries:
            return {"total": 0, "chosen_rate": 0.0, "by_kind": {}, "recent": []}
        by_kind: dict[str, int] = {}
        for e in entries:
            kind = str(e.get("kind") or "unknown")
            by_kind[kind] = by_kind.get(kind, 0) + 1
        fallback = sum(1 for e in entries if e.get("fallback"))
        total = len(entries)
        return {
            "total": total,
            "chosen_rate": round((total - fallback) / total, 4) if total else 0.0,
            "fallback_count": fallback,
            "by_kind": by_kind,
            "recent": entries[:10],
        }

    def _read_decision_log(self, limit: int = 200) -> list[dict[str, Any]]:
        if self._decision_log_dir is None:
            return []
        out: list[dict[str, Any]] = []
        files = sorted(self._decision_log_dir.glob("decision_log_*.jsonl"))
        for path in files:
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except Exception:
                logger.debug("decision log read failed: %s", path.name, exc_info=True)
        out.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return out[:limit]

    def dashboard(self, window: str = "7d") -> dict[str, Any]:
        days = {"24h": 1, "7d": 7, "30d": 30}.get(str(window), 7)
        return {
            "tokens": {
                "daily_series": self.daily_token_series(days=days),
                "by_provider": self.token_by_provider(days=days),
            },
            "topics": {"top": self.top_topics(limit=5)},
            "decisions": self.decision_stats(),
        }

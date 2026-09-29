"""阶段 4 · 话题生命周期状态机测试.

构造「提起 → 沉寂 → 关键词再触发」时序（注入可控 now），断言：
- 状态迁移正确（active → dormant → dead）；
- 激活时返回的历史摘要非空；
- 未达阈值不发生迁移；
- 阈值热加载生效；
- dead 存根归档接线（persist_stub 有调用方）。
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Optional

import pytest

from core.topic_lifecycle import TopicLifecycle
from core.topic_tracker import TopicTracker

HOUR = 3600.0
DAY = 86400.0
T0 = 1_000_000.0


def _make(
    tmp_path: Path,
    t0: float = T0,
    *,
    config: Optional[str] = None,
    enabled_check=None,
    store_stub=None,
) -> TopicLifecycle:
    """构造隔离的状态机（tmp 状态文件 + 可选 tmp 配置 + 可控时钟）。"""
    config_path = tmp_path / "topic_lifecycle.yaml"
    if config is not None:
        config_path.write_text(config, encoding="utf-8")
    tracker = TopicTracker(
        state_path=tmp_path / "topic_state.json",
        clock=lambda: t0,
    )
    return TopicLifecycle(
        tracker=tracker,
        config_path=config_path,
        clock=lambda: t0,
        enabled_check=enabled_check,
        store_stub=store_stub,
    )


def test_default_thresholds_when_config_missing(tmp_path):
    """无配置文件的兜底默认：24 / 30 / 0.70 / 3 / 14。"""
    lifecycle = _make(tmp_path)
    config = lifecycle.config()
    assert config["dormant_after_hours"] == 24.0
    assert config["dead_after_days"] == 30.0
    assert config["similarity_threshold"] == 0.70
    assert config["demote_after_silent_turns"] == 3
    assert config["demote_after_inactive_days"] == 14.0


def test_active_to_dormant_to_dead(tmp_path):
    """提起 → 沉寂 → 超阈值迁移：active → dormant → dead。"""
    lifecycle = _make(tmp_path)
    lifecycle.observe({"text": "你最近看的那本书怎么样", "now": T0, "user_id": 1})
    topic = lifecycle.tracker.topics[0]
    assert topic.lifecycle == "active"
    assert topic.last_context == "你最近看的那本书怎么样"

    # 沉寂 25h（超 24h）：另一话题触发迁移评估 → dormant
    lifecycle.observe({"text": "今天天气不错", "now": T0 + 25 * HOUR, "user_id": 1})
    assert topic.lifecycle == "dormant"
    assert topic.dormancy_since is not None

    # 连续沉寂（推时间 + 空文本观察）→ 兴趣评分衰减
    lifecycle.observe({"text": "", "now": T0 + 26 * HOUR, "user_id": 1})
    lifecycle.observe({"text": "", "now": T0 + 27 * HOUR, "user_id": 1})
    assert topic.interest_score <= 1e-9

    # 超 30 天且兴趣归零 → dead
    lifecycle.observe({"text": "", "now": T0 + 31 * DAY, "user_id": 1})
    assert topic.lifecycle == "dead"


def test_activation_injects_history_summary(tmp_path):
    """沉寂话题被关键词再触发 → 迁回 active 并返回非空历史摘要。"""
    lifecycle = _make(tmp_path)
    lifecycle.observe({"text": "你最近看的那本书怎么样", "now": T0, "user_id": 1})
    lifecycle.observe({"text": "今天天气不错", "now": T0 + 25 * HOUR, "user_id": 1})
    dormant = [t for t in lifecycle.tracker.topics if t.lifecycle == "dormant"]
    assert dormant, "应先出现一个 dormant 话题"

    result = lifecycle.observe({"text": "那本书", "now": T0 + 26 * HOUR, "user_id": 1})
    assert result is not None
    assert result["activated"] is True
    assert result["summary"]  # 历史摘要非空
    assert "书" in result["summary"]
    assert dormant[0].lifecycle == "active"
    assert dormant[0].interest_score == 1.0


def test_no_transition_before_threshold(tmp_path):
    """未达阈值不发生迁移，且不相关的文本不激活沉寂话题。"""
    lifecycle = _make(tmp_path)
    lifecycle.observe({"text": "你最近看的那本书怎么样", "now": T0, "user_id": 1})
    topic = lifecycle.tracker.topics[0]

    # 23h 未达 24h → 仍 active
    lifecycle.observe({"text": "", "now": T0 + 23 * HOUR, "user_id": 1})
    assert topic.lifecycle == "active"

    # 25h 达阈值 → dormant
    lifecycle.observe({"text": "", "now": T0 + 25 * HOUR, "user_id": 1})
    assert topic.lifecycle == "dormant"

    # 不相关文本：相似度低于阈值 → 不激活
    result = lifecycle.observe(
        {"text": "完全无关的另一件事", "now": T0 + 25.5 * HOUR, "user_id": 1}
    )
    assert result is None
    assert topic.lifecycle == "dormant"


def test_config_hot_reload(tmp_path):
    """config/topic_lifecycle.yaml 改动后运行时生效（mtime 热加载）。"""
    config_path = tmp_path / "topic_lifecycle.yaml"
    config_path.write_text("dormant_after_hours: 1\n", encoding="utf-8")
    tracker = TopicTracker(state_path=tmp_path / "topic_state.json", clock=lambda: T0)
    lifecycle = TopicLifecycle(
        tracker=tracker, config_path=config_path, clock=lambda: T0
    )
    assert lifecycle.config()["dormant_after_hours"] == 1.0

    config_path.write_text("dormant_after_hours: 100\n", encoding="utf-8")
    bumped = time.time() + 5
    os.utime(config_path, (bumped, bumped))
    assert lifecycle.config()["dormant_after_hours"] == 100.0


def test_disabled_observe_is_noop(tmp_path):
    """开关关闭 → 观察空转，状态机不写盘。"""
    lifecycle = _make(tmp_path, enabled_check=lambda: False)
    result = lifecycle.observe({"text": "你最近看的那本书怎么样", "now": T0, "user_id": 1})
    assert result is None
    assert lifecycle.tracker.topics == []


def test_dead_topic_archives_stub(tmp_path):
    """dead 迁移接线 persist_stub：存根归档回调被调用。"""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def store(content: str, metadata: dict) -> str:
        captured.append((content, metadata))
        return "mem-1"

    lifecycle = _make(tmp_path, store_stub=store)

    async def run() -> None:
        lifecycle.observe({"text": "你最近看的那本书怎么样", "now": T0, "user_id": 1})
        lifecycle.observe({"text": "今天天气不错", "now": T0 + 25 * HOUR, "user_id": 1})
        lifecycle.observe({"text": "", "now": T0 + 26 * HOUR, "user_id": 1})
        lifecycle.observe({"text": "", "now": T0 + 27 * HOUR, "user_id": 1})
        lifecycle.observe({"text": "", "now": T0 + 31 * DAY, "user_id": 1})
        # 让 fire-and-forget 归档任务完成
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert captured, "dead 话题的存根应被归档到记忆库"
    assert captured[0][1]["kind"] == "topic_stub"


def test_lifecycle_fields_survive_roundtrip(tmp_path):
    """扩容字段随 topic_state.json 往返持久化（读取结构不变）。"""
    lifecycle = _make(tmp_path)
    lifecycle.observe({"text": "你最近看的那本书怎么样", "now": T0, "user_id": 1})
    lifecycle.observe({"text": "", "now": T0 + 25 * HOUR, "user_id": 1})

    reloaded = TopicTracker(
        state_path=tmp_path / "topic_state.json", clock=lambda: T0
    )
    assert reloaded.topics
    assert reloaded.topics[0].lifecycle == "dormant"
    assert reloaded.topics[0].last_context == "你最近看的那本书怎么样"


# ── 语义相似度：词法 + 向量 ─────────────────────────────

def _inject_embedding(monkeypatch, table: dict[str, list[float]]):
    """注入确定性 embedding，避免测试依赖真实 ONNX 模型与网络。"""
    from core import topic_lifecycle as tl

    monkeypatch.setattr(tl, "_embedding_fn", lambda: (lambda t: table[t]))
    tl._embed_normalized.cache_clear()


def test_similarity_substring_short_circuits_before_embedding(monkeypatch):
    """字面命中直接 1.0，省掉 embedding 调用。"""
    from core import topic_lifecycle as tl

    calls: list[str] = []
    monkeypatch.setattr(
        tl, "_embedding_fn", lambda: (lambda t: calls.append(t) or [1.0, 0.0])
    )
    tl._embed_normalized.cache_clear()

    assert tl.similarity("重庆小面", "昨天吃了重庆小面") == 1.0
    assert calls == [], "子串命中不应触发 embedding"


def test_similarity_uses_vector_cosine_when_lexical_misses(monkeypatch):
    """词法不命中时走向量 cosine：取 max(词法, 向量)。"""
    from core import topic_lifecycle as tl

    _inject_embedding(monkeypatch, {"甲": [1.0, 0.0], "乙": [0.6, 0.8]})

    # 单字无二元组 → 词法 0；两向量 cosine = 0.6。
    assert tl.similarity("甲", "乙") == pytest.approx(0.6)


def test_similarity_falls_back_to_lexical_without_embedding(monkeypatch):
    """embedding 不可用时退化为纯词法，不抛错。"""
    from core import topic_lifecycle as tl

    monkeypatch.setattr(tl, "_embedding_fn", lambda: None)
    tl._embed_normalized.cache_clear()

    # 「小面 / 好吃」两个二元组命中（3 个中的 2 个）。
    score = tl.similarity("小面好吃", "重庆小面真的很好吃")
    assert score == pytest.approx(2 / 3)


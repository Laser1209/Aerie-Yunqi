"""P0 topic system tests — 主动消息话题续接/再造模式 + 话题追踪引擎.

测试目标：主动消息（generate_push）不再硬编码"开新话题"——
续接(continue)/再造(revive)模式必须注入对话上下文并指令延续话题。
本文件同时承载 TopicTracker 话题追踪引擎测试（追加于后）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.llm_caller import LLMCaller


# ── 测试工具：拦截 chat 捕获 system prompt ──────────────────────
def _capture_system_prompt():
    """Monkey-patch LLMCaller.chat to capture system prompt, then raise
    RuntimeError so generate_push falls back to template filling."""
    original_chat = LLMCaller.chat
    seen: list[str] = []

    async def stub_chat(self, messages, *a, **kw):
        for m in messages:
            if m.get("role") == "system":
                seen.append(m["content"])
        raise RuntimeError("no provider")

    LLMCaller.chat = stub_chat

    def restore():
        LLMCaller.chat = original_chat

    return seen, restore


# ── generate_push 话题模式（P0a）───────────────────────────────
class TestGeneratePushTopicMode:
    def test_new_mode_default_keeps_original_instruction(self):
        """默认 new 模式：保持"开新话题"，不注入对话上下文。"""
        seen, restore = _capture_system_prompt()
        try:
            asyncio.run(LLMCaller().generate_push("在干嘛。"))
        finally:
            restore()
        system = seen[0]
        assert "开新话题的第一句话" in system
        assert "延续你们刚才的话题" not in system
        assert "你们最近聊的" not in system

    def test_continue_mode_injects_dialogue_and_continues(self):
        """续接模式：指令延续话题 + 注入最近对话。"""
        seen, restore = _capture_system_prompt()
        try:
            asyncio.run(
                LLMCaller().generate_push(
                    "在干嘛。",
                    topic_mode="continue",
                    dialogue_context="他：昨天那本书看到第三章了\n你：我也想看！",
                )
            )
        finally:
            restore()
        system = seen[0]
        assert "延续你们刚才的话题" in system
        assert "你们最近聊的" in system
        assert "昨天那本书看到第三章了" in system
        assert "开新话题的第一句话" not in system
        assert "主动开一个新话题" not in system

    def test_revive_mode_mentions_old_topic(self):
        """再造模式：指令重新提起旧话题 + 注入对话上下文。"""
        seen, restore = _capture_system_prompt()
        try:
            asyncio.run(
                LLMCaller().generate_push(
                    "上次你提到想学做那道菜",
                    topic_mode="revive",
                    dialogue_context="你们之前聊过：你答应教他做红烧排骨",
                )
            )
        finally:
            restore()
        system = seen[0]
        assert "重新提起那段旧话题" in system
        assert "你们最近聊的" in system
        assert "红烧排骨" in system
        assert "开新话题的第一句话" not in system

    def test_dialogue_context_ignored_in_new_mode(self):
        """new 模式即使传入 dialogue_context 也不注入（防误用）。"""
        seen, restore = _capture_system_prompt()
        try:
            asyncio.run(
                LLMCaller().generate_push(
                    "早安。",
                    dialogue_context="不该出现的上下文",
                )
            )
        finally:
            restore()
        system = seen[0]
        assert "你们最近聊的" not in system
        assert "不该出现的上下文" not in system

    def test_continue_mode_fallback_returns_template(self):
        """续接模式 LLM 不可用 → 回退模板填充（不阻断链路）。"""
        original_chat = LLMCaller.chat

        async def stub_chat(self, messages, *a, **kw):
            raise RuntimeError("no provider")

        LLMCaller.chat = stub_chat
        try:
            out = asyncio.run(
                LLMCaller().generate_push(
                    "在干嘛。",
                    topic_mode="continue",
                    dialogue_context="他：昨天那本书",
                )
            )
        finally:
            LLMCaller.chat = original_chat
        assert out == "在干嘛。"


# ── TopicTracker 话题追踪引擎（P0b）─────────────────────────────
from core.topic_tracker import (  # noqa: E402
    CLOSE_AFTER_HOURS,
    PAUSE_AFTER_HOURS,
    Topic,
    TopicTracker,
)


def _tracker(tmp_path, now: float) -> TopicTracker:
    return TopicTracker(state_path=tmp_path / "topic_state.json", clock=lambda: now)


class TestTopicTracker:
    def test_first_dialogue_creates_active_topic(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        topic = t.record_dialogue("今天上班好累，项目又延期了")
        assert topic is not None
        assert topic.state == "active"
        assert topic.subject == "工作"  # detect_topics 类目名兜底
        assert t.active_topic(1000.0) is topic

    def test_continuation_updates_active_topic(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        first = t.record_dialogue("今天上班好累")
        t.record_dialogue("是啊，老板又开会了", now=1000.0 + 300)
        assert first.turn_count == 2
        assert t.active_topic(1000.0 + 300) is first

    def test_closure_word_closes_topic(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        t.record_dialogue("今天上班好累")
        t.record_dialogue("那先这样，明天再说", now=1000.0 + 600)
        assert t.active_topic(1000.0 + 600) is None
        closed = t.latest_closed(1000.0 + 600)
        assert closed is not None
        assert closed.state == "closed"
        assert closed.stub  # 生成存根

    def test_paused_is_derived_state(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        t.record_dialogue("我们聊到哪了")
        assert t.active_topic(1000.0).is_paused(1000.0) is False
        # 沉寂超过 4h → 派生 paused
        late = 1000.0 + PAUSE_AFTER_HOURS * 3600 + 1
        assert t.active_topic(late) is not None  # 24h 内仍 active
        assert t.active_topic(late).is_paused(late) is True

    def test_plan_continue_when_active(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        t.record_dialogue("你最近看的那本书怎么样")
        plan = t.continuation_plan(1000.0 + PAUSE_AFTER_HOURS * 3600)
        assert plan["mode"] == "continue"
        assert "书" in plan["dialogue_context"]

    def test_plan_revive_when_no_active_but_recent_stub(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        t.record_dialogue("你最近看的那本书怎么样")
        t.record_dialogue("那先这样，明天再说", now=1000.0 + 600)
        # 4h 后无 active；closed 在再造窗口内 → revive
        late = 1000.0 + PAUSE_AFTER_HOURS * 3600 + 60
        plan = t.continuation_plan(late)
        assert plan["mode"] == "revive"
        assert "书" in plan["dialogue_context"]

    def test_plan_new_when_nothing(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        plan = t.continuation_plan(1000.0)
        assert plan["mode"] == "new"
        assert plan["topic"] is None
        assert plan["dialogue_context"] == ""

    def test_inactive_closure_after_24h(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        t.record_dialogue("你最近看的那本书怎么样")
        late = 1000.0 + CLOSE_AFTER_HOURS * 3600 + 60
        # 超 24h 后主动清理
        closed = t.mark_inactive_closure(late)
        assert closed is not None
        assert closed.state == "closed"
        assert t.active_topic(late) is None

    def test_reload_reclassifies_long_inactive_as_closed(self, tmp_path):
        path = tmp_path / "topic_state.json"
        t1 = _tracker(tmp_path, now=1000.0)
        t1.record_dialogue("你最近看的那本书怎么样")
        # 新 tracker 用晚 48h 的时钟加载同一文件 → active 应被重判为 closed
        late = 1000.0 + 48 * 3600
        t2 = TopicTracker(state_path=path, clock=lambda: late)
        assert t2.active_topic(late) is None
        assert t2.latest_closed(late) is not None

    def test_persist_stub_calls_store_with_kind(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        t.record_dialogue("你最近看的那本小说怎么样")
        t.record_dialogue("那先这样", now=1000.0 + 600)
        closed = t.latest_closed(1000.0 + 600)
        captured = {}

        async def fake_store(content: str, metadata: dict) -> str:
            captured["content"] = content
            captured["metadata"] = metadata
            return "mem-1"

        import asyncio

        asyncio.run(t.persist_stub(closed, user_id=3489352115, store=fake_store))
        assert captured["metadata"]["kind"] == "topic_stub"
        assert captured["metadata"]["subject"] == "娱乐"
        assert "话题存根" in captured["content"]

    def test_state_roundtrip(self, tmp_path):
        t = _tracker(tmp_path, now=1000.0)
        t.record_dialogue("你最近看的那本小说怎么样")
        # 直接重建读取同文件
        t2 = _tracker(tmp_path, now=1000.0)
        assert len(t2.topics) == 1
        assert t2.topics[0].subject == "娱乐"


# ── 主动消息动机重定义（P0c）──────────────────────────────────
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from core.companion import Companion  # noqa: E402
from core.decision_log import DecisionLogger  # noqa: E402


class _FakeBrain:
    def __init__(self):
        self.kwargs = None

    async def generate_push(self, **kwargs):
        self.kwargs = dict(kwargs)
        return "记得休息。"


def _make_companion(tmp_path, db_rows=None):
    """构造不跑 __init__ 的 Companion，仅注入 P0 相关依赖。"""
    c = object.__new__(Companion)
    c.get_primary_user_selection = lambda: SimpleNamespace(user_id=3489352115)
    c.feature_flags = SimpleNamespace(is_enabled=lambda flag: False)
    c.knowledge = SimpleNamespace(search=lambda *a, **k: [])
    c.brain = _FakeBrain()
    c.topic_tracker = TopicTracker(state_path=tmp_path / "topic_state.json")
    c.decision_log = DecisionLogger(log_dir=tmp_path / "logs")
    c.qq = SimpleNamespace(send_message=AsyncMock(return_value=True))
    c.db = SimpleNamespace(
        query=lambda sql, params=(): list(db_rows or []),
        insert=lambda *a, **k: 1,
    )
    c.settings = {"proactive": {}}
    return c


class TestDispatchPushTopicMode:
    def test_continue_mode_passes_topic_context(self, tmp_path):
        c = _make_companion(
            tmp_path,
            db_rows=[
                {"role": "user", "content": "昨天那本书看到第三章了"},
                {"role": "assistant", "content": "我也想看！"},
            ],
        )
        # 先创建活跃话题（不命中收尾词）
        c.topic_tracker.record_dialogue("你最近看的那本小说怎么样")
        result = asyncio.run(c._dispatch_push("idle_care", {}))
        assert result is True
        assert c.brain.kwargs["topic_mode"] == "continue"
        assert "小说" in c.brain.kwargs["dialogue_context"]
        assert "昨天那本书看到第三章了" in c.brain.kwargs["dialogue_context"]
        # 决策日志埋点 1 已写
        entries = c.decision_log.recent()
        assert len(entries) >= 1
        assert entries[0]["kind"] == "topic_motive"
        assert entries[0]["chosen"]["mode"] == "continue"

    def test_new_mode_when_no_topic(self, tmp_path):
        c = _make_companion(tmp_path)
        result = asyncio.run(c._dispatch_push("weather_push", {}))
        assert result is True
        assert c.brain.kwargs["topic_mode"] == "new"
        assert c.brain.kwargs["dialogue_context"] == ""

    def test_revive_mode_when_recent_stub(self, tmp_path):
        c = _make_companion(tmp_path)
        c.topic_tracker.record_dialogue("你最近看的那本小说怎么样")
        c.topic_tracker.record_dialogue("那先这样，明天再说")
        result = asyncio.run(c._dispatch_push("idle_care", {}))
        assert result is True
        assert c.brain.kwargs["topic_mode"] == "revive"

    def test_decision_log_failure_does_not_block(self, tmp_path):
        """决策日志写入失败不得阻断发送链路。"""
        c = _make_companion(tmp_path)
        c.decision_log.append = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        result = asyncio.run(c._dispatch_push("weather_push", {}))
        assert result is True


# ── 提示词框架 L0.5 话题认知层（P0d）───────────────────────────
from core.context_builder import ContextBuilder  # noqa: E402
from core.feature_flags import FeatureFlags  # noqa: E402


class TestTopicCognitionLayer:
    def test_disabled_by_default(self, monkeypatch):
        """topic_tracking_v1 默认关闭 → 不注入话题段。"""
        monkeypatch.setattr(FeatureFlags, "is_enabled", lambda self, f: False)
        cb = ContextBuilder()
        cb.set_topic_provider(lambda: {"subject": "工作", "turn_count": 3})
        msgs = cb.build(1, "你好", "FULL", history_msgs=[])
        assert "【当前话题】" not in msgs[0]["content"]

    def test_injects_active_topic_when_enabled(self, monkeypatch):
        """flag 开启 + 有活跃话题 → 注入话题事实段。"""
        monkeypatch.setattr(
            FeatureFlags, "is_enabled", lambda self, f: f == "topic_tracking_v1"
        )
        cb = ContextBuilder()
        cb.set_topic_provider(lambda: {"subject": "看书", "turn_count": 3})
        msgs = cb.build(1, "你看到哪了", "FULL", history_msgs=[])
        system = msgs[0]["content"]
        assert "【当前话题】你们正在聊一个围绕「看书」的话题" in system
        assert "已聊 3 轮" in system
        # 只注入事实，不注入判定指令
        assert "终止判定" not in system

    def test_no_inject_when_no_topic(self, monkeypatch):
        """无活跃话题 → 不注入。"""
        monkeypatch.setattr(
            FeatureFlags, "is_enabled", lambda self, f: f == "topic_tracking_v1"
        )
        cb = ContextBuilder()
        cb.set_topic_provider(lambda: None)
        msgs = cb.build(1, "你好", "FULL", history_msgs=[])
        assert "【当前话题】" not in msgs[0]["content"]

    def test_basic_mode_skips_topic_layer(self, monkeypatch):
        """BASIC 模式不注入话题层。"""
        monkeypatch.setattr(
            FeatureFlags, "is_enabled", lambda self, f: f == "topic_tracking_v1"
        )
        cb = ContextBuilder()
        cb.set_topic_provider(lambda: {"subject": "看书", "turn_count": 3})
        msgs = cb.build(1, "你好", "BASIC", history_msgs=[])
        assert "【当前话题】" not in msgs[0]["content"]

    def test_provider_error_safe(self, monkeypatch):
        """provider 抛异常 → 安全跳过不阻断。"""
        monkeypatch.setattr(
            FeatureFlags, "is_enabled", lambda self, f: f == "topic_tracking_v1"
        )

        def boom():
            raise RuntimeError("no topic")

        cb = ContextBuilder()
        cb.set_topic_provider(boom)
        msgs = cb.build(1, "你好", "FULL", history_msgs=[])
        assert "【当前话题】" not in msgs[0]["content"]


# ── 沉寂检测统一（P0e）──────────────────────────────────────
import time as _time  # noqa: E402

from core.companion_state import CompanionState  # noqa: E402
from core.push_event_engine import EventType, PushEvent, PushEventEngine  # noqa: E402


class TestUnifiedActivityClock:
    def test_idle_hours_zero_when_never_active(self):
        state = CompanionState()
        assert state.idle_hours() == 0.0

    def test_mark_user_active_records_epoch(self, monkeypatch):
        state = CompanionState()
        monkeypatch.setattr(_time, "time", lambda: 1000.0)
        state.mark_user_active()
        assert state.last_user_active_at == 1000.0

    def test_serialization_roundtrip(self, tmp_path):
        state = CompanionState()
        state.last_user_active_at = 12345.0
        path = tmp_path / "companion_state.json"
        state.save(path)
        loaded = CompanionState.load(path)
        assert loaded.last_user_active_at == 12345.0

    def test_legacy_state_without_field_loads_safely(self, tmp_path):
        """旧版 companion_state.json 无该字段 → 安全加载为 0。"""
        path = tmp_path / "companion_state.json"
        path.write_text(
            '{"relationship_stage": "intimate"}', encoding="utf-8"
        )
        loaded = CompanionState.load(path)
        assert loaded.last_user_active_at == 0.0

    def test_push_engine_hook_on_record_activity(self):
        engine = PushEventEngine()
        calls = []
        engine.on_user_active = lambda: calls.append(1)
        engine.record_user_activity()
        assert calls == [1]

    def test_push_engine_hook_on_user_message_event(self):
        engine = PushEventEngine()
        calls = []
        engine.on_user_active = lambda: calls.append(1)
        engine._on_user_message(PushEvent(event_type=EventType.USER_MESSAGE))
        assert calls == [1]

"""SessionAggregator 单元测试:验证会话聚合层的判定逻辑。

覆盖 decide() 的 6 条路径(对应文档 §6 判定流程),以及语义三分类的输入输出。
纯 mock,不启动 DSH 子进程、不调真实 LLM。
"""

import time

import pytest

from communication.message import IncomingMessage
from core.session_aggregator import AggregateDecision, SessionAggregator, SessionContext


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage.from_local(text, 1)


def _ctx(**kwargs) -> SessionContext:
    defaults = dict(current=_msg("补充指令"), active_session_id="s1", preset="file-organizer")
    defaults.update(kwargs)
    return SessionContext(**defaults)


class _FakeLLM:
    """按预设文本回复的假 LLM。"""

    def __init__(self, text: str):
        self._text = text
        self.prompt_seen: str | None = None

    async def chat(self, messages, **kwargs):
        self.prompt_seen = str(messages[0]["content"])
        return type("R", (), {"text": self._text})()


@pytest.mark.asyncio
async def test_no_active_session_returns_new():
    agg = SessionAggregator(_FakeLLM("supplement"))
    d = await agg.decide(SessionContext(current=_msg("整理 D 盘")))
    assert isinstance(d, AggregateDecision)
    assert (d.action, d.reason) == ("new", "no_active_session")
    assert d.session_id is None
    assert d.confidence == 1.0


@pytest.mark.asyncio
async def test_task_running_continues_without_semantic_call():
    # running 且在 90s 窗口内 → 直接续接,跳过语义(不调 LLM)
    fake = _FakeLLM("whatever")
    agg = SessionAggregator(fake)
    d = await agg.decide(_ctx(dsh_status="running", last_activity_at=time.time()))
    assert (d.action, d.reason, d.session_id) == ("continue", "task_running", "s1")
    assert d.confidence == 1.0
    assert fake.prompt_seen is None  # 未触发语义判定


@pytest.mark.asyncio
async def test_window_expired_returns_new():
    agg = SessionAggregator(_FakeLLM("supplement"))
    d = await agg.decide(_ctx(dsh_status="idle", last_activity_at=time.time() - 120))
    assert (d.action, d.reason) == ("new", "window_expired")


@pytest.mark.asyncio
async def test_window_active_supplement_continues():
    agg = SessionAggregator(_FakeLLM("supplement"))
    d = await agg.decide(_ctx(dsh_status="idle", last_activity_at=time.time()))
    assert (d.action, d.reason, d.session_id) == ("continue", "window_active", "s1")
    assert d.confidence == 0.8


@pytest.mark.asyncio
async def test_window_active_followup_continues():
    agg = SessionAggregator(_FakeLLM("followup"))
    d = await agg.decide(_ctx(dsh_status="idle", last_activity_at=time.time()))
    assert (d.action, d.reason) == ("continue", "window_active")


@pytest.mark.asyncio
async def test_window_active_new_task_returns_new():
    agg = SessionAggregator(_FakeLLM("new_task"))
    d = await agg.decide(_ctx(dsh_status="idle", last_activity_at=time.time()))
    assert (d.action, d.reason) == ("new", "semantic_new")


@pytest.mark.asyncio
async def test_semantic_failure_degrades_to_new():
    # 语义模型异常 → 降级 new(宁开新会话,不误合并)
    class Boom:
        async def chat(self, messages, **kwargs):
            raise RuntimeError("llm boom")

    agg = SessionAggregator(Boom())
    d = await agg.decide(_ctx(dsh_status="idle", last_activity_at=time.time()))
    assert (d.action, d.reason) == ("new", "semantic_new")


@pytest.mark.asyncio
async def test_semantic_prompt_contains_recent_context():
    # 语义 prompt 应包含历史消息 + 当前消息
    fake = _FakeLLM("supplement")
    agg = SessionAggregator(fake)
    await agg.decide(_ctx(
        dsh_status="idle",
        last_activity_at=time.time(),
        recent_messages=[{"role": "user", "content": "帮我整理 D 盘"}],
    ))
    assert fake.prompt_seen is not None
    assert "帮我整理 D 盘" in fake.prompt_seen
    assert "supplement" in fake.prompt_seen  # 三分类说明已注入

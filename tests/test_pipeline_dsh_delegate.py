"""DSH 委托流程单元测试:验证 pipeline._try_delegate_to_dsh 完整链路。

覆盖:
  - 开关关闭 / 空文本 / 路由未命中 → 返回 None(聊天零阻塞回退)
  - 无聚合层 / 首次消息 → 新会话(session_id=None)
  - 聚合层续接(窗口内语义判定 supplement) → 续接 session_id
  - 聚合层超窗 → 新会话
  - 协议解析 + 执行器渲染
  - delegate 抛异常 → 返回 None(降级 LLMCaller)

纯 mock,不启动 DSH node 子进程、不调真实 LLM、不碰真实文件系统。
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from communication.message import IncomingMessage
from core.dsh_cli import DshRunResult
from core.llm_caller import LLMCallerResponse
from core.pipeline import Pipeline
from core.session_aggregator import SessionAggregator


class _FakeLightLLM:
    """按预设文本回复的假轻量 LLM(供真实 SessionAggregator 做语义判定)。"""

    def __init__(self, text: str):
        self._text = text

    async def chat(self, messages, **kwargs):
        return SimpleNamespace(text=self._text)


def _delegate_decision(kind: str, preset: str | None, reason: str):
    return SimpleNamespace(kind=kind, preset=preset, reason=reason)


def _router(decision) -> MagicMock:
    r = MagicMock()
    r.decide = AsyncMock(return_value=decision)
    return r


def _cli(result: DshRunResult | Exception) -> MagicMock:
    c = MagicMock()
    if isinstance(result, Exception):
        c.delegate = AsyncMock(side_effect=result)
    else:
        c.delegate = AsyncMock(return_value=result)
    return c


def _executor(results: list[dict]) -> MagicMock:
    e = MagicMock()
    e.execute = AsyncMock(return_value=results)
    return e


def _make_pipeline(
    monkeypatch,
    *,
    enabled: bool = True,
    cli: MagicMock | None = None,
    router: MagicMock | None = None,
    executor: MagicMock | None = None,
    aggregator: SessionAggregator | None = None,
    session_state: dict | None = None,
    workspace: Any = None,
) -> Pipeline:
    """构造最小 Pipeline 实例(跳过重量级 __init__,只注入 DSH 相关属性)。

    cli/router/executor 默认注入 truthy mock,以满足 _try_delegate_to_dsh 的守卫
    条件(三者任一为假都直接返回 None)。
    """
    monkeypatch.setattr(
        Pipeline,
        "_load_preset_protocol_prompt",
        staticmethod(lambda preset: "PROTOCOL_PROMPT"),
    )
    p = Pipeline.__new__(Pipeline)
    p._dsh_enabled = enabled
    p._dsh_cli = cli if cli is not None else MagicMock()
    p._dsh_router = router if router is not None else MagicMock()
    p._dsh_executor = executor if executor is not None else MagicMock()
    p._dsh_aggregator = aggregator
    p._dsh_session_state = session_state if session_state is not None else {}
    p._dsh_workspace = workspace
    p._dsh_persona = None
    return p


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage.from_local(text, 12345)


def _run_result(final_response: str, session_id: str = "dsh-file-organizer-abc") -> DshRunResult:
    return DshRunResult(
        session_id=session_id,
        final_response=final_response,
        finish_reason="stop",
        events=[],
        usage={"inputTokens": 120, "outputTokens": 80},
    )


# --------------------------------------------------------------------------- 负路径


@pytest.mark.asyncio
async def test_disabled_returns_none(monkeypatch):
    p = _make_pipeline(monkeypatch, enabled=False)
    assert await p._try_delegate_to_dsh("整理 D 盘", _msg("整理 D 盘")) is None


@pytest.mark.asyncio
async def test_empty_text_returns_none(monkeypatch):
    p = _make_pipeline(monkeypatch)
    assert await p._try_delegate_to_dsh("   ", _msg("   ")) is None


@pytest.mark.asyncio
async def test_router_not_delegate_returns_none(monkeypatch):
    router = _router(_delegate_decision("llm", None, "fallback"))
    p = _make_pipeline(monkeypatch, router=router)
    assert await p._try_delegate_to_dsh("你好呀", _msg("你好呀")) is None
    router.decide.assert_awaited_once()


@pytest.mark.asyncio
async def test_delegate_failure_returns_none(monkeypatch):
    """DSH delegate 抛异常 → 返回 None,调用方回退 brain.chat。"""
    cli = _cli(RuntimeError("dsh boom"))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    p = _make_pipeline(monkeypatch, cli=cli, router=router)
    assert await p._try_delegate_to_dsh("整理 D 盘", _msg("整理 D 盘")) is None


# --------------------------------------------------------------------------- 正路径


@pytest.mark.asyncio
async def test_no_aggregator_plain_text_new_session(monkeypatch):
    """无聚合层 + 纯文本输出 → session_id=None 传给 delegate,状态被更新。"""
    cli = _cli(_run_result("已按计划整理完成。"))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    p = _make_pipeline(monkeypatch, cli=cli, router=router, aggregator=None)

    resp = await p._try_delegate_to_dsh("整理 D 盘", _msg("整理 D 盘"))

    assert isinstance(resp, LLMCallerResponse)
    assert resp.text == "已按计划整理完成。"
    assert resp.provider == "dsh"
    assert resp.model == "dsh-file-organizer"
    assert resp.tokens_prompt == 120
    assert resp.tokens_completion == 80

    # 首次消息:无活跃会话,不续接 → session_id=None
    cli.delegate.assert_awaited_once_with(
        "整理 D 盘",
        preset="file-organizer",
        system_prompt="PROTOCOL_PROMPT",
        session_id=None,
    )
    # 委托成功后按 preset 记录本轮实际 session
    assert p._dsh_session_state["file-organizer"]["session_id"] == "dsh-file-organizer-abc"
    assert "last_activity_at" in p._dsh_session_state["file-organizer"]


@pytest.mark.asyncio
async def test_first_message_opens_new_session_and_executes_protocol(monkeypatch):
    """真实聚合层(无活跃会话)→ new,DSH 输出 WorkProtocol → 执行器渲染。"""
    protocol = {
        "protocol_version": 1,
        "task_type": "file_organize",
        "persona_id": "ita",
        "session_id": "s-any",
        "goal": "整理 D 盘",
        "plan": {"source_dir": "D:\\T08171634"},
    }
    cli = _cli(_run_result(json.dumps(protocol, ensure_ascii=False)))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    executor = _executor([{"op": "file_organize", "status": "ok", "detail": "已整理 12 项"}])
    agg = SessionAggregator(_FakeLightLLM("supplement"))
    p = _make_pipeline(monkeypatch, cli=cli, router=router, executor=executor, aggregator=agg)

    resp = await p._try_delegate_to_dsh("整理 D 盘", _msg("整理 D 盘"))

    assert resp.provider == "dsh"
    assert "✓ file_organize" in resp.text
    assert "已整理 12 项" in resp.text
    # 无活跃会话 → 新会话,不传 session_id
    cli.delegate.assert_awaited_once()
    assert cli.delegate.call_args.kwargs["session_id"] is None
    executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_message_within_window_continues_session(monkeypatch):
    """窗口内语义判定 supplement → 续接历史 session_id。"""
    cli = _cli(_run_result("已删除重复文件。", session_id="s1"))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    agg = SessionAggregator(_FakeLightLLM("supplement"))
    state = {
        "file-organizer": {"session_id": "s1", "last_activity_at": time.time()},
    }
    p = _make_pipeline(
        monkeypatch,
        cli=cli,
        router=router,
        aggregator=agg,
        session_state=state,
    )

    resp = await p._try_delegate_to_dsh("顺便把重复的删了", _msg("顺便把重复的删了"))

    assert resp.provider == "dsh"
    # 续接 → 传入历史 session_id
    cli.delegate.assert_awaited_once_with(
        "顺便把重复的删了",
        preset="file-organizer",
        system_prompt="PROTOCOL_PROMPT",
        session_id="s1",
    )


@pytest.mark.asyncio
async def test_window_expired_opens_new_session(monkeypatch):
    """超过续接窗口(>60s)→ 强制新会话,不续接。"""
    cli = _cli(_run_result("好的。", session_id="s2"))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    agg = SessionAggregator(_FakeLightLLM("supplement"))
    state = {
        "file-organizer": {"session_id": "s1", "last_activity_at": time.time() - 120},
    }
    p = _make_pipeline(
        monkeypatch,
        cli=cli,
        router=router,
        aggregator=agg,
        session_state=state,
    )

    await p._try_delegate_to_dsh("帮我写周报", _msg("帮我写周报"))

    # 超窗 → 新会话,session_id 仍为 None
    assert cli.delegate.call_args.kwargs["session_id"] is None
    # 本轮结果记录新 session
    assert p._dsh_session_state["file-organizer"]["session_id"] == "s2"


# --------------------------------------------------------------------------- 跨 preset 续接


@pytest.mark.asyncio
async def test_cross_preset_continues_most_recent_session(monkeypatch):
    """路由层判错 preset 时,聚合层应跨 preset 找最近活跃 session 并续接。

    场景:消息 1 "帮我整理 D 盘" → 路由命中 file-organizer,session=s1。
         消息 2 "顺便把重复的删了" → 路由 L2 判 work 但 preset=default(无 session),
         聚合层应跨 preset 找到 file-organizer 下的 s1 并续接。
    """
    cli = _cli(_run_result("已删除 3 个重复文件。", session_id="s1"))
    # 路由层把补充指令判为 default(无 preset 命中)
    router = _router(_delegate_decision("delegate", "default", "light"))
    agg = SessionAggregator(_FakeLightLLM("supplement"))
    state = {
        "file-organizer": {"session_id": "s1", "last_activity_at": time.time()},
    }
    p = _make_pipeline(
        monkeypatch,
        cli=cli,
        router=router,
        aggregator=agg,
        session_state=state,
    )

    resp = await p._try_delegate_to_dsh("顺便把重复的删了", _msg("顺便把重复的删了"))

    assert resp is not None
    # 续接 → 传历史 session_id
    assert cli.delegate.call_args.kwargs["session_id"] == "s1"
    # 续接用 file-organizer 的 preset(不是路由层判的 default)
    assert cli.delegate.call_args.kwargs["preset"] == "file-organizer"
    # system_prompt 也用 file-organizer 的
    assert cli.delegate.call_args.kwargs["system_prompt"] == "PROTOCOL_PROMPT"


@pytest.mark.asyncio
async def test_find_recent_active_prefers_routed_preset(monkeypatch):
    """_find_recent_active_session 优先返回路由层判的 preset 自己的 session。"""
    p = Pipeline.__new__(Pipeline)
    p._dsh_session_state = {
        "file-organizer": {"session_id": "s1", "last_activity_at": time.time() - 5},
        "default": {"session_id": "s2", "last_activity_at": time.time()},
    }
    # preferred=default → 应返回 default/s2(即使 file-organizer 更老)
    preset, state = p._find_recent_active_session("default")
    assert preset == "default"
    assert state["session_id"] == "s2"


# --------------------------------------------------------------------------- 工作区感知


def _fake_workspace(active_root: str):
    ws = MagicMock()
    ws.active_root.return_value = active_root
    return ws


@pytest.mark.asyncio
async def test_active_workspace_injected_into_system_prompt(monkeypatch):
    """激活工作区应注入 DSH system_prompt,让 Agent 感知操作范围。"""
    cli = _cli(_run_result("已整理完成。", session_id="s1"))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    ws = _fake_workspace(r"D:\T08171634")
    p = _make_pipeline(monkeypatch, cli=cli, router=router, workspace=ws)

    await p._try_delegate_to_dsh("整理一下", _msg("整理一下"))

    prompt = cli.delegate.call_args.kwargs["system_prompt"]
    assert "PROTOCOL_PROMPT" in prompt
    assert r"D:\T08171634" in prompt  # 工作区路径已注入
    assert "[当前工作区]" in prompt


@pytest.mark.asyncio
async def test_no_active_workspace_keeps_protocol_prompt(monkeypatch):
    """无激活工作区时,不附加工作区上下文。"""
    cli = _cli(_run_result("已整理完成。", session_id="s1"))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    ws = _fake_workspace(None)  # active_root() 返回 None
    p = _make_pipeline(monkeypatch, cli=cli, router=router, workspace=ws)

    await p._try_delegate_to_dsh("整理一下", _msg("整理一下"))

    prompt = cli.delegate.call_args.kwargs["system_prompt"]
    assert prompt == "PROTOCOL_PROMPT"  # 不含工作区注入
    assert "当前工作区" not in prompt


@pytest.mark.asyncio
async def test_no_workspace_keeps_protocol_prompt(monkeypatch):
    """workspace 未初始化时,保持原行为(仅 protocol_prompt)。"""
    cli = _cli(_run_result("已整理完成。", session_id="s1"))
    router = _router(_delegate_decision("delegate", "file-organizer", "keyword"))
    p = _make_pipeline(monkeypatch, cli=cli, router=router, workspace=None)

    await p._try_delegate_to_dsh("整理一下", _msg("整理一下"))

    prompt = cli.delegate.call_args.kwargs["system_prompt"]
    assert prompt == "PROTOCOL_PROMPT"

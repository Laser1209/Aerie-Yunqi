"""会话聚合层(Session Aggregation Layer):判定连续消息是否属于同一件事。

纯判定层:输入 SessionContext,输出 AggregateDecision,无副作用(不写库、不改 DSH
session、不启动进程)。由上游 pipeline 执行决策结果。

判定流程(见 docs/aerie-dsh-session-aggregation.md §6):
  1. 无活跃会话            → new(no_active_session)
  2. DSH running 且在放宽窗口内 → continue(task_running,跳过语义判定)
  3. 超过续接窗口          → new(window_expired)
  4. 窗口内                → 语义三分类(supplement/followup → continue;new_task → new)
  5. 语义模型失败          → new(semantic_new,宁开新会话不误合并)

日志埋点与 dsh_cli/work_mode_router 对齐:INFO=判定结果,WARNING=降级,DEBUG=细节。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from communication.message import IncomingMessage
from core.llm_caller import LLMCaller

logger = logging.getLogger(__name__)

# 三分类 prompt(通用技术措辞,不做人设微调)
_CLASSIFY_PROMPT = (
    "判断下面这条消息与前面对话的关系,只回复一个词:\n"
    "supplement - 对前面任务的补充/追加要求(如'顺便把重复的删了')\n"
    "followup - 对前面任务的追问或修改(如'改成按日期分'、'整理好了吗')\n"
    "new_task - 全新话题,与前面无关(如'帮我写个周报')\n"
    "前面对话:\n{recent}\n"
    "当前消息:{current}\n"
    "回复:"
)

# 语义判定超时(秒);失败降级 new_task
_CLASSIFY_TIMEOUT_S = 5.0


@dataclass
class SessionContext:
    """聚合层判定所需的上下文(由调用方传入)。

    current: 当前待判定的消息(含 content 与 timestamp)。
    active_session_id: 现有活跃会话的 DSH session_id;无活跃会话时为 None。
    preset: 场景名(file-organizer 等)。
    dsh_status: DSH session 状态("running" | "idle" | None)。
    last_activity_at: 活跃会话的最后活动时间戳(epoch 秒)。
    recent_messages: 最近历史消息 [{role, content}],供语义判定参考。
    """

    current: IncomingMessage
    active_session_id: str | None = None
    preset: str | None = None
    dsh_status: str | None = None
    last_activity_at: float | None = None
    recent_messages: list[dict] = field(default_factory=list)


@dataclass
class AggregateDecision:
    """聚合层返回的归属决策(唯一输出)。

    action: "continue"(续接现有会话) | "new"(新会话)。
    session_id: continue 时 = 归属的 DSH session_id;new 时为 None。
    preset: 建议的路由场景(可复用路由层结果)。
    reason: 判定依据(no_active_session / task_running / window_active /
            window_expired / semantic_new)。
    confidence: 0.0~1.0;规则路径恒 1.0,语义路径取 0.8。
    """

    action: str
    session_id: str | None = None
    preset: str | None = None
    reason: str = "no_active_session"
    confidence: float = 1.0


class SessionAggregator:
    """会话聚合层:判定连续消息的会话归属(纯判定,无副作用)。"""

    def __init__(
        self,
        light_llm: LLMCaller,
        *,
        active_window_sec: float = 30.0,
        running_extend_sec: float = 90.0,
        idle_window_sec: float = 60.0,
        classify_timeout_s: float = _CLASSIFY_TIMEOUT_S,
    ) -> None:
        self._light_llm = light_llm
        self._active_window_sec = active_window_sec
        self._running_extend_sec = running_extend_sec
        self._idle_window_sec = idle_window_sec
        self._classify_timeout_s = classify_timeout_s

    async def decide(self, ctx: SessionContext) -> AggregateDecision:
        """判定当前消息归入哪个会话(核心接口)。

        输入 SessionContext,输出 AggregateDecision;无副作用。
        """
        now = time.time()
        elapsed = (
            (now - ctx.last_activity_at) if ctx.last_activity_at is not None else None
        )
        content = (ctx.current.content or "").strip()
        logger.debug(
            "[aggregator] decide active=%s preset=%s dsh_status=%s elapsed=%s text=%s",
            ctx.active_session_id, ctx.preset, ctx.dsh_status,
            (f"{elapsed:.1f}s" if elapsed is not None else "None"), content[:60],
        )

        # 1. 无活跃会话 → 首条消息,直接新会话
        if not ctx.active_session_id:
            logger.info("[aggregator] 无活跃会话,新会话")
            return AggregateDecision(
                action="new", preset=ctx.preset, reason="no_active_session", confidence=1.0
            )

        # 2. DSH running 且在放宽窗口内 → 快速续接(跳过语义判定)
        if ctx.dsh_status == "running" and elapsed is not None and elapsed <= self._running_extend_sec:
            logger.info("[aggregator] DSH running 且窗口内,直接续接 session=%s", ctx.active_session_id)
            return AggregateDecision(
                action="continue", session_id=ctx.active_session_id,
                preset=ctx.preset, reason="task_running", confidence=1.0,
            )

        # 3. 超过续接窗口 → 强制新会话
        if elapsed is not None and elapsed > self._idle_window_sec:
            logger.info("[aggregator] 超过续接窗口(%.1fs > %.0fs),新会话", elapsed, self._idle_window_sec)
            return AggregateDecision(
                action="new", preset=ctx.preset, reason="window_expired", confidence=1.0
            )

        # 4. 窗口内 → 语义三分类
        verdict = await self._classify_semantic(content, ctx.recent_messages)
        if verdict in ("supplement", "followup"):
            logger.info("[aggregator] 语义判定=%s,续接 session=%s", verdict, ctx.active_session_id)
            return AggregateDecision(
                action="continue", session_id=ctx.active_session_id,
                preset=ctx.preset, reason="window_active", confidence=0.8,
            )
        logger.info("[aggregator] 语义判定=%s,新会话", verdict)
        return AggregateDecision(
            action="new", preset=ctx.preset, reason="semantic_new", confidence=0.8
        )

    async def _classify_semantic(self, current_text: str, recent_messages: list[dict]) -> str:
        """内部:轻量模型三分类 supplement/followup/new_task(超时降级 new_task)。"""
        if not current_text:
            return "new_task"
        prompt = _CLASSIFY_PROMPT.format(
            recent=_format_recent(recent_messages), current=current_text[:200]
        )
        t0 = time.monotonic()
        try:
            resp = await asyncio.wait_for(
                self._light_llm.chat(
                    [{"role": "user", "content": prompt}],
                    preferred_provider="siliconflow-light",
                ),
                timeout=self._classify_timeout_s,
            )
            raw = (resp.text or "").strip().lower()
            logger.debug("[aggregator] 语义分类耗时=%.2fs 原文=%r", time.monotonic() - t0, raw[:40])
            for verdict in ("supplement", "followup", "new_task"):
                if verdict in raw:
                    return verdict
            return "new_task"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[aggregator] 语义分类失败(降级 new_task): %s", exc)
            return "new_task"


def _format_recent(messages: list[dict], limit: int = 3, max_len: int = 100) -> str:
    """把最近历史消息格式化为 prompt 参考(最多 limit 条,每条截断 max_len)。"""
    if not messages:
        return "(无)"
    lines = []
    for m in messages[-limit:]:
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))[:max_len]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


__all__ = ["SessionAggregator", "SessionContext", "AggregateDecision"]

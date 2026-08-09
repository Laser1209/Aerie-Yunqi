"""Aerie · 云栖 — Agent thin facade (P2-C/D converged).

The former S1 six-step loop (perceive → reason → decide → act → reflect →
express) re-implemented Pipeline's orchestration end-to-end and was never
instantiated in production (Companion calls Pipeline directly). Per the
"single orchestrator" target, that duplicated orchestration has been removed.

Agent is now a thin facade: ``handle()`` delegates to ``companion.pipeline``
and wraps the result in ``AgentResult`` for callers that expect the Agent API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Dict

from communication.message import IncomingMessage
from core.companion import Companion


# ── Data model (public API surface) ───────────────────

@dataclass
class PerceivedInput:
    """感知层输出（保留为公开数据模型；编排已收敛到 Pipeline）. """
    msg: IncomingMessage
    route_mode: str
    context: List[Dict[str, Any]]
    emotion_info: Dict[str, Any]
    eruption_info: Optional[Dict[str, Any]]
    memory_hits: List[Dict[str, Any]]
    history: List[Dict[str, Any]]
    reply_to: Optional[Dict[str, Any]]
    decision_candidates: Optional[Dict[str, Any]] = None
    complexity: Optional[Any] = None
    selected_provider: Optional[str] = None


@dataclass
class Thought:
    """思考层输出（保留为公开数据模型）. """
    raw_text: str
    reply_text: str
    react_trace: Dict[str, Any]
    tool_results: List[Dict[str, Any]]
    model: str
    usage: Dict[str, Any]
    reasoning: str = ""


@dataclass
class Decision:
    """决策层输出（保留为公开数据模型）. """
    intent: str
    selected_skill: Optional[str]
    skill_args: Optional[Dict[str, Any]]
    emotion: Dict[str, Any]
    pacing: tuple[float, str]
    decision_trace: Optional[Dict[str, Any]] = None


@dataclass
class SkillCall:
    """工具调用记录（保留为公开数据模型）. """
    skill_name: str
    args: Dict[str, Any]
    result: Any
    duration_ms: float
    success: bool = True


@dataclass
class AgentResult:
    """Agent 统一输出格式（由 Pipeline 结果包装而来）. """
    segments: List[str]
    actions: List[SkillCall]
    trace: Dict[str, Any]
    decision: Decision
    reflection: Optional[Dict[str, Any]]
    reply_text: str
    user_msg_id: int
    ai_msg_ids: List[int]


# ── Thin facade ───────────────────────────────────────

class Agent:
    """Thin facade over Pipeline (single orchestrator).

    Delegates message handling to ``companion.pipeline.handle`` and wraps the
    result in ``AgentResult`` so existing callers keep the same return shape.
    """

    def __init__(self, companion: Companion) -> None:
        self.pipeline = companion.pipeline
        self.cognition = companion.cognition

    async def handle(self, msg: IncomingMessage, force_full: bool = False) -> AgentResult | None:
        """Delegate to Pipeline and wrap the result in AgentResult."""
        result = await self.pipeline.handle(msg, force_full)
        if result is None:
            return None
        return AgentResult(
            segments=list(result.get("segments", [])),
            actions=[],
            trace={"id": result.get("cognition_id", 0)},
            decision=Decision(
                intent="reply",
                selected_skill=None,
                skill_args=None,
                emotion={"label": result.get("emotion", "neutral")},
                pacing=(1.0, "normal"),
            ),
            reflection=None,
            reply_text=str(result.get("reply", "")),
            user_msg_id=int(result.get("user_msg_id", 0) or 0),
            ai_msg_ids=[int(i) for i in (result.get("ai_msg_ids") or [])],
        )

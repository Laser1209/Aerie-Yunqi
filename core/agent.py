"""Aerie · 云栖 v0.1.0-beta.1 — Agent 抽象层 (S1 M1.1 + M1.2).

将原有的 7 大核心模块收口为统一的 Agent 视角，通过委托模式
调用 Companion 内部的各个引擎，实现显式的六步主循环：

    Perceive → Reason → Decide → Act → Reflect → Express

与旧 Pipeline 双轨运行，可通过 settings 切换，保证平滑过渡。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict

from communication.message import IncomingMessage, OutgoingReply
from core.companion import Companion
from core.agent_reflection_queue import ReflectionQueue, ReflectionTask
from core.provider_router import ProviderRouter, ComplexityScore, ComplexityLevel
from core.budget_tracker import BudgetTracker, BudgetConfig

logger = logging.getLogger(__name__)


# ── Data Classes (M1.1 交付) ────────────────────────────

@dataclass
class PerceivedInput:
    """感知层输出: 路由 + 情绪 + 上下文 + 记忆 + 决策候选."""
    msg: IncomingMessage
    route_mode: str
    context: List[Dict[str, Any]]
    emotion_info: Dict[str, Any]
    eruption_info: Optional[Dict[str, Any]]
    memory_hits: List[Dict[str, Any]]
    history: List[Dict[str, Any]]
    reply_to: Optional[Dict[str, Any]]
    decision_candidates: Optional[Dict[str, Any]] = None
    complexity: Optional[ComplexityScore] = None  # S2 M2.1: 复杂度评分
    selected_provider: Optional[str] = None       # S2 M2.1: 选中的 provider


@dataclass
class Thought:
    """思考层输出: LLM 原始回复 + ReAct trace + 工具结果."""
    raw_text: str
    reply_text: str
    react_trace: Dict[str, Any]
    tool_results: List[Dict[str, Any]]
    model: str
    usage: Dict[str, Any]
    reasoning: str = ""


@dataclass
class Decision:
    """决策层输出: 最终意图 + 选中的 skill + 情绪 + 节奏."""
    intent: str
    selected_skill: Optional[str]
    skill_args: Optional[Dict[str, Any]]
    emotion: Dict[str, Any]
    pacing: tuple[float, str]
    decision_trace: Optional[Dict[str, Any]] = None


@dataclass
class SkillCall:
    """工具调用记录."""
    skill_name: str
    args: Dict[str, Any]
    result: Any
    duration_ms: float
    success: bool = True


@dataclass
class AgentResult:
    """Agent 完整 run 输出."""
    segments: List[str]
    actions: List[SkillCall]
    trace: Dict[str, Any]
    decision: Decision
    reflection: Optional[Dict[str, Any]]
    reply_text: str
    user_msg_id: int
    ai_msg_ids: List[int]


# ── Agent Class (M1.1 + M1.2) ───────────────────────────

class Agent:
    """
    Aerie Agent 抽象类 (v11.0.0 S1).

    将原有的 7 个核心模块收口为统一的 Agent 视角，
    通过委托模式 (Delegation) 调用 Companion 内部的各个引擎。
    显式实现 Perceive → Reason → Decide → Act → Reflect → Express 六步循环。
    """

    def __init__(self, companion: Companion) -> None:
        self.companion = companion

        # 核心引擎委托
        self.brain = companion.brain
        self.emotion = companion.emotion
        self.cognition = companion.cognition
        self.memory = companion.memory
        self.knowledge = companion.knowledge
        self.tool_registry = companion.tool_registry
        self.pipeline = companion.pipeline
        self.self_evolver = companion.self_evolver
        self.router = companion.router
        self.db = companion.db
        self.ctx_builder = companion.pipeline.ctx_builder

        # 决策引擎 (Phase 9 §10.2 多层决策)
        self.decision_engine = getattr(companion.pipeline, 'decision_engine', None)

        # 反思队列 (M1.3: 异步反思，不阻塞主流程)
        self.reflection_queue = ReflectionQueue(
            self_evolver=self.self_evolver,
            db=self.db,
        )
        self._reflection_started = False

        # Provider 智能路由 (S2 M2.1: 复杂度评估 + 动态路由)
        self.provider_router = ProviderRouter(
            brain=self.brain,
            arbiter_enabled=settings.get("agent", {}).get("arbiter_enabled", True)
            if isinstance(settings, dict) else True,
        )

        # 全局预算跟踪 (S2 M2.2: 预算跟踪 + 动态降级)
        budget_cfg = None
        if isinstance(settings, dict) and settings.get("budget"):
            b = settings["budget"]
            budget_cfg = BudgetConfig(
                monthly_budget_usd=b.get("monthly_budget_usd"),
                weekly_budget_usd=b.get("weekly_budget_usd"),
                daily_budget_usd=b.get("daily_budget_usd"),
                low_threshold_pct=b.get("low_threshold_pct", 0.50),
                critical_threshold_pct=b.get("critical_threshold_pct", 0.20),
            )
        self.budget_tracker = BudgetTracker(
            config=budget_cfg,
            data_file=settings.get("budget", {}).get("data_file", "budget_data.json")
            if isinstance(settings, dict) else "budget_data.json",
        )
        self.budget_tracker.load()

        # 复杂度缓存（用于预算跟踪）
        self._last_complexity: Optional[ComplexityScore] = None

        # S1 双轨模式: True = Agent 路径, False = 旧 Pipeline 路径
        settings = companion.settings if hasattr(companion, 'settings') else {}
        if isinstance(settings, dict):
            self._use_agent_path = settings.get("agent", {}).get("enabled", False)
            self._task_planner_enabled = settings.get("agent", {}).get("task_planner_enabled", False)
            self._max_plan_steps = settings.get("agent", {}).get("max_plan_steps", 10)
        else:
            self._use_agent_path = False
            self._task_planner_enabled = False
            self._max_plan_steps = 10

        # 任务规划器（可选，默认关闭）
        self._task_planner = None
        if self._task_planner_enabled:
            try:
                from core.task_planner import TaskPlanner
                self._task_planner = TaskPlanner(max_steps=self._max_plan_steps)
                logger.info("Agent task planner enabled (max_steps=%d)", self._max_plan_steps)
            except Exception:
                logger.exception("Failed to initialize TaskPlanner, task planning disabled")
                self._task_planner = None

    @property
    def use_agent_path(self) -> bool:
        return self._use_agent_path

    @use_agent_path.setter
    def use_agent_path(self, value: bool) -> None:
        self._use_agent_path = value

    # ── Public entrypoint ────────────────────────────

    async def handle(self, msg: IncomingMessage, force_full: bool = False) -> AgentResult | None:
        """
        Agent 主入口: 双轨模式切换。

        - use_agent_path=True → 走新的六步 Agent 循环
        - use_agent_path=False → 走旧 Pipeline (返回 None 由调用方处理)
        """
        if not self._use_agent_path:
            # 双轨: 降级到旧 pipeline
            old_result = await self.pipeline.handle(msg, force_full)
            if old_result is None:
                return None
            # 将旧结果包装成 AgentResult 格式，保持调用方一致
            return AgentResult(
                segments=old_result.get("segments", []),
                actions=[],
                trace={},
                decision=Decision(
                    intent="reply",
                    selected_skill=None,
                    skill_args=None,
                    emotion={},
                    pacing=(1.0, "normal"),
                ),
                reflection=None,
                reply_text=old_result.get("reply", ""),
                user_msg_id=old_result.get("user_msg_id", 0),
                ai_msg_ids=old_result.get("ai_msg_ids", []),
            )

        return await self.run(msg)

    # ── Step 1: Perceive ─────────────────────────────

    async def perceive(self, msg: IncomingMessage) -> PerceivedInput:
        """感知阶段: 路由 → 情绪更新 → 历史 → 记忆 → 上下文构建."""
        # 1. 路由
        route_mode = self.router.route(msg.user_id)

        # 2. 情绪更新 (异步，不阻塞主流程但我们等它完成)
        try:
            await self.emotion.update_trajectory_async(msg.user_id, msg.content)
        except Exception:
            logger.exception("emotion update error in perceive")

        # 3. 获取情绪状态
        emotion_info = {}
        eruption_info = None
        try:
            state = self.emotion.get_state(msg.user_id)
            emotion_info = {
                "label": state.get("label", "neutral"),
                "pad": state.get("pad", {}),
                "thresholds": state.get("thresholds", {}),
            }
            eruption_info = state.get("eruption")
        except Exception:
            pass

        # 4. 历史记录
        history = []
        try:
            history = self.db.query(
                "SELECT role, content FROM chat_log WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                (msg.user_id,),
            )
            history.reverse()
        except Exception:
            pass

        # 5. 记忆检索
        memory_hits = []
        try:
            memory_hits = await self.memory.search(msg.content, top_k=5)
        except Exception:
            pass

        # 6. 回复引用
        reply_to_data = None
        if msg.reply_to_id:
            try:
                quoted = self.db.query_one(
                    "SELECT id, role, content FROM chat_log WHERE id = ?",
                    (msg.reply_to_id,),
                )
                if quoted:
                    reply_to_data = {
                        "id": quoted["id"],
                        "role": quoted["role"],
                        "content": quoted["content"],
                    }
            except Exception:
                pass

        # 7. 上下文构建
        ctx_messages = self.ctx_builder.build(
            msg.user_id,
            msg.content,
            route_mode,
            history_msgs=history,
            emotion_info=emotion_info,
            eruption_info=eruption_info,
            reply_to=reply_to_data,
            attachments=msg.attachments if msg.attachments else None,
        )

        # 7.5 Provider 复杂度评估 (S2 M2.1)
        complexity = None
        selected_provider = None
        try:
            context_turns = len(history) // 2 if history else 0
            complexity = await self.provider_router.evaluate(
                message_text=msg.content,
                context_turns=context_turns,
                memory_hits=len(memory_hits),
                attachments=msg.attachments if msg.attachments else None,
                route_mode=route_mode,
            )
            self._last_complexity = complexity
            # 用预算状态来动态选择 provider
            budget_status = self.budget_tracker.get_status()
            selected_provider = self.provider_router.select_provider(
                complexity, budget_status=budget_status,
            )
            logger.debug(
                "Complexity: %.2f → %s (provider: %s, arbiter: %s)",
                complexity.total, complexity.level.value,
                selected_provider, complexity.used_arbiter,
            )
        except Exception:
            logger.exception("provider router error in perceive")

        # 8. 多层决策候选 (M1.2: 在感知阶段就先跑决策，为 Reason 阶段提供约束)
        decision_candidates = None
        if self.decision_engine:
            try:
                decision_candidates = self.decision_engine.decide_for_message(
                    user_id=msg.user_id,
                    route_mode=route_mode,
                    source=msg.source,
                    emotion_label=emotion_info.get("label"),
                    tools_offered=route_mode == "FULL",
                    active_eruption=eruption_info.get("mode") if eruption_info else None,
                )
            except Exception:
                logger.exception("decision engine error in perceive")

        return PerceivedInput(
            msg=msg,
            route_mode=route_mode,
            context=ctx_messages,
            emotion_info=emotion_info,
            eruption_info=eruption_info,
            memory_hits=memory_hits,
            history=history,
            reply_to=reply_to_data,
            decision_candidates=decision_candidates,
            complexity=complexity,
            selected_provider=selected_provider,
        )

    # ── Step 2: Reason ───────────────────────────────

    async def reason(self, perceived: PerceivedInput) -> Thought:
        """思考阶段: 调用 LLM Brain 进行推理."""
        tools = self.tool_registry.get_openai_schema() if perceived.route_mode == "FULL" else None

        # 可选：任务规划注入（仅 FULL 模式且启用时）
        context = perceived.context
        if (self._task_planner and self._task_planner_enabled
                and perceived.route_mode == "FULL"
                and perceived.msg.content
                and self._task_planner.should_plan(perceived.msg.content)):
            try:
                plan = self._task_planner.create_plan(perceived.msg.content)
                context = self._inject_plan_into_context(context, plan)
                logger.debug("Task plan injected: %d steps", plan.total_steps)
            except Exception:
                logger.exception("Task planning failed, falling back to normal mode")
                context = perceived.context

        response = await self.brain.chat(context, tools=tools)
        raw_text = getattr(response, "text", "") or ""
        react_trace = getattr(response, "react_trace", None) or {}
        tool_results = getattr(response, "tool_results", None) or []
        model_name = getattr(response, "model", "unknown")
        usage = getattr(response, "usage", None) or {}

        # 去掉 <think> 块
        reply_text = self._strip_think(raw_text)

        # 如果 react_trace 没有 thought，从阶段数据合成
        react_trace = self._ensure_react_trace(react_trace, raw_text, tool_results)

        return Thought(
            raw_text=raw_text,
            reply_text=reply_text,
            react_trace=react_trace,
            tool_results=tool_results,
            model=model_name,
            usage=usage,
            reasoning=react_trace.get("thought", ""),
        )

    # ── Step 3: Decide ───────────────────────────────

    async def decide(self, perceived: PerceivedInput, thought: Thought) -> Decision:
        """决策阶段: 从感知候选和思考结果中选出最终执行路径."""
        # 使用感知阶段已经计算好的决策候选
        decision_trace = perceived.decision_candidates or {}
        chosen = decision_trace.get("chosen", "reply") if decision_trace else "reply"

        # 从工具结果中提取选中的 skill
        selected_skill = None
        skill_args = None
        if thought.tool_results:
            first_tool = thought.tool_results[0]
            selected_skill = first_tool.get("name")
            skill_args = first_tool.get("arguments")

        # 计算 persona pacing
        from core.persona_pacing import compute_persona_interval
        emotion_label = (perceived.emotion_info.get("label") if perceived.emotion_info else "neutral") or "neutral"
        thresholds = (perceived.emotion_info or {}).get("thresholds", {}) or {}
        is_eruption = bool(perceived.eruption_info and perceived.eruption_info.get("mode"))

        interval_sec, style = compute_persona_interval(
            segment_index=0,
            emotion_label=emotion_label,
            threshold=thresholds,
            is_eruption=is_eruption,
            segment_content=thought.reply_text[:100] if thought.reply_text else "",
        )

        return Decision(
            intent=chosen,
            selected_skill=selected_skill,
            skill_args=skill_args,
            emotion=perceived.emotion_info,
            pacing=(interval_sec, style),
            decision_trace=decision_trace,
        )

    # ── Step 4: Act ──────────────────────────────────

    async def act(self, decision: Decision, thought: Thought) -> List[SkillCall]:
        """行动阶段: 执行工具调用并记录结果."""
        actions = []
        for tr in thought.tool_results:
            skill_name = tr.get("name", "unknown")
            args = tr.get("arguments", {}) or {}
            result = tr.get("result", {})
            duration = tr.get("duration_ms", 0)
            success = tr.get("success", True)
            actions.append(SkillCall(
                skill_name=skill_name,
                args=args,
                result=result,
                duration_ms=duration,
                success=success,
            ))
        return actions

    # ── Step 5: Reflect ──────────────────────────────

    async def reflect(self, perceived: PerceivedInput, decision: Decision,
                      actions: List[SkillCall], thought: Thought) -> Optional[Dict[str, Any]]:
        """反思阶段: 将反思任务塞入异步队列，立即返回，不阻塞主流程."""
        # 确保队列已启动
        if not self._reflection_started:
            await self.reflection_queue.start()
            self._reflection_started = True

        task = ReflectionTask(
            user_id=perceived.msg.user_id,
            user_message=perceived.msg.content,
            react_trace=thought.react_trace,
            tool_results=thought.tool_results,
            source="agent-run",
        )
        enqueued = await self.reflection_queue.enqueue(task)
        if enqueued:
            return {"enqueued": True, "queue_size": self.reflection_queue.qsize}
        return {"enqueued": False, "reason": "queue_full_or_dedup"}

    # ── Step 6: Express ──────────────────────────────

    async def express(self, decision: Decision, actions: List[SkillCall],
                      thought: Thought, perceived: PerceivedInput) -> List[str]:
        """表达阶段: 情绪润色 + 屏幕动作净化 + 自检 + 语义分段."""
        # 1. 情绪润色
        reply_text = self.emotion.tune(thought.reply_text)

        # 2. 屏幕隔空铁律净化
        try:
            from core.screen_action_sanitizer import sanitize as _sanitize_action
            reply_text = _sanitize_action(reply_text)
        except Exception:
            logger.exception("screen_action_sanitizer failed")

        # 3. 输出自检
        try:
            from core.output_self_check import OutputSelfCheck
            _sc = OutputSelfCheck()
            _sc_result = _sc.check(reply_text)
            reply_text = _sc_result.cleaned_text
        except Exception:
            logger.exception("output_self_check failed")

        # 4. 语义分段
        from communication.splitter import SemanticMessageSplitter
        splitter = SemanticMessageSplitter()
        segments = splitter.split(reply_text) or [reply_text]

        return segments

    # ── Main Loop: run() ─────────────────────────────

    async def run(self, msg: IncomingMessage) -> AgentResult:
        """
        Agent 主循环: Perceive → Reason → Decide → Act → Reflect → Express.

        完整实现六步循环，同时写入 cognition trace，保持与旧 pipeline 兼容。
        """
        # ── Cognition Trace 开始 ──
        trace = self.cognition.begin(msg.user_id, msg.source, msg.content)

        try:
            # ═══ Step 1: Perceive ═══
            perceived = await self.perceive(msg)

            # BASIC 模式跳过 (与旧 pipeline 一致)
            if perceived.route_mode == "BASIC":
                logger.debug("BASIC skip for user %s", msg.user_id)
                self.cognition.record(trace, "route", {"mode": "BASIC", "skipped": True})
                self.cognition.commit(trace, "BASIC")
                # 不返回 None，返回一个空的 AgentResult 保持接口一致
                return AgentResult(
                    segments=[],
                    actions=[],
                    trace=trace,
                    decision=Decision(
                        intent="skip",
                        selected_skill=None,
                        skill_args=None,
                        emotion=perceived.emotion_info,
                        pacing=(0, "skip"),
                    ),
                    reflection=None,
                    reply_text="",
                    user_msg_id=0,
                    ai_msg_ids=[],
                )

            self.cognition.record(trace, "route", {"mode": perceived.route_mode, "skipped": False})
            self.cognition.record(trace, "emotion", {
                "label": perceived.emotion_info.get("label"),
                "pad": perceived.emotion_info.get("pad"),
            })
            self.cognition.record(trace, "threshold", perceived.emotion_info.get("thresholds"))

            # 记录决策 trace
            if perceived.decision_candidates:
                self.cognition.record_decision(trace, perceived.decision_candidates)

            # 记录 context 阶段
            system_chars = len(perceived.context[0]["content"]) if perceived.context else 0
            history_chars = sum(len(m.get("content", "")) for m in perceived.context[1:])
            tools_offered = perceived.route_mode == "FULL"
            self.cognition.record(trace, "context", {
                "messages": len(perceived.context),
                "system_prompt_chars": system_chars,
                "history_chars": history_chars,
                "tools_offered": tools_offered,
            })

            # ═══ Step 2: Reason ═══
            thought = await self.reason(perceived)

            self.cognition.record(trace, "brain", {
                "model": thought.model,
                "tokens": thought.usage,
                "raw_chars": len(thought.raw_text),
                "react": thought.react_trace,
            })
            self.cognition.record_react(trace, thought.react_trace)

            # ═══ Step 3: Decide ═══
            decision = await self.decide(perceived, thought)

            # ═══ Step 4: Act ═══
            actions = await self.act(decision, thought)

            # 记录工具阶段
            tool_summary = []
            for a in actions:
                try:
                    rid = self.db.insert("tool_call_log", {
                        "ts": int(time.time() * 1000),
                        "user_id": msg.user_id,
                        "tool_name": a.skill_name,
                        "arguments": json.dumps(a.args, ensure_ascii=False),
                        "result": json.dumps(a.result, ensure_ascii=False)[:2000],
                        "success": 1 if a.success else 0,
                        "duration_ms": int(a.duration_ms),
                    })
                except Exception:
                    logger.exception("tool_call_log insert error")
                tool_summary.append({
                    "name": a.skill_name,
                    "success": a.success,
                    "duration_ms": int(a.duration_ms),
                })
            self.cognition.record(trace, "tools", tool_summary)

            # ═══ Step 6: Express (先于 Reflect，因为用户需要先看到回复) ═══
            segments = await self.express(decision, actions, thought, perceived)
            reply_text = "".join(segments)

            # 记录后处理阶段
            self.cognition.record(trace, "postprocess", {
                "tune_label": perceived.emotion_info.get("label"),
                "eruption_mode": perceived.eruption_info.get("mode") if perceived.eruption_info else None,
                "raw_chars": len(thought.reply_text),
                "tuned_chars": len(reply_text),
            })
            self.cognition.record(trace, "split", {
                "segments": segments,
                "count": len(segments),
            })

            # ═══ 持久化用户消息 ═══
            user_row_id = 0
            try:
                user_row_id = self.db.insert("chat_log", {
                    "user_id": msg.user_id,
                    "role": "user",
                    "content": msg.content,
                    "msg_type": msg.msg_type,
                    "route_mode": perceived.route_mode,
                    "reply_to_id": perceived.reply_to["id"] if perceived.reply_to else None,
                    "reply_to_content": perceived.reply_to["content"] if perceived.reply_to else None,
                    "reply_to_role": perceived.reply_to["role"] if perceived.reply_to else None,
                    "attachments": json.dumps(msg.attachments, ensure_ascii=False) if msg.attachments else None,
                })
            except Exception:
                logger.exception("db insert user msg error")

            # 发射用户事件
            try:
                from core.chat_events import emit
                emit(
                    "user",
                    role="user",
                    id=user_row_id,
                    user_id=msg.user_id,
                    content=msg.content,
                    source=msg.source,
                )
            except Exception:
                pass

            # ═══ 持久化 AI 回复 ═══
            ai_row_ids: list[int] = []
            try:
                for seg in segments:
                    rid = self.db.insert("chat_log", {
                        "user_id": msg.user_id,
                        "role": "assistant",
                        "content": seg,
                        "msg_type": msg.msg_type,
                        "route_mode": perceived.route_mode,
                    })
                    ai_row_ids.append(rid)
            except Exception:
                logger.exception("db insert ai msg error")

            # 记录 output 阶段
            self.cognition.record(trace, "output", {
                "ai_msg_ids": ai_row_ids,
                "user_msg_id": user_row_id,
                "source": msg.source,
                "segment_count": len(ai_row_ids),
            })

            # 提交 cognition trace
            self.cognition.commit(trace, perceived.route_mode)

            # ═══ Step 5: Reflect (异步队列，零阻塞) ═══
            reflection_result = await self.reflect(perceived, decision, actions, thought)

            # ═══ 发射 assistant 事件 (与旧 pipeline 行为一致) ═══
            try:
                from core.chat_events import emit
                from core.persona_pacing import compute_persona_interval

                emotion_label_local = (perceived.emotion_info.get("label") if perceived.emotion_info else "neutral") or "neutral"
                is_eruption_local = bool(perceived.eruption_info and perceived.eruption_info.get("mode"))
                threshold_summary_local = (perceived.emotion_info or {}).get("thresholds", {}) or {}

                pacing_log: list[dict] = []
                for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
                    emit_kwargs = {
                        "role": "assistant",
                        "id": rid,
                        "user_id": msg.user_id,
                        "content": seg,
                        "source": msg.source,
                    }
                    if idx == 0:
                        if perceived.emotion_info:
                            emit_kwargs["emotion"] = perceived.emotion_info["label"]
                        if perceived.eruption_info:
                            emit_kwargs["eruption"] = perceived.eruption_info["mode"]
                    emit("assistant", **emit_kwargs)

                    # 计算下一段的 pacing
                    if idx < len(segments) - 1:
                        interval_sec, style = compute_persona_interval(
                            segment_index=idx,
                            emotion_label=emotion_label_local,
                            threshold=threshold_summary_local,
                            is_eruption=is_eruption_local,
                            segment_content=seg,
                        )
                        pacing_log.append({
                            "seg_idx": idx,
                            "next_style": style,
                            "next_interval_ms": int(interval_sec * 1000),
                            "source": "agent-local",
                        })
                        if msg.source == "local" and interval_sec > 0:
                            await asyncio.sleep(interval_sec)

                # 记录 pacing 决策
                if pacing_log:
                    trace_id = trace.get("id") or 0
                    if trace_id and self.cognition is not None:
                        self.cognition.append_pacing_decisions(trace_id, pacing_log)
            except Exception:
                logger.exception("assistant emit error")

            # ═══ QQ 消息 → SendQueue ═══
            if msg.source == "qq":
                try:
                    reply_to_qq_mid = 0
                    if msg.reply_to_id:
                        q = self.db.query_one(
                            "SELECT qq_message_id FROM chat_log WHERE id = ?",
                            (msg.reply_to_id,),
                        )
                        if q and q.get("qq_message_id"):
                            reply_to_qq_mid = int(q["qq_message_id"])

                    reply = OutgoingReply(
                        user_id=msg.user_id,
                        content=reply_text,
                        msg_id=ai_row_ids[0] if ai_row_ids else 0,
                        reply_to_qq_message_id=reply_to_qq_mid,
                        cognition_id=int(trace.get("id") or 0),
                    )
                    if perceived.eruption_info and perceived.eruption_info.get("mode"):
                        setattr(reply, "eruption_mode", perceived.eruption_info["mode"])
                    self.companion.queue.enqueue(reply)
                except Exception:
                    logger.exception("QQ enqueue error")

            return AgentResult(
                segments=segments,
                actions=actions,
                trace=trace,
                decision=decision,
                reflection=reflection_result,
                reply_text=reply_text,
                user_msg_id=user_row_id,
                ai_msg_ids=ai_row_ids,
            )

        except Exception:
            logger.exception("Agent.run() error")
            # 出错时尝试走旧 pipeline 作为 fallback
            try:
                old_result = await self.pipeline.handle(msg, force_full=True)
                if old_result:
                    return AgentResult(
                        segments=old_result.get("segments", []),
                        actions=[],
                        trace=trace,
                        decision=Decision(
                            intent="fallback",
                            selected_skill=None,
                            skill_args=None,
                            emotion={},
                            pacing=(1.0, "normal"),
                        ),
                        reflection=None,
                        reply_text=old_result.get("reply", ""),
                        user_msg_id=old_result.get("user_msg_id", 0),
                        ai_msg_ids=old_result.get("ai_msg_ids", []),
                    )
            except Exception:
                logger.exception("fallback pipeline also failed")
            raise

    # ── Internal helpers ──────────────────────────────

    def _strip_think(self, text: str) -> str:
        """去掉回复中的 <think> 思考块."""
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return text.strip()

    def _ensure_react_trace(self, react_trace: dict | None, raw_text: str,
                            tool_results: list[dict] | None) -> dict:
        """确保 react_trace 有 thought 字段，没有的话从现有数据合成."""
        if react_trace and react_trace.get("thought"):
            return react_trace

        synthesized = dict(react_trace or {})
        if not synthesized.get("thought"):
            # 从工具结果或原始回复中合成一个 thought
            if tool_results:
                tool_names = ", ".join(t.get("name", "unknown") for t in tool_results)
                synthesized["thought"] = f"用户需要调用工具: {tool_names}"
            else:
                synthesized["thought"] = "直接生成回复"
            synthesized["react_source"] = "agent-synthesized"

        return synthesized

    def _inject_plan_into_context(self, context: list[dict], plan) -> list[dict]:
        """将任务计划注入到系统提示词中，引导 LLM 按步骤执行.

        Args:
            context: 原始上下文消息列表
            plan: TaskPlan 对象

        Returns:
            注入计划后的新上下文列表
        """
        if not context or not plan or not plan.steps:
            return context

        # 构建计划描述文本
        plan_lines = [
            "",
            "---",
            "",
            "【任务执行计划 · Task Execution Plan】",
            f"任务：{plan.title}",
            f"类型：{plan.task_type.value if hasattr(plan.task_type, 'value') else str(plan.task_type)}",
            f"总步数：{plan.total_steps}",
            "",
            "请按以下步骤逐步执行任务：",
        ]

        for step in plan.steps:
            status_text = f"[{step.status.value}]" if hasattr(step.status, 'value') else ""
            plan_lines.append(
                f"  {step.step_id}. {step.title} {status_text}"
            )
            if step.description:
                plan_lines.append(f"     说明：{step.description}")
            if step.tool and step.tool != "direct":
                plan_lines.append(f"     推荐工具：{step.tool}")

        plan_lines.extend([
            "",
            "执行要求：",
            "1. 按步骤顺序执行，每步完成后验证结果",
            "2. 不要跳步，也不要在一步内做多个步骤的事",
            "3. 如果某步失败，分析原因后重试或调整方案",
            "4. 全部完成后做最终检查，确保任务目标达成",
            "",
        ])

        plan_text = "\n".join(plan_lines)

        # 复制上下文，在系统提示词末尾追加计划
        new_context = []
        for i, msg in enumerate(context):
            if i == 0 and msg.get("role") == "system":
                new_msg = dict(msg)
                new_msg["content"] = msg.get("content", "") + plan_text
                new_context.append(new_msg)
            else:
                new_context.append(dict(msg))

        return new_context

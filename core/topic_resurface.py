"""Aerie · 话题复现触发源（阶段 5）.

把阶段 4 的 **dormant 话题状态**作为调制输入，在行为层按概率发射一条
"想起旧话题"的主动消息。严格两阶段：

- 阶段一「候选召回」（确定性、广撒网、低门槛）：从话题库取 ``lifecycle == "dormant"``
  的话题，按「上下文相关度」粗筛（低于 ``context_candidate_floor`` 丢弃）；
- 阶段二「概率发射」（唯一采样点）：把候选的调制信号 m 映射为概率 p，由
  ``behavior_sampler.sample_once`` 采样一次决定是否发射。**禁止**「m 超阈值就发」的
  硬闸门写法——低 m 仍有非零概率（``p_floor``），高 m 也仍可能不发射（``p_ceiling``）。

调制信号 m（三因子全部归一化到 [0,1] 后取**加权几何平均**）：
    m = interest^wi * dormancy^wd * relevance^wc      （wi + wd + wc = 1）
- interest：话题兴趣评分（阶段 4 落在 0..1，直接 clamp01）；
- dormancy：沉寂时长 / ``dormancy_cap_hours`` 后 clamp01（超过上限即视为"足够久"）；
- relevance：候选指纹与当前上下文（最近的 active 话题）的相关度，取值 [0,1]；
  无参考上下文时取中性兜底 ``relevance_default``。
加权几何平均保证 m ∈ [0,1] 且对每个因子单调，同时保留"相乘"语义。

本模块只做「生成候选 + 采样决策 + 额度记账 + 复现后状态复位」，
实际消息生成与投递交给注入的 dispatcher（复用既有 `PushScheduler._dispatch` 分支），
频控（``PushPolicy.can_push()``）完全复用、不复制判定。
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from core.behavior_sampler import clamp01, emit_probability, sample_once
from core.topic_lifecycle import similarity

logger = logging.getLogger(__name__)

# 代码兜底默认（业务数值一律从 config/proactive.yaml 的 scene 读取，此处仅兜底）。
DEFAULT_SCENE_PARAMS: dict[str, Any] = {
    "interest_weight": 0.4,          # 兴趣评分权重
    "dormancy_weight": 0.35,         # 沉寂时长权重
    "context_weight": 0.25,          # 上下文相关度权重
    "dormancy_cap_hours": 168.0,     # 沉寂时长归一化上限（小时）
    "relevance_default": 0.5,        # 无参考上下文时的中性相关度
    "context_candidate_floor": 0.15, # 阶段一候选召回门槛
    "tau": 0.25,                     # 采样温度 τ
    "m_midpoint": 0.5,               # 概率拐点
    "p_floor": 0.02,                 # 低 m 概率下限（>0）
    "p_ceiling": 0.9,                # 高 m 概率上限（<1）
    "low_m_threshold": 0.5,          # m 低于该值判为低 m
    "main_budget": 4,                # 主额度（高 m 消耗）
    "low_m_budget": 1,               # 低 m 单独子额度
    "replay_days": 7,                # 基线回放天数 N
}


def resolve_params(scene_cfg: Optional[dict]) -> dict[str, Any]:
    """从 scene 配置解析调制 / 采样 / 额度参数（缺项回退代码默认）。"""
    src = scene_cfg or {}
    out: dict[str, Any] = dict(DEFAULT_SCENE_PARAMS)
    for key, default in DEFAULT_SCENE_PARAMS.items():
        if key not in src:
            continue
        try:
            out[key] = float(src[key]) if isinstance(default, float) else int(src[key])
        except (TypeError, ValueError):
            continue
    # 三因子权重归一化，保证加权几何平均落在 [0,1]。
    wi, wd, wc = (
        max(0.0, float(out["interest_weight"])),
        max(0.0, float(out["dormancy_weight"])),
        max(0.0, float(out["context_weight"])),
    )
    total = wi + wd + wc
    if total <= 0:
        wi = float(DEFAULT_SCENE_PARAMS["interest_weight"])
        wd = float(DEFAULT_SCENE_PARAMS["dormancy_weight"])
        wc = float(DEFAULT_SCENE_PARAMS["context_weight"])
        total = wi + wd + wc
    out["interest_weight"] = wi / total
    out["dormancy_weight"] = wd / total
    out["context_weight"] = wc / total
    return out


@dataclass
class ResurfaceProposal:
    """阶段一产出的复现候选（含归一化因子、m、p 与低 m 标记）。"""

    topic_id: str
    subject: str
    context: str
    interest: float
    dormancy: float
    relevance: float
    m: float
    p: float
    is_low: bool
    emitted: bool = False


class TopicResurface:
    """话题复现触发源：召回 + 调制 + 单点采样 + 额度记账。"""

    def __init__(
        self,
        *,
        lifecycle_provider: Optional[Callable[[], Any]] = None,
        rng: Callable[[], float] = random.random,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._lifecycle_provider = lifecycle_provider
        self.rng = rng
        self._clock = clock or time.time
        # 低 m 子额度 / 主额度按日滚动（进程内，跨重启重置）。
        self._day: Optional[Any] = None
        self._main_used = 0
        self._low_used = 0

    # ── 配置 ───────────────────────────────────────────

    def resolve_params(self, scene_cfg: Optional[dict]) -> dict[str, Any]:
        return resolve_params(scene_cfg)

    # ── 阶段一：候选召回 ───────────────────────────────

    def recall(self, params: dict[str, Any], now: Optional[float] = None) -> list[ResurfaceProposal]:
        """召回 dormant 话题并按上下文相关度粗筛（确定性，无随机）。"""
        moment = self._clock() if now is None else float(now)
        lifecycle = self._lifecycle() if self._lifecycle_provider else None
        if lifecycle is None or not lifecycle.is_enabled():
            return []
        tracker = lifecycle.tracker
        reference = self._context_reference(tracker, moment)
        floor = float(params["context_candidate_floor"])
        cap_hours = max(1e-6, float(params["dormancy_cap_hours"]))

        proposals: list[ResurfaceProposal] = []
        for topic in getattr(tracker, "topics", []):
            if str(getattr(topic, "lifecycle", "active")) != "dormant":
                continue
            relevance = self._relevance(topic, reference, params)
            if relevance < floor:
                continue
            interest = clamp01(float(getattr(topic, "interest_score", 0.0)))
            since = getattr(topic, "dormancy_since", None) or getattr(
                topic, "last_active_at", moment
            )
            dormancy_hours = max(0.0, (moment - float(since)) / 3600.0)
            dormancy = clamp01(dormancy_hours / cap_hours)
            m = self._modulation(interest, dormancy, relevance, params)
            proposals.append(
                ResurfaceProposal(
                    topic_id=str(getattr(topic, "id", "")),
                    subject=str(getattr(topic, "subject", "") or ""),
                    context=self._context_text(topic),
                    interest=interest,
                    dormancy=dormancy,
                    relevance=relevance,
                    m=m,
                    p=emit_probability(
                        m,
                        reference=float(params["m_midpoint"]),
                        tau=float(params["tau"]),
                        floor=float(params["p_floor"]),
                        ceiling=float(params["p_ceiling"]),
                    ),
                    is_low=m < float(params["low_m_threshold"]),
                )
            )
        return proposals

    def propose(self, params: dict[str, Any], now: Optional[float] = None) -> Optional[ResurfaceProposal]:
        """取 m 最大的候选（确定性，未采样）。"""
        candidates = self.recall(params, now)
        if not candidates:
            return None
        return max(candidates, key=lambda c: (c.m, c.interest))

    # ── 阶段二：概率发射（唯一采样点）──────────────────

    def decide(self, params: dict[str, Any], now: Optional[float] = None) -> Optional[ResurfaceProposal]:
        """召回 → 取最优候选 → 采样一次决定是否发射。无候选返回 None。"""
        proposal = self.propose(params, now)
        if proposal is None:
            return None
        proposal.emitted = sample_once(proposal.p, self.rng)
        return proposal

    # ── 额度：主额度 + 低 m 子额度 ─────────────────────

    def budget_allows(
        self, is_low: bool, params: dict[str, Any], now: Optional[float] = None
    ) -> bool:
        """低 m 用子额度、高 m 用主额度，二者互不挤占。"""
        self._roll_day(self._clock() if now is None else float(now))
        if is_low:
            return self._low_used < int(params["low_m_budget"])
        return self._main_used < int(params["main_budget"])

    def consume(
        self, is_low: bool, params: dict[str, Any], now: Optional[float] = None
    ) -> None:
        self._roll_day(self._clock() if now is None else float(now))
        if is_low:
            self._low_used += 1
        else:
            self._main_used += 1

    # ── 复现命中后的状态复位 ───────────────────────────

    def mark_resurfaced(
        self, proposal: ResurfaceProposal, now: Optional[float] = None
    ) -> None:
        """把被复现的话题迁回 active，避免同一话题被反复选中。"""
        lifecycle = self._lifecycle() if self._lifecycle_provider else None
        if lifecycle is None:
            return
        try:
            lifecycle.reactivate(
                proposal.topic_id,
                now=self._clock() if now is None else float(now),
            )
        except Exception:
            logger.debug("topic resurface reactivate failed", exc_info=True)

    # ── 内部辅助 ───────────────────────────────────────

    def _lifecycle(self) -> Any:
        try:
            return self._lifecycle_provider() if self._lifecycle_provider else None
        except Exception:
            logger.debug("topic lifecycle provider failed", exc_info=True)
            return None

    def _roll_day(self, now: float) -> None:
        today = datetime.fromtimestamp(now).date()
        if today != self._day:
            self._day = today
            self._main_used = 0
            self._low_used = 0

    @staticmethod
    def _modulation(
        interest: float,
        dormancy: float,
        relevance: float,
        params: dict[str, Any],
    ) -> float:
        """加权几何平均：m = interest^wi * dormancy^wd * relevance^wc。"""

        def _pow(base: float, weight: float) -> float:
            if weight <= 0:
                return 1.0
            return max(0.0, float(base)) ** weight

        m = (
            _pow(interest, float(params["interest_weight"]))
            * _pow(dormancy, float(params["dormancy_weight"]))
            * _pow(relevance, float(params["context_weight"]))
        )
        return clamp01(m)

    @staticmethod
    def _context_reference(tracker: Any, now: float) -> str:
        """当前上下文指纹：最近的 active 话题；无则空串（走中性兜底）。"""
        try:
            active = tracker.active_topic(now)
        except Exception:
            active = None
        return TopicResurface._fingerprint(active) if active is not None else ""

    @staticmethod
    def _relevance(topic: Any, reference: str, params: dict[str, Any]) -> float:
        if not reference:
            return clamp01(float(params["relevance_default"]))
        return clamp01(similarity(TopicResurface._fingerprint(topic), reference))

    @staticmethod
    def _fingerprint(topic: Any) -> str:
        if topic is None:
            return ""
        return " ".join(
            str(part)
            for part in (
                getattr(topic, "subject", ""),
                getattr(topic, "last_context", ""),
                getattr(topic, "summary", ""),
                getattr(topic, "stub", ""),
            )
            if part
        )

    @staticmethod
    def _context_text(topic: Any) -> str:
        base = (
            getattr(topic, "stub", "")
            or getattr(topic, "summary", "")
            or getattr(topic, "last_context", "")
            or ""
        )
        subject = str(getattr(topic, "subject", "") or "")
        head = str(base).strip()
        if head:
            return f"[话题：{subject}] {head}"
        return f"[话题：{subject}]"

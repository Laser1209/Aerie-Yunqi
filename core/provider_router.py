"""Aerie · 云栖 v0.1.0-beta.1 — Provider 复杂度评估 (S2 M2.1).

基于 5 个维度的加权评分，将消息分为 5 档复杂度：
  1. TRIVIAL  (0-20)   — 极简：单字回复、表情、确认
  2. SIMPLE   (20-40)  — 简单：日常对话、简短问答
  3. MEDIUM   (40-60)  — 中等：一般聊天、简单工具调用
  4. COMPLEX  (60-80)  — 复杂：长文、多轮推理、代码生成
  5. DEEP     (80-100) — 深度：研究、长文写作、复杂系统设计

5 个评分维度（权重可调）：
  - message_length    (0.15)  消息长度
  - context_depth     (0.20)  上下文深度（历史轮数 + 记忆命中）
  - multimodal        (0.15)  多模态（图片/语音/文件）
  - reasoning_signal  (0.25)  推理需求（关键词检测：为什么/分析/对比/代码等）
  - writing_length    (0.25)  写作长度预期（关键词：写一篇/报告/方案等）

混合模式：
  - 快速路径: 分数不在边界区间 → 直接返回档位
  - 仲裁路径: 分数在边界 ±10% → 调用轻量 LLM 二次确认
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)


# ── Complexity Levels ────────────────────────────────

class ComplexityLevel(str, Enum):
    TRIVIAL = "trivial"    # 极简
    SIMPLE = "simple"      # 简单
    MEDIUM = "medium"      # 中等
    COMPLEX = "complex"    # 复杂
    DEEP = "deep"          # 深度


LEVEL_ORDER = [
    ComplexityLevel.TRIVIAL,
    ComplexityLevel.SIMPLE,
    ComplexityLevel.MEDIUM,
    ComplexityLevel.COMPLEX,
    ComplexityLevel.DEEP,
]

LEVEL_THRESHOLDS = {
    ComplexityLevel.TRIVIAL: 15,
    ComplexityLevel.SIMPLE: 35,
    ComplexityLevel.MEDIUM: 55,
    ComplexityLevel.COMPLEX: 68,
    ComplexityLevel.DEEP: 100,
}


# ── Scoring DTO ─────────────────────────────────────

@dataclass
class ComplexityScore:
    """复杂度评分详情."""
    total: float = 0.0
    message_length: float = 0.0
    context_depth: float = 0.0
    multimodal: float = 0.0
    reasoning_signal: float = 0.0
    writing_length: float = 0.0
    level: ComplexityLevel = ComplexityLevel.MEDIUM
    used_arbiter: bool = False
    arbiter_reason: str = ""
    dimension_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# ── Dimension Weights (可配置) ───────────────────────

DEFAULT_WEIGHTS = {
    "message_length": 0.15,
    "context_depth": 0.20,
    "multimodal": 0.10,
    "reasoning_signal": 0.30,
    "writing_length": 0.25,
}

# 边界区间宽度 (±10%)
BOUNDARY_TOLERANCE = 0.10


# ── Reasoning Keywords ───────────────────────────────

REASONING_KEYWORDS = {
    "high": [
        "为什么", "原因", "分析", "对比", "比较", "区别",
        "代码", "编程", "实现", "算法", "架构", "设计",
        "优化", "调试", "bug", "错误", "问题",
        "研究", "方案", "策略", "规划", "路线图",
        "复杂", "深入", "详细", "全面",
    ],
    "medium": [
        "怎么", "如何", "怎么办", "建议", "推荐",
        "解释", "说明", "介绍", "步骤", "流程",
        "列表", "清单", "汇总", "总结",
    ],
    "low": [
        "什么", "谁", "哪里", "什么时候",
        "可以", "能", "会不会",
    ],
}

WRITING_KEYWORDS = {
    "high": [
        "写一篇", "写一份", "撰写", "报告", "论文", "研究",
        "方案", "计划书", "规格", "设计文档", "白皮书",
        "长篇", "万字", "详细写", "深度分析", "系统设计",
        "架构设计", "完整方案",
    ],
    "medium": [
        "写个", "写一段", "生成", "创建",
        "邮件", "消息", "文案", "简介",
        "日记", "记录", "笔记",
    ],
    "low": [
        "回复", "回答", "说一下", "告诉我",
    ],
}


# ── Provider Router ──────────────────────────────────

class ProviderRouter:
    """
    Provider 智能路由 (v11.1.0 S2).

    根据消息复杂度 + 预算状态选择合适的 Provider。

    用法::

        router = ProviderRouter(brain=companion.brain)
        score = router.evaluate(msg, context=...)
        provider_name = router.select_provider(score, budget_status="normal")
    """

    def __init__(
        self,
        brain: Any = None,
        weights: Dict[str, float] | None = None,
        boundary_tolerance: float = BOUNDARY_TOLERANCE,
        arbiter_enabled: bool = True,
        arbiter_provider_name: str | None = None,
    ) -> None:
        self.brain = brain
        self.weights = weights or DEFAULT_WEIGHTS
        self.boundary_tolerance = boundary_tolerance
        self.arbiter_enabled = arbiter_enabled
        self.arbiter_provider_name = arbiter_provider_name

        # 预编译正则
        self._reasoning_high_re = re.compile(
            "|".join(re.escape(k) for k in REASONING_KEYWORDS["high"]),
            re.IGNORECASE,
        )
        self._reasoning_medium_re = re.compile(
            "|".join(re.escape(k) for k in REASONING_KEYWORDS["medium"]),
            re.IGNORECASE,
        )
        self._reasoning_low_re = re.compile(
            "|".join(re.escape(k) for k in REASONING_KEYWORDS["low"]),
            re.IGNORECASE,
        )
        self._writing_high_re = re.compile(
            "|".join(re.escape(k) for k in WRITING_KEYWORDS["high"]),
            re.IGNORECASE,
        )
        self._writing_medium_re = re.compile(
            "|".join(re.escape(k) for k in WRITING_KEYWORDS["medium"]),
            re.IGNORECASE,
        )
        self._writing_low_re = re.compile(
            "|".join(re.escape(k) for k in WRITING_KEYWORDS["low"]),
            re.IGNORECASE,
        )

    # ── Public API ────────────────────────────────

    def evaluate_sync(
        self,
        message_text: str,
        context_turns: int = 0,
        memory_hits: int = 0,
        attachments: list[dict] | None = None,
        route_mode: str = "FULL",
    ) -> ComplexityScore:
        """
        同步评估复杂度（快速路径，不调用 LLM 仲裁）。

        Args:
            message_text: 用户消息文本
            context_turns: 上下文轮数（历史消息数 / 2）
            memory_hits: 记忆命中数
            attachments: 附件列表
            route_mode: FULL / AUTO / BASIC

        Returns:
            ComplexityScore 评分详情
        """
        score = ComplexityScore()

        # 1. 消息长度
        score.message_length = self._score_message_length(message_text)
        score.dimension_details["message_length"] = {
            "raw": len(message_text),
            "weight": self.weights["message_length"],
        }

        # 2. 上下文深度
        score.context_depth = self._score_context_depth(context_turns, memory_hits)
        score.dimension_details["context_depth"] = {
            "context_turns": context_turns,
            "memory_hits": memory_hits,
            "weight": self.weights["context_depth"],
        }

        # 3. 多模态
        score.multimodal = self._score_multimodal(attachments)
        score.dimension_details["multimodal"] = {
            "attachment_count": len(attachments) if attachments else 0,
            "weight": self.weights["multimodal"],
        }

        # 4. 推理信号
        reasoning_score, reasoning_details = self._score_reasoning(message_text)
        score.reasoning_signal = reasoning_score
        score.dimension_details["reasoning_signal"] = {
            **reasoning_details,
            "weight": self.weights["reasoning_signal"],
        }

        # 5. 写作长度预期
        writing_score, writing_details = self._score_writing(message_text)
        score.writing_length = writing_score
        score.dimension_details["writing_length"] = {
            **writing_details,
            "weight": self.weights["writing_length"],
        }

        # 计算总分 (加权平均 × 100)
        total = (
            score.message_length * self.weights["message_length"]
            + score.context_depth * self.weights["context_depth"]
            + score.multimodal * self.weights["multimodal"]
            + score.reasoning_signal * self.weights["reasoning_signal"]
            + score.writing_length * self.weights["writing_length"]
        ) / sum(self.weights.values())

        score.total = round(total, 2)
        score.level = self._score_to_level(score.total)

        # BASIC 模式强制降级
        if route_mode == "BASIC":
            score.level = ComplexityLevel.TRIVIAL
            score.total = min(score.total, 10.0)

        return score

    async def evaluate(
        self,
        message_text: str,
        context_turns: int = 0,
        memory_hits: int = 0,
        attachments: list[dict] | None = None,
        route_mode: str = "FULL",
    ) -> ComplexityScore:
        """
        异步评估复杂度（快速路径 + 可选 LLM 仲裁）。

        如果分数落在边界区间且 arbiter_enabled=True，
        会调用 LLM 做二次确认。
        """
        score = self.evaluate_sync(
            message_text=message_text,
            context_turns=context_turns,
            memory_hits=memory_hits,
            attachments=attachments,
            route_mode=route_mode,
        )

        # 检查是否需要仲裁
        if self.arbiter_enabled and self._is_near_boundary(score.total) and self.brain:
            try:
                arbiter_level, reason = await self._llm_arbiter(
                    message_text, score.level
                )
                if arbiter_level and arbiter_level != score.level:
                    logger.info(
                        "Complexity arbiter: %s → %s (reason: %s)",
                        score.level.value, arbiter_level.value, reason,
                    )
                    score.level = arbiter_level
                    score.used_arbiter = True
                    score.arbiter_reason = reason
            except Exception:
                logger.exception("LLM arbiter failed, using rule-based score")

        return score

    def select_provider(
        self,
        score: ComplexityScore,
        budget_status: str = "normal",
        provider_configs: List[Dict[str, Any]] | None = None,
    ) -> str | None:
        """
        根据复杂度评分和预算状态选择 Provider。

        Args:
            score: 复杂度评分结果
            budget_status: "normal" | "low" | "critical"
            provider_configs: Provider 配置列表，每项含 name, tier, cost_level

        Returns:
            选中的 Provider 名称，None 表示没有可用 Provider
        """
        if provider_configs is None:
            # 从 brain 中获取
            if self.brain and hasattr(self.brain, "_providers"):
                provider_configs = [
                    {"name": p.get("name", ""), "tier": p.get("tier", "medium"),
                     "cost_level": p.get("cost_level", "medium")}
                    for p in self.brain._providers
                ]
            else:
                provider_configs = []

        if not provider_configs:
            return None

        # 预算紧张时调整 tier 选择优先级
        target_tiers = self._level_to_tiers(score.level)
        if budget_status == "low":
            # low 预算: 优先尝试低一档
            target_tiers = self._shift_tiers_down(target_tiers, 1)
        elif budget_status == "critical":
            # critical 预算: 直接用最低档
            target_tiers = ["low", "medium", "high"]

        # 优先选匹配 tier 的第一个
        for tier in target_tiers:
            for cfg in provider_configs:
                if cfg.get("tier") == tier or cfg.get("cost_level") == tier:
                    return cfg.get("name")

        # 没有匹配的，返回第一个
        return provider_configs[0].get("name") if provider_configs else None

    # ── Scoring Dimensions ─────────────────────────

    def _score_message_length(self, text: str) -> float:
        """消息长度评分: 0-100."""
        length = len(text)
        if length <= 3:
            return 5.0
        elif length <= 10:
            return 12.0
        elif length <= 30:
            return 25.0
        elif length <= 80:
            return 40.0
        elif length <= 150:
            return 55.0
        elif length <= 300:
            return 70.0
        elif length <= 500:
            return 82.0
        else:
            return 95.0

    def _score_context_depth(self, turns: int, memory_hits: int) -> float:
        """上下文深度评分: 0-100."""
        turn_score = min(turns * 8, 50)  # 每轮 8 分，最多 50
        memory_score = min(memory_hits * 12, 35)  # 每条记忆 12 分，最多 35
        base = 5.0  # 保底 5 分
        return min(base + turn_score + memory_score, 100)

    def _score_multimodal(self, attachments: list[dict] | None) -> float:
        """多模态评分: 0-100."""
        if not attachments:
            return 0.0
        count = len(attachments)
        # 图片/视频权重更高
        has_image = any(
            a.get("type") in ("image", "photo", "picture")
            for a in attachments
        )
        has_video = any(
            a.get("type") in ("video", "video_file")
            for a in attachments
        )
        has_file = any(
            a.get("type") in ("file", "document", "pdf", "doc")
            for a in attachments
        )

        base = min(count * 20, 60)
        if has_image:
            base += 15
        if has_video:
            base += 25
        if has_file:
            base += 20
        return min(base, 100)

    def _score_reasoning(self, text: str) -> Tuple[float, Dict[str, Any]]:
        """推理信号评分: 0-100.

        采用"起步分 + 加成"模式，而不是线性计数，
        确保只要有推理需求就能拿到合理的基础分。
        """
        details = {"high_hits": 0, "medium_hits": 0, "low_hits": 0}

        high_matches = self._reasoning_high_re.findall(text)
        medium_matches = self._reasoning_medium_re.findall(text)
        low_matches = self._reasoning_low_re.findall(text)

        details["high_hits"] = len(high_matches)
        details["medium_hits"] = len(medium_matches)
        details["low_hits"] = len(low_matches)

        # 起步分：按最高档位给基础分
        if len(high_matches) > 0:
            base = 65.0  # 有高优关键词，起步 65 分
            bonus = min(len(high_matches) * 8, 20)  # 每个额外 +8，最多 +20
            score = base + bonus
        elif len(medium_matches) > 0:
            base = 40.0  # 有中优关键词，起步 40 分
            bonus = min(len(medium_matches) * 6, 15)
            score = base + bonus
        elif len(low_matches) > 0:
            base = 20.0  # 有低优关键词，起步 20 分
            bonus = min(len(low_matches) * 3, 10)
            score = base + bonus
        else:
            score = 10.0  # 无关键词，给 10 分保底

        return min(score, 100), details

    def _score_writing(self, text: str) -> Tuple[float, Dict[str, Any]]:
        """写作长度预期评分: 0-100."""
        details = {"high_hits": 0, "medium_hits": 0, "low_hits": 0}

        high_matches = self._writing_high_re.findall(text)
        medium_matches = self._writing_medium_re.findall(text)
        low_matches = self._writing_low_re.findall(text)

        details["high_hits"] = len(high_matches)
        details["medium_hits"] = len(medium_matches)
        details["low_hits"] = len(low_matches)

        if len(high_matches) > 0:
            base = 82.0
            bonus = min(len(high_matches) * 7, 16)
            score = base + bonus
        elif len(medium_matches) > 0:
            base = 40.0
            bonus = min(len(medium_matches) * 8, 20)
            score = base + bonus
        elif len(low_matches) > 0:
            base = 15.0
            bonus = min(len(low_matches) * 3, 10)
            score = base + bonus
        else:
            score = 5.0

        return min(score, 100), details

    # ── Helpers ────────────────────────────────────

    def _score_to_level(self, score: float) -> ComplexityLevel:
        """分数转复杂度等级."""
        if score < LEVEL_THRESHOLDS[ComplexityLevel.TRIVIAL]:
            return ComplexityLevel.TRIVIAL
        elif score < LEVEL_THRESHOLDS[ComplexityLevel.SIMPLE]:
            return ComplexityLevel.SIMPLE
        elif score < LEVEL_THRESHOLDS[ComplexityLevel.MEDIUM]:
            return ComplexityLevel.MEDIUM
        elif score < LEVEL_THRESHOLDS[ComplexityLevel.COMPLEX]:
            return ComplexityLevel.COMPLEX
        else:
            return ComplexityLevel.DEEP

    def _is_near_boundary(self, score: float) -> bool:
        """检查分数是否在边界附近（需要仲裁）."""
        tol = self.boundary_tolerance * 100  # 转为 0-100 尺度
        for threshold in LEVEL_THRESHOLDS.values():
            if abs(score - threshold) <= tol:
                return True
        return False

    def _downgrade_level(self, level: ComplexityLevel, steps: int) -> ComplexityLevel:
        """降级复杂度等级（预算不足时）."""
        idx = LEVEL_ORDER.index(level)
        new_idx = max(0, idx - steps)
        return LEVEL_ORDER[new_idx]

    def _level_to_tiers(self, level: ComplexityLevel) -> List[str]:
        """复杂度等级 → 推荐 Provider tier 列表（从优到次）."""
        if level in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE):
            return ["low", "medium", "high"]
        elif level == ComplexityLevel.MEDIUM:
            return ["medium", "low", "high"]
        elif level == ComplexityLevel.COMPLEX:
            return ["high", "medium", "low"]
        else:  # DEEP
            return ["high", "medium", "low"]

    def _shift_tiers_down(self, tiers: List[str], steps: int) -> List[str]:
        """将 tier 偏好列表向下移动 n 档（预算不足时用）."""
        tier_order = ["low", "medium", "high"]
        result = []
        for tier in tiers:
            if tier in tier_order:
                idx = tier_order.index(tier)
                new_idx = max(0, idx - steps)
                result.append(tier_order[new_idx])
            else:
                result.append(tier)
        # 去重保持顺序
        seen = set()
        unique = []
        for t in result:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        # 确保所有 tier 都在列表里
        for t in tier_order:
            if t not in unique:
                unique.append(t)
        return unique

    # ── LLM Arbiter ────────────────────────────────

    async def _llm_arbiter(
        self, message_text: str, current_level: ComplexityLevel,
    ) -> Tuple[Optional[ComplexityLevel], str]:
        """
        LLM 仲裁器：对边界 case 进行二次确认。

        使用轻量提示词，让模型判断消息应该属于哪个复杂度档位。
        """
        if not self.brain:
            return None, "no brain available"

        levels_desc = "\n".join([
            "trivial (极简): 单字、表情、确认类消息，几乎不需要思考",
            "simple (简单): 日常对话、简单问答，一两句话就能回答",
            "medium (中等): 一般聊天、简单工具调用，需要适度思考",
            "complex (复杂): 长文分析、代码生成、多步骤推理",
            "deep (深度): 长篇写作、系统设计、复杂研究、深度分析",
        ])

        system = f"""你是一个复杂度评估助手。根据用户消息，判断它属于哪个复杂度等级。

复杂度等级定义：
{levels_desc}

只回答等级名称（trivial/simple/medium/complex/deep），不要解释。"""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message_text[:500]},
        ]

        try:
            response = await self.brain.chat(messages, tools=None)
            raw = response.text.strip().lower()

            # 解析结果
            for level in LEVEL_ORDER:
                if level.value in raw:
                    return level, f"arbiter said: {raw[:50]}"

            return None, f"unparsed response: {raw[:50]}"
        except Exception as e:
            return None, f"error: {str(e)[:50]}"

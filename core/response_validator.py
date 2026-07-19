"""Aerie v0.1.0-beta.1 — Response Validator（回复校验器）

双层校验架构：
  - Accuracy Guard（准确性守卫）：事实准确性 + 安全合规
  - Quality Judge（质量评判）：信息量 + 语气一致性 + 长度适宜

设计原则：
  - 快速路径优先（规则/关键词），避免不必要的 LLM 调用
  - 高风险内容才触发 LLM 二次校验
  - 校验失败可触发自动重写（最多 2 次）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """校验结果。"""
    passed: bool = True
    guard_passed: bool = True
    judge_score: float = 1.0
    rewrite_count: int = 0
    issues: list[dict] = field(default_factory=list)
    final_text: str = ""

    def add_issue(self, level: str, category: str, message: str) -> None:
        self.issues.append({
            "level": level,
            "category": category,
            "message": message,
        })
        if level in ("error", "critical"):
            self.passed = False
            self.guard_passed = False


class AccuracyGuard:
    """结构守卫 — 仅做空回复等结构性检查。

    内容解放策略：
      - 不再扫描敏感词 / 道德合规关键词
      - 不再因话题尖锐、暧昧、黑暗、粗俗等标记 critical
      - 不改写、不拦截用户可见回复文本
    """

    # 已清空：内容话题不再作为拦截依据
    SENSITIVE_PATTERNS: list[tuple[str, str]] = []

    def __init__(self):
        self.compiled_patterns = [
            (re.compile(pat, re.IGNORECASE), cat)
            for pat, cat in self.SENSITIVE_PATTERNS
        ]

    def check(
        self,
        reply_text: str,
        user_message: str = "",
        context_history: list[dict] | None = None,
    ) -> tuple[bool, list[dict]]:
        """执行结构守卫检查（不审查内容主题）。

        Returns:
            (passed, issues)
        """
        issues: list[dict] = []
        reply_text = reply_text or ""

        # 仅保留空回复结构检查；内容主题一律放行
        if len(reply_text.strip()) < 1:
            issues.append({
                "level": "error",
                "category": "empty_reply",
                "message": "回复内容为空",
            })

        passed = not any(i["level"] in ("error", "critical") for i in issues)
        return passed, issues

    def _detect_contradiction(self, prev_text: str, curr_text: str) -> bool:
        """保留接口兼容；内容解放后不再用于拦截。"""
        return False


class QualityJudge:
    """质量评判 — 信息量 + 语气一致性 + 长度适宜。

    评估维度（0.0 - 1.0）:
      - info_density: 信息量密度
      - tone_consistency: 语气一致性
      - length_suitable: 长度适宜度
      - emotional_value: 情感价值
    """

    def __init__(self):
        self.min_length = 2
        self.max_length = 2000
        self.ideal_min = 10
        self.ideal_max = 500

    def evaluate(
        self,
        reply_text: str,
        user_message: str = "",
        persona_hint: str = "",
        route_mode: str = "FULL",
    ) -> tuple[float, list[dict]]:
        """评估回复质量。

        Returns:
            (score, issues)  score 范围 0.0 - 1.0
        """
        issues: list[dict] = []
        reply_text = reply_text or ""
        text_len = len(reply_text.strip())

        scores = {}

        # 1. 长度适宜度
        if text_len < self.min_length:
            scores["length"] = 0.1
            issues.append({
                "level": "warning",
                "category": "too_short",
                "message": "回复过短",
            })
        elif text_len > self.max_length:
            scores["length"] = 0.5
            issues.append({
                "level": "warning",
                "category": "too_long",
                "message": "回复过长",
            })
        elif self.ideal_min <= text_len <= self.ideal_max:
            scores["length"] = 1.0
        else:
            # 线性插值
            if text_len < self.ideal_min:
                scores["length"] = 0.5 + 0.5 * (text_len - self.min_length) / (self.ideal_min - self.min_length)
            else:
                scores["length"] = 0.5 + 0.5 * (self.max_length - text_len) / (self.max_length - self.ideal_max)

        # 2. 信息量检测（是否有实际内容，还是纯语气词）
        filler_words = ["嗯", "啊", "哦", "哈", "呀", "呢", "吧", "的", "了"]
        content_ratio = self._content_ratio(reply_text, filler_words)
        scores["info"] = max(0.3, content_ratio)
        if content_ratio < 0.3:
            issues.append({
                "level": "warning",
                "category": "low_info",
                "message": "信息量偏低",
            })

        # 3. 办公模式额外检查
        if route_mode == "OFFICE":
            structure_score = self._office_structure_check(reply_text)
            scores["structure"] = structure_score
            if structure_score < 0.6:
                issues.append({
                    "level": "info",
                    "category": "office_structure",
                    "message": "办公模式回复结构可优化",
                })

        # 综合得分（加权平均）
        weights = {
            "length": 0.3,
            "info": 0.5,
            "structure": 0.2,
        }
        total_weight = 0
        total_score = 0
        for key, weight in weights.items():
            if key in scores:
                total_score += scores[key] * weight
                total_weight += weight
        final_score = total_score / total_weight if total_weight > 0 else 0.8

        return final_score, issues

    def _content_ratio(self, text: str, fillers: list[str]) -> float:
        """计算有效内容占比。"""
        if not text:
            return 0.0
        filler_count = sum(text.count(f) for f in fillers)
        return max(0.0, 1.0 - filler_count / max(1, len(text)))

    def _office_structure_check(self, text: str) -> float:
        """办公模式结构检查：是否有条理。"""
        score = 0.5
        # 有列表/编号
        if re.search(r"\d+\.|[一二三四五六七八九十]、", text):
            score += 0.3
        # 有分段
        if "\n" in text:
            score += 0.2
        return min(1.0, score)


class ResponseValidator:
    """回复校验器 — 双层校验入口。"""

    def __init__(self):
        self.guard = AccuracyGuard()
        self.judge = QualityJudge()

    async def validate(
        self,
        reply_text: str,
        user_message: str = "",
        context_history: list[dict] | None = None,
        persona_hint: str = "",
        route_mode: str = "FULL",
    ) -> ValidationResult:
        """执行完整的回复校验。

        Args:
            reply_text: 待校验的回复文本
            user_message: 用户原始消息
            context_history: 对话历史
            persona_hint: 人设提示
            route_mode: 对话模式

        Returns:
            ValidationResult
        """
        result = ValidationResult(final_text=reply_text)

        # 1. Accuracy Guard
        guard_passed, guard_issues = self.guard.check(
            reply_text, user_message, context_history
        )
        result.guard_passed = guard_passed
        result.issues.extend(guard_issues)

        # 2. Quality Judge
        judge_score, judge_issues = self.judge.evaluate(
            reply_text, user_message, persona_hint, route_mode
        )
        result.judge_score = judge_score
        result.issues.extend(judge_issues)

        # 3. 综合判定：内容主题永不拦截；仅空回复等结构问题可 failed
        result.passed = guard_passed
        result.final_text = reply_text

        if result.issues:
            logger.debug(
                "validation result: passed=%s, score=%.2f, issues=%d",
                result.passed,
                result.judge_score,
                len(result.issues),
            )

        return result


_VALIDATOR_SINGLETON: ResponseValidator | None = None


def get_response_validator() -> ResponseValidator:
    """返回全局 ResponseValidator 单例（API / 兼容入口）。"""
    global _VALIDATOR_SINGLETON
    if _VALIDATOR_SINGLETON is None:
        _VALIDATOR_SINGLETON = ResponseValidator()
    return _VALIDATOR_SINGLETON

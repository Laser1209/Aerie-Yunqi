"""Aerie v13.0 — Response Validator 回复校验机制

双层校验架构：
┌─────────────────────────────────────────────┐
│  Layer 1: Accuracy Guard 准确性闸门         │
│  - 事实核查（常识性错误检测）               │
│  - 安全合规（敏感内容 / 违规词检测）        │
│  - 自相矛盾检测（前后文一致性）             │
│  - 幻觉风险评分（未确定信息标记）           │
├─────────────────────────────────────────────┤
│  Layer 2: Quality Judge 质量评判           │
│  - 信息量评估（回答是否切题、完整）         │
│  - 语气一致性（是否符合人设）               │
│  - 长度适宜度（不过长也不太短）             │
│  - 情绪价值（是否提供正向情绪支持）         │
└─────────────────────────────────────────────┘

校验优先级：准确性 > 质量。不准确的回复直接拦截或修正。
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """校验结果严重程度"""
    PASS = "pass"           # 通过
    WARN = "warn"           # 警告（可放行，标记）
    BLOCK = "block"         # 拦截（需修正或拒绝）


@dataclass
class ValidationIssue:
    """单个校验问题"""
    code: str
    severity: ValidationSeverity
    message: str
    details: dict = field(default_factory=dict)
    layer: str = "guard"  # "guard" | "judge"


@dataclass
class ValidationResult:
    """完整校验结果"""
    passed: bool = True
    score: float = 1.0  # 0.0 ~ 1.0
    issues: list[ValidationIssue] = field(default_factory=list)
    guard_score: float = 1.0
    judge_score: float = 1.0
    needs_revision: bool = False
    revision_suggestion: str = ""
    # 供下游使用的元数据
    metadata: dict = field(default_factory=dict)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == ValidationSeverity.WARN for i in self.issues)

    @property
    def has_blocks(self) -> bool:
        return any(i.severity == ValidationSeverity.BLOCK for i in self.issues)


# ── Accuracy Guard ────────────────────────────

class AccuracyGuard:
    """第一层：准确性闸门

    负责安全合规、事实性基础检查、自相矛盾检测。
    不依赖 LLM（零延迟），用规则 + 关键词 + 启发式。
    """

    # 敏感/违规关键词（基础版，可扩展）
    _SENSITIVE_PATTERNS: list[tuple[str, str, ValidationSeverity]] = [
        # 违法违规
        (r"(\b|^)毒品\b|海洛因|冰毒|大麻", "illegal_drugs", ValidationSeverity.BLOCK),
        (r"自杀|自伤|割腕|跳楼", "self_harm", ValidationSeverity.BLOCK),
        (r"(\b|^)暴力\b|恐怖袭击|杀人", "violence", ValidationSeverity.WARN),
        # 虚假信息模式
        (r"绝对|100%|毫无疑问|肯定是|一定是", "absolute_claim", ValidationSeverity.WARN),
        (r"据我所知|可能是|好像|大概|也许|说不定", "uncertain_claim", ValidationSeverity.WARN),
    ]

    # 医疗/法律/财务等专业领域免责提示触发词
    _PROFESSIONAL_DOMAINS = {
        "medical": ["医生", "医院", "药", "病", "症状", "诊断", "治疗", "手术"],
        "legal": ["法律", "律师", "法院", "诉讼", "合同", "违法", "判刑"],
        "financial": ["股票", "基金", "投资", "理财", "赚钱", "彩票"],
    }

    def __init__(self) -> None:
        self._compiled_patterns = []
        for pattern, code, severity in self._SENSITIVE_PATTERNS:
            self._compiled_patterns.append((re.compile(pattern, re.IGNORECASE), code, severity))

    def check(self, text: str, context: dict | None = None) -> list[ValidationIssue]:
        """执行准确性检查

        Args:
            text: 待校验的回复文本
            context: 上下文信息（user_message, history 等）

        Returns:
            问题列表
        """
        issues: list[ValidationIssue] = []
        text = text or ""
        if not text.strip():
            issues.append(ValidationIssue(
                code="empty_response",
                severity=ValidationSeverity.BLOCK,
                message="回复内容为空",
                layer="guard",
            ))
            return issues

        # 1. 敏感内容检测
        for pattern, code, severity in self._compiled_patterns:
            matches = pattern.findall(text)
            if matches:
                count = len(matches)
                issues.append(ValidationIssue(
                    code=code,
                    severity=severity,
                    message=f"检测到敏感内容（{count}处）",
                    details={"matches": [str(m) for m in matches[:5]], "count": count},
                    layer="guard",
                ))

        # 2. 专业领域免责声明检查
        domain_hits = {}
        for domain, keywords in self._PROFESSIONAL_DOMAINS.items():
            hits = [kw for kw in keywords if kw in text]
            if hits:
                domain_hits[domain] = hits
        if domain_hits:
            has_disclaimer = any(kw in text for kw in ["仅供参考", "建议咨询", "不能替代", "请咨询专业"])
            if not has_disclaimer:
                issues.append(ValidationIssue(
                    code="professional_without_disclaimer",
                    severity=ValidationSeverity.WARN,
                    message=f"涉及专业领域但缺少免责声明: {', '.join(domain_hits.keys())}",
                    details={"domains": list(domain_hits.keys())},
                    layer="guard",
                ))

        # 3. 自相矛盾检测（简单版：检测明显的正反词同时出现）
        contradictions = self._detect_contradiction(text)
        for cont in contradictions:
            issues.append(ValidationIssue(
                code="contradiction",
                severity=ValidationSeverity.WARN,
                message=f"可能存在自相矛盾: {cont}",
                details={"pair": cont},
                layer="guard",
            ))

        # 4. 数字/事实夸大检测
        exaggeration = self._detect_exaggeration(text)
        if exaggeration:
            issues.append(ValidationIssue(
                code="exaggeration",
                severity=ValidationSeverity.WARN,
                message="可能存在数字夸大",
                details={"examples": exaggeration[:3]},
                layer="guard",
            ))

        return issues

    def _detect_contradiction(self, text: str) -> list[str]:
        """简单自相矛盾检测"""
        pairs = [
            ("是", "不是"),
            ("可以", "不可以"),
            ("能", "不能"),
            ("会", "不会"),
            ("好", "不好"),
            ("对", "不对"),
        ]
        hits = []
        for pos, neg in pairs:
            if pos in text and neg in text:
                # 简单的位置检查：如果相隔很远，可能是不同语境
                pos_idx = text.find(pos)
                neg_idx = text.find(neg)
                if abs(pos_idx - neg_idx) < 200:
                    hits.append(f"{pos}/{neg}")
        return hits

    def _detect_exaggeration(self, text: str) -> list[str]:
        """数字夸大检测"""
        # 匹配"数字 + 倍/万/亿/%"等，检查是否有极端数字
        pattern = r"\d+(\.\d+)?\s*(倍|万|亿|%|千元|万元|亿元|次|个)"
        matches = re.findall(pattern, text)
        examples = []
        for m in matches[:5]:
            full_match = m[0] + m[1] if isinstance(m, tuple) else m
            # 检查是否有极端数字
            num_match = re.search(r"\d+(\.\d+)?", str(full_match))
            if num_match:
                num = float(num_match.group())
                if num > 10000 or num > 100 and "倍" in str(full_match):
                    examples.append(str(full_match))
        return examples


# ── Quality Judge ────────────────────────────

class QualityJudge:
    """第二层：质量评判

    评估回复的信息量、语气一致性、长度适宜度、情绪价值。
    同样用规则 + 启发式，零延迟。
    """

    def __init__(self) -> None:
        # 人设语气关键词（根据人设动态调整，这里是默认值）
        self._persona_keywords = {
            "warmth": ["宝贝", "亲爱的", "呢", "呀", "啦", "嘛", "～", "~"],
            "cold": ["哼", "切", "无聊", "随便"],
            "formal": ["您好", "请", "谢谢", "抱歉", "敬请"],
        }

    def check(
        self,
        text: str,
        user_message: str = "",
        persona_style: str = "warm",
        office_mode: bool = False,
    ) -> tuple[list[ValidationIssue], float]:
        """执行质量评估

        Returns:
            (问题列表, 质量评分 0~1)
        """
        issues: list[ValidationIssue] = []
        text = text or ""
        char_count = len(text.strip())

        # 1. 长度评估
        length_score = self._score_length(char_count, user_message, office_mode)
        if length_score < 0.6:
            if char_count < 10:
                issues.append(ValidationIssue(
                    code="too_short",
                    severity=ValidationSeverity.WARN,
                    message=f"回复过短（{char_count}字），信息量可能不足",
                    details={"char_count": char_count},
                    layer="judge",
                ))
            elif char_count > 2000:
                issues.append(ValidationIssue(
                    code="too_long",
                    severity=ValidationSeverity.WARN,
                    message=f"回复过长（{char_count}字），建议精简",
                    details={"char_count": char_count},
                    layer="judge",
                ))

        # 2. 信息量 / 切题度（简单启发式：是否回应用户问题）
        relevance_score = self._score_relevance(text, user_message)
        if relevance_score < 0.5:
            issues.append(ValidationIssue(
                code="low_relevance",
                severity=ValidationSeverity.WARN,
                message="回复可能与用户问题关联度较低",
                details={"relevance_score": relevance_score},
                layer="judge",
            ))

        # 3. 语气一致性
        tone_score = self._score_tone(text, persona_style, office_mode)
        if tone_score < 0.5:
            issues.append(ValidationIssue(
                code="tone_mismatch",
                severity=ValidationSeverity.WARN,
                message="语气风格与当前模式不太匹配",
                details={"expected": persona_style, "score": tone_score},
                layer="judge",
            ))

        # 4. 情绪价值（陪伴模式下评估）
        emotion_score = self._score_emotion_value(text, persona_style)
        if not office_mode and emotion_score < 0.4:
            issues.append(ValidationIssue(
                code="low_emotion_value",
                severity=ValidationSeverity.WARN,
                message="情绪价值偏低，可增加温度",
                details={"score": emotion_score},
                layer="judge",
            ))

        # 综合评分
        quality_score = (length_score * 0.25 + relevance_score * 0.35
                         + tone_score * 0.25 + emotion_score * 0.15)
        quality_score = max(0.0, min(1.0, quality_score))

        return issues, round(quality_score, 3)

    def _score_length(self, char_count: int, user_message: str, office_mode: bool) -> float:
        """长度评分"""
        if char_count == 0:
            return 0.0

        user_len = len(user_message) if user_message else 0

        # 办公模式：信息密度优先，长度适中偏长也 OK
        if office_mode:
            if 50 <= char_count <= 1500:
                return 1.0
            elif char_count < 50:
                return char_count / 50
            else:
                return max(0.5, 1.0 - (char_count - 1500) / 1500)

        # 聊天模式：不需要太长，自然对话
        if user_len > 0:
            ratio = char_count / user_len
            if 0.5 <= ratio <= 3.0:
                return 1.0
            elif ratio < 0.5:
                return max(0.3, ratio / 0.5)
            else:
                return max(0.4, 1.0 - (ratio - 3.0) / 5.0)

        if 10 <= char_count <= 200:
            return 1.0
        elif char_count < 10:
            return char_count / 10
        else:
            return max(0.5, 1.0 - (char_count - 200) / 800)

    def _score_relevance(self, text: str, user_message: str) -> float:
        """切题度评分（关键词重叠启发式）"""
        if not user_message or not text:
            return 0.5

        # 提取用户问题中的关键词（简单分词：2字以上的词）
        user_words = set()
        for i in range(len(user_message) - 1):
            word = user_message[i:i+2]
            if any('\u4e00' <= c <= '\u9fff' for c in word):
                user_words.add(word)

        if not user_words:
            return 0.5

        # 检查回复中是否包含这些词
        hit_count = sum(1 for w in user_words if w in text)
        ratio = hit_count / len(user_words)

        # 惩罚完全无重叠
        if ratio < 0.1:
            return 0.3
        return min(1.0, 0.5 + ratio * 0.5)

    def _score_tone(self, text: str, persona_style: str, office_mode: bool) -> float:
        """语气一致性评分"""
        if office_mode:
            # 办公模式：专业、结构化
            formal_count = sum(1 for kw in self._persona_keywords["formal"] if kw in text)
            has_structure = bool(re.search(r"[1-9][\.\、]|第.点|首先|其次|最后|总结", text))
            score = 0.5 + formal_count * 0.1
            if has_structure:
                score += 0.2
            return min(1.0, score)

        # 陪伴模式：温暖感
        if persona_style == "warm":
            warm_hits = sum(1 for kw in self._persona_keywords["warmth"] if kw in text)
            return min(1.0, 0.4 + warm_hits * 0.12)

        return 0.6

    def _score_emotion_value(self, text: str, persona_style: str) -> float:
        """情绪价值评分"""
        # 正向情绪词
        positive_words = ["开心", "快乐", "喜欢", "爱", "温暖", "幸福", "抱抱", "摸摸头",
                          "支持你", "陪着你", "相信你", "加油", "没事", "没关系", "懂你"]
        # 负向情绪词
        negative_words = ["无聊", "烦", "难过", "伤心", "生气", "讨厌", "滚", "闭嘴"]

        pos_count = sum(1 for w in positive_words if w in text)
        neg_count = sum(1 for w in negative_words if w in text)

        score = 0.5 + pos_count * 0.1 - neg_count * 0.15
        return max(0.0, min(1.0, score))


# ── Validator 总控 ────────────────────────────

class ResponseValidator:
    """回复校验总控

    执行流程：Guard → Judge → 综合评分
    """

    def __init__(self) -> None:
        self.guard = AccuracyGuard()
        self.judge = QualityJudge()
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def validate(
        self,
        response_text: str,
        user_message: str = "",
        context: dict | None = None,
        persona_style: str = "warm",
        office_mode: bool = False,
    ) -> ValidationResult:
        """执行完整的双层校验

        Args:
            response_text: AI 回复文本
            user_message: 用户原始消息
            context: 上下文（history 等）
            persona_style: 人设风格 warm/cold/formal
            office_mode: 是否办公模式

        Returns:
            ValidationResult
        """
        if not self._enabled:
            return ValidationResult(passed=True, score=1.0)

        result = ValidationResult()
        all_issues: list[ValidationIssue] = []

        # Layer 1: Accuracy Guard
        guard_issues = self.guard.check(response_text, context)
        all_issues.extend(guard_issues)

        guard_blocked = any(i.severity == ValidationSeverity.BLOCK for i in guard_issues)
        guard_warn_count = sum(1 for i in guard_issues if i.severity == ValidationSeverity.WARN)

        # Guard 评分：有 BLOCK 直接 0 分，每个 WARN 扣 0.1 分
        if guard_blocked:
            guard_score = 0.0
        else:
            guard_score = max(0.3, 1.0 - guard_warn_count * 0.1)
        result.guard_score = round(guard_score, 3)

        # Layer 2: Quality Judge
        judge_issues, judge_score = self.judge.check(
            response_text, user_message, persona_style, office_mode
        )
        all_issues.extend(judge_issues)
        result.judge_score = judge_score

        result.issues = all_issues
        result.passed = not guard_blocked
        result.needs_revision = guard_warn_count >= 2 or judge_score < 0.5

        # 综合评分（Guard 权重更高）
        total_score = guard_score * 0.6 + judge_score * 0.4
        result.score = round(max(0.0, min(1.0, total_score)), 3)

        # 生成修正建议
        if result.needs_revision or result.has_blocks:
            result.revision_suggestion = self._build_revision_suggestion(
                all_issues, response_text, office_mode
            )

        logger.debug(
            "validation: passed=%s, score=%.2f, guard=%.2f, judge=%.2f, issues=%d",
            result.passed, result.score, result.guard_score,
            result.judge_score, len(result.issues),
        )

        return result

    def _build_revision_suggestion(
        self, issues: list[ValidationIssue], text: str, office_mode: bool
    ) -> str:
        """生成修正建议"""
        suggestions = []
        for issue in issues:
            if issue.severity == ValidationSeverity.BLOCK:
                suggestions.append(f"[严重] {issue.message}")
            elif issue.severity == ValidationSeverity.WARN:
                suggestions.append(f"[建议] {issue.message}")

        if office_mode and len(text) < 50:
            suggestions.append("[建议] 办公模式下回复请更详细，增加结构化要点")

        if not suggestions:
            return ""

        return "\n".join(suggestions)


# ── 单例 ──────────────────────────────────────

_validator_instance: Optional[ResponseValidator] = None


def get_response_validator() -> ResponseValidator:
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = ResponseValidator()
    return _validator_instance

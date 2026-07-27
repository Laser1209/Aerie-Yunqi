"""Aerie · 云栖 v0.1.0-beta.1 — EmpathyStrategyChain: 共情响应策略链 (Task P1-A.3).

结构化共情响应五步骤:
    validate_input -> reflect -> clarify -> support -> next_step

设计要点:
  - 基于确定性中文关键词匹配识别情感, 不调用外部模型
  - 按情感类型选择激活的策略步骤, 保证固定执行顺序
  - 每步输出结构化结果 (step_name / content / emotion_detected)
  - 负面情感 (frustration/sadness/anger/fear) 自动 add_pain_point
  - 正面情感 (joy) 自动 add_joy_point
  - 输入: 消息文本 + CompanionState; 输出: EmpathyStrategyResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.companion_state import CompanionState


# ── 情感类型枚举 ────────────────────────────────────
class EmotionType(str, Enum):
    frustration = "frustration"
    confusion = "confusion"
    joy = "joy"
    sadness = "sadness"
    anger = "anger"
    fear = "fear"
    neutral = "neutral"


# ── 关键词映射 (确定性匹配, 不调用模型) ────────────
EMOTION_KEYWORDS: dict[EmotionType, tuple[str, ...]] = {
    EmotionType.frustration: ("烦", "讨厌", "气死", "崩溃", "累", "压力"),
    EmotionType.confusion: ("不知道", "迷茫", "怎么办", "困惑", "不懂", "纠结"),
    EmotionType.joy: ("开心", "高兴", "太棒", "超喜欢", "幸福", "好快乐"),
    EmotionType.sadness: ("难过", "伤心", "想哭", "失落", "孤独", "委屈"),
    EmotionType.anger: ("气死", "可恶", "恨", "生气"),
    EmotionType.fear: ("害怕", "担心", "焦虑", "紧张", "恐惧"),
}

# 匹配优先级: 先匹配的情感优先 (anger 的 "气死" 与 frustration 重合, 需要 anger 先)
EMOTION_PRIORITY: tuple[EmotionType, ...] = (
    EmotionType.anger,
    EmotionType.fear,
    EmotionType.sadness,
    EmotionType.joy,
    EmotionType.confusion,
    EmotionType.frustration,
)

# 负面情感集合: 自动记录 pain_point
NEGATIVE_EMOTIONS: frozenset[EmotionType] = frozenset(
    {
        EmotionType.frustration,
        EmotionType.sadness,
        EmotionType.anger,
        EmotionType.fear,
        EmotionType.confusion,
    }
)

# 策略固定顺序
STRATEGY_ORDER: tuple[str, ...] = (
    "validate_input",
    "reflect",
    "clarify",
    "support",
    "next_step",
)


# ── 结构化输出 ──────────────────────────────────────
@dataclass
class EmpathyStepResult:
    step_name: str
    content: str
    emotion_detected: EmotionType


@dataclass
class EmpathyStrategyResult:
    emotion_detected: EmotionType
    steps: list[EmpathyStepResult] = field(default_factory=list)
    message: str = ""


# ── 策略步骤基类 ────────────────────────────────────
class EmpathyStep:
    """共情策略步骤基类."""

    name: str = "base"

    def should_run(self, emotion: EmotionType) -> bool:
        return True

    def run(self, message: str, emotion: EmotionType) -> str:
        raise NotImplementedError


class ValidateInputStep(EmpathyStep):
    """校验输入并识别情感基调 (始终执行)."""

    name = "validate_input"

    def should_run(self, emotion: EmotionType) -> bool:
        return True

    def run(self, message: str, emotion: EmotionType) -> str:
        if emotion == EmotionType.neutral:
            return "我收到啦, 听起来是一次平常的分享~"
        return f"我听到啦, 感觉你现在带着 {_emotion_cn(emotion)} 的情绪"


class ReflectStep(EmpathyStep):
    """回映情感 (负面/强烈情绪时触发)."""

    name = "reflect"

    def should_run(self, emotion: EmotionType) -> bool:
        return emotion in NEGATIVE_EMOTIONS or emotion == EmotionType.joy

    def run(self, message: str, emotion: EmotionType) -> str:
        mapping = {
            EmotionType.frustration: "听起来你现在挺烦躁的, 这种感觉确实让人不舒服",
            EmotionType.sadness: "我感受到你有点难过, 这种时候真的不容易",
            EmotionType.anger: "你现在一定很生气吧, 这种情绪我能理解",
            EmotionType.fear: "能感觉到你在担心什么, 害怕的感觉并不好受",
            EmotionType.confusion: "我能感觉到你现在有点迷茫, 不确定该往哪走",
            EmotionType.joy: "哇, 能感觉到你现在的好心情, 真替你开心",
        }
        return mapping.get(emotion, "我能感受到你此刻的情绪")


class ClarifyStep(EmpathyStep):
    """确认需求, 邀请用户多说一点 (困惑/负面情绪时触发)."""

    name = "clarify"

    def should_run(self, emotion: EmotionType) -> bool:
        return emotion in {
            EmotionType.confusion,
            EmotionType.frustration,
            EmotionType.sadness,
            EmotionType.anger,
            EmotionType.fear,
        }

    def run(self, message: str, emotion: EmotionType) -> str:
        if emotion == EmotionType.confusion:
            return "愿意多跟我说说现在纠结的点吗? 我们可以一起理一理"
        return "你愿意多跟我聊聊吗? 说出来可能会好受一些"


class SupportStep(EmpathyStep):
    """提供情感支持 (所有情绪均可用, 喜悦时侧重肯定)."""

    name = "support"

    def should_run(self, emotion: EmotionType) -> bool:
        return True

    def run(self, message: str, emotion: EmotionType) -> str:
        if emotion == EmotionType.joy:
            return "真好呀, 这种开心的时刻值得好好记住~"
        if emotion == EmotionType.neutral:
            return "嗯嗯, 我在听呢"
        return "不管发生什么, 我都在这儿陪着你"


class NextStepStep(EmpathyStep):
    """给出轻量的下一步建议 (困惑/负面时给方向, 喜悦时给鼓励)."""

    name = "next_step"

    def should_run(self, emotion: EmotionType) -> bool:
        return emotion != EmotionType.neutral

    def run(self, message: str, emotion: EmotionType) -> str:
        mapping = {
            EmotionType.confusion: "要不我们先把你最在意的那一点列出来, 慢慢看?",
            EmotionType.frustration: "要不先深呼吸一下, 等心情平复一些我们再一起看?",
            EmotionType.sadness: "如果难受的话, 不用急着好起来, 我会一直陪着你",
            EmotionType.anger: "如果愿意的话, 可以把让你生气的事说出来, 我听着",
            EmotionType.fear: "我们可以先把担心的事拆小一点, 一步一步来",
            EmotionType.joy: "要不要把这件开心的事记下来, 以后心情不好的时候翻一翻?",
        }
        return mapping.get(emotion, "我们可以继续聊, 也可以做点别的, 你决定就好")


# ── 情感中文映射 ────────────────────────────────────
def _emotion_cn(emotion: EmotionType) -> str:
    return {
        EmotionType.frustration: "烦躁",
        EmotionType.confusion: "迷茫",
        EmotionType.joy: "开心",
        EmotionType.sadness: "难过",
        EmotionType.anger: "生气",
        EmotionType.fear: "担心",
        EmotionType.neutral: "平静",
    }.get(emotion, "复杂")


# ── 情感检测 ────────────────────────────────────────
def detect_emotion(text: str) -> EmotionType:
    """基于关键词的确定性情感检测."""
    if not text:
        return EmotionType.neutral
    for emotion in EMOTION_PRIORITY:
        for kw in EMOTION_KEYWORDS[emotion]:
            if kw in text:
                return emotion
    return EmotionType.neutral


# ── 策略链 ──────────────────────────────────────────
class EmpathyStrategyChain:
    """共情响应策略链.

    使用方式::

        chain = EmpathyStrategyChain()
        result = chain.run("我好烦", companion_state)
        for step in result.steps:
            print(step.step_name, step.content)
    """

    def __init__(self) -> None:
        self._steps: dict[str, EmpathyStep] = {
            ValidateInputStep.name: ValidateInputStep(),
            ReflectStep.name: ReflectStep(),
            ClarifyStep.name: ClarifyStep(),
            SupportStep.name: SupportStep(),
            NextStepStep.name: NextStepStep(),
        }

    def detect(self, message: str) -> EmotionType:
        return detect_emotion(message)

    def run(self, message: str, state: "CompanionState | None" = None) -> EmpathyStrategyResult:
        text = str(message or "")
        emotion = detect_emotion(text)
        result = EmpathyStrategyResult(emotion_detected=emotion, message=text)

        # 按固定顺序执行激活的步骤
        for name in STRATEGY_ORDER:
            step = self._steps[name]
            if step.should_run(emotion):
                content = step.run(text, emotion)
                result.steps.append(
                    EmpathyStepResult(
                        step_name=name,
                        content=content,
                        emotion_detected=emotion,
                    )
                )

        # 自动记录 pain_point / joy_point 到 CompanionState
        if state is not None and text:
            if emotion == EmotionType.joy:
                state.add_joy_point(text, note=f"emotion={emotion.value}")
            elif emotion in NEGATIVE_EMOTIONS:
                state.add_pain_point(text, note=f"emotion={emotion.value}")

        return result

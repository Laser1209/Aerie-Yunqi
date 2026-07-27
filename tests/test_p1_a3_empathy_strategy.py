"""TDD tests for Task P1-A.3: EmpathyStrategyChain 共情响应策略链.

覆盖:
  - 挫败表达消息触发 validate -> reflect 策略
  - 困惑表达触发 clarify 策略
  - 喜悦表达触发 support -> acknowledge 策略
  - 中性消息使用默认策略
  - 策略链按顺序执行 (validate_input, reflect, clarify, support, next_step)
  - 策略输出结构化: 每步有 step_name / content / emotion_detected
  - pain_point 自动记录到 CompanionState (挫败/痛苦)
  - joy_point 自动记录到 CompanionState (喜悦)
"""

from __future__ import annotations

import pytest

from core.companion_state import CompanionState


# ── 挫败: validate + reflect ────────────────────────
@pytest.mark.parametrize(
    "msg",
    ["我好烦", "烦死了", "今天真累, 压力好大", "这工作太讨厌了", "快崩溃了"],
)
def test_frustration_triggers_validate_and_reflect(msg):
    from core.empathy_strategy import EmpathyStrategyChain, EmotionType

    chain = EmpathyStrategyChain()
    state = CompanionState()
    result = chain.run(msg, state)

    assert result.emotion_detected == EmotionType.frustration
    step_names = [s.step_name for s in result.steps]
    assert "validate_input" in step_names
    assert "reflect" in step_names
    # validate_input 应出现在 reflect 之前
    assert step_names.index("validate_input") < step_names.index("reflect")


# ── 困惑: clarify 出场 ──────────────────────────────
@pytest.mark.parametrize(
    "msg",
    ["我不知道怎么办", "我好迷茫", "纠结要不要换工作", "困惑中不懂怎么选"],
)
def test_confusion_triggers_clarify(msg):
    from core.empathy_strategy import EmotionType, EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    result = chain.run(msg, state)

    assert result.emotion_detected == EmotionType.confusion
    step_names = [s.step_name for s in result.steps]
    assert "clarify" in step_names


# ── 喜悦: support + acknowledge ─────────────────────
@pytest.mark.parametrize(
    "msg",
    ["我今天超开心", "太棒了, 考试过了", "好幸福啊", "超喜欢这份礼物"],
)
def test_joy_triggers_support_and_acknowledge(msg):
    from core.empathy_strategy import EmotionType, EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    result = chain.run(msg, state)

    assert result.emotion_detected == EmotionType.joy
    step_names = [s.step_name for s in result.steps]
    assert "support" in step_names


# ── 中性: 默认策略 ──────────────────────────────────
def test_neutral_message_uses_default_strategy():
    from core.empathy_strategy import EmotionType, EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    result = chain.run("今天天气不错", state)

    assert result.emotion_detected == EmotionType.neutral


# ── 策略链顺序 ──────────────────────────────────────
def test_strategy_chain_runs_in_fixed_order():
    from core.empathy_strategy import EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    result = chain.run("我好烦, 不知道怎么办", state)

    step_names = [s.step_name for s in result.steps]
    expected_order = ["validate_input", "reflect", "clarify", "support", "next_step"]
    # 步骤在结果中应严格按 expected_order 的相对顺序出现
    filtered = [n for n in expected_order if n in step_names]
    assert filtered == step_names


# ── 结构化输出 ──────────────────────────────────────
def test_each_step_has_required_fields():
    from core.empathy_strategy import EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    result = chain.run("我好烦", state)

    for step in result.steps:
        assert step.step_name, "step_name 不能为空"
        assert isinstance(step.content, str) and step.content, "content 不能为空"
        assert step.emotion_detected is not None, "emotion_detected 必须存在"


# ── pain_point 自动记录 ────────────────────────────
@pytest.mark.parametrize(
    "msg,emotion",
    [
        ("我好烦", "frustration"),
        ("我好难过, 想哭", "sadness"),
        ("气死我了", "anger"),
        ("我好害怕明天的考试", "fear"),
    ],
)
def test_negative_emotion_records_pain_point(msg, emotion):
    from core.empathy_strategy import EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    chain.run(msg, state)
    assert len(state.recent_pain_points) == 1
    assert state.recent_pain_points[0].text == msg
    # 应同时调度 care_followup
    assert len(state.care_followups) >= 1


# ── joy_point 自动记录 ─────────────────────────────
def test_joy_records_joy_point():
    from core.empathy_strategy import EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    chain.run("我今天超开心", state)
    assert len(state.recent_joy_points) == 1
    assert state.recent_joy_points[0].text == "我今天超开心"


# ── 中性消息不记录 pain/joy ────────────────────────
def test_neutral_does_not_record_points():
    from core.empathy_strategy import EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    chain.run("今天吃了米饭", state)
    assert len(state.recent_pain_points) == 0
    assert len(state.recent_joy_points) == 0


# ── 其他情感分类 ────────────────────────────────────
@pytest.mark.parametrize(
    "msg,expected",
    [
        ("我好难过, 很伤心", "sadness"),
        ("气死了, 真可恶", "anger"),
        ("我好害怕, 很焦虑", "fear"),
    ],
)
def test_other_emotion_types_detected(msg, expected):
    from core.empathy_strategy import EmotionType, EmpathyStrategyChain

    chain = EmpathyStrategyChain()
    state = CompanionState()
    result = chain.run(msg, state)
    assert result.emotion_detected.value == expected or result.emotion_detected == EmotionType(expected)
    assert result.emotion_detected == EmotionType(expected)

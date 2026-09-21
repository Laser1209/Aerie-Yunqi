"""模型自报消息条数（intent-first）约定：解析、回退、收敛、与净化协同。

背景：此前切点由标点决定——模型写一整段，程序按 。！？ 猜着切。现在
``core.context_builder.OUTPUT_IRON_RULE`` 要求模型用「单独一行 ---」自己划出
消息边界，``SemanticMessageSplitter`` 优先按它分条；模型不照做时回退标点切分
（缺分隔符绝不丢内容），条数仍受 ``max_segments`` 硬上限约束。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from communication.splitter import SemanticMessageSplitter  # noqa: E402
from core.context_builder import OUTPUT_IRON_RULE  # noqa: E402
from core.model_output import normalize_model_text  # noqa: E402


def _segments(text: str, **kwargs) -> list[str]:
    return SemanticMessageSplitter(**kwargs).split(text)


# ══════════════════════════════════════════════════════════
# 1. 模型遵守约定 → 按模型自报的条数发
# ══════════════════════════════════════════════════════════

def test_intent_marks_become_separate_messages():
    text = "我到家了。\n---\n你先睡，不用等我。\n---\n明天早上想吃你做的粥。"
    assert _segments(text) == ["我到家了。", "你先睡，不用等我。", "明天早上想吃你做的粥。"]


def test_intent_marks_tolerate_blank_lines_and_indent():
    """分隔符行两侧的空行/缩进不影响识别，且空行不会变成空气泡。"""
    text = "我到家了。\n\n  ---  \n\n你先睡。\n\n-----\n\n粥给你留着。"
    assert _segments(text) == ["我到家了。", "你先睡。", "粥给你留着。"]


def test_intent_boundary_beats_punctuation():
    """气泡内部不再按标点二次切分：模型划的边界就是最终边界。"""
    text = "我在。\n---\n<action>她笑了一下。把手机扣在桌上。</action>想你了。"
    assert _segments(text) == [
        "我在。",
        "<action>她笑了一下。把手机扣在桌上。</action>想你了。",
    ]


def test_intent_marks_inside_code_fence_are_content():
    """围栏代码块里的 --- 是内容（YAML 分隔线），不是消息边界。"""
    text = "看这个配置。\n\n```yaml\n---\nname: 伊塔\n---\n```\n\n---\n\n跑一下试试。"
    segs = _segments(text)
    assert len(segs) == 2
    assert segs[0].count("---") == 2
    assert "name: 伊塔" in segs[0]
    assert segs[1] == "跑一下试试。"


# ══════════════════════════════════════════════════════════
# 2. 模型不遵守约定 → 回退标点切分，不丢内容
# ══════════════════════════════════════════════════════════

def test_falls_back_to_punctuation_without_marks():
    text = "我靠在椅背上，看着窗外的雨。你今天过得怎么样。我现在就在这里。"
    segs = _segments(text)
    assert len(segs) >= 2
    assert "".join(segs) == text


def test_single_bubble_with_stray_marks_is_cleaned():
    """模型只发一条却写了分隔符：分隔符不能当内容发给用户。"""
    text = "---\n\n单条消息，只是想跟你说句话。\n\n---"
    segs = _segments(text)
    assert segs == ["单条消息，只是想跟你说句话。"]


def test_separator_only_reply_produces_nothing():
    assert _segments("") == []
    assert _segments("---") == []


# ══════════════════════════════════════════════════════════
# 3. 条数上限：模型少给就尊重，模型多给就收敛
# ══════════════════════════════════════════════════════════

def test_fewer_than_cap_is_respected():
    """低于上限不凑数：模型发几条就是几条。"""
    text = "第一句在这里。\n---\n第二句在这里。"
    assert _segments(text, max_segments=3) == ["第一句在这里。", "第二句在这里。"]


def test_over_cap_converges_without_losing_content():
    text = (
        "第一句在这里。\n---\n第二句在这里。\n---\n"
        "第三句在这里。\n---\n第四句在这里。"
    )
    segs = _segments(text, max_segments=2)
    assert len(segs) == 2
    assert "".join(segs) == (
        "第一句在这里。第二句在这里。第三句在这里。第四句在这里。"
    )
    payload = sum(len(seg) for seg in segs)
    assert max(len(seg) for seg in segs) <= payload * 0.6  # 不堆成文字墙


def test_overlong_bubble_is_split_again_without_losing_content():
    """模型划的单条超过 max_len 时再切：气泡边界归模型，但单条不得变回文字墙。"""
    long_part = "第一部分。" * 60  # 300 字
    text = f"{long_part}\n---\n就这样。"
    segs = _segments(text)
    assert len(segs) == 3
    assert all(len(seg) <= 200 for seg in segs)
    assert "".join(segs) == long_part + "就这样。"


# ══════════════════════════════════════════════════════════
# 4. 与净化层协同：先 normalize 再 split
# ══════════════════════════════════════════════════════════

def test_normalize_then_split_drops_narration_only_bubble():
    raw = "我在的。\n---\n（把手机拿起来看了一眼）我也刚到家。\n---\n（只是心理活动）"
    segs = _segments(normalize_model_text(raw))
    assert segs == ["我在的。", "我也刚到家。"]
    assert all("（" not in seg and "---" not in seg for seg in segs)


def test_normalize_then_split_ignores_marks_inside_think_block():
    """think 块里的 --- 不是消息边界：净化先于分条，think 早已剥掉。

    think 标签用拼接构造，避免测试源码里出现完整标签字面量。
    """
    think_block = "<thi" + "nk>他可能睡了。\n---\n别吵。</thi" + "nk>"
    raw = f"{think_block}[09-22 03:10] 睡了吗。\n---\n我这边刚忙完。"
    assert _segments(normalize_model_text(raw)) == ["睡了吗。", "我这边刚忙完。"]


# ══════════════════════════════════════════════════════════
# 5. 提示词与解析器是同一份约定（防漂移）
# ══════════════════════════════════════════════════════════

def test_iron_rule_declares_separator_convention():
    assert "单独一行的 `---` 隔开" in OUTPUT_IRON_RULE


def test_persona_yaml_keeps_separator_convention():
    """内置人设的静态提示词副本要与 OUTPUT_IRON_RULE 同步。"""
    text = (_ROOT / "config" / "persona.yaml").read_text(encoding="utf-8")
    assert "输出铁律" in text
    assert "单独一行的 --- 隔开" in text

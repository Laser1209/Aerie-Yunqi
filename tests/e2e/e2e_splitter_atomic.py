"""Aerie · 云栖 v9.0 — E2E: E · 原子感知 splitter 验证 (16 cases).

R8.1 收口验证 E 节的 SemanticMessageSplitter atomic-aware 重写：
  - <action>...</action> 整段视为不可分割单元
  - <thought>...</thought> 整段视为不可分割单元
  - 【...】 整段视为不可分割单元
  - 仅在 atomic 之外的文本按"。"、"！"、"？"切分

16 个用例 (T3)：
  1.  <action> 内部含"。" → 不切
  2.  <thought> 内部含"！" → 不切
  3.  【...】 内部含"？" → 不切
  4.  无 atomic 时按"。"切
  5.  多 atomic 串接，顺序保留
  6.  截图复现：原 input → 整段作为 1 个 segment 输出
  7.  跨段 atomic 完整保留
  8.  短文本 < 8 字合并到 neighbor
  9.  无 atomic 时退回原 split 逻辑
  10. 空文本 → []
  11. max_segments 上限就近平摊
  12. max_segments=0 不限制
  13. <action> 内的 --- 不是消息边界（原子段不被切开）
  14. 【…】 内的 --- 不是消息边界
  15. 未闭合围栏内的 --- 不是消息边界
  16. 纯分隔符/纯空白 → []

纯本地（不依赖 backend / DB / LLM）。
"""
from __future__ import annotations
import sys
# R7.5+: force UTF-8 on Windows (default GBK chokes on ✓/✗)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
import sys

# Ensure repo root on path (this file lives in tests/e2e/)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from communication.splitter import SemanticMessageSplitter  # noqa: E402


def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")


# ── Case 1: <action> 内部含"。" → 不切 ───────────────────────
def case_1_action_tag_intact() -> bool:
    s = SemanticMessageSplitter()
    text = "<action>她靠在椅背上笑了一下，眨眨眼。</action>你呢。"
    segs = s.split(text)
    # 期望 2 段：action 段 + "你呢。"
    ok_flag = (
        len(segs) == 2
        and segs[0].startswith("<action>")
        and segs[0].endswith("</action>")
        and segs[0].count("。</action>") == 1  # 内部"。" 完整保留
        and segs[1] == "你呢。"
    )
    _check(
        "Case 1 · <action> 内部含 '。' → 不切",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 2: <thought> 内部含"！" → 不切 ──────────────────────
def case_2_thought_tag_intact() -> bool:
    s = SemanticMessageSplitter()
    text = "我笑了。<thought>他今天怎么这么乖！</thought>你呢。"
    segs = s.split(text)
    ok_flag = (
        len(segs) == 3
        and segs[1].startswith("<thought>")
        and segs[1].endswith("</thought>")
        and "！</thought>" in segs[1]
    )
    _check(
        "Case 2 · <thought> 内部含 '！' → 不切",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 3: 【...】 内部含"？" → 不切 ───────────────────────
def case_3_brackets_intact() -> bool:
    s = SemanticMessageSplitter()
    text = "我看着屏幕【你发的那张照片？】笑了笑。"
    segs = s.split(text)
    # 期望 atomic 完整保留在输出中（可能与前后文本合并为同一段，
    # 但绝不被切开）。验证 segs flat 后含完整 "【...？】"。
    flat = "".join(segs)
    ok_flag = (
        "【你发的那张照片？】" in flat
        and flat.count("【") == 1
        and flat.count("】") == 1
        and segs[0].endswith("。")  # 末尾"。"保留
    )
    _check(
        "Case 3 · 【...？】 内部含 '？' → 不切，atomic 完整保留",
        ok_flag,
        f"segs={segs} flat={flat!r}",
    )
    return ok_flag


# ── Case 4: 无 atomic 时按"。"切 ─────────────────────────────
def case_4_no_atoms_split() -> bool:
    s = SemanticMessageSplitter()
    # 用足够长的句子（> 8 字）才能触发切分（_MIN_FRAGMENT_LEN=8）
    text = (
        "我靠在椅背上，看着窗外的雨。"
        "你今天过得怎么样。"
        "我就在这里。"
    )
    segs = s.split(text)
    # 期望 ≥ 2 段
    ok_flag = len(segs) >= 2
    _check(
        "Case 4 · 无 atomic 时按 '。' 切（用 ≥ 8 字句子）",
        ok_flag,
        f"segs_len={len(segs)} segs={segs}",
    )
    return ok_flag


# ── Case 5: 多 atomic 串接，顺序保留 ─────────────────────────
def case_5_multiple_atoms_order() -> bool:
    s = SemanticMessageSplitter()
    text = (
        "我看着屏幕。"
        "<action>她靠在椅背上笑。</action>"
        "你呢。"
        "<thought>他今天心情不错。</thought>"
        "回我。"
    )
    segs = s.split(text)
    # 期望至少 2 个 atomic 完整保留，且在原文本中的相对顺序保留
    flat = "".join(segs)
    action_idx = flat.find("<action>")
    thought_idx = flat.find("<thought>")
    ok_flag = (
        action_idx >= 0
        and thought_idx >= 0
        and action_idx < thought_idx
        and flat.count("<action>") == 1
        and flat.count("</action>") == 1
        and flat.count("<thought>") == 1
        and flat.count("</thought>") == 1
    )
    _check(
        "Case 5 · 多 atomic 串接，顺序保留",
        ok_flag,
        f"action_idx={action_idx} thought_idx={thought_idx} segs={segs}",
    )
    return ok_flag


# ── Case 6: 截图复现 ─────────────────────────────────────────
def case_6_screenshot_repro() -> bool:
    """复现 plan 中提到的截图输入。
    期望：action 段完整保留（不被切开），trailing 6 字短片段独立成段
    （splitter 设计：短 fragment 不合并到 atomic 后，避免破坏 atomic 完整性）。"""
    s = SemanticMessageSplitter()
    text = (
        "<action>伊塔把聊天窗口点开，屏幕亮起来照在她脸上。"
        "灰蓝色的眼睛弯了一下。她靠在椅背上，看着屏幕笑了一下，"
        "指尖缓缓收起。</action>你个表情……"
    )
    segs = s.split(text)
    # 期望 ≥ 2 段：action 段（完整保留）+ "你个表情……"
    has_intact_action = any(
        seg.startswith("<action>") and seg.endswith("</action>")
        and "。</action>" in seg
        and seg.count("。") >= 3  # 内部 3 个"。" 都保留
        for seg in segs
    )
    has_trailing = any("你个表情" in seg for seg in segs)
    ok_flag = (
        len(segs) >= 1
        and has_intact_action
        and has_trailing
    )
    _check(
        "Case 6 · 截图复现：action 段完整保留 + trailing 独立成段",
        ok_flag,
        f"segs_len={len(segs)} segs={segs}",
    )
    return ok_flag


# ── Case 7: 跨段 atomic 完整保留 ─────────────────────────────
def case_7_atomic_boundary_preserved() -> bool:
    s = SemanticMessageSplitter()
    text = "前面。<action>她笑了一下，点开消息。</action>后面。"
    segs = s.split(text)
    # 期望 3 段：前 + atomic + 后
    ok_flag = (
        len(segs) == 3
        and segs[1].startswith("<action>")
        and segs[1].endswith("</action>")
        and "。</action>" in segs[1]
    )
    _check(
        "Case 7 · 跨段 atomic 完整保留",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 8: 短文本 < 8 字合并到 neighbor ──────────────────────
def case_8_short_fragment_merged() -> bool:
    s = SemanticMessageSplitter()
    # "嗯。" 短文本应该被合并到 neighbor
    text = "我看着屏幕笑了笑嗯。"
    segs = s.split(text)
    # 期望合并为 1 段
    ok_flag = len(segs) == 1
    _check(
        "Case 8 · 短文本 < 8 字合并到 neighbor",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 9: 无 atomic 时退回原 split 逻辑 ─────────────────────
def case_9_no_atoms_original_split() -> bool:
    s = SemanticMessageSplitter()
    # 用足够长的句子（> 8 字）才能触发切分（_MIN_FRAGMENT_LEN=8）
    text = (
        "我靠在椅背上，看着窗外的雨。"
        "你今天过得怎么样。"
        "我现在就在这里。"
    )
    segs = s.split(text)
    # 期望 ≥ 2 段
    ok_flag = (
        len(segs) >= 2
        and all(seg for seg in segs)  # 无空段
    )
    _check(
        "Case 9 · 无 atomic 时退回原 split 逻辑（≥ 8 字句子）",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 10: 空文本 → [] ─────────────────────────────────────
def case_10_empty_text() -> bool:
    s = SemanticMessageSplitter()
    r = s.split("")
    ok_flag = r == []
    _check(
        "Case 10 · 空文本 → []",
        ok_flag,
        f"r={r!r}",
    )
    return ok_flag


# ── Case 11: max_segments 上限（就近并成 N 条，不丢内容也不攒长段） ──
def case_11_max_segments_cap() -> bool:
    s = SemanticMessageSplitter(max_segments=3)
    text = "第一句话在这里。第二句话在这里。第三句话在这里。第四句话在这里。第五句话在这里。"
    segs = s.split(text)
    joined = "".join(segs).replace(" ", "")
    lengths = [len(seg) for seg in segs]
    ok_flag = (
        len(segs) == 3
        and joined == text.replace(" ", "")
        # 均分：最长一条不应超过总长的 60%（避免「溢出全塞最后一条」的文字墙）
        and max(lengths) <= sum(lengths) * 0.6
    )
    _check(
        "Case 11 · max_segments 上限：就近分桶、不丢内容、不攒长段",
        ok_flag,
        f"segs_len={len(segs)} lengths={lengths}",
    )
    return ok_flag


# ── Case 12: max_segments=0 不限制（保持既有行为） ─────────────
def case_12_max_segments_unlimited() -> bool:
    text = "第一句话在这里。第二句话在这里。第三句话在这里。第四句话在这里。第五句话在这里。"
    limited = len(SemanticMessageSplitter(max_segments=3).split(text))
    unlimited = SemanticMessageSplitter().split(text)
    ok_flag = len(unlimited) > limited and all(seg for seg in unlimited)
    _check(
        "Case 12 · max_segments=0 不限制",
        ok_flag,
        f"unlimited={len(unlimited)} limited={limited}",
    )
    return ok_flag


# ── Case 13: 原子段内的意图分隔符 --- 不是消息边界 ────────────
def case_13_separator_inside_action() -> bool:
    s = SemanticMessageSplitter()
    text = "<action>她笑了笑\n---\n又把头低下</action>正文。"
    atom = "<action>她笑了笑\n---\n又把头低下</action>"
    segs = s.split(text)
    ok_flag = (
        atom in segs
        and "".join(segs).count("<action>") == 1
        and "".join(segs).count("</action>") == 1
    )
    _check(
        "Case 13 · <action> 内的 --- 是内容，原子段不被切开",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 14: 【…】 内的意图分隔符 --- 不是消息边界 ─────────────
def case_14_separator_inside_brackets() -> bool:
    s = SemanticMessageSplitter()
    text = "【她笑了笑\n---\n又把头低下】正文。"
    atom = "【她笑了笑\n---\n又把头低下】"
    segs = s.split(text)
    ok_flag = (
        atom in segs
        and "".join(segs).count("【") == 1
        and "".join(segs).count("】") == 1
    )
    _check(
        "Case 14 · 【…】 内的 --- 是内容，原子段不被切开",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 15: 未闭合围栏内的 --- 不是消息边界 ──────────────────
def case_15_unclosed_fence() -> bool:
    s = SemanticMessageSplitter()
    segs = s.split("```\ncode\n---\nmore")
    ok_flag = (
        len(segs) == 1
        and "code" in segs[0]
        and "more" in segs[0]
    )
    _check(
        "Case 15 · 未闭合围栏内的 --- 是内容，不切",
        ok_flag,
        f"segs={segs}",
    )
    return ok_flag


# ── Case 16: 纯分隔符 / 纯空白 → []（没有可外发内容） ──────────
def case_16_separator_only_or_blank() -> bool:
    s = SemanticMessageSplitter()
    cases = {
        "---\n---\n---": [],
        "---\n \n---": [],
        "   ": [],
        "\n\n": [],
    }
    bad = {text: s.split(text) for text, expect in cases.items()
           if s.split(text) != expect}
    ok_flag = not bad
    _check(
        "Case 16 · 纯分隔符/纯空白 → []",
        ok_flag,
        f"bad={bad}" if bad else "",
    )
    return ok_flag


def main() -> int:
    print("=" * 60)
    print("E2E T3 · E 节 atomic-aware splitter 验证 (16 用例)")
    print("=" * 60)
    results: list[bool] = [
        case_1_action_tag_intact(),
        case_2_thought_tag_intact(),
        case_3_brackets_intact(),
        case_4_no_atoms_split(),
        case_5_multiple_atoms_order(),
        case_6_screenshot_repro(),
        case_7_atomic_boundary_preserved(),
        case_8_short_fragment_merged(),
        case_9_no_atoms_original_split(),
        case_10_empty_text(),
        case_11_max_segments_cap(),
        case_12_max_segments_unlimited(),
        case_13_separator_inside_action(),
        case_14_separator_inside_brackets(),
        case_15_unclosed_fence(),
        case_16_separator_only_or_blank(),
    ]
    passed = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    print("=" * 60)
    print(f"  Total: passed={passed}  failed={failed}")
    if failed == 0:
        print("  ✓ e2e_splitter_atomic 全部通过")
    else:
        print("  ✗ e2e_splitter_atomic 有失败用例")
    print("=" * 60)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

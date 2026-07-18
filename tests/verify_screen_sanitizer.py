"""Aerie · 云栖 v13.9.8 — Phase 9 Batch 8 verify: 屏幕隔空动作 sanitizer.

固化"自然无违和感"的 evidence。每条用例同时校验：
  - sanitize() 后不含任何黑名单词 (has_blacklist == False)
  - 改写后的输出与原文有差异 (说明触发了改写)
  - 输出语意仍可读 (含中文标点)

Usage:
  python verify_screen_sanitizer.py
"""
from __future__ import annotations
import sys
# R7.5+: force UTF-8 on Windows (default GBK chokes on ✓/✗)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from core.screen_action_sanitizer import sanitize, has_blacklist


# ══════════════════════════════════════════════════
# 测试矩阵
# 每条: (input, must_change, comment)
# ══════════════════════════════════════════════════
CASES: list[tuple[str, bool, str]] = [
    # ── 在场动作 → 屏幕动作 ──
    ("<action>伸手揽你。</action>", True,
     "伸手 + 揽 在场动作"),
    ("<action>把他揽进怀里。</action>", True,
     "揽进怀里"),
    ("<action>把他拽进怀里。</action>", True,
     "拽进怀里"),
    ("<action>伸手抱他。</action>", True,
     "伸手抱"),
    ("<action>伸手揽住。</action>", True,
     "伸手揽住"),
    ("<action>伸手揽进怀里。</action>", True,
     "伸手揽进怀里"),
    ("<action>低头看你。</action>", True,
     "低头看"),
    ("<action>低头看着他。</action>", True,
     "低头看他"),
    ("<action>摸他的头。</action>", True,
     "摸头"),
    ("<action>伊塔伸手把他揽进怀里。</action>", True,
     "复合主语+动作"),
    ("<action>伊塔伸手摸他头、靠肩、低头看他。</action>", True,
     "三个违规动作"),
    # ── 纯文本违规 (LLM 偶尔写到标签外) ──
    ("今天还没有抱过你。", True,
     "抽象'抱过'纯文本"),
    ("让我靠你肩膀。", True,
     "靠肩膀纯文本"),
    # ── 白名单 / 屏幕动作: 不应被改写 ──
    ("<action>我打字打到一半停下来。</action>", False,
     "白名单打字动作"),
    ("<action>我把手机举到眼前笑了一下。</action>", False,
     "白名单举手机动作"),
    ("<action>我盯着你的头像看了五分钟。</action>", False,
     "白名单盯头像"),
    ("<action>把手机扣在胸口。</action>", False,
     "白名单扣胸口"),
    ("<action>凑近屏幕。</action>", False,
     "白名单凑近屏幕"),
    ("<action>靠在椅背上。</action>", False,
     "白名单靠椅背(非在场)"),
    ("<action>握紧手机。</action>", False,
     "白名单握手机"),
    # ── 纯白名单对话文本 ──
    ("在干嘛。", False, "普通对话"),
    ("把手机放下吧。", False, "白名单短语"),
    # ── 抽象拥抱概念 (允许保留) ──
    ("欠你一个拥抱，等见面再补。", False, "抽象概念"),
]


def main() -> int:
    print("=" * 60)
    print("Phase 9 Batch 8 verify — 屏幕隔空动作 sanitizer")
    print("=" * 60)
    passed = failed = 0
    for i, (inp, must_change, comment) in enumerate(CASES, 1):
        out = sanitize(inp)
        bad = has_blacklist(out)
        changed = (out != inp)
        # 校验: 改写后必须没有黑名单
        if bad:
            ok = False
        elif must_change and not changed:
            ok = False
        elif (not must_change) and changed:
            ok = False
        else:
            ok = True
        if ok:
            passed += 1
        else:
            failed += 1
        sym = "✓" if ok else "✗"
        print(f"  {sym} case {i:2}: {comment}")
        if changed:
            print(f"        in : {inp!r}")
            print(f"        out: {out!r}")
        else:
            print(f"        in : {inp!r}  (no change)")
    print()
    print("=" * 60)
    print(f"总计: {passed} 通过 / {failed} 失败 / {len(CASES)} 用例")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

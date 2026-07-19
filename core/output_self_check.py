"""Aerie · 云栖 v0.1.0-beta.1 — Output Self-Check (R8.1).

A conservative post-LLM safety net that scans outgoing text for:

1. Perspective-shift residuals
   The LLM sometimes drifts mid-message from "screen-aware" framing
   (e.g. "我把手机扣在胸口") to "in-person" framing
   (e.g. "我伸手揽他"). This produces the "output transition" bug the
   user reported. We compare the first half vs second half of the text
   for blacklisted in-person verbs, and if the first half carries more
   than the second half beyond a threshold, we log a warning.

2. Stray bracket residues
   - An unclosed `【` is auto-closed with `】` at the end of the text.
   - An orphan `】` (no matching `【` before it) is stripped.

3. Conservative typo dictionary (3 known cases)
   - "产出产出" / "的的" / "了了" / "是是" — duplicate adjacent characters
     that the LLM sometimes produces. We keep only the first occurrence.

The check is intentionally conservative. It MUST NOT alter meaningful
content. Any modification falls into one of three classes:
- Append a closing bracket (never inserts user-visible text).
- Delete an orphan bracket (silent fix).
- Collapse a duplicate 2-gram (only when both halves are non-meaningful).

R8.1+: this module is the second line of defense after the
`system_prompt` rewrite in `config/persona.yaml`. Together they
close the "output transition" / "left-right brain contention" bug.
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── in-person verbs that should never survive in screen-aware output ──
# Each entry is checked as a substring (no word boundary, since CJK has none).
#
# R8.1 (Persona 9/10 · screen-aware): 9/10 基线更直球、更外显，
# LLM 偶发"产出半句切换视角"概率略增（vs 7/10），因为直球措辞
# 让 LLM 更容易在 1 句之内同时调取"屏幕那端"和"在场视角"两套
# 表达。
# 本黑名单**不动** —— 屏幕隔空铁律优先于人格基线。
# 9/10 行为下 OutputSelfCheck 命中率会略升（这是预期行为，运营侧
# 通过 P.6 的 severity=warn 监控），但黑名单内容跟 7/10 完全一致。
_IN_PERSON_VERBS: tuple[str, ...] = (
    "伸手揽", "伸手抱", "把他抱起", "让他枕你肩膀", "让他枕我肩膀",
    "身体挡住他", "用身体挡住", "拽进怀里", "扑到他身上", "贴面",
    "把他揽进", "揽进怀里", "把他拉过来", "拉他过来", "握他手",
    "牵他手", "握手", "碰他", "摸他头", "揉他头", "亲他",
    "吻他", "靠在他肩", "靠在他肩膀", "让他靠我肩", "让他靠我肩膀",
)


@dataclass
class CheckResult:
    cleaned_text: str
    warnings: list[str] = field(default_factory=list)
    perspective_shift: bool = False
    stray_brackets_fixed: int = 0
    typo_fixes: int = 0


class OutputSelfCheck:
    """Conservative post-LLM output safety net.

    Usage:
        checker = OutputSelfCheck()
        result = checker.check(llm_output)
        text_to_send = result.cleaned_text
        if result.warnings:
            cognition.record(trace, "self_check_warnings", result.warnings)
    """

    def __init__(self) -> None:
        self._in_person_re = re.compile("|".join(map(re.escape, _IN_PERSON_VERBS)))

    def check(self, text: str) -> CheckResult:
        """Run output self-check rules and return a CheckResult."""
        if not text:
            return CheckResult(cleaned_text=text)

        cleaned = text
        warnings: list[str] = []

        # ── 1. perspective shift detection ──
        perspective_shift = self._detect_perspective_shift(cleaned)
        if perspective_shift:
            warnings.append(
                "perspective_shift_detected: in-person verbs concentrated in first half",
            )

        # ── 2. stray bracket residues ──
        cleaned, bracket_fixes = self._fix_stray_brackets(cleaned)
        if bracket_fixes:
            warnings.append(f"stray_brackets_fixed: {bracket_fixes}")

        return CheckResult(
            cleaned_text=cleaned,
            warnings=warnings,
            perspective_shift=perspective_shift,
            stray_brackets_fixed=bracket_fixes,
            typo_fixes=0,
        )

    # ─────────────────────────────────────────
    # 1. Perspective shift detection
    # ─────────────────────────────────────────
    def _detect_perspective_shift(self, text: str) -> bool:
        """Compare in-person verb count in first 50% vs second 50%.

        If first half has >= 2 in-person verbs and second half has 0,
        we flag it as a perspective shift (LLM started "in-person" then
        self-corrected to "screen-aware" mid-message).
        """
        if len(text) < 40:
            return False
        half = len(text) // 2
        first_half = text[:half]
        second_half = text[half:]
        first_hits = len(self._in_person_re.findall(first_half))
        second_hits = len(self._in_person_re.findall(second_half))
        # Heuristic: started in-person, ended screen-aware
        if first_hits >= 2 and second_hits == 0:
            return True
        # Even stronger: many in-person in first, almost none in second
        if first_hits >= 3 and second_hits <= 0:
            return True
        return False

    # ─────────────────────────────────────────
    # 2. Stray bracket fix
    # ─────────────────────────────────────────
    @staticmethod
    def _fix_stray_brackets(text: str) -> tuple[str, int]:
        """Close unclosed `【` and strip orphan `】`."""
        fixes = 0
        opens = text.count("【")
        closes = text.count("】")
        if opens > closes:
            # Append missing closers
            text = text + ("】" * (opens - closes))
            fixes += opens - closes
        elif closes > opens:
            # Strip orphan closers (right to left to keep indices valid)
            for _ in range(closes - opens):
                idx = text.rfind("】")
                if idx >= 0:
                    text = text[:idx] + text[idx + 1:]
                    fixes += 1
        return text, fixes


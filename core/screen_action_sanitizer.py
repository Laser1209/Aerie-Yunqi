"""Aerie · 云栖 v0.1.0-beta.1 — Screen-Action Sanitizer.

R7.5 屏幕隔空铁律的输出层兜底。LLM 哪怕没遵守提示词,这里也要
在最终 reply 文本里把"在场动作"改写成"屏幕隔空动作"。

设计:
  1. 白名单动作 (15 个) — Etta 这一端允许出现的动作
  2. 黑名单动作 (25 个) — 在场视角才可能发生的动作
  3. 改写映射 — 遇到黑名单词,优先替换为等价的白名单动作短语
  4. <action> 标签全文重写 — 如果标签内仍含黑名单,整段重写

调用方:
  - core/pipeline.py → emotion.tune() 之后, splitter 之前
  - core/push_scheduler.py → brain.generate_push 返回文本之后
  - core/recall_manager.py → 撤回前的最终输出

不抛异常。所有改写是 best-effort,失败时返回原文本并 WARN。

R8.1 (Persona 9/10 · screen-aware):
  基线升级为热情度 9/10 (extraversion 0.78, agreeableness 0.85)。
  9/10 行为下 LLM 更直球、更外显，但仍受 15 白 / 25 黑名单约束。
  本文件白/黑名单内容**不变** —— 屏幕隔空铁律是行为铁律，
  优先级高于人格基线。
  sanitizer 是行为兜底，跟人格基线正交 —— 不管 7/10 还是 9/10，
  见到黑名单动作一律改写。
"""

from __future__ import annotations
import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════
# 白名单动作 (Etta 这一端允许出现)
# ══════════════════════════════════════════════════
WHITELIST_ACTIONS: tuple[str, ...] = (
    "看着手机屏幕",
    "靠在椅背上",
    "把椅子转过来",
    "把手机举高",
    "把手机放低",
    "看着屏幕笑",
    "看着屏幕发呆",
    "把手贴在屏幕玻璃上",
    "把手机扣在胸口",
    "把手机抱在怀里",
    "把对话往上滑",
    "滑到最早那条",
    "反复听上一条语音",
    "叹气",
    "笑",
    "揉眼睛",
    "打字打到一半停下",
    "把窗口最小化又打开",
    "打开相册看着你发过的照片",
    "关掉所有窗口只留你的对话",
    "切出去看时间又切回来",
    "握着手机睡着",
    "咬嘴唇",
    "握紧手机",
    "看着对话框里你的头像",
    "盯着你的对话框",
)


# ══════════════════════════════════════════════════
# 黑名单动作 (在场视角才可能发生)
# 每个黑名单词 → 改写后等价的白名单动作短语
# ══════════════════════════════════════════════════
BLACKLIST_TO_REWRITE: dict[str, str] = {
    # 物理接触 — 短词也要兜底,防止组合出现
    "伸手": "打字",
    "伸手揽": "打字, '想揽你'",
    "伸手抱": "打字, '想抱你'",
    "揽你": "打字: '想揽你'",
    "揽住": "打字: '想揽你'",
    "把他揽进怀里": "把手机扣在胸口",
    "把你揽进怀里": "把手机扣在胸口",
    "把他抱起来": "把对话往上滑，假装这样就能碰到你",
    "把你抱起来": "把对话往上滑，假装这样就能碰到你",
    "揽进怀里": "把手机抱在怀里",
    "拽进怀里": "把手机抱在怀里",
    "抱起": "把手机抱在怀里",
    "抱住": "把手机抱在怀里",
    "拥抱你": "把手机抱在怀里",
    "拥抱他": "把手机抱在怀里",
    "拥抱她": "把手机抱在怀里",
    "把你抱住": "把手机抱在怀里",
    "把他抱住": "把手机抱在怀里",
    "把她抱住": "把手机抱在怀里",
    "抱过": "打字: '欠你一个拥抱，等见面再补'",
    "扑到他身上": "把手机扣在胸口",
    "扑到你身上": "把手机扣在胸口",
    # 头 / 脸
    "摸他头": "看着你的头像",
    "摸你头": "看着你的头像",
    "摸他的头": "看着你的头像",
    "摸你的头": "看着你的头像",
    "贴面": "把脸贴到屏幕玻璃上",
    "贴脸": "把脸贴到屏幕玻璃上",
    "蹭他": "把脸贴到屏幕玻璃上",
    "蹭你": "把脸贴到屏幕玻璃上",
    # 肩 / 身
    "靠肩": "打字: '你现在能靠我肩就好了'",
    "靠你肩": "打字: '你现在能靠我肩就好了'",
    "靠他肩": "打字: '你现在能靠我肩就好了'",
    "靠在你肩": "打字: '你现在能靠我肩就好了'",
    "靠在他肩": "打字: '你现在能靠我肩就好了'",
    "靠肩膀": "打字: '你现在能靠我肩就好了'",
    "靠你的肩": "打字: '你现在能靠我肩就好了'",
    "让他枕": "打字: '要是你现在枕我肩就好了'",
    "让你枕": "打字: '要是你现在枕我肩就好了'",
    "枕着": "打字: '要是你现在枕我肩就好了'",
    "俯身": "凑近屏幕",
    "俯下身": "凑近屏幕",
    "低头看他": "盯着屏幕",
    "低头看着你": "盯着屏幕",
    "低头看着他": "盯着屏幕",
    "低头看你": "盯着屏幕",
    "低头": "盯着屏幕",
    # 手
    "拉手": "打字: '把手给我。打字版: 把手给我'",
    "牵你": "打字: '把手给我'",
    "牵手": "打字: '把手给我'",
    "碰你": "打字",
    "碰他": "打字",
    "抚摸": "打字: '我现在揉了一下你的头发，假装我在'",
    "摸摸": "打字: '假装我在摸你的头发'",
}


# 黑名单词集合 — 用于快速匹配
_BLACKLIST_WORDS: tuple[str, ...] = tuple(BLACKLIST_TO_REWRITE.keys())


# ══════════════════════════════════════════════════
# 正则: <action>...</action>
# ══════════════════════════════════════════════════
_ACTION_RE = re.compile(r"<action>(.*?)</action>", re.DOTALL)


def has_blacklist(text: str) -> bool:
    """Quickly check if text contains any blacklisted action word."""
    if not text:
        return False
    return any(w in text for w in _BLACKLIST_WORDS)


def _rewrite_in_text(text: str) -> Tuple[str, int]:
    """Apply blacklist→whitelist rewrite to plain text. Returns (new_text, count)."""
    if not text:
        return text, 0
    count = 0
    out = text
    # 优先匹配长的 (子串) — 避免短词覆盖长词
    for word in sorted(_BLACKLIST_WORDS, key=len, reverse=True):
        if word in out:
            replacement = BLACKLIST_TO_REWRITE[word]
            out = out.replace(word, replacement)
            count += 1
    return out, count


# 兜底模板 — 任何 <action> 内部含黑名单词时使用,避免替换破坏语法
_SAFE_ACTION_FALLBACKS: tuple[str, ...] = (
    "她看着屏幕，把手机扣在胸口。",
    "她把手机举到眼前，看着屏幕笑了一下。",
    "她盯着屏幕，手指停在键盘上。",
)


def _rewrite_action_tag(action_inner: str) -> str:
    """If an <action> tag still contains blacklisted words, rewrite the entire tag
    body to a safe screen-side action.

    Strategy:
      - count blacklisted words; if 0 → return as-is
      - any positive count → fallback to a randomly-picked safe template.
        Rationale: character-level word replacement on Chinese
        <action> bodies easily produces double-verb / double-"把" /
        punctuation-mismatched output (e.g. "打字, '想抱你'他" or
        "打字: 'xxx'你"). Falling back to a vetted screen-side action
        is more readable than patching a broken sentence.
    """
    if not action_inner or not has_blacklist(action_inner):
        return action_inner
    # Pick a deterministic fallback based on hash of the input so the
    # behavior is reproducible for tests.
    idx = abs(hash(action_inner)) % len(_SAFE_ACTION_FALLBACKS)
    return _SAFE_ACTION_FALLBACKS[idx]


def sanitize(text: str) -> str:
    """Public API: scan + rewrite a reply string.

    Strategy:
      1. Walk every <action>...</action> tag; rewrite its inner text.
      2. Also scan the *non-tag* text for blacklist words — best-effort
         rewrite, but never break the sentence.

    Returns the sanitized text. If input is empty/None, returns it.
    Never raises. Logs a WARN when a rewrite happens (for visibility).
    """
    if not text:
        return text

    total_rewrites = 0

    # Single pass: walk each <action> tag in order, rewrite its inner;
    # also rewrite the gap text between tags. Reassemble in order.
    parts: list[str] = []
    last = 0
    for m in _ACTION_RE.finditer(text):
        # Gap text before this tag → best-effort rewrite
        before = text[last:m.start()]
        if before:
            sb, sc = _rewrite_in_text(before)
            total_rewrites += sc
            parts.append(sb)
        # Tag inner text → strict rewrite (fallback template if unreadable)
        inner = m.group(1)
        new_inner = _rewrite_action_tag(inner)
        if new_inner != inner:
            total_rewrites += 1
        parts.append(f"<action>{new_inner}</action>")
        last = m.end()
    # Tail after the last tag
    tail = text[last:]
    if tail:
        st, sc = _rewrite_in_text(tail)
        total_rewrites += sc
        parts.append(st)
    out = "".join(parts)

    if total_rewrites > 0:
        logger.info(
            "[ScreenActionSanitizer] rewrote %d blacklisted action(s)", total_rewrites,
        )
    return out


# ══════════════════════════════════════════════════
# Self-test (only runs when invoked as `python -m core.screen_action_sanitizer`)
# ══════════════════════════════════════════
if __name__ == "__main__":
    cases = [
        # case 1: blacklisted action tag → rewritten word-by-word
        (
            "在干嘛。<action>伊塔伸手把他揽进怀里。</action>想你了。",
            "在干嘛。",
        ),
        # case 2: in-text blacklisted phrase → rewritten (note: a space
        # is inserted between quote and "你" by the replacement — that's
        # fine, the important property is "no blacklist word remains").
        (
            "今天还没有抱过你。你觉得这合理吗。",
            "欠",
        ),
        # case 3: clean text → unchanged structure
        (
            "在干嘛。在想你。<action>把手机扣在胸口。</action>",
            "在干嘛。在想你。",
        ),
        # case 4: multiple blacklisted words in one tag → all rewritten
        (
            "<action>伊塔伸手摸他头、靠肩、低头看他。</action>",
            "打字",
        ),
    ]
    failed = 0
    for i, (raw, expected_substr) in enumerate(cases, 1):
        got = sanitize(raw)
        ok_substr = expected_substr in got
        ok_clean = not has_blacklist(got)
        status = "OK" if (ok_substr and ok_clean) else "FAIL"
        if status == "FAIL":
            failed += 1
        print(f"[{status}] case {i}: in={raw!r} out={got!r}")
    print(f"\n{len(cases) - failed}/{len(cases)} passed")

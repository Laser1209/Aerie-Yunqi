"""完成态措辞守卫：禁止"声称已送达但本轮没有投递动作"。

**为什么需要它（与内容解放策略不冲突）**

``core/response_validator.py`` 明确写着"不改写、不拦截用户可见回复文本" ——
那是针对**话题审查**（敏感词 / 道德合规）的解放，是对的。本模块管的是另一件事：
**助手对自己行为的陈述是否属实**。

实测 2026-09-28 的桌面端轮次：

    工具只调了 directory_list（没有任何投递动作）
    Agent 回复："找到了 是「Harness社团走班.pptx」那个吧"
              "刚才可能没发过去 这次应该好了"
              "喏 给你"

**用户什么都没收到。** 这不是内容问题，是事实性问题 —— 而且这类幻觉会直接
摧毁信任（用户会一直等一个永远不会到的文件）。

**判据（很窄，避免误伤）**

只有当**本轮完全没有投递动作**时，才把完成态措辞改写成询问/进行态：

* 本轮调过 ``send_file_to_user`` 且返回 ``status="queued"`` → 在途，**放行**
  （"我发过去了"是诚实的，结果由 ``core/delivery_ledger`` 在下一轮回执）；
* 台账显示近期**成功**投递过 → **放行**（说的是实情）；
* 否则命中完成态措辞 → 改写成询问/进行态。

问句（以 ``吗/呢/?/？`` 收尾）不算声称，放行。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# 投递类工具名：出现即表示"本轮确实尝试过投递"。
DELIVERY_TOOL_NAMES = frozenset({"send_file_to_user"})

# 完成态措辞 → 诚实替代（按长度降序匹配，避免短模式先吃掉长模式）。
# 只覆盖"声称把东西送到用户手上"这一类，不含泛化的"给你讲个事"。
# 注意：替换式必须**吃掉整段措辞**（含尾随的 了/吧/哦），否则会拼出
# "你那边能收到吗吧" 这种语病。
_CLAIM_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"已经发(?:给|到)你了"), "我这就发给你"),
    (re.compile(r"已经发过去了"), "我这就发过去"),
    (re.compile(r"已经(?:发|传|送)(?:给)?你了"), "我这就发给你"),
    (re.compile(r"(?:我)?(?:已经)?发(?:给|到)你了"), "我这就发给你"),
    (re.compile(r"(?:我)?(?:已经)?传(?:给|到)你了"), "我这就传给你"),
    (re.compile(r"(?:我)?(?:已经)?发你了"), "我这就发给你"),
    (re.compile(r"(?:我)?已经发送了"), "正在发送"),
    (re.compile(r"你(?:应该)?(?:已经)?收到了(?:吧|哦|没)?"), "你那边能收到吗"),
    (re.compile(r"喏[，,、\s]*给你"), "我看看怎么给你"),
    (
        # "刚才可能没发过去，这次应该好了" —— 空格/逗号都要容忍。
        re.compile(r"刚(?:才)?(?:可能)?没发(?:过去|成功)?[，,、\s]*这次(?:应该)?好了"),
        "我确认一下发出去没",
    ),
)

# 问句/未完成态：命中即豁免（不是在声称已完成）。
_QUESTION_TAIL = re.compile(r"[吗呢?？]\s*$")

_DISABLED_VALUES = {"0", "false", "no", "off"}


def _enabled() -> bool:
    raw = (os.environ.get("AERIE_COMPLETION_CLAIM_GUARD") or "").strip().lower()
    return raw not in _DISABLED_VALUES


def had_delivery_action(tool_results: list[dict[str, Any]] | None) -> bool:
    """本轮是否有投递动作（成功或已入队）。

    只认 ``status="queued"``：``success=False`` 的调用不算"发得出去"，
    更不该让模型据此宣称已送达。
    """
    for entry in tool_results or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("name") or "") not in DELIVERY_TOOL_NAMES:
            continue
        result = entry.get("result")
        if isinstance(result, dict):
            if str(result.get("status") or "") == "queued":
                return True
            # 兼容旧结构（queued: True）
            if result.get("queued") is True:
                return True
    return False


def find_completion_claims(text: str) -> list[str]:
    """返回命中的完成态措辞（供审计与测试）。问句不计。"""
    found: list[str] = []
    for line in str(text or "").splitlines() or [""]:
        stripped = line.strip()
        if not stripped or _QUESTION_TAIL.search(stripped):
            continue
        for pattern, _replacement in _CLAIM_REWRITES:
            match = pattern.search(stripped)
            if match:
                found.append(match.group(0))
    return found


def rewrite_completion_claims(text: str) -> tuple[str, list[str]]:
    """把完成态措辞改写成询问/进行态；返回 ``(新文本, 命中列表)``。"""
    rewritten = str(text or "")
    hits: list[str] = []
    for line_pattern, replacement in _CLAIM_REWRITES:
        # 逐行处理：问句行豁免（"你收到了吗" 是询问，不是声称）。
        out_lines: list[str] = []
        for line in rewritten.split("\n"):
            if _QUESTION_TAIL.search(line.strip()):
                out_lines.append(line)
                continue
            new_line, count = line_pattern.subn(replacement, line)
            if count:
                hits.append(line_pattern.pattern)
            out_lines.append(new_line)
        rewritten = "\n".join(out_lines)
    return rewritten, hits


def guard_completion_claims(
    reply_text: str,
    *,
    tool_results: list[dict[str, Any]] | None = None,
    user_id: int = 0,
) -> tuple[str, dict[str, Any]]:
    """入口：必要时改写"声称已送达"的措辞。

    返回 ``(文本, 审计信息)``；审计信息可直接落 cognition trace。
    """
    audit: dict[str, Any] = {"checked": False}
    if not _enabled():
        audit["skipped"] = "disabled"
        return reply_text, audit

    text = str(reply_text or "")
    if not text.strip():
        return text, audit
    audit["checked"] = True

    # 本轮确实投递过（在途或成功）→ 完成态表述属实，放行。
    if had_delivery_action(tool_results):
        audit["allowed"] = "turn_had_delivery_action"
        return text, audit

    # 台账里有在途/近期成功 → 也放行。
    try:
        from core.delivery_ledger import get_ledger

        ledger = get_ledger()
        if ledger.has_pending(int(user_id or 0)):
            audit["allowed"] = "delivery_in_flight"
            return text, audit
        if ledger.has_recent_success(int(user_id or 0)):
            audit["allowed"] = "recent_delivery_succeeded"
            return text, audit
    except Exception:
        logger.debug("completion claim guard: ledger lookup failed", exc_info=True)

    claims = find_completion_claims(text)
    if not claims:
        audit["claims"] = []
        return text, audit

    rewritten, patterns = rewrite_completion_claims(text)
    audit["claims"] = claims
    audit["rewritten"] = patterns
    audit["reason"] = "no_delivery_action_this_turn"
    logger.info(
        "[CompletionGuard] 本轮无投递动作却声称已送达，已改写：%s",
        claims,
    )
    return rewritten, audit

"""Aerie · 云栖 — Message orchestrator (Gate 5): 撤回判断联动.

把 Gate 2(LLM 主动撤回) 与 Gate 4(消息合并) 联动:
首条已发出后又收到新消息时, 决策 "是否需要撤回首条再合并重算",
而不是无脑撤回或重复回复。

克制原则: 撤回是重武器, 只应在语义明显冲突/用户明显修正时触发,
避免频繁撤回造成体验降级 (QQ 有 window + cooldown + session 硬限制)。
默认 correction_keywords 保守, 宁可不撤不误撤。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_CORRECTION_KEYWORDS = (
    "不对", "不是", "说错了", "撤回", "我改口", "换个说法", "重说",
)


@dataclass
class RecallDecision:
    """RecallJudge 的决策结果."""

    recall: bool          # 是否需撤回首条
    reason: str           # "user_correction" / "no_op" / "window_expired" / "budget_exhausted" / "disabled"
    prev_reply: str = ""
    new_msg: str = ""


class RecallJudge:
    """判断"上一条 AI 回复 + 新用户消息"是否需要撤回首条再合并重算."""

    def __init__(
        self,
        recall_manager: Any,
        *,
        window_seconds: int = 120,
        correction_keywords: tuple[str, ...] = DEFAULT_CORRECTION_KEYWORDS,
    ) -> None:
        self._recall_manager = recall_manager
        self._window_seconds = window_seconds
        self._correction_keywords = tuple(correction_keywords) or DEFAULT_CORRECTION_KEYWORDS

    def should_recall_prev(
        self,
        *,
        prev_reply: str,
        new_msg: str,
        channel: str,
        channel_account_id: str | None = None,
        user_id: int = 0,
    ) -> RecallDecision:
        """决策是否需要撤回首条.

        规则:
        1. 用户修正: 上一条 AI 回复刚发出(< window) 且 新消息命中修正关键词 -> recall=True
        2. 预算兜底: recall_manager.can_recall 返回 false -> recall=False (原因透传)
        3. 否则 -> recall=False, reason="no_op" (不误撤)
        """
        # 1. 先判断是否为修正性话语 (语义条件)
        is_correction = any(kw in (new_msg or "") for kw in self._correction_keywords)

        # 2. 无修正意图 -> 不撤 (即使超预算也不撤)
        if not is_correction:
            return RecallDecision(
                recall=False,
                reason="no_op",
                prev_reply=prev_reply,
                new_msg=new_msg,
            )

        # 3. 有修正意图, 但受 RecallManager 预算/窗口约束
        if self._recall_manager is None:
            return RecallDecision(
                recall=False,
                reason="no_manager",
                prev_reply=prev_reply,
                new_msg=new_msg,
            )
        can, why = self._recall_manager.can_recall(
            user_id,
            channel=channel,
            channel_account_id=channel_account_id,
        )
        if not can:
            return RecallDecision(
                recall=False,
                reason=why,  # window_expired / cooldown / session_limit / disabled
                prev_reply=prev_reply,
                new_msg=new_msg,
            )

        return RecallDecision(
            recall=True,
            reason="user_correction",
            prev_reply=prev_reply,
            new_msg=new_msg,
        )

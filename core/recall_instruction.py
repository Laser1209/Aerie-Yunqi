"""Aerie · 云栖 — LLM 主动撤回指令 (Gate 2).

允许 AI 在回复中输出可执行撤回指令, 与纯文本的 <action>(人设动作描写)
严格分离:
  - <action>  : 人设描写, 发送时被过滤, 不执行
  - <recall>  : 框架指令, 执行撤回上一条已发 AI 消息, 并从正文剔除

格式:
    <recall reason="说错话了">这条我撤回</recall>

受 RecallManager 预算约束 (window / cooldown / session limit), 不越权撤回。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

RECALL_RE = re.compile(r"<recall\b[^>]*>(.*?)</recall>", re.DOTALL | re.IGNORECASE)
REASON_ATTR_RE = re.compile(r"""\breason\s*=\s*["']([^"']*)["']""", re.IGNORECASE)


@dataclass
class RecallInstruction:
    reason: str
    raw_tag: str


def extract_recall_instruction(raw: str) -> RecallInstruction | None:
    """从 LLM 原始输出中提取首个撤回指令; 无则返回 None.

    reason 取 <recall reason="..."> 属性值 (缺省为空串), 内部正文被忽略。
    """
    if not raw:
        return None
    m = RECALL_RE.search(raw)
    if not m:
        return None
    attr = REASON_ATTR_RE.search(m.group(0))
    reason = attr.group(1).strip() if attr else ""
    return RecallInstruction(reason=reason, raw_tag=m.group(0))


def strip_recall_instruction(text: str) -> str:
    """从正文剔除所有撤回指令标签 (不发送给用户)."""
    return RECALL_RE.sub("", text or "")


async def execute_recall_instruction(
    recall_manager: Any,
    *,
    channel: str,
    channel_account_id: str | None,
    user_id: int,
    reason: str,
) -> dict[str, Any]:
    """执行撤回指令: 撤回该 channel 用户上一条已发 AI 消息.

    Returns RecallManager.try_recall 的结果 dict.
    """
    if recall_manager is None:
        return {"status": "skipped", "reason": "no_manager", "channel": channel}
    return await recall_manager.try_recall(
        user_id,
        reason=reason or "llm_instruction",
        channel=channel,
        channel_account_id=channel_account_id,
    )

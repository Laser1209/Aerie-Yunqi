"""自我进化提案工具 —— 让模型能**主动提出**改进建议，但绝不自己动手。

背景（Part D2）：在补上这个工具之前，全仓没有任何 `self_evolve*` 工具，
模型只能等管线内部被动触发（关键词 + 工具调用失败双条件命中）。
于是"AI 想改自己"这件事，模型既说不了、也提不了。

设计边界（重要）：
- 本工具**只登记一条待审提案**，不生成文件内容、不写盘、不跑闸门；
- 真正产生 `file_changes` 的路径仍是既有内部链路（缺口检测 → LLM 生成 →
  四道门 → 人工确认），模型主动提案只是把"我觉得该改 X"这句话变成一条记录，
  交给用户/小伊面板去处理；
- 因此这里对"提案后有没有文件变化"的测试断言是：**一个字节都不许动**。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SUMMARY_CHARS = 200
_MAX_DETAIL_CHARS = 2000
_MAX_HINT_CHARS = 200


def propose_self_improvement(summary: str, detail: str = "", target_hint: str = "") -> dict:
    """登记一条「建议改进本程序」的提案，等待人工确认。

    - `summary`：一句话说清要改什么（必填）
    - `detail`：为什么改 / 怎么改 / 影响面（可选）
    - `target_hint`：涉及的路径或模块名（可选，如 `core/topic_resurface.py`）
    """
    title = str(summary or "").strip()[:_MAX_SUMMARY_CHARS]
    if not title:
        return {"error": "missing summary", "provider_hint": "text"}

    from core.companion import get_companion

    companion = get_companion()
    evolver = getattr(companion, "l4_evolution", None) if companion else None
    if evolver is None:
        return {
            "status": "unavailable",
            "error": "自我进化链路未启用（feature_flags.self_evolve_l4_enabled 为 false）",
        }

    try:
        proposal = evolver.submit_model_proposal(
            title=title,
            description=str(detail or "").strip()[:_MAX_DETAIL_CHARS],
            target_hint=str(target_hint or "").strip()[:_MAX_HINT_CHARS],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("propose_self_improvement 登记失败")
        return {"status": "error", "error": str(exc)[:300]}

    return {
        "status": "ok",
        "proposal_id": proposal.proposal_id,
        "pending": True,
        "note": "已登记为待审提案，等待用户确认；本工具不会修改任何文件",
    }


def register_self_evolve_tools(registry: Any) -> None:
    registry.register("propose_self_improvement", propose_self_improvement, {
        "description": (
            "当你发现本程序本身有可改进之处（缺失的能力、明显的 bug、反复出错的流程）"
            "时，用这个工具**登记一条待审提案**：一句话说清改什么，可以补充原因与涉及的路径。"
            "它只会生成一条等待用户确认的记录，**不会修改任何文件、不会自动生效**。"
            "用户问「你能不能改自己」时也用这个工具给出正式提议，而不是口头答应。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "一句话说清要改什么（必填）",
                },
                "detail": {
                    "type": "string",
                    "description": "可选。为什么改 / 怎么改 / 影响面",
                },
                "target_hint": {
                    "type": "string",
                    "description": "可选。涉及的路径或模块名，如 core/topic_resurface.py",
                },
            },
            "required": ["summary"],
        },
    })

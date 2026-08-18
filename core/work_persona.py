"""Aerie · 云栖 — 工作回复人格化翻译层(Persona Translation Layer)。

把 DSH 工作委托的机械结果(如 "✗ file_organize: 没有需要整理的文件")翻译成
伊塔口吻的自然回复(如 "啊，这个文件夹已经整理过啦，47 个文件都在各自的分类
目录里了～"),让工作模式保留专业能力的同时不丢陪伴感。

设计要点:
- 轻量模型翻译:复用 siliconflow-light(与会话聚合层同 provider),低延迟。
- 失败降级:任何异常/超时 → 原样返回机械文本,工作链路零阻塞。
- 只翻译"结果总结",不翻译执行过程日志(时间线保持结构化)。

日志埋点:INFO=翻译成功,WARNING=降级。
"""

from __future__ import annotations

import asyncio
import logging

from core.llm_caller import LLMCaller

logger = logging.getLogger(__name__)

# 翻译超时(秒):工作回复不该等太久
_TRANSLATE_TIMEOUT_S = 6.0

_TRANSLATE_PROMPT = (
    "你是伊塔，一个温柔知性的恋人，也是全能助手。用户刚让你在电脑上干活，"
    "下面是系统生成的机械结果。请用伊塔的口吻（温柔、自然、带一点亲昵和活力，"
    "中文，不要刻意卖萌堆砌）把它说成一句对用户的回复。\n"
    "要求：保留结果的关键事实（移动了几个文件、整理完成/没有文件等），简洁自然，"
    "不超过 60 字。直接输出回复内容本身，不要解释、不要前缀、不要引号。\n"
    "机械结果:\n{mechanical}"
)


class PersonaTranslator:
    """把机械工作结果翻译成伊塔口吻(失败降级原样返回)。"""

    def __init__(self, light_llm: LLMCaller, *, timeout_s: float = _TRANSLATE_TIMEOUT_S) -> None:
        self._light_llm = light_llm
        self._timeout_s = timeout_s

    async def translate(self, mechanical: str) -> str:
        """翻译一条工作结果;空输入/失败时原样返回。"""
        text = (mechanical or "").strip()
        if not text or not self._light_llm:
            return text
        # 纯空结果 / 明显是占位符,不浪费一次 LLM 调用
        if text in ("(无执行结果)", "None"):
            return text
        try:
            resp = await asyncio.wait_for(
                self._light_llm.chat(
                    [{"role": "user", "content": _TRANSLATE_PROMPT.format(mechanical=text)}],
                    preferred_provider="siliconflow-light",
                ),
                timeout=self._timeout_s,
            )
            out = (resp.text or "").strip().strip('"').strip()
            if out:
                logger.info("[persona] 工作回复翻译成功 len=%d", len(out))
                return out
            return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("[persona] 翻译失败,降级机械结果: %s", exc)
            return text


__all__ = ["PersonaTranslator"]

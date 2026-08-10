"""Aerie · 云栖 — Typo Corrector (错别字纠错通道).

在主回复被生成之前，先用一个轻量模型（默认硅基流动 · 小米 MiMo）对用户消息
做一次独立的"检出 + 订正"，把订正后的文本交给主模型理解，避免主模型因一个
错字/同音字误解用户意思（例如 "换好了美呀" 实为 "换好了没呀"）。

信任边界：
- 判断是语义化的：由小模型结合原文判断是否为明显错漏，只订正确有把握的，
  其余保持原样，不臆测、不改写语气。
- 仅在高置信时替换：若小模型输出与原文一致，说明未检出错字，原样返回。
- 只要轻量 provider 未配置或调用失败，就静默回退原文，绝不阻塞主链路，
  也绝不 fallback 到昂贵的主模型上去做纠错。
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# 纠错通道专用 provider（复用 siliconflow-light，避免触碰主模型）。
_LIGHT_PROVIDER = "siliconflow-light"
# 超时上限：宁可跳过也不拖慢一条聊天。
_DEFAULT_TIMEOUT = 6.0
# 超过该长度的文本不做纠错，避免延迟与误改。
_MAX_CHARS = 200


def _light_provider_available() -> bool:
    """轻量 provider 配齐了才启用纠错，避免误用主模型。"""
    return bool(os.getenv("SILICONFLOW_API_KEY")) and bool(
        os.getenv("SILICONFLOW_LIGHT_MODEL")
    )


_SYSTEM_PROMPT = (
    "你是中文错别字订正助手。用户打字时偶尔会有同音字或错别字，"
    "例如把“没呀”打成“美呀”、“换好了没呀”打成“换好了美呀”。\n"
    "你的任务：\n"
    "1. 若原文有明显错别字/同音字，输出订正后的完整文本；\n"
    "2. 若没有，原样输出原文；\n"
    "3. 只订正确有把握的、结合上下文能确定的明显错漏，不要臆测、"
    "不要改变原意、不要改写语气或风格。\n"
    "严格只输出订正后的文本本身，不要任何解释、引号或前后缀。"
)


async def correct_typos(
    brain,
    text: str,
    *,
    provider: str = _LIGHT_PROVIDER,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """对用户文本做错别字订正，返回订正后的文本；未检出/失败/超长时返回原文。

    Args:
        brain: LLMCaller 实例（具备 ``chat`` 方法）。
        text: 用户原始消息文本。

    Returns:
        订正后的文本；任何异常或条件不满足时原样返回 ``text``。
    """
    if not text or not str(text).strip():
        return str(text or "")

    original = str(text)
    if len(original) > _MAX_CHARS:
        logger.debug("[TypoCorrector] 文本过长(%d>%d)，跳过纠错", len(original), _MAX_CHARS)
        return original
    if not _light_provider_available():
        logger.debug("[TypoCorrector] 轻量 provider 未配置，跳过纠错")
        return original

    try:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": original},
        ]
        call = brain.chat(
            messages,
            preferred_provider=provider,
            temperature=0.0,
        )
        resp = await asyncio.wait_for(call, timeout=timeout)
    except Exception as e:
        logger.debug("[TypoCorrector] 纠错调用失败，回退原文: %s", e)
        return original

    corrected = (resp.text or "").strip()
    if not corrected or corrected == original:
        return original

    logger.info("[TypoCorrector] 订正 %r -> %r", original, corrected)
    return corrected
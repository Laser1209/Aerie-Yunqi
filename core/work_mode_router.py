"""Aerie · 云栖 — 工作模式路由(三层判定)。

决定一条用户消息走「DSH 委托」还是「原 LLMCaller」。判定从便宜到贵:
  L1 关键词正则(免费) → L2 轻量模型三分类(低) → L3 用户显式(强制)。

设计要点:
- 只做「路由判定」,不启动 DSH、不执行协议(那是 dsh_cli / work_protocol 的事)。
- 降级:DSH 熔断时恒返回 kind="llm",聊天零阻塞(整合文档 V2/降级路径)。
- 日志埋点与 dsh_cli.py 对齐:INFO=判定结果,WARNING=降级,DEBUG=每层细节。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from core.dsh_cli import DshCli
from core.llm_caller import LLMCaller

logger = logging.getLogger(__name__)

# 工作动词表 → 场景 preset 名(正则匹配,命中即委托)
_KEYWORD_PRESETS: list[tuple[str, str]] = [
    (r"整理|归类|分类|重命名|归档|移动文件", "file-organizer"),
    (r"打开|点击|截图|执行命令|运行命令|输入|打字|操控电脑|控制电脑|按下", "computer-control"),
    (r"写文档|写报告|生成报告|写方案|写总结|写周报|写纪要|文档", "doc-writer"),
    (r"搜索|调研|查资料|研究|检索|查一下", "research"),
]

# L2 轻量分类的超时(秒)
_CLASSIFY_TIMEOUT_S = 5.0

_CLASSIFY_PROMPT = (
    "判断下面这句话属于「工作型任务」还是「日常聊天」。"
    "工作型任务包括:整理文件、操作电脑、写文档/报告、搜索调研、执行命令等。"
    "只回复一个词:work 或 daily。\n"
    "用户:"
)


@dataclass(slots=True)
class RouteDecision:
    """路由决策结果。"""

    kind: str  # "delegate" | "llm"
    preset: str | None  # delegate 时的场景名
    reason: str  # keyword / light / explicit / fallback / dsh_unavailable


class WorkModeRouter:
    """工作模式路由:三层判定消息是否委托 DSH。"""

    def __init__(self, dsh: DshCli, llm: LLMCaller | None = None) -> None:
        self._dsh = dsh
        self._llm = llm

    async def decide(
        self,
        text: str,
        *,
        user_id: str,
        explicit: bool = False,
    ) -> RouteDecision:
        """判定一条消息的路由。返回 RouteDecision(kind, preset, reason)。"""
        text = (text or "").strip()
        logger.info(
            "[wrouter] decide text_len=%d user_id=%s explicit=%s text=%s",
            len(text), user_id, explicit, text[:80],
        )

        # 降级前置:DSH 熔断 → 恒走 LLMCaller
        status = await self._dsh.status()
        if status.get("degraded"):
            logger.warning("[wrouter] DSH 熔断,降级 LLMCaller")
            return RouteDecision(kind="llm", preset=None, reason="dsh_unavailable")

        if not text:
            return RouteDecision(kind="llm", preset=None, reason="fallback")

        # L3:用户显式(最高优先级)
        if explicit:
            preset = self._match_keyword(text)
            logger.info("[wrouter] L3 显式委托 preset=%s", preset)
            return RouteDecision(kind="delegate", preset=preset, reason="explicit")

        # L1:关键词正则(免费)
        preset = self._match_keyword(text)
        if preset:
            logger.info("[wrouter] L1 关键词命中 preset=%s", preset)
            return RouteDecision(kind="delegate", preset=preset, reason="keyword")

        # L2:轻量模型三分类(低,5s 超时,失败降级)
        if self._llm is not None:
            verdict = await self._classify_light(text)
            if verdict == "work":
                logger.info("[wrouter] L2 轻量分类=work,委托(默认 preset)")
                return RouteDecision(kind="delegate", preset=None, reason="light")
            if verdict == "daily":
                logger.info("[wrouter] L2 轻量分类=daily,走 LLMCaller")
                return RouteDecision(kind="llm", preset=None, reason="light")

        logger.info("[wrouter] 未命中,走 LLMCaller")
        return RouteDecision(kind="llm", preset=None, reason="fallback")

    # ------------------------------------------------------------------ 判定层

    @staticmethod
    def _match_keyword(text: str) -> str | None:
        """L1 关键词正则匹配,返回首个命中的 preset 名。"""
        for pattern, preset in _KEYWORD_PRESETS:
            if re.search(pattern, text):
                logger.debug("[wrouter] 关键词命中 pattern=%s preset=%s", pattern, preset)
                return preset
        return None

    async def _classify_light(self, text: str) -> str | None:
        """L2 轻量模型三分类,返回 work/daily/None(失败)。"""
        assert self._llm is not None
        t0 = asyncio.get_running_loop().time()
        try:
            resp = await asyncio.wait_for(
                self._llm.chat([{"role": "user", "content": _CLASSIFY_PROMPT + text}]),
                timeout=_CLASSIFY_TIMEOUT_S,
            )
            elapsed = asyncio.get_running_loop().time() - t0
            raw = (resp.text or "").strip().lower()
            logger.debug("[wrouter] 轻量分类耗时=%.2fs 原文=%r", elapsed, raw[:40])
            if "work" in raw:
                return "work"
            if "daily" in raw:
                return "daily"
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wrouter] 轻量分类失败(降级): %s", exc)
            return None


__all__ = ["WorkModeRouter", "RouteDecision"]

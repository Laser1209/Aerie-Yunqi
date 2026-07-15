"""AI 核心：API 调用、回复生成、意图分类

Phase 2 重构：
- 剥离 Prompt 构建 → core/personality.py
- 保留 API 调用 + 容灾切换
- 新增 classify_intent() 用于意图分类
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI


class AIBrain:
    """AI 大脑：管理 API 调用、Provider 容灾切换"""

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: AI 配置节（settings.yaml 中的 ai 段）
        """
        self._config = config
        self._providers = self._init_providers()
        self._primary_index = 0

    def _init_providers(self) -> List[Dict[str, Any]]:
        """初始化三家 AI 提供商"""
        providers = []

        # 主 API：硅基流动
        silicon_key = os.getenv("SILICONFLOW_API_KEY", "")
        if silicon_key:
            providers.append({
                "name": "siliconflow",
                "client": AsyncOpenAI(
                    api_key=silicon_key,
                    base_url="https://api.siliconflow.cn/v1",
                ),
                "model": self._config.get("primary", {}).get(
                    "model", "deepseek-ai/DeepSeek-V3"
                ),
            })

        # 备选：DeepSeek
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        if deepseek_key:
            providers.append({
                "name": "deepseek",
                "client": AsyncOpenAI(
                    api_key=deepseek_key,
                    base_url="https://api.deepseek.com/v1",
                ),
                "model": "deepseek-chat",
            })

        # 兜底：智谱
        zhipu_key = os.getenv("ZHIPUAI_API_KEY", "")
        if zhipu_key:
            providers.append({
                "name": "zhipu",
                "client": AsyncOpenAI(
                    api_key=zhipu_key,
                    base_url="https://open.bigmodel.cn/api/paas/v4",
                ),
                "model": "glm-4-flash",
            })

        if not providers:
            raise RuntimeError(
                "没有配置任何 AI API Key！请在 .env 中设置 "
                "SILICONFLOW_API_KEY / DEEPSEEK_API_KEY / ZHIPUAI_API_KEY"
            )

        logger.info(
            f"AI 提供商已就绪: {', '.join(p['name'] for p in providers)} "
            f"(主: {providers[0]['name']})"
        )
        return providers

    async def _call_api(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        调用 AI API（含三级容灾）。

        Args:
            messages: OpenAI 格式的消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            timeout: 超时秒数

        Returns:
            AI 生成的回复内容

        Raises:
            RuntimeError: 所有提供商均失败
        """
        temperature = temperature if temperature is not None else self._config.get("temperature", 0.8)
        max_tokens = max_tokens if max_tokens is not None else self._config.get("max_tokens", 1024)
        timeout = timeout if timeout is not None else self._config.get("timeout", 30)

        last_error = None
        for provider in self._providers:
            try:
                msg_count = len(messages)
                preview = messages[-1].get("content", "")[:50] if messages else ""
                logger.debug(f"尝试 {provider['name']}: [{msg_count} msgs] {preview}...")

                resp = await asyncio.wait_for(
                    provider["client"].chat.completions.create(
                        model=provider["model"],
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        top_p=0.9,
                    ),
                    timeout=timeout,
                )
                reply = resp.choices[0].message.content or ""
                logger.info(f"[{provider['name']}] 回复: {reply[:100]}...")
                return reply

            except asyncio.TimeoutError:
                last_error = f"{provider['name']} 超时 ({timeout}s)"
                logger.warning(last_error)
            except Exception as e:
                last_error = f"{provider['name']}: {e}"
                logger.warning(last_error)

        raise RuntimeError(f"所有 AI 提供商均失败，最后错误: {last_error}")

    async def generate_reply(self, messages: List[Dict[str, str]]) -> str:
        """
        生成对话回复。

        Args:
            messages: 完整消息列表（已包含 System Prompt + 历史 + 当前消息）

        Returns:
            AI 生成的回复内容
        """
        return await self._call_api(messages)

    async def classify_intent(
        self,
        text: str,
        system_prompt: str,
    ) -> str:
        """
        轻量意图分类（用于 IntentClassifier 的回退）。

        Args:
            text: 用户消息
            system_prompt: 分类 System Prompt

        Returns:
            分类结果字符串（如 "chat" / "command" / "query"）
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        return await self._call_api(
            messages,
            temperature=0.1,   # 分类任务用极低温度
            max_tokens=10,      # 分类只需一个词
            timeout=5,          # 分类允许更短超时
        )

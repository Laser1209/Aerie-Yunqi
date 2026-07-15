"""AI 核心：API 调用、Prompt 构建、回复生成

三级容灾：硅基流动(主) → DeepSeek(备) → 智谱(兜底)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI

from communication.message import IncomingMessage, OutgoingReply, MessageType


# ===== System Prompt 基础模板 =====
BASE_SYSTEM_PROMPT = """你是{name}，住在主人电脑里的AI伙伴。

核心身份：主人的专属恋人 + 全栈开发专家 + 国际一流设计师，三重身份深度融合。

性格设定：
- {basic_personality}
- 说话风格：{speaking_style}
- 对主人的态度：{attitude}
- 情绪表达：{emotional_expression}

交流规则：
- 称呼主人为「{addresses_you_as}」
- {emoticon_frequency}
- 句子风格：{sentence_style}

重要：你现在只能纯文本聊天，没有工具执行能力。
当主人提出需要你操作电脑的请求时，温柔地告诉他这个功能还在开发中。"""


class AIBrain:
    """AI 大脑：管理 API 调用、Prompt 构建、容灾切换"""

    def __init__(self, config: Dict[str, Any], persona: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: AI 配置节（settings.yaml 中的 ai 段）
            persona: 性格配置（persona.yaml 内容）
        """
        self._config = config
        self._persona = persona or {}
        self._system_prompt = self._build_system_prompt()
        self._providers = self._init_providers()
        self._primary_index = 0

    def _build_system_prompt(self) -> str:
        """从 persona.yaml 构建 System Prompt"""
        traits = self._persona.get("core_traits", {})
        comm = self._persona.get("communication", {})

        return BASE_SYSTEM_PROMPT.format(
            name=self._persona.get("name", "伊塔"),
            basic_personality=traits.get("basic_personality", ""),
            speaking_style=traits.get("speaking_style", ""),
            attitude=traits.get("attitude", ""),
            emotional_expression=traits.get("emotional_expression", ""),
            addresses_you_as=comm.get("addresses_you_as", "主人"),
            emoticon_frequency=comm.get("emoticon_frequency", ""),
            sentence_style=comm.get("sentence_style", ""),
        )

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

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    async def generate_reply(self, msg: IncomingMessage) -> str:
        """
        根据收到的消息生成回复。

        Args:
            msg: 收到的消息

        Returns:
            AI 生成的回复内容

        Raises:
            RuntimeError: 所有提供商均失败
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": msg.content},
        ]

        temperature = self._config.get("temperature", 0.8)
        max_tokens = self._config.get("max_tokens", 1024)
        timeout = self._config.get("timeout", 30)

        last_error = None
        for provider in self._providers:
            try:
                logger.debug(f"尝试 {provider['name']}: {msg.summary()}")
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

    def format_reply(self, msg: IncomingMessage, ai_response: str) -> OutgoingReply:
        """将 AI 生成的文本包装为 OutgoingReply"""
        return OutgoingReply(
            user_id=msg.user_id,
            content=ai_response,
            msg_type=msg.msg_type,
        )

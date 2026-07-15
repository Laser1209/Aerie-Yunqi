"""AI 核心：API 调用、回复生成、意图分类

Phase 3 扩展：
- 新增 generate_with_tools() 支持 OpenAI Function Calling
- 三级容灾 + tool_choice="auto" 自动决策
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI


@dataclass
class ToolCallResult:
    """Function Calling 结果"""
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: str = "stop"


class AIBrain:
    """AI 大脑：管理 API 调用、Provider 容灾切换"""

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._providers = self._init_providers()
        # 启动期轻量校验：探测每个 provider 的模型是否真实存在
        # 默认开启，配置中可设 startup_ping: false 关闭
        if self._config.get("startup_ping", True):
            self._startup_ping_done = False

    def _init_providers(self) -> List[Dict[str, Any]]:
        """初始化 AI 提供商：从 settings.yaml 的 primary + fallback 列表读取"""
        providers = []

        # ===== 主 provider（从 config.primary 读取）=====
        primary_cfg = self._config.get("primary", {})
        primary_provider = primary_cfg.get("provider", "siliconflow").lower()
        primary_key = self._get_api_key(primary_provider)
        if primary_key:
            providers.append({
                "name": primary_provider,
                "client": AsyncOpenAI(
                    api_key=primary_key,
                    base_url=self._get_base_url(primary_provider),
                ),
                "model": primary_cfg.get("model", "deepseek-ai/DeepSeek-V3"),
            })

        # ===== 备选 providers（从 config.fallback 列表读取）=====
        for fb in self._config.get("fallback", []):
            fb_provider = fb.get("provider", "").lower()
            if not fb_provider:
                continue
            fb_key = self._get_api_key(fb_provider)
            if fb_key:
                providers.append({
                    "name": fb_provider,
                    "client": AsyncOpenAI(
                        api_key=fb_key,
                        base_url=self._get_base_url(fb_provider),
                    ),
                    "model": fb.get("model", ""),
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

    def _get_api_key(self, provider: str) -> str:
        """根据 provider 名获取对应的 API key"""
        env_map = {
            "siliconflow": "SILICONFLOW_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "zhipu": "ZHIPUAI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        env_var = env_map.get(provider, f"{provider.upper()}_API_KEY")
        return os.getenv(env_var, "")

    def _get_base_url(self, provider: str) -> str:
        """根据 provider 名获取对应的 base_url"""
        url_map = {
            "siliconflow": "https://api.siliconflow.cn/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4",
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
        }
        return url_map.get(provider, "")

    async def _ping_provider(self, provider: Dict[str, Any]) -> bool:
        """
        启动期探测：检查 provider 的模型是否真实可用。
        区分 401 (key 失效) vs 404 (模型不存在) — 给出精准提示。
        失败/超时不会抛错，只记录警告。
        """
        try:
            models = await provider["client"].models.list()
            available = [m.id for m in models.data]
            target = provider["model"]
            if target not in available:
                # 模糊匹配：找前缀相同或包含关键词的
                suggestions = [
                    m for m in available
                    if target.split("/")[-1].lower() in m.lower()
                ][:5]
                logger.warning(
                    f"⚠️ [{provider['name']}] 模型 {target!r} 不在可用列表。"
                    f"建议改用: {suggestions or available[:5]}"
                )
                return False
            logger.info(f"✅ [{provider['name']}] 模型 {target!r} 可用（共 {len(available)} 个模型）")
            return True
        except Exception as e:
            err_type = type(e).__name__
            err_msg = str(e)
            if "401" in err_msg or "Authentication" in err_type or "Auth" in err_type:
                logger.warning(
                    f"🔑 [{provider['name']}] API Key 失效（401）！"
                    f"请检查 .env 中 {provider['name'].upper()}_API_KEY 是否正确或已过期"
                )
            elif "404" in err_msg or "NotFound" in err_type:
                logger.warning(
                    f"🔍 [{provider['name']}] 模型 {provider['model']!r} 不存在（404）"
                )
            else:
                logger.debug(f"[{provider['name']}] ping 失败（忽略）: {err_type}: {err_msg}")
            return True  # 探测失败不阻断，启动后实际调用时再报错

    async def startup_check(self) -> None:
        """启动期检查所有 provider（每个独立超时 3s，总计不超过 10s）"""
        # 已跑过则跳过（避免重复探测）
        if getattr(self, "_startup_ping_done", False):
            return
        if not self._config.get("startup_ping", True):
            logger.info("启动期模型校验已关闭（startup_ping=false）")
            self._startup_ping_done = True
            return
        self._startup_ping_done = True
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *[self._ping_provider(p) for p in self._providers],
                    return_exceptions=True,
                ),
                timeout=10,
            )
        except asyncio.TimeoutError:
            logger.warning("启动期模型校验超时（>10s），跳过剩余")

    async def _call_api_raw(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ):
        """
        底层 API 调用（返回原始 Response）。

        Returns:
            OpenAI ChatCompletion response object
        """
        temperature = temperature if temperature is not None else self._config.get("temperature", 0.8)
        max_tokens = max_tokens if max_tokens is not None else self._config.get("max_tokens", 1024)
        timeout = timeout if timeout is not None else self._config.get("timeout", 30)

        last_error = None
        for provider in self._providers:
            try:
                kwargs = dict(
                    model=provider["model"],
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=0.9,
                )
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                resp = await asyncio.wait_for(
                    provider["client"].chat.completions.create(**kwargs),
                    timeout=timeout,
                )
                logger.info(f"[{provider['name']}] 完成: {resp.choices[0].finish_reason}")
                return resp

            except asyncio.TimeoutError:
                last_error = f"{provider['name']} 超时 ({timeout}s)"
                logger.warning(last_error)
            except Exception as e:
                last_error = f"{provider['name']}: {e}"
                logger.warning(last_error)

        raise RuntimeError(f"所有 AI 提供商均失败，最后错误: {last_error}")

    async def generate_reply(self, messages: List[Dict[str, str]]) -> str:
        """生成对话回复"""
        resp = await self._call_api_raw(messages)
        return resp.choices[0].message.content or ""

    async def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
    ) -> ToolCallResult:
        """
        带 Function Calling 的回复生成。

        Args:
            messages: 完整消息列表
            tools: OpenAI Function Calling tools 定义列表

        Returns:
            ToolCallResult —— content 或 tool_calls 必有一个
        """
        resp = await self._call_api_raw(
            messages,
            tools=tools,
            temperature=0.1,   # 命令执行用低温度
        )

        choice = resp.choices[0]
        msg = choice.message

        # 工具调用
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                })
            return ToolCallResult(
                tool_calls=tool_calls,
                content=msg.content,
                finish_reason=choice.finish_reason,
            )

        # 纯文本回复
        return ToolCallResult(
            content=msg.content or "",
            finish_reason=choice.finish_reason,
        )

    async def classify_intent(self, text: str, system_prompt: str) -> str:
        """轻量意图分类"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        resp = await self._call_api_raw(
            messages, temperature=0.1, max_tokens=10, timeout=5,
        )
        return resp.choices[0].message.content or ""

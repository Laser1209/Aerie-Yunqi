"""Aerie · 云栖 v9.0 — Brain: multi-provider LLM dispatcher with fallback chain.

Order: Qwen → DeepSeek → Gemini. If primary fails, automatically
fall back to the next provider.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from core.providers.base import LLMResponse, Provider
from core.providers.qwen import QwenProvider
from core.providers.deepseek import DeepSeekProvider
from core.providers.gemini import GeminiProvider
from core.token_tracker import TokenTracker
from communication.message import OutgoingReply


class Brain:
    """Multi-provider LLM dispatcher for Aerie · 云栖."""

    def __init__(
        self,
        providers: Optional[list[Provider]] = None,
        tracker: Optional[TokenTracker] = None,
    ) -> None:
        self.providers = providers or self._default_providers()
        self.tracker = tracker or TokenTracker()

    def _default_providers(self) -> list[Provider]:
        providers: list[Provider] = []
        # Try to construct each provider; missing API key is OK — we'll skip on use.
        try:
            providers.append(QwenProvider())
        except Exception:
            pass
        try:
            providers.append(DeepSeekProvider())
        except Exception:
            pass
        try:
            providers.append(GeminiProvider())
        except Exception:
            pass
        return providers

    def add_provider(self, provider: Provider) -> None:
        self.providers.append(provider)

    async def think(
        self,
        messages: list[dict],
        scene: str = "chat",
        user_id: int = 0,
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Try each provider in order; return the first successful response."""
        last_error: Optional[Exception] = None
        for provider in self.providers:
            start = time.perf_counter()
            try:
                resp = await provider.complete(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                duration_ms = int((time.perf_counter() - start) * 1000)
                if resp.success:
                    self.tracker.record(
                        user_id=user_id,
                        provider=resp.provider,
                        model=resp.model,
                        scene=scene,
                        prompt_tokens=resp.prompt_tokens,
                        completion_tokens=resp.completion_tokens,
                        duration_ms=duration_ms,
                        success=True,
                    )
                    return resp
            except Exception as e:
                last_error = e
                duration_ms = int((time.perf_counter() - start) * 1000)
                self.tracker.record(
                    user_id=user_id,
                    provider=provider.name,
                    model=provider.model,
                    scene=scene,
                    duration_ms=duration_ms,
                    success=False,
                    error_message=str(e)[:200],
                )
        # All providers failed
        return LLMResponse(
            content="",
            provider="none",
            model="none",
            finish_reason="all_failed",
        )

    async def generate_push(
        self,
        template: str,
        mood: str = "neutral",
        user_id: int = 0,
        **kwargs: Any,
    ) -> str:
        """Generate a proactive-push message.

        If LLM is available, ask it to color the template with current mood
        and kwargs. If LLM fails, fall back to the template verbatim.
        """
        from config.persona_loader import load_persona

        persona = load_persona()
        system = persona.get("system_prompt", "")
        # Quick template substitution
        for k, v in kwargs.items():
            template = template.replace("{" + k + "}", str(v))
        prompt = (
            f"{system}\n\n"
            f"当前心境：{mood}\n"
            f"参考模板：{template}\n\n"
            f"要求：以伊塔的口吻重写这条主动消息。≤30 字，命令式短句，"
            f"可省略主语，可加 0-1 个 emoji。不允许编造用户没有说过的话。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        resp = await self.think(messages, scene="proactive_push", user_id=user_id, temperature=0.8)
        if resp.success and resp.content:
            return resp.content.strip()
        return template

    async def health_check(self) -> dict[str, bool]:
        """Return per-provider health status."""
        results: dict[str, bool] = {}
        for p in self.providers:
            results[p.name] = await p.health_check()
        return results

"""Aerie · 云栖 v9.0 — MiniMax provider (OpenAI-compatible)."""

from __future__ import annotations

import os
from typing import Any, Optional

from openai import AsyncOpenAI

from core.providers.base import LLMResponse, Provider


class MiniMaxProvider(Provider):
    name = "minimax"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ):
        api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        base_url = base_url or os.getenv(
            "MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"
        )
        model = model or os.getenv("MINIMAX_MODEL", "MiniMax-M3")
        super().__init__(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    async def complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            params["tools"] = tools
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        params.update(kwargs)
        completion = await self.client.chat.completions.create(**params)
        choice = completion.choices[0]
        msg = choice.message
        content = msg.content or ""
        tool_calls: list[dict] = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })
        usage = completion.usage or None
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
            finish_reason=choice.finish_reason or "stop",
            tool_calls=tool_calls,
            raw=completion,
        )

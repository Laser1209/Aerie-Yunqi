"""Aerie · 云栖 v9.0 — Brain: multi-provider LLM call layer."""

from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class BrainResponse:
    text: str
    provider: str = ""
    model: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    duration_ms: int = 0


class Brain:
    """Multi-provider AI brain with fallback chain."""

    def __init__(self) -> None:
        self._base_url = os.getenv(
            "OPENAI_BASE_URL",
            "https://api.siliconflow.cn/v1",
        )
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        self._model = os.getenv("OPENAI_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        self._temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self._max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2048"))

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> BrainResponse:
        """Send chat completion request to LLM provider."""
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=body,
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.error("LLM error %d: %.200s", resp.status_code, resp.text)
                    return BrainResponse(text="(思考中...请稍后再试)")

                data = resp.json()
                choice = data["choices"][0]
                message = choice.get("message", {})

                # Handle tool calls
                if message.get("tool_calls"):
                    text = json.dumps(message["tool_calls"], ensure_ascii=False)
                else:
                    text = message.get("content", "") or ""

                usage = data.get("usage", {})
                duration = int((time.monotonic() - t0) * 1000)

                return BrainResponse(
                    text=text.strip(),
                    provider="siliconflow",
                    model=self._model,
                    tokens_prompt=usage.get("prompt_tokens", 0),
                    tokens_completion=usage.get("completion_tokens", 0),
                    duration_ms=duration,
                )
        except Exception as e:
            logger.exception("LLM call failed: %s", e)
            return BrainResponse(text="(连接大脑失败，稍后再试...)")

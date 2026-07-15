"""Aerie · 云栖 v9.0 — Provider abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMResponse:
    """Standard LLM response wrapper across providers."""

    content: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    tool_calls: list[dict] = field(default_factory=list)
    raw: Any = None

    @property
    def success(self) -> bool:
        return bool(self.content or self.tool_calls)


class Provider(ABC):
    """Abstract base for all LLM providers."""

    name: str = "base"

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 30.0):
        if not api_key:
            raise ValueError(f"{self.name}: api_key is required")
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request and return the LLMResponse."""
        raise NotImplementedError

    async def health_check(self) -> bool:
        """Quick liveness probe. Default implementation: send a tiny prompt."""
        try:
            resp = await self.complete(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=4,
                temperature=0.0,
            )
            return resp.success
        except Exception:
            return False

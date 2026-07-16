"""Aerie · 云栖 v9.0 — Tool registry with OpenAI function-calling schema."""

from __future__ import annotations
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

ToolFn = Callable[..., dict]


class ToolRegistry:
    def __init__(self, db: Any = None) -> None:
        self._tools: dict[str, tuple[ToolFn, dict]] = {}
        self.db = db

    def register(self, name: str, func: ToolFn, schema: dict) -> None:
        self._tools[name] = (func, schema)

    def get_openai_schema(self) -> list[dict]:
        result = []
        for name, (_, schema) in self._tools.items():
            result.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {}),
                },
            })
        return result

    async def execute(self, name: str, args: dict) -> dict:
        if name not in self._tools:
            return {"error": f"unknown tool: {name}"}
        func, _ = self._tools[name]
        try:
            result = func(**args)
            import asyncio
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            logger.exception("tool %s error", name)
            return {"error": str(e)}

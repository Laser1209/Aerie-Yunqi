"""Aerie · 云栖 v9.0 — Tool registry and dispatcher."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from core.database import Database


logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    func: Callable[..., Awaitable[Any]]
    schema: dict
    category: str = "general"
    description: str = ""

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description or self.schema.get("description", ""),
                "parameters": self.schema,
            },
        }


class ToolRegistry:
    """In-process registry of callable tools."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        schema: dict,
        category: str = "general",
        description: str = "",
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name,
            func=func,
            schema=schema,
            category=category,
            description=description,
        )

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [
            {"name": t.name, "category": t.category, "description": t.description}
            for t in self._tools.values()
        ]

    def to_schemas(self) -> list[dict]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def increment_usage(self, name: str, user_id: int = 0, success: bool = True, duration_ms: int = 0) -> None:
        try:
            self.db.insert(
                "tool_usage",
                {
                    "tool_name": name,
                    "user_id": user_id,
                    "success": 1 if success else 0,
                    "duration_ms": duration_ms,
                },
            )
        except Exception:
            pass

    def usage_stats(self) -> list[dict]:
        return self.db.query(
            "SELECT tool_name, COUNT(*) AS calls, SUM(success) AS successes "
            "FROM tool_usage GROUP BY tool_name ORDER BY calls DESC"
        )

    async def execute(self, name: str, **kwargs: Any) -> Any:
        t = self.get(name)
        if not t:
            raise ValueError(f"tool not found: {name}")
        start = time.perf_counter()
        success = True
        try:
            if asyncio.iscoroutinefunction(t.func):
                result = await t.func(**kwargs)
            else:
                result = t.func(**kwargs)
            return result
        except Exception as e:
            success = False
            logger.warning("tool %s failed: %s", name, e)
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self.increment_usage(name, success=success, duration_ms=duration_ms)


async def execute_tool_call(registry: ToolRegistry, name: str, arguments: Any) -> Any:
    """Parse arguments (string or dict) and invoke a tool."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except Exception:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return await registry.execute(name, **arguments)

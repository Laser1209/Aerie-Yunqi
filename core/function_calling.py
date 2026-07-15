"""Aerie · 云栖 v9.0 — Function calling core.

Aggregates tool schemas for the LLM and dispatches tool calls.
"""

from __future__ import annotations

import json
from typing import Any

from core.tool_registry import ToolRegistry


async def execute_tool_call(registry: ToolRegistry, name: str, arguments: Any) -> Any:
    """Parse arguments (string or dict) and invoke a tool via the registry."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except Exception:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return await registry.execute(name, **arguments)

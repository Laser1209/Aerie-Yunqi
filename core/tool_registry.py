"""Aerie · 云栖 v0.1.0-beta.1 — Tool registry with OpenAI function-calling schema.

Block-4C R3.2: each registered tool carries a ``provider_hint`` that the
SkillRouter (or any future routing layer) can use to pick a real model
when the tool_call lands. The hint is appended to the tool description
in the OpenAI schema as ``[provider=<hint>]`` so the model can also see
which provider will execute the call (helps with model-aware routing).

Backwards compatibility:
  - ``register(name, func, schema)`` still works; ``provider_hint``
    defaults to ``"text"``.
  - Old code that iterates ``self._tools.items()`` and expects
    ``(func, schema)`` tuples is updated in-place; if any third-party
    code outside the project still depends on the tuple shape, those
    calls go through the ``get(name)`` accessor.
"""

from __future__ import annotations
import asyncio
import logging
from copy import deepcopy
from typing import Any, Callable

logger = logging.getLogger(__name__)

ToolFn = Callable[..., dict]


class ToolRegistry:
    def __init__(self, db: Any = None) -> None:
        # name -> {"func": ToolFn, "schema": dict, "provider_hint": str, "category": str}
        self._tools: dict[str, dict] = {}
        self.db = db

    def register(
        self,
        name: str,
        func: ToolFn,
        schema: dict,
        provider_hint: str = "text",
        category: str = "utility",
    ) -> None:
        """Register a tool. ``provider_hint`` is consumed by SkillRouter
        and surfaced in the OpenAI function-calling schema.

        ``category`` is used for tool grouping and prompt-side guidance:
        - system_control: 底层系统控制（截图、键鼠、shell、窗口等）
        - office: 办公场景工具（文件、文档、数据、日历等）
        - browser: 浏览器相关工具
        - douyin: 抖音互动工具
        - utility: 通用实用工具（默认）
        """
        self._tools[name] = {
            "func": func,
            "schema": schema or {},
            "provider_hint": str(provider_hint or "text"),
            "category": str(category or "utility"),
        }
        logger.debug(
            "tool %s registered (provider_hint=%s, category=%s)",
            name, provider_hint, category,
        )

    def get(self, name: str) -> dict | None:
        """Return the full tool entry (func + schema + provider_hint) or None."""
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def list_provider_hints(self) -> dict[str, str]:
        """Return name -> provider_hint mapping for brain routing."""
        return {n: t["provider_hint"] for n, t in self._tools.items()}

    def get_tool_categories(self) -> list[str]:
        """Return all distinct tool categories."""
        cats = set()
        for t in self._tools.values():
            cats.add(t.get("category", "utility"))
        return sorted(cats)

    def get_tools_by_category(self, category: str) -> list[str]:
        """Return tool names belonging to a specific category."""
        result = []
        for name, t in self._tools.items():
            if t.get("category", "utility") == category:
                result.append(name)
        return result

    def get_category_map(self) -> dict[str, list[str]]:
        """Return category -> [tool_names] mapping for prompt-side guidance."""
        mapping: dict[str, list[str]] = {}
        for name, t in self._tools.items():
            cat = t.get("category", "utility")
            if cat not in mapping:
                mapping[cat] = []
            mapping[cat].append(name)
        return mapping

    def summary(self) -> str:
        """Return a human-readable summary of registered tools, for logging."""
        cats = self.get_category_map()
        total = len(self._tools)
        lines = [f"ToolRegistry: {total} tools total"]
        for cat in sorted(cats.keys()):
            tools = sorted(cats[cat])
            lines.append(f"  - {cat}: {len(tools)} tools ({', '.join(tools)})")
        return "\n".join(lines)

    def get_openai_schema(self) -> list[dict]:
        """Return OpenAI function-calling schema for every registered tool.

        The provider hint is appended to the tool description as
        ``[provider=<hint>]`` so the LLM is aware of which model will
        actually execute the call (for routing-aware planning).

        Supports two schema formats:
        - New format: {"type": "function", "function": {"name", "description", "parameters"}}
        - Old format: {"description": "...", "parameters": {...}}
        """
        result = []
        for name, t in self._tools.items():
            schema = deepcopy(t["schema"])
            if not isinstance(schema, dict):
                continue

            # Detect format: new (has "function" key) vs old (direct description+parameters)
            if "function" in schema and isinstance(schema["function"], dict):
                # New format
                fn = schema["function"]
                fn["name"] = fn.get("name") or name
                desc = fn.get("description", "") or ""
                hint = t["provider_hint"]
                if hint and hint != "text":
                    fn["description"] = f"{desc} [provider={hint}]".strip()
                if "type" not in schema:
                    schema["type"] = "function"
            else:
                # Old format: wrap into standard OpenAI function schema
                desc = schema.get("description", "") or ""
                params = schema.get("parameters", {}) or {}
                hint = t["provider_hint"]
                if hint and hint != "text":
                    desc = f"{desc} [provider={hint}]".strip()
                schema = {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": desc,
                        "parameters": params,
                    },
                }

            result.append(schema)
        return result

    async def execute(self, name: str, args: dict) -> dict:
        if name not in self._tools:
            return {"error": f"unknown tool: {name}"}
        func = self._tools[name]["func"]
        try:
            result = func(**(args or {}))
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except TypeError as e:
            # Surface signature mismatch to the caller (was previously
            # silently swallowed by the tuple-based impl).
            logger.exception("tool %s signature error", name)
            return {"error": f"tool_signature: {e}"}
        except Exception as e:
            logger.exception("tool %s error", name)
            return {"error": str(e)}

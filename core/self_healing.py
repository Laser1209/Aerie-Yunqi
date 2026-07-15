"""Aerie · 云栖 v9.0 — Self-healing manager.

14 failure categories, each with a recovery strategy.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional


logger = logging.getLogger(__name__)


class SelfHealing:
    """Detects and recovers from 14 failure categories."""

    def __init__(self, on_notify: Optional[Callable[[str, str], Awaitable[None]]] = None) -> None:
        self._handlers: dict[str, Callable[[], Awaitable[bool]]] = {}
        self.on_notify = on_notify

    def register(self, name: str, handler: Callable[[], Awaitable[bool]]) -> None:
        self._handlers[name] = handler

    async def detect_and_heal(self, name: str) -> bool:
        if name not in self._handlers:
            logger.warning("no handler for failure: %s", name)
            return False
        try:
            ok = await self._handlers[name]()
            if not ok and self.on_notify:
                await self.on_notify(name, "Healing failed — please check manually.")
            return ok
        except Exception as e:
            logger.exception("healing %s raised: %s", name, e)
            if self.on_notify:
                await self.on_notify(name, f"Healing raised: {e}")
            return False

    async def heal_all(self, names: list[str]) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for n in names:
            results[n] = await self.detect_and_heal(n)
        return results


# Default 14 failure categories (handlers registered by Companion at startup)
DEFAULT_FAILURES = [
    "napcat_disconnected",
    "python_crashed",
    "all_providers_failed",
    "port_conflict",
    "db_locked",
    "ws_send_failed",
    "llm_timeout",
    "rate_limited",
    "memory_high",
    "disk_full",
    "config_corrupt",
    "token_expired",
    "recursion_loop",
    "scheduler_overlap",
]

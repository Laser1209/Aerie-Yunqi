"""Aerie · 云栖 v9.0 — Short-term memory.

In-process ring buffer of the most recent N messages (default 8).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class MemoryEntry:
    role: str
    content: str
    timestamp: str = ""


class ShortTermMemory:
    """Thread-safe ring buffer of recent messages."""

    def __init__(self, capacity: int = 8) -> None:
        self.capacity = capacity
        self._buf: deque[MemoryEntry] = deque(maxlen=capacity)

    def add(self, msg: MemoryEntry) -> None:
        self._buf.append(msg)

    def get_recent(self, limit: Optional[int] = None) -> list[MemoryEntry]:
        if limit is None:
            return list(self._buf)
        return list(self._buf)[-limit:]

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)

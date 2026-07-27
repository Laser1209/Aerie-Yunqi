"""Aerie · 云栖 — companion_mode / office_mode 模式切换 (Task P1-B.5).

职责:
  - CompanionMode 枚举: COMPANION / OFFICE
  - ModeSwitch.switch_mode(target_mode, reason) → bool (False 表示已是该模式, 无操作)
  - ModeSwitch.get_current_mode() → CompanionMode
  - ModeSwitch.trace: list[dict] 记录每次切换 (timestamp / from_mode / to_mode / reason)
  - ModeSwitch.is_proactive_allowed():
        COMPANION → True
        OFFICE    → False (办公模式禁用主动消息, 避免打扰专注)
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


class CompanionMode(str, enum.Enum):
    COMPANION = "companion"
    OFFICE = "office"


# 允许的字符串别名
_STRING_ALIASES: dict[str, CompanionMode] = {
    "companion": CompanionMode.COMPANION,
    "companion_mode": CompanionMode.COMPANION,
    "chat": CompanionMode.COMPANION,
    "office": CompanionMode.OFFICE,
    "office_mode": CompanionMode.OFFICE,
    "work": CompanionMode.OFFICE,
}


def _coerce_mode(value: Any) -> CompanionMode:
    if isinstance(value, CompanionMode):
        return value
    if isinstance(value, str):
        key = value.strip().lower()
        if key in _STRING_ALIASES:
            return _STRING_ALIASES[key]
        # 兜底: enum value
        try:
            return CompanionMode(key)
        except ValueError:
            raise ValueError(f"unknown mode: {value!r}") from None
    raise TypeError(f"mode must be CompanionMode or str, got {type(value).__name__}")


@dataclass
class ModeSwitch:
    """管理 companion ↔ office 模式切换及切换追踪."""

    initial: CompanionMode | str = CompanionMode.COMPANION

    def __post_init__(self) -> None:
        self._current: CompanionMode = _coerce_mode(self.initial)
        self.trace: list[dict[str, Any]] = []

    # ── 查询 ─────────────────────────────────────
    def get_current_mode(self) -> CompanionMode:
        return self._current

    @property
    def current_mode(self) -> CompanionMode:
        return self._current

    # ── 切换 ─────────────────────────────────────
    def switch_mode(self, target_mode: CompanionMode | str, reason: str = "") -> bool:
        """切换到目标模式. 已在目标模式时返回 False 且不记录 trace."""
        target = _coerce_mode(target_mode)
        if target == self._current:
            return False
        from_mode = self._current
        self._current = target
        self.trace.append(
            {
                "timestamp": time.time(),
                "from_mode": from_mode,
                "to_mode": target,
                "reason": str(reason or ""),
            }
        )
        return True

    # ── 主动消息闸门 ────────────────────────────
    def is_proactive_allowed(self) -> bool:
        """办公模式下禁止主动消息."""
        return self._current == CompanionMode.COMPANION

    # ── 辅助 ─────────────────────────────────────
    def last_switch(self) -> Optional[dict[str, Any]]:
        return self.trace[-1] if self.trace else None

    def reset_trace(self) -> None:
        self.trace = []

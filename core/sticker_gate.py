"""Aerie · 云栖 — 表情包入口 (Task P1-D.2).

职责:
  - StickerEmotion 枚举: 情绪标签 (joy / love / encourage / thanks ...)
  - StickerScene 枚举: 场景标签 (greeting / celebration / console / farewell ...)
  - Sticker 数据结构: id / path / label / emotions / scenes
  - StickerCatalog 标签检索: 注册、按情绪 / 场景检索、按 id 取用
  - StickerGate 发送审计与用户关闭开关:
        - 默认开启, 通过 allow_send(sticker, user_id) 放行并记录审计
        - 用户 set_enabled(False) 关闭后禁止发送, 且拒绝事件同样进入审计
        - 重新开启后恢复发送
不调用真实模型 / API / 推送, 仅作发送前的闸门与审计层.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ── 情绪标签 ───────────────────────────────────────
class StickerEmotion(str, enum.Enum):
    JOY = "joy"
    LOVE = "love"
    ENCOURAGE = "encourage"
    THANKS = "thanks"
    SUPPORT = "support"
    GREETING = "greeting"


# ── 场景标签 ───────────────────────────────────────
class StickerScene(str, enum.Enum):
    GREETING = "greeting"
    CELEBRATION = "celebration"
    CONSOLE = "console"
    FAREWELL = "farewell"
    DAILY = "daily"


# ── 表情包数据结构 ─────────────────────────────────
@dataclass
class Sticker:
    """单个表情包条目.

    - id: 唯一标识
    - path: 本地表情文件路径
    - label: 展示用文字标签
    - emotions: 情绪标签列表 (任意字符串, 建议使用 StickerEmotion 的 value)
    - scenes: 场景标签列表 (任意字符串, 建议使用 StickerScene 的 value)
    """

    id: str
    path: str = ""
    label: str = ""
    emotions: list[str] = field(default_factory=list)
    scenes: list[str] = field(default_factory=list)


# ── 标签检索: 表情包目录 ──────────────────────────
class StickerCatalog:
    """表情包注册与按标签检索."""

    def __init__(self) -> None:
        self._stickers: dict[str, Sticker] = {}

    def register(self, sticker: Sticker) -> None:
        """注册一张表情包. 重复 id 抛 ValueError."""
        if not sticker.id:
            raise ValueError("sticker id 不能为空")
        if sticker.id in self._stickers:
            raise ValueError(f"sticker already registered: {sticker.id}")
        self._stickers[sticker.id] = sticker

    def get(self, sticker_id: str) -> Optional[Sticker]:
        return self._stickers.get(str(sticker_id or ""))

    def search(
        self,
        emotion: Optional[str] = None,
        scene: Optional[str] = None,
    ) -> list[Sticker]:
        """按情绪 / 场景标签检索; 均未传时返回全部."""
        results: list[Sticker] = []
        for sticker in self._stickers.values():
            if emotion and emotion not in sticker.emotions:
                continue
            if scene and scene not in sticker.scenes:
                continue
            results.append(sticker)
        return results

    def all(self) -> list[Sticker]:
        return list(self._stickers.values())

    def __len__(self) -> int:
        return len(self._stickers)


# ── 发送闸门与审计 ─────────────────────────────────
@dataclass
class StickerGate:
    """表情包发送闸门: 用户关闭开关 + 发送审计.

    - allow_send(sticker, user_id) -> bool: 开启时返回 True 并记录 sent 审计;
      关闭时返回 False 并记录 denied_disabled 审计.
    - send_audit: 每次调用 (无论放行与否) 追加一条审计记录.
    """

    catalog: StickerCatalog = field(default_factory=StickerCatalog)
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.catalog is None:
            self.catalog = StickerCatalog()
        self.send_audit: list[dict[str, Any]] = []

    # ── 开关 ─────────────────────────────────────
    @property
    def is_enabled(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    # ── 发送判定与审计 ───────────────────────────
    def allow_send(
        self,
        sticker: Sticker | str,
        user_id: str = "",
    ) -> bool:
        """判定是否允许发送该表情包, 并记录审计."""
        sticker_id = getattr(sticker, "id", None) or str(sticker or "")
        if not self.enabled:
            self._audit(sticker_id, user_id, "denied_disabled")
            return False
        self._audit(sticker_id, user_id, "sent")
        return True

    def _audit(self, sticker_id: str, user_id: str, status: str) -> None:
        self.send_audit.append(
            {
                "sticker_id": sticker_id,
                "user_id": str(user_id or ""),
                "status": status,
                "timestamp": time.time(),
            }
        )

    def clear_audit(self) -> None:
        self.send_audit = []

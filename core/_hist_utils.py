"""历史消息标签公共工具。

供 ContextBuilder 与 ContextAssembler 共用，避免两处维护同一逻辑（审计 M2）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

# 通道标识 → 短标签，用于历史消息来源标注
_CHANNEL_SHORT: dict[str, str] = {
    "qq": "QQ",
    "desktop": "桌面",
    "local": "本地",
}


def channel_short(channel: str | None) -> str:
    """通道 → 短标签；未知通道原样返回。"""
    if not channel:
        return ""
    return _CHANNEL_SHORT.get(channel, channel)


def hist_label(row: Mapping[str, Any], *, current_channel: str | None = None) -> str:
    """给一条历史消息生成前缀，如 `[08-09 04:07] ` 或 `[08-09 04:07] [QQ] `。

    消息可能来自 turns/messages（created_at）或 legacy chat_log（created_at/ts）。
    无法解析时返回空串，保证不破坏原有内容。
    当消息的 channel 与当前通道不同（跨通道来源，如 P3 全局视图）时，
    追加来源短标签；同通道消息不标注，避免冗余。
    """
    ts = row.get("created_at") or row.get("ts")
    prefix = ""
    if ts:
        try:
            dt = datetime.fromisoformat(str(ts))
        except (ValueError, TypeError):
            dt = None
        if dt is not None:
            prefix = f"[{dt.strftime('%m-%d %H:%M')}] "
    item_channel = row.get("channel") or (row.get("source") if "channel" not in row else "")
    if current_channel and item_channel and item_channel != current_channel:
        short = channel_short(str(item_channel))
        if short:
            prefix += f"[{short}] "
    return prefix

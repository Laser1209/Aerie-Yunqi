"""历史消息标签公共工具。

供 ContextBuilder 与 ContextAssembler 共用，避免两处维护同一逻辑（审计 M2）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def hist_label(row: Mapping[str, Any]) -> str:
    """给一条历史消息生成绝对时间前缀，如 `[08-09 04:07] `。

    消息可能来自 turns/messages（created_at）或 legacy chat_log（created_at/ts）。
    无法解析时返回空串，保证不破坏原有内容。
    """
    ts = row.get("created_at") or row.get("ts")
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts))
    except (ValueError, TypeError):
        return ""
    return f"[{dt.strftime('%m-%d %H:%M')}] "

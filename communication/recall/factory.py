"""RecallAdapter 工厂: 按 channel 返回对应适配器."""
from __future__ import annotations

from typing import Any

from communication.recall.base import RecallAdapter
from communication.recall.local import CHANNEL as LOCAL_CHANNEL
from communication.recall.local import LocalRecallAdapter
from communication.recall.qq import CHANNEL as QQ_CHANNEL
from communication.recall.qq import QQRecallAdapter
from communication.recall.wechat_stub import CHANNEL as CLAWBOT_CHANNEL
from communication.recall.wechat_stub import WeChatClawbotAdapter


def get_recall_adapter(
    channel: str | None,
    qq_client: Any = None,
) -> RecallAdapter:
    """按 channel 分派撤回适配器; 未知 channel 回退本地标记."""
    ch = (channel or "").lower()

    if ch in (QQ_CHANNEL, "qq"):
        return QQRecallAdapter(qq_client=qq_client)
    if ch in (CLAWBOT_CHANNEL, "wechat", "clawbot", "wx"):
        return WeChatClawbotAdapter()
    # local / local-chat / 未知 → 本地标记
    return LocalRecallAdapter()

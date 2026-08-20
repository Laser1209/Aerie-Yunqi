"""OneBot11 上行事件模型与类型常量（自研实现）。

OneBot11 引擎通过 WS 推送的事件分为四类（``post_type``）：

- ``message``    消息事件（私聊/群聊/临时会话）
- ``meta_event`` 元事件（生命周期 lifecycle / 心跳 heartbeat）
- ``notice``     通知事件（撤回、群变动等）
- ``request``    请求事件（加好友、入群申请）

业务层订阅 :class:`EventDispatcher` 即可拿到结构化后的事件 dict，
本模块只定义常量与轻量解析辅助，不绑定业务逻辑。
"""

from __future__ import annotations

# ── post_type ─────────────────────────────────────────────
POST_MESSAGE = "message"
POST_META_EVENT = "meta_event"
POST_NOTICE = "notice"
POST_REQUEST = "request"

# ── message_type ──────────────────────────────────────────
MESSAGE_PRIVATE = "private"
MESSAGE_GROUP = "group"

# ── meta_event_type ───────────────────────────────────────
META_LIFECYCLE = "lifecycle"
META_HEARTBEAT = "heartbeat"

# ── lifecycle sub_type ────────────────────────────────────
LIFECYCLE_CONNECT = "connect"        # 账号上线（登录就绪信号）
LIFECYCLE_ENABLE = "enable"
LIFECYCLE_DISABLE = "disable"

# ── notice_type ───────────────────────────────────────────
NOTICE_RECALL = "recall"             # 消息撤回
NOTICE_GROUP_RECALL = "group_recall"

# ── request_type ──────────────────────────────────────────
REQUEST_FRIEND = "friend"
REQUEST_GROUP = "group"


def post_type(event: dict) -> str:
    """取事件的 ``post_type``，缺失返回空串。"""
    return str(event.get("post_type", ""))


def is_connected_lifecycle(event: dict) -> bool:
    """判断是否为「连接建立且账号在线」的 lifecycle 事件。

    这是引擎账号就绪的可靠信号：只在一次成功登录/重连后触发，
    用于唤醒等待登录的调用方（对应主动推送前的登录闸门）。
    """
    return (
        post_type(event) == POST_META_EVENT
        and event.get("meta_event_type") == META_LIFECYCLE
        and event.get("sub_type") == LIFECYCLE_CONNECT
    )


def extract_message_id(event: dict) -> int:
    """从消息事件里取平台消息 id（无则 0）。"""
    try:
        return int(event.get("message_id", 0))
    except (TypeError, ValueError):
        return 0

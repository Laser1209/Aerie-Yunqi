"""投递路由：把「这条请求从哪来」变成**请求级**数据，并定义主动消息的端口策略。

为什么需要它（§九）
------------------
投递侧原先只有一个**全局**的"最后一次入站通道"（``Companion._last_inbound_target``），
而且只在 QQ / 微信入站时写入。后果有两个：

* **桌面端要文件** → 投到上一次的 QQ/微信通道；若从未有 QQ/微信入站 → 静默丢件；
* **多端并发必然错乱** —— 你在桌面问、手机同时来一条推送，文件就投错端。

这是结构问题，打补丁治不好。本模块提供两件事：

1. **请求级来源**（:class:`DeliveryContext` + ContextVar）：pipeline 在一轮对话真正
   执行模型/工具的那个窗口里 ``bind``，工具执行期（同步、同一协程）用 ``current()``
   读到"这条请求从哪个端口来"。取不到就是**真的没有来源**（例如脚本直调），
   此时按策略降级，而不是去猜一个过期的全局值。
2. **主动消息端口策略**（:func:`resolve_proactive_channel`）：主动推送不是用户请求
   触发的，没有来源端口，必须显式定义规则：默认 ``auto`` = 最近活跃端口（含桌面）
   且需在时间窗内；窗口内无记录则落桌面端（最保守、一定能看到，不打扰手机）。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 三端端口枚举。mobile_gateway 目前不作为独立端口（见计划 §9.5-3）。
DELIVERY_CHANNELS = frozenset({"qq", "ilink", "local_chat"})

# 入站 source → 投递 channel 的归一映射（'local' 即桌面端）。
_SOURCE_TO_CHANNEL = {"qq": "qq", "ilink": "ilink", "local": "local_chat"}

DEFAULT_PROACTIVE_CHANNEL = "auto"
DEFAULT_RECENT_WINDOW_MIN = 30.0

FALLBACK_CHANNEL = "local_chat"

# 配置里写的端口别名 → 内部端口枚举。
# `primary_channel` 是既有键（electron 的「外部连接」面板就在写它），历史上 Python 侧
# 早就不读了 —— 于是那个设置"看得见但不生效"。这里把它接回来，并支持 `auto`：
# 一个键 = 一个真源，不再新造第二个键。
_PROACTIVE_CHANNEL_ALIASES = {
    "desktop": "local_chat",
    "local": "local_chat",
    "local_chat": "local_chat",
    "qq": "qq",
    "ilink": "ilink",
    "wechat": "ilink",
    "auto": "auto",
}


@dataclass(frozen=True)
class DeliveryContext:
    """一条请求的来源端口。"""

    channel: str
    user_id: int
    channel_account_id: str = ""
    turn_id: str = ""


def normalize_channel(value: Any) -> str:
    """把任意 source/channel 取值归一为 ``qq`` / ``ilink`` / ``local_chat``。"""
    raw = str(value or "").strip().lower()
    if raw in DELIVERY_CHANNELS:
        return raw
    return _SOURCE_TO_CHANNEL.get(raw, FALLBACK_CHANNEL)


def context_from_message(msg: Any) -> DeliveryContext | None:
    """从入站消息构造来源上下文；没有 user_id 时返回 None（无从投递）。"""
    user_id = int(getattr(msg, "user_id", 0) or 0)
    if not user_id:
        return None
    channel = normalize_channel(
        getattr(msg, "channel", "") or getattr(msg, "source", "")
    )
    # channel_account_id 只对微信有意义：QQ 与桌面都按 user_id 定点投递
    # （与 pipeline 聊天要图链路 `_resolve_delivery_target` 同一口径）。
    account = str(getattr(msg, "channel_account_id", "") or "") if channel == "ilink" else ""
    return DeliveryContext(
        channel=channel,
        user_id=user_id,
        channel_account_id=account,
        turn_id=str(getattr(msg, "platform_message_id", "") or ""),
    )


# ── 请求级来源（ContextVar：同协程内的工具执行期可见） ──────────────────────

_current: ContextVar[DeliveryContext | None] = ContextVar(
    "aerie_delivery_context", default=None,
)


def bind(context: DeliveryContext | None) -> Token:
    """绑定当前请求的来源端口；返回 token，交给 :func:`unbind` 还原。"""
    return _current.set(context)


def unbind(token: Token) -> None:
    """还原 :func:`bind`；token 失效（跨上下文误用）时忽略，不影响主流程。"""
    try:
        _current.reset(token)
    except (ValueError, RuntimeError):
        logger.debug("delivery context reset failed", exc_info=True)


def current() -> DeliveryContext | None:
    """当前请求的来源端口；不在请求轮次内时返回 None。"""
    return _current.get()


# ── 主动消息（无来源端口）的端口策略 ─────────────────────────────────────


def proactive_channel_config(settings: Any) -> tuple[str, float]:
    """读 ``proactive.primary_channel`` / ``proactive.auto_recent_window_min``。

    ``primary_channel`` 取值：``auto``（默认）/ ``qq`` / ``ilink`` / ``desktop``。
    别名（desktop / local / wechat）在这里归一，未知值一律按 ``auto`` —— 宁可按
    "最近活跃端口"投，也不要因为写错一个词就投到没人看的端口。
    """
    cfg = (settings or {}).get("proactive") if isinstance(settings, dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}
    raw_mode = str(cfg.get("primary_channel") or "").strip().lower()
    mode = _PROACTIVE_CHANNEL_ALIASES.get(raw_mode, DEFAULT_PROACTIVE_CHANNEL)
    try:
        window_min = float(cfg.get("auto_recent_window_min", DEFAULT_RECENT_WINDOW_MIN))
    except (TypeError, ValueError):
        window_min = DEFAULT_RECENT_WINDOW_MIN
    if window_min <= 0:
        window_min = DEFAULT_RECENT_WINDOW_MIN
    return mode, window_min


def resolve_proactive_channel(
    *,
    configured: str = DEFAULT_PROACTIVE_CHANNEL,
    recent: DeliveryContext | None = None,
    recent_fresh: bool = False,
) -> str:
    """主动消息该投到哪一端。

    * ``configured`` 是三端之一 → 固定投该端口（用户明确要"主动消息都发我微信"）；
    * ``auto``（默认）→ 最近一次活跃端口（**含桌面**）且需在时间窗内；
    * 窗口内无活跃记录 → 落桌面端：最保守，用户一定能看到，也不会打扰手机。
    """
    mode = str(configured or DEFAULT_PROACTIVE_CHANNEL).strip().lower()
    if mode in DELIVERY_CHANNELS:
        return mode
    if recent is not None and recent_fresh and recent.channel in DELIVERY_CHANNELS:
        return recent.channel
    return FALLBACK_CHANNEL

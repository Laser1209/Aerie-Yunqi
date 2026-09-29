"""系统自省工具 —— 让模型能查「有什么能力 / 缺什么 / 去哪儿配」与运行状况。

为什么需要（Part C3）：在补齐之前，不可用能力被**静默过滤**，模型既看不见清单外的
能力，也不知道自己缺什么；用户说"我要用 seedream"，它只会答"我做不到"。
这两个工具把 `core/capability_catalog`（唯一事实来源）与运行态健康信息暴露成
**可被按需调用**的工具，而不是常驻上下文（那样会挤掉对话预算）。

与 `get_system_info` 的分工：那个报的是**操作系统**信息（平台/CPU/Python 版本），
这里报的是**本程序自身**的能力与运行状况。
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# snapshot 默认截断：概览只给前 N 条未就绪项，避免一次把上百条灌进上下文。
_DEFAULT_LIMIT = 20


def _uptime_seconds() -> float:
    """进程 up 时长。取 API 服务记录的启动时刻（/api/health 用的同一份）。"""
    try:
        from core import api_server

        return max(0.0, time.time() - float(api_server._START_TIME))
    except Exception:
        return 0.0


def _format_uptime(seconds: float) -> str:
    total = int(max(0.0, seconds))
    hours, mins = divmod(total // 60, 60)
    if hours:
        return f"{hours} 小时 {mins} 分"
    return f"{mins} 分"


def system_status(name: str = "", limit: int = _DEFAULT_LIMIT) -> dict:
    """查能力清单：不给 name 给概览，给了 name 给单项详情。

    - 概览：`total / ready_count / unavailable_count` + 未就绪清单（含"去哪儿配"）
    - 单项：该能力的 `ready / unavailable_reason / missing / where / fix_kind`
    - **名字查不到就报错**，不返回空对象假装查到了（模型才不会误判成"没有这个能力"）
    """
    from core import capability_catalog

    requested = str(name or "").strip()
    if requested:
        entry = capability_catalog.lookup(requested)
        if entry is None:
            known = sorted(e.name for e in capability_catalog.build_catalog())
            return {
                "error": f"unknown capability: {requested}",
                "hint": "先用不传 name 的概览拿到可用名字",
                "known_sample": known[:40],
            }
        return {"status": "ok", "capability": entry.to_dict()}

    try:
        cap = max(0, int(limit))
    except (TypeError, ValueError):
        cap = _DEFAULT_LIMIT
    payload = capability_catalog.snapshot(limit=cap)
    payload["status"] = "ok"
    return payload


def system_health() -> dict:
    """运行状况：进程 up 时长 / 被熔断的模型厂商 / MCP 开关状态。"""
    uptime = _uptime_seconds()
    payload: dict[str, Any] = {
        "status": "ok",
        "uptime_seconds": round(uptime, 1),
        "uptime_text": _format_uptime(uptime),
    }

    try:
        from core.provider_health import ProviderHealthManager

        payload["providers_banned"] = sorted(ProviderHealthManager().banned_names())
    except Exception:
        logger.debug("provider health 读取失败", exc_info=True)
        payload["providers_banned"] = []

    try:
        from core.mcp_client import DEFAULT_CONFIG_PATH, load_servers_config

        mcp_enabled, raw = load_servers_config(DEFAULT_CONFIG_PATH)
        payload["mcp_enabled"] = bool(mcp_enabled)
        payload["mcp_servers"] = sorted((raw or {}).keys())
        # MCP 开关是启动期生效的（设置页也这么写），所以这里给的是"要不要重启"的提示，
        # 而不是假装能检测到"改动已生效"。
        payload["mcp_note"] = "MCP 开关改动需重启后端后生效"
    except Exception:
        logger.debug("MCP 状态读取失败", exc_info=True)

    try:
        from core import capability_catalog

        snap = capability_catalog.snapshot()
        payload["capabilities_total"] = snap["total"]
        payload["capabilities_unavailable"] = snap["unavailable_count"]
    except Exception:
        logger.debug("能力目录读取失败", exc_info=True)

    return payload


def register_system_tools(registry: Any) -> None:
    """把系统自省工具注册进 registry。"""
    registry.register("system_status", system_status, {
        "description": (
            "查询本程序的能力清单：哪些能力现在可用、哪些不可用、各缺什么、"
            "该去哪里配置（如「设置页 → 平台凭证 → 火山 Seedream 文生图」）。"
            "用户问「你能做 X 吗」「为什么用不了 X」时先查这里，再如实回答；"
            "不要假装能做到。不给 name 返回概览，给 name 返回单项详情。"
            "注意：查操作系统信息用 get_system_info。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "可选。能力名（skill / 功能包 / MCP 服务器），留空返回概览",
                },
                "limit": {
                    "type": "integer",
                    "description": "可选。概览里未就绪项最多返回几条，默认 20",
                },
            },
        },
    })

    registry.register("system_health", system_health, {
        "description": (
            "查询本程序运行状况：已连续运行多久、哪些模型厂商被熔断、"
            "MCP 服务器开关状态，以及当前有多少能力未就绪。"
            "用户问「你还正常吗」「运行多久了」时用；查操作系统信息用 get_system_info。"
        ),
        "parameters": {"type": "object", "properties": {}},
    })

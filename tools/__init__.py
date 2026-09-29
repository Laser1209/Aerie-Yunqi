"""Aerie · 云栖 v0.1.0-beta.1 — Built-in tools for the tool registry."""

from __future__ import annotations
import platform
import time
import datetime


def get_time(format_str: str = "%Y-%m-%d %H:%M:%S") -> dict:
    """Get current system time."""
    now = datetime.datetime.now()
    return {
        "time": now.strftime(format_str),
        "timestamp": int(time.time()),
        "timezone": str(datetime.timezone(datetime.timedelta(hours=8))),
    }


def get_system_info() -> dict:
    """Get basic system information."""
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }


async def echo(text: str) -> dict:
    """Echo back the input text."""
    return {"echo": text}


def _browser_backend() -> str:
    """浏览器工具来源配置：``auto``（默认）| ``playwright`` | ``webbridge``。

    为什么必须能切：``ToolRegistry.register()`` 是**直接赋值覆盖**，而
    ``core/companion.py`` 的注册顺序是「功能包先、核心工具后」。核心若无条件注册
    ``browser_*``，browser 功能包注册的同名工具会被整个顶掉 —— 用户装了 170MB 的
    Playwright 内核，实际仍在调外部 WebBridge，且毫无报错。
    """
    try:
        import yaml

        from core.paths import project_root

        cfg = yaml.safe_load(
            (project_root() / "config" / "settings.yaml").read_text(encoding="utf-8")
        ) or {}
        return str((cfg.get("browser") or {}).get("backend") or "auto").strip().lower()
    except Exception:
        return "auto"


def _should_register_webbridge() -> bool:
    """核心是否要注册内置的 WebBridge ``browser_*``。

    * ``webbridge``：注册（显式选定，无视是否装了包）
    * ``playwright``：不注册（由功能包提供，没装包就等于没有这个能力）
    * ``auto``（默认）：**装了 browser 功能包就让位，没装就用内置通道**

    为什么默认是 ``auto`` 而不是 ``playwright``：核心瘦身的目标是"包按需下载"，
    但不能因此让**已经在用浏览器的用户静默失去这个能力**——他们没装包，
    ``browser_*`` 直接消失，且没有任何提示。``auto`` 两头都占：装了包用包，
    没装包维持现状。
    """
    mode = _browser_backend()
    if mode == "webbridge":
        return True
    if mode == "playwright":
        return False
    try:
        from core import plugin_host

        return not plugin_host.is_installed("browser")
    except Exception:
        # 插件宿主不可用时按"没装包"处理：宁可维持现状，也不要静默失能
        return True


def register_all_tools(registry) -> None:
    """Register all built-in tools with the given registry."""

    registry.register("get_time", get_time, {
        "description": "获取当前系统时间",
        "parameters": {
            "type": "object",
            "properties": {
                "format_str": {
                    "type": "string",
                    "description": "时间格式字符串，默认 %Y-%m-%d %H:%M:%S",
                },
            },
        },
    })

    registry.register("get_system_info", get_system_info, {
        "description": "获取系统信息（操作系统、CPU、Python版本等）",
        "parameters": {"type": "object", "properties": {}},
    })

    registry.register("echo", echo, {
        "description": "回显输入文本（用于测试）",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要回显的文本"},
            },
            "required": ["text"],
        },
    })

    # 浏览器工具：默认 auto —— 装了 browser 功能包就让位（否则核心后注册会顶掉包），
    # 没装就维持内置 WebBridge 通道（不让现有用户静默失去浏览器能力）。
    # 见 _should_register_webbridge()。
    if _should_register_webbridge():
        try:
            from .browser_tools import register_webbridge_tools
            register_webbridge_tools(registry)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("webbridge tools registration failed: %s", e)

    # v13.0: Office tools 办公工具集
    try:
        from core.office_tools import register_office_tools
        register_office_tools(registry)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("office tools registration failed: %s", e)

    # Douyin search via JustOneAPI（聚合 API 主通道）
    try:
        from tools.douyin_search import register_douyin_tools
        register_douyin_tools(registry)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("douyin search tools registration failed: %s", e)

    # 通用多平台搜索（JustOneAPI）
    try:
        from tools.social_search import register_social_search_tools
        register_social_search_tools(registry)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("social search tools registration failed: %s", e)

    # [扩展] v0.1.0-beta.1: computer control tools — previously never registered,
    # so LLM Function Calling could not invoke any computer_control actions.
    # ZERO-BREAKING: adds new tool entries without touching existing ones.
    try:
        from tools.compute_tools import register_computer_tools
        from core.companion import get_companion
        companion = get_companion()
        if companion and companion.computer_controller:
            register_computer_tools(registry, companion.computer_controller)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("computer tools registration failed: %s", e)

    # 知识库写入工具：让 AI 主动把重要信息沉淀进知识库
    try:
        from tools.knowledge_tools import register_knowledge_tools
        register_knowledge_tools(registry)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("knowledge tools registration failed: %s", e)

    # 打印工具注册统计，便于排查
    try:
        import logging
        summary = registry.summary() if hasattr(registry, "summary") else f"{len(registry._tools)} tools"
        logging.getLogger(__name__).info("Tool registration complete:\n%s", summary)
    except Exception:
        pass

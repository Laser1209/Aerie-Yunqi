"""Aerie · 云栖 v9.0 — Built-in tools for the tool registry."""

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

    try:
        from .browser_tools import register_webbridge_tools
        register_webbridge_tools(registry)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("webbridge tools registration failed: %s", e)

    try:
        from .douyin_tools import register_douyin_tools
        register_douyin_tools(registry)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("douyin tools registration failed: %s", e)

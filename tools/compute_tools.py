"""Aerie v0.1.0-beta.1 — ComputerControl tool registrations.

Registers computer control tools (screenshot, keyboard, mouse, shell, UIA, window)
with the tool registry so LLM Function Calling can invoke them. Previously these
tools were never registered, making them unreachable from LLM.

[零破坏] All registration names match ComputerController method names directly.
[ZERO-BREAKING] No existing tool names are changed or removed.
"""

from __future__ import annotations
from typing import Any

from core.computer_control import ComputerController


def register_computer_tools(registry: Any, controller: ComputerController) -> None:
    """Register all computer control tools."""

    registry.register("screenshot", controller.take_screenshot, {
        "name": "screenshot",
        "description": "截取当前屏幕或指定区域的截图。参数 region 可选：(x1, y1, x2, y2)",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "截图区域 (x1, y1, x2, y2)，省略则全屏截图",
                },
            },
        },
    })

    registry.register("mouse_move", controller.mouse_move, {
        "name": "mouse_move",
        "description": "移动鼠标到指定坐标。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "目标 X 坐标"},
                "y": {"type": "integer", "description": "目标 Y 坐标"},
                "duration": {"type": "number", "description": "移动持续时间（秒），默认 0.2"},
            },
            "required": ["x", "y"],
        },
    })

    registry.register("mouse_click", controller.mouse_click, {
        "name": "mouse_click",
        "description": "鼠标点击。默认左键单击。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "点击 X 坐标，省略则点击当前位置"},
                "y": {"type": "integer", "description": "点击 Y 坐标"},
                "button": {"type": "string", "description": "按键: left, right, middle"},
                "clicks": {"type": "integer", "description": "连击次数，默认 1"},
            },
        },
    })

    registry.register("mouse_scroll", controller.mouse_scroll, {
        "name": "mouse_scroll",
        "description": "鼠标滚轮。正值为向上滚动，负值为向下。",
        "parameters": {
            "type": "object",
            "properties": {
                "clicks": {"type": "integer", "description": "滚动步数"},
            },
            "required": ["clicks"],
        },
    })

    registry.register("key_press", controller.key_press, {
        "name": "key_press",
        "description": "按下并释放一个键盘按键。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名称，如 enter, escape, tab"},
            },
            "required": ["key"],
        },
    })

    registry.register("type_text", controller.type_text, {
        "name": "type_text",
        "description": "在焦点窗口输入文本（模拟键盘逐字输入）。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文本"},
            },
            "required": ["text"],
        },
    })

    registry.register("hotkey", controller.hotkey, {
        "name": "hotkey",
        "description": "按下组合快捷键，如 ctrl+c",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "组合键列表，如 ['ctrl', 'c']",
                },
            },
            "required": ["keys"],
        },
    })

    registry.register("shell_execute", controller.shell_execute, {
        "name": "shell_execute",
        "description": (
            "在用户电脑上执行一个简单命令（注意：不支持管道 |、重定向 >、或命令链 && / ;）。"
            "复杂任务请分步调用，或使用文件操作工具替代。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令字符串"},
                "cwd": {"type": "string", "description": "工作目录（可选）"},
            },
            "required": ["command"],
        },
    })

    registry.register("uia_action", controller.uia_action, {
        "name": "uia_action",
        "description": "通过 Windows UI Automation 执行界面操作（如点击按钮、获取控件文本）。",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "操作类型：click, get_text, set_value, invoke, select",
                },
                "params": {
                    "type": "object",
                    "description": "操作参数（控件定位信息等）",
                },
            },
            "required": ["action_type"],
        },
    })

    registry.register("list_windows", controller.list_windows, {
        "name": "list_windows",
        "description": "列出当前所有可见窗口的标题和句柄。",
        "parameters": {"type": "object", "properties": {}},
    })

    registry.register("focus_window", controller.focus_window, {
        "name": "focus_window",
        "description": "将指定句柄的窗口切换到前台。",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄（从 list_windows 获得）"},
            },
            "required": ["hwnd"],
        },
    })

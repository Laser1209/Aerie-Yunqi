"""Aerie v13.9 — Screen Control Tools
电脑操控工具集，注册到 tool_registry 供 AI function calling 调用。

工具清单：
- screen_screenshot      截图（返回描述）
- screen_window_list    获取窗口列表
- screen_mouse_click    鼠标点击
- screen_key_type       键盘输入
- app_launch            打开应用/文件
- screen_shell          受限 shell 命令
- screen_uia_action     UIA 深度操控
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from .computer_control import ComputerController, PermissionLevel, ControlAction
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

_controller: Optional[ComputerController] = None


def get_controller() -> ComputerController:
    global _controller
    if _controller is None:
        # v13.9: 优先使用 companion 中的共享实例，确保权限设置全局生效
        try:
            from core.companion import get_companion
            comp = get_companion()
            if comp and hasattr(comp, "computer_controller"):
                _controller = comp.computer_controller
        except Exception:
            pass
        if _controller is None:
            _controller = ComputerController()
    return _controller


def set_permission_level(level: str) -> None:
    """设置权限档位。"""
    controller = get_controller()
    level_map = {
        "VIEW_ONLY": PermissionLevel.VIEW_ONLY,
        "STANDARD": PermissionLevel.STANDARD,
        "FULL": PermissionLevel.FULL,
        "view_only": PermissionLevel.VIEW_ONLY,
        "standard": PermissionLevel.STANDARD,
        "full": PermissionLevel.FULL,
    }
    perm = level_map.get(level, PermissionLevel.VIEW_ONLY)
    controller.set_permission(perm)
    logger.info("screen control permission set to %s", perm.value)


def get_permission_level() -> str:
    controller = get_controller()
    return controller.permission_level().value.upper()


# ── 工具函数 ──────────────────────────────────────


def tool_screen_screenshot(
    region_x: int = 0,
    region_y: int = 0,
    region_w: int = 0,
    region_h: int = 0,
) -> dict:
    """截取屏幕并返回描述信息 + 缩略图。

    Args:
        region_x: 区域左上角 X（0 表示全屏）
        region_y: 区域左上角 Y
        region_w: 区域宽度（0 表示全屏）
        region_h: 区域高度

    Returns:
        截图信息（尺寸、缩略图 dataURL、简要描述）
    """
    controller = get_controller()
    region = None
    if region_w > 0 and region_h > 0:
        region = (region_x, region_y, region_w, region_h)

    result = controller.take_screenshot(region=region)
    if not result.success:
        return {"success": False, "error": result.message}

    data = result.data or {}
    # 返回缩略图（压缩到 800px 宽），避免 token 爆炸
    img_path = data.get("path", "")
    width = data.get("width", 0)
    height = data.get("height", 0)

    thumbnail_b64 = ""
    try:
        from PIL import Image
        import io

        if img_path:
            img = Image.open(img_path)
            img.thumbnail((800, 800))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            thumbnail_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        pass

    return {
        "success": True,
        "width": width,
        "height": height,
        "path": img_path,
        "thumbnail_dataurl": f"data:image/jpeg;base64,{thumbnail_b64}" if thumbnail_b64 else "",
        "description": f"截图成功，尺寸 {width}x{height}",
    }


def tool_screen_window_list() -> dict:
    """获取当前所有窗口列表。

    Returns:
        窗口列表（标题、句柄、进程名、位置尺寸）
    """
    controller = get_controller()
    result = controller.list_windows()
    if not result.success:
        return {"success": False, "error": result.message}

    windows = (result.data or {}).get("windows", [])
    # 只返回前 20 个，避免太长
    return {
        "success": True,
        "count": len(windows),
        "windows": windows[:20],
        "truncated": len(windows) > 20,
    }


def tool_screen_mouse_click(
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
) -> dict:
    """执行鼠标点击操作。

    Args:
        x: 点击 X 坐标（None 表示当前位置）
        y: 点击 Y 坐标
        button: left / right / middle
        clicks: 点击次数

    Returns:
        操作结果
    """
    controller = get_controller()
    result = controller.mouse_click(x=x, y=y, button=button, clicks=clicks)
    return {
        "success": result.success,
        "message": result.message,
        "position": result.data.get("position") if result.data else None,
    }


def tool_screen_key_type(text: str, interval: float = 0.01) -> dict:
    """输入文本。

    Args:
        text: 要输入的文本内容
        interval: 每个字符间隔（秒）

    Returns:
        操作结果
    """
    controller = get_controller()
    # 安全截断
    if len(text) > 500:
        text = text[:500]
    result = controller.type_text(text)
    return {
        "success": result.success,
        "message": result.message,
        "chars_typed": len(text),
    }


def tool_app_launch(app_name: str, args: str = "") -> dict:
    """打开应用程序或文件。

    Args:
        app_name: 应用名（如 notepad、calc、chrome）或文件路径
        args: 启动参数

    Returns:
        启动结果
    """
    controller = get_controller()

    # 常见应用快捷映射
    app_map = {
        "notepad": "notepad.exe",
        "记事本": "notepad.exe",
        "calc": "calc.exe",
        "计算器": "calc.exe",
        "paint": "mspaint.exe",
        "画图": "mspaint.exe",
        "explorer": "explorer.exe",
        "资源管理器": "explorer.exe",
        "cmd": "cmd.exe",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
    }

    exe = app_map.get(app_name.lower(), app_name)
    try:
        import os
        import subprocess

        if args:
            subprocess.Popen([exe, args], shell=False)
        else:
            os.startfile(exe)  # type: ignore[attr-defined]
        return {
            "success": True,
            "message": f"已启动: {app_name}",
            "executable": exe,
        }
    except Exception as e:
        logger.exception("app launch error")
        return {"success": False, "error": str(e)}


def tool_screen_shell(command: str, cwd: str = "") -> dict:
    """执行受限 shell 命令。

    Args:
        command: 命令内容
        cwd: 工作目录

    Returns:
        命令执行结果（stdout/stderr/returncode）
    """
    controller = get_controller()
    result = controller.shell_execute(command, cwd=cwd or None)
    data = result.data or {}
    stdout = data.get("stdout", "")
    stderr = data.get("stderr", "")
    # 截断输出，避免 token 爆炸
    if len(stdout) > 2000:
        stdout = stdout[:2000] + "\n... [truncated]"
    if len(stderr) > 1000:
        stderr = stderr[:1000] + "\n... [truncated]"

    return {
        "success": result.success,
        "message": result.message,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": data.get("returncode", -1),
    }


def tool_screen_uia_action(
    action: str,
    window_title: str = "",
    control_name: str = "",
) -> dict:
    """UIA 深度操控（需 FULL 权限）。

    Args:
        action: 操作类型（list_controls / click_control）
        window_title: 窗口标题关键词
        control_name: 控件名

    Returns:
        操作结果
    """
    controller = get_controller()

    if action == "list_controls":
        result = controller.uia.list_controls(title=window_title or None)
        return {
            "success": result.success,
            "message": result.message,
            "controls": (result.data or {}).get("controls", [])[:30],
        }
    elif action == "click_control":
        result = controller.uia.click_control(control_name)
        return {
            "success": result.success,
            "message": result.message,
        }
    else:
        return {"success": False, "error": f"unknown uia action: {action}"}


# ── 注册到 ToolRegistry ──────────────────────────

_TOOL_SCHEMAS = {
    "screen_screenshot": {
        "type": "function",
        "function": {
            "name": "screen_screenshot",
            "description": "截取电脑屏幕，返回截图尺寸和缩略图。用于查看屏幕内容、识别界面元素、获取当前窗口状态。仅查看，不做任何修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region_x": {"type": "integer", "description": "截图区域左上角 X 坐标，0 表示全屏", "default": 0},
                    "region_y": {"type": "integer", "description": "截图区域左上角 Y 坐标", "default": 0},
                    "region_w": {"type": "integer", "description": "截图区域宽度，0 表示全屏", "default": 0},
                    "region_h": {"type": "integer", "description": "截图区域高度", "default": 0},
                },
                "required": [],
            },
        },
    },
    "screen_window_list": {
        "type": "function",
        "function": {
            "name": "screen_window_list",
            "description": "获取当前打开的所有窗口列表，包括窗口标题、句柄、位置尺寸。用于了解用户当前在使用什么程序。仅查看。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "screen_mouse_click": {
        "type": "function",
        "function": {
            "name": "screen_mouse_click",
            "description": "在屏幕指定位置执行鼠标点击操作。用于模拟用户点击按钮、链接、菜单等界面元素。需要 STANDARD 或更高权限。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "点击位置 X 坐标（像素）"},
                    "y": {"type": "integer", "description": "点击位置 Y 坐标（像素）"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "鼠标按键", "default": "left"},
                    "clicks": {"type": "integer", "description": "点击次数", "default": 1},
                },
                "required": ["x", "y"],
            },
        },
    },
    "screen_key_type": {
        "type": "function",
        "function": {
            "name": "screen_key_type",
            "description": "在当前活动窗口输入文本内容。用于填写表单、输入文字、发送消息等。需要 STANDARD 或更高权限。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文本内容（最多 500 字符）"},
                },
                "required": ["text"],
            },
        },
    },
    "app_launch": {
        "type": "function",
        "function": {
            "name": "app_launch",
            "description": "打开应用程序或文件。支持常用应用快捷名（notepad/calc/chrome/edge等），也支持完整路径。需要 STANDARD 或更高权限。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "应用名（如 notepad、chrome、记事本）或文件路径"},
                    "args": {"type": "string", "description": "启动参数", "default": ""},
                },
                "required": ["app_name"],
            },
        },
    },
    "screen_shell": {
        "type": "function",
        "function": {
            "name": "screen_shell",
            "description": "执行受限的 Windows shell 命令。有安全黑名单，危险命令会被拦截。需要 STANDARD 或更高权限，且需用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "cwd": {"type": "string", "description": "工作目录", "default": ""},
                },
                "required": ["command"],
            },
        },
    },
    "screen_uia_action": {
        "type": "function",
        "function": {
            "name": "screen_uia_action",
            "description": "UIA 自动化深度操控，可枚举窗口控件、点击控件等。需要 FULL 权限，且需用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list_controls", "click_control"], "description": "操作类型"},
                    "window_title": {"type": "string", "description": "窗口标题关键词", "default": ""},
                    "control_name": {"type": "string", "description": "控件名称", "default": ""},
                },
                "required": ["action"],
            },
        },
    },
}


def register_screen_tools(registry: ToolRegistry) -> None:
    """将所有屏幕控制工具注册到工具注册表。"""
    tool_fns = {
        "screen_screenshot": tool_screen_screenshot,
        "screen_window_list": tool_screen_window_list,
        "screen_mouse_click": tool_screen_mouse_click,
        "screen_key_type": tool_screen_key_type,
        "app_launch": tool_app_launch,
        "screen_shell": tool_screen_shell,
        "screen_uia_action": tool_screen_uia_action,
    }

    for name, fn in tool_fns.items():
        schema = _TOOL_SCHEMAS.get(name, {})
        registry.register(
            name=name,
            func=fn,
            schema=schema,
            provider_hint="screen",
        )
        logger.debug("screen tool registered: %s", name)

    logger.info("screen control tools registered: %d tools", len(tool_fns))


def get_available_tools(permission_level: str) -> list[str]:
    """根据权限档位返回可用工具列表。"""
    level = permission_level.upper()
    if level == "VIEW_ONLY":
        return ["screen_screenshot", "screen_window_list"]
    elif level == "STANDARD":
        return [
            "screen_screenshot",
            "screen_window_list",
            "screen_mouse_click",
            "screen_key_type",
            "app_launch",
            "screen_shell",
        ]
    elif level == "FULL":
        return list(_TOOL_SCHEMAS.keys())
    else:
        return ["screen_screenshot", "screen_window_list"]

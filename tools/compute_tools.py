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
        "description": """截取当前屏幕或指定区域的截图。

使用场景：
- 需要查看屏幕上显示的内容时
- 定位窗口、按钮或控件位置时
- 验证操作结果是否正确显示时
- 需要记录当前屏幕状态时

参数说明：
- region: 可选，截图区域坐标 [x1, y1, x2, y2]，省略则全屏截图

注意事项：
- 全屏截图文件较大，建议按需截取目标区域
- 建议先用 list_windows 找到目标窗口，再截取对应区域
- 截图后可配合 uia_action 进行深度控件识别

相关工具：list_windows, uia_action, focus_window""",
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
    }, category="system_control")

    registry.register("mouse_move", controller.mouse_move, {
        "name": "mouse_move",
        "description": """移动鼠标到指定屏幕坐标。

使用场景：
- 需要将鼠标移到某个按钮或控件上方时
- 鼠标悬停查看提示信息时
- 拖拽操作前的定位准备

参数说明：
- x: 目标 X 坐标（像素，从屏幕左上角开始）
- y: 目标 Y 坐标（像素）
- duration: 移动持续时间（秒），默认 0.2，值越大移动越平滑

注意事项：
- 坐标从屏幕左上角 (0,0) 开始计算
- 多显示器场景下注意坐标范围
- 建议先用 screenshot 确认目标位置再移动

相关工具：mouse_click, mouse_scroll, screenshot""",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "目标 X 坐标"},
                "y": {"type": "integer", "description": "目标 Y 坐标"},
                "duration": {"type": "number", "description": "移动持续时间（秒），默认 0.2"},
            },
            "required": ["x", "y"],
        },
    }, category="system_control")

    registry.register("mouse_click", controller.mouse_click, {
        "name": "mouse_click",
        "description": """在指定位置执行鼠标点击操作。

使用场景：
- 点击按钮、链接、菜单等界面元素
- 双击打开文件或文件夹
- 右键调出上下文菜单
- 点击选中文本或对象

参数说明：
- x: 点击 X 坐标，省略则点击当前位置
- y: 点击 Y 坐标（x 和 y 必须同时提供）
- button: 按键类型，left(左键) / right(右键) / middle(中键)，默认 left
- clicks: 连击次数，1=单击，2=双击，默认 1

注意事项：
- 点击前建议先用 screenshot 确认位置准确
- 双击时 clicks 设为 2
- 右键菜单操作后通常需要配合键盘操作

相关工具：mouse_move, mouse_scroll, key_press""",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "点击 X 坐标，省略则点击当前位置"},
                "y": {"type": "integer", "description": "点击 Y 坐标"},
                "button": {"type": "string", "description": "按键: left, right, middle"},
                "clicks": {"type": "integer", "description": "连击次数，默认 1"},
            },
        },
    }, category="system_control")

    registry.register("mouse_scroll", controller.mouse_scroll, {
        "name": "mouse_scroll",
        "description": """控制鼠标滚轮上下滚动。

使用场景：
- 浏览长文档、网页时滚动页面
- 在列表中上下翻找内容
- 缩放图片或画布（配合 Ctrl 键）

参数说明：
- clicks: 滚动步数，正值向上滚动，负值向下滚动

注意事项：
- 一步大约等于滚轮的一个刻度
- 滚动效果取决于当前焦点窗口
- 大页面建议分多次滚动，每次滚动后确认位置

相关工具：mouse_move, mouse_click, key_press""",
        "parameters": {
            "type": "object",
            "properties": {
                "clicks": {"type": "integer", "description": "滚动步数，正值向上，负值向下"},
            },
            "required": ["clicks"],
        },
    }, category="system_control")

    registry.register("key_press", controller.key_press, {
        "name": "key_press",
        "description": """按下并释放一个键盘按键。

使用场景：
- 按 Enter 确认、按 Escape 取消
- 按 Tab 切换输入焦点
- 功能键操作（F1~F12）
- 方向键导航

参数说明：
- key: 按键名称，如 enter, escape, tab, space, backspace, delete,
  up, down, left, right, f1~f12, ctrl, alt, shift 等

注意事项：
- 组合快捷键请使用 hotkey 工具
- 输入文本请使用 type_text 工具
- 按键名称不区分大小写

相关工具：type_text, hotkey""",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名称，如 enter, escape, tab"},
            },
            "required": ["key"],
        },
    }, category="system_control")

    registry.register("type_text", controller.type_text, {
        "name": "type_text",
        "description": """在当前焦点窗口输入文本（模拟键盘逐字输入）。

使用场景：
- 在文本框、编辑器中输入内容
- 填写表单、搜索框输入关键词
- 在命令行中输入命令
- 任何需要键盘输入文字的场景

参数说明：
- text: 要输入的文本内容

注意事项：
- 输入前请确保目标输入框已获得焦点
- 支持中文、英文及各种符号
- 大段文本建议分批输入，避免丢字
- 输入后建议用 screenshot 验证输入结果

相关工具：key_press, hotkey, focus_window""",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文本"},
            },
            "required": ["text"],
        },
    }, category="system_control")

    registry.register("hotkey", controller.hotkey, {
        "name": "hotkey",
        "description": """按下组合快捷键（如 Ctrl+C、Ctrl+V 等）。

使用场景：
- 复制粘贴：ctrl+c / ctrl+v
- 全选、撤销、保存：ctrl+a / ctrl+z / ctrl+s
- 窗口管理：alt+tab / win+d
- 浏览器操作：ctrl+t / ctrl+w / f5

参数说明：
- keys: 组合键列表，按顺序排列，如 ['ctrl', 'c']

常用快捷键参考：
- 复制: ['ctrl', 'c']
- 粘贴: ['ctrl', 'v']
- 全选: ['ctrl', 'a']
- 保存: ['ctrl', 's']
- 撤销: ['ctrl', 'z']
- 切换窗口: ['alt', 'tab']
- 显示桌面: ['win', 'd']

注意事项：
- 按键名称不区分大小写
- 组合键会同时按下所有按键后再释放
- 单个按键请用 key_press

相关工具：key_press, type_text""",
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
    }, category="system_control")

    registry.register("shell_execute", controller.shell_execute, {
        "name": "shell_execute",
        "description": """在用户电脑上执行一个简单的 shell 命令。

使用场景：
- 执行系统内置命令（如 dir, ls, ping, ipconfig 等）
- 启动可执行程序
- 查询系统信息
- 文件操作的简单场景

参数说明：
- command: 要执行的命令字符串
- cwd: 工作目录（可选），不指定则使用默认工作目录

注意事项：
- 不支持管道 |、重定向 >、命令链 && / ; 等复杂语法
- 复杂任务请分步调用，或使用专用的文件操作工具
- 执行前请确认命令安全，禁止执行高危系统命令
- 禁止访问或修改系统敏感目录和文件

相关工具：app_open, system_info, process_list""",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令字符串"},
                "cwd": {"type": "string", "description": "工作目录（可选）"},
            },
            "required": ["command"],
        },
    }, category="system_control")

    registry.register("uia_action", controller.uia_action, {
        "name": "uia_action",
        "description": """通过 Windows UI Automation 执行界面自动化操作。

使用场景：
- 精确点击按钮、菜单等标准控件
- 获取输入框、标签的文本内容
- 设置输入框的值
- 选择下拉框选项
- 比纯坐标点击更稳定可靠

参数说明：
- action_type: 操作类型
  - click: 点击控件
  - get_text: 获取控件文本
  - set_value: 设置控件值
  - invoke: 调用控件默认动作
  - select: 选择下拉框选项
- params: 操作参数，包含控件定位信息（如 Name, AutomationId, ClassName 等）

注意事项：
- UIA 依赖应用程序对 UI Automation 的支持程度
- 部分自定义控件可能无法被 UIA 识别
- 定位失败时可改用 screenshot + mouse_click 的方案
- 建议先用 list_windows 找到目标窗口再操作

相关工具：screenshot, list_windows, focus_window, mouse_click""",
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
    }, category="system_control")

    registry.register("list_windows", controller.list_windows, {
        "name": "list_windows",
        "description": """列出当前所有可见窗口的标题和句柄。

使用场景：
- 查找某个应用窗口是否已打开
- 获取窗口句柄用于后续的 focus_window 操作
- 确认目标应用程序是否启动成功
- 枚举所有窗口进行筛选

返回内容：
- 每个窗口包含标题（title）和句柄（hwnd）
- 句柄可用于 focus_window 和其他窗口操作

注意事项：
- 只返回可见窗口，最小化的窗口也会列出
- 窗口标题可能随应用状态变化
- 可以通过标题关键词过滤找到目标窗口

相关工具：focus_window, app_open, screenshot""",
        "parameters": {"type": "object", "properties": {}},
    }, category="system_control")

    registry.register("focus_window", controller.focus_window, {
        "name": "focus_window",
        "description": """将指定句柄的窗口切换到前台并激活。

使用场景：
- 切换到目标应用窗口进行操作
- 确保输入焦点在正确的窗口
- 窗口被遮挡时调到最前面

参数说明：
- hwnd: 窗口句柄，从 list_windows 获取

注意事项：
- 必须提供有效的窗口句柄
- 某些全屏应用可能阻止窗口切换
- 切换后建议用 screenshot 确认窗口已在前台

相关工具：list_windows, app_open, screenshot""",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄（从 list_windows 获得）"},
            },
            "required": ["hwnd"],
        },
    }, category="system_control")

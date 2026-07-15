"""系统操作工具

支持操作：
- open_app — 打开指定软件
- system_status — 查看系统状态（CPU、内存、磁盘）
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any, Dict, Tuple

import psutil
from loguru import logger

from tools.base import Tool


# ===== 允许的应用映射 =====
_APP_MAP: Dict[str, str] = {
    "记事本": "notepad.exe",
    "notepad": "notepad.exe",
    "计算器": "calc.exe",
    "calculator": "calc.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "资源管理器": "explorer.exe",
    "explorer": "explorer.exe",
    "浏览器": "https://www.baidu.com",
    "edge": "msedge.exe",
    "chrome": "chrome.exe",
    "vscode": "code.cmd",
    "pycharm": "pycharm64.exe",
}


class OpenAppTool(Tool):
    name = "open_app"
    description = "打开指定的软件或网址。支持的软件：记事本、计算器、cmd、浏览器、VS Code 等。也可以传入网址。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "要打开的软件名称或网址（如：记事本、计算器、浏览器、https://www.baidu.com）",
                },
            },
            "required": ["app_name"],
        }

    async def execute(self, app_name: str = "", **kwargs) -> Tuple[bool, str]:
        if not app_name:
            return False, "错误：未指定要打开的应用"

        app_lower = app_name.lower().strip()

        # URL 直接打开
        if app_lower.startswith("http://") or app_lower.startswith("https://"):
            try:
                os.startfile(app_name)
                return True, f"已在浏览器中打开: {app_name}"
            except Exception as e:
                return False, f"打开网址失败: {e}"

        # 查找映射
        target = _APP_MAP.get(app_lower, _APP_MAP.get(app_name, ""))

        if target:
            try:
                if platform.system() == "Windows":
                    # 用 subprocess.Popen 替换 os.startfile：
                    # os.startfile("notepad.exe") 不会解析 PATH，
                    # 会导致"系统找不到指定的路径"（截图 bug）
                    subprocess.Popen(target)
                else:
                    subprocess.Popen([target], shell=True)
                logger.info(f"open_app: {app_name} → {target}")
                return True, f"已启动: {app_name}"
            except Exception as e:
                return False, f"启动失败: {type(e).__name__}: {e}"

        return False, f"不支持的应用: {app_name}。当前支持: {', '.join(sorted(set(_APP_MAP.keys())))}"


class SystemStatusTool(Tool):
    name = "system_status"
    description = "查看当前系统的 CPU 使用率、内存使用量、磁盘空间等状态信息"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs) -> Tuple[bool, str]:
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")

            lines = [
                f"💻 系统状态",
                f"CPU 使用率: {cpu_percent}%",
                f"内存: {mem.used / (1024**3):.1f}GB / {mem.total / (1024**3):.1f}GB ({mem.percent}%)",
                f"C盘: {disk.used / (1024**3):.1f}GB / {disk.total / (1024**3):.1f}GB ({disk.percent}%)",
                f"系统: {platform.system()} {platform.release()}",
                f"Python: {platform.python_version()}",
            ]

            logger.debug("system_status 已查询")
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"获取系统状态失败: {e}"

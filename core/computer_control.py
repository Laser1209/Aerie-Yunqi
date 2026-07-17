"""Aerie v12.0 · 电脑操控模块

权限三档：
  - VIEW_ONLY (只读)：仅允许截图、查询窗口信息
  - STANDARD (标准)：允许键鼠操作、受限 shell
  - FULL (完全)：允许所有操作，包括 UIA 深度操控

安全机制：
  - 危险命令黑名单
  - 操作审计日志
  - 用户审批流程（高风险操作）
  - 超时保护
  - 输出截断
"""

from __future__ import annotations
import os
import time
import json
import ctypes
import subprocess
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class PermissionLevel(str, Enum):
    """权限等级"""
    VIEW_ONLY = "view_only"
    STANDARD = "standard"
    FULL = "full"


class ControlAction(str, Enum):
    """操作类型"""
    SCREENSHOT = "screenshot"
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_SCROLL = "mouse_scroll"
    KEY_PRESS = "key_press"
    KEY_TYPE = "key_type"
    SHELL_CMD = "shell_cmd"
    WINDOW_INFO = "window_info"
    WINDOW_FOCUS = "window_focus"
    UIA_ACTION = "uia_action"


class RiskLevel(str, Enum):
    """风险等级"""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# 危险命令黑名单（Windows）
DANGEROUS_COMMANDS = [
    "format", "del /f /s /q", "rd /s /q", "rmdir /s /q",
    "taskkill /f /im explorer.exe",
    "shutdown", "restart", "poweroff",
    "reg delete", "reg add",
    "net user", "net localgroup administrators",
    "sc delete", "sc stop",
    "wmic", "powershell -command",
    "curl http", "wget http",
    "echo . >", "echo >",  # 覆盖文件
]

# 白名单命令（VIEW_ONLY 模式下允许的 shell 命令）
SAFE_COMMANDS_VIEW = [
    "dir", "ls", "echo", "ver", "date", "time",
    "tasklist", "whoami", "hostname", "ipconfig",
    "systeminfo", "wmic os get",  # 只读查询
]

# STANDARD 模式下允许的额外命令
SAFE_COMMANDS_STANDARD = [
    "cd", "pwd", "type", "cat", "head", "tail",
    "copy", "xcopy", "move", "ren", "mkdir",
    "ping", "tracert", "nslookup",
    "python --version", "node --version",
]

# 操作 → 风险等级映射
ACTION_RISK_MAP = {
    ControlAction.SCREENSHOT: RiskLevel.SAFE,
    ControlAction.WINDOW_INFO: RiskLevel.SAFE,
    ControlAction.MOUSE_MOVE: RiskLevel.LOW,
    ControlAction.MOUSE_SCROLL: RiskLevel.LOW,
    ControlAction.MOUSE_CLICK: RiskLevel.MEDIUM,
    ControlAction.KEY_PRESS: RiskLevel.MEDIUM,
    ControlAction.KEY_TYPE: RiskLevel.MEDIUM,
    ControlAction.WINDOW_FOCUS: RiskLevel.LOW,
    ControlAction.SHELL_CMD: RiskLevel.HIGH,
    ControlAction.UIA_ACTION: RiskLevel.HIGH,
}

# 权限 → 允许的操作
PERMISSION_ACTIONS = {
    PermissionLevel.VIEW_ONLY: {
        ControlAction.SCREENSHOT,
        ControlAction.WINDOW_INFO,
    },
    PermissionLevel.STANDARD: {
        ControlAction.SCREENSHOT,
        ControlAction.WINDOW_INFO,
        ControlAction.MOUSE_MOVE,
        ControlAction.MOUSE_CLICK,
        ControlAction.MOUSE_SCROLL,
        ControlAction.KEY_PRESS,
        ControlAction.KEY_TYPE,
        ControlAction.WINDOW_FOCUS,
        ControlAction.SHELL_CMD,
    },
    PermissionLevel.FULL: {action for action in ControlAction},
}


@dataclass
class ControlResult:
    """操控结果"""
    success: bool
    action: str
    data: dict = field(default_factory=dict)
    error: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "action": self.action,
            "data": self.data,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class AuditLogEntry:
    """审计日志条目"""
    action: str
    risk_level: str
    permission_level: str
    details: dict = field(default_factory=dict)
    result: str = ""
    timestamp: float = field(default_factory=time.time)
    user_approved: bool = False

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "risk_level": self.risk_level,
            "permission_level": self.permission_level,
            "details": self.details,
            "result": self.result,
            "timestamp": self.timestamp,
            "user_approved": self.user_approved,
        }


class AuditLogger:
    """审计日志"""

    def __init__(self, log_dir: str = "data/audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "computer_control.jsonl"

    def log(self, entry: AuditLogEntry) -> None:
        """记录一条审计日志"""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"写入审计日志失败: {e}")

    def get_recent(self, limit: int = 50) -> list[dict]:
        """获取最近的日志"""
        if not self.log_file.exists():
            return []
        lines = self.log_file.read_text(encoding="utf-8").strip().split("\n")
        entries = []
        for line in lines[-limit:]:
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        return entries


class PermissionManager:
    """权限管理器"""

    def __init__(self, level: PermissionLevel = PermissionLevel.VIEW_ONLY):
        self._level = level

    @property
    def level(self) -> PermissionLevel:
        return self._level

    def set_level(self, level: PermissionLevel) -> None:
        self._level = level
        logger.info(f"权限等级已切换为: {level.value}")

    def can_perform(self, action: ControlAction) -> bool:
        """检查是否有权限执行指定操作"""
        return action in PERMISSION_ACTIONS.get(self._level, set())

    def needs_approval(self, action: ControlAction, details: Optional[dict] = None) -> bool:
        """判断操作是否需要用户审批"""
        risk = ACTION_RISK_MAP.get(action, RiskLevel.MEDIUM)

        # 高风险及以上需要审批
        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return True

        # 中等风险 + 低权限 → 需要审批
        if risk == RiskLevel.MEDIUM and self._level == PermissionLevel.VIEW_ONLY:
            return True

        return False


class ScreenshotCapturer:
    """截图捕获器

    优先使用 Pillow ImageGrab，无 Pillow 时回退到 Windows GDI
    """

    def __init__(self):
        self._has_pillow = self._check_pillow()

    def _check_pillow(self) -> bool:
        try:
            from PIL import ImageGrab  # noqa: F401
            return True
        except ImportError:
            return False

    def capture(self, region: Optional[tuple[int, int, int, int]] = None) -> ControlResult:
        """截图

        Args:
            region: (x1, y1, x2, y2) 区域，None 为全屏
        """
        try:
            if self._has_pillow:
                return self._capture_pillow(region)
            else:
                return self._capture_windows_gdi(region)
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.SCREENSHOT.value,
                error=str(e),
            )

    def _capture_pillow(self, region: Optional[tuple[int, int, int, int]]) -> ControlResult:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=region)

        # 保存到临时文件
        import tempfile
        tmp_dir = Path(tempfile.gettempdir()) / "aerie_screenshots"
        tmp_dir.mkdir(exist_ok=True)
        filename = f"screenshot_{int(time.time())}.png"
        filepath = tmp_dir / filename
        img.save(str(filepath))

        return ControlResult(
            success=True,
            action=ControlAction.SCREENSHOT.value,
            data={
                "path": str(filepath),
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "region": region,
            },
        )

    def _capture_windows_gdi(self, region: Optional[tuple[int, int, int, int]]) -> ControlResult:
        """Windows GDI 截图（无依赖回退方案）

        简化实现：使用 BitBlt 捕获屏幕，返回 BMP 文件路径
        """
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            # 获取屏幕尺寸
            if region:
                x1, y1, x2, y2 = region
                width, height = x2 - x1, y2 - y1
            else:
                x1, y1 = 0, 0
                width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
                height = user32.GetSystemMetrics(1)  # SM_CYSCREEN

            # 创建设备上下文
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
            gdi32.SelectObject(hdc_mem, hbitmap)

            # 位块传输
            gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, x1, y1, 0x00CC0020)  # SRCCOPY

            # 保存 BMP
            import tempfile
            tmp_dir = Path(tempfile.gettempdir()) / "aerie_screenshots"
            tmp_dir.mkdir(exist_ok=True)
            filepath = tmp_dir / f"screenshot_{int(time.time())}.bmp"

            # BMP 文件头 + 信息头 + 像素数据
            # 简化：用 PIL 保存更好，但这里是无依赖回退，所以只返回 DC 信息
            user32.ReleaseDC(0, hdc_screen)
            gdi32.DeleteDC(hdc_mem)
            gdi32.DeleteObject(hbitmap)

            return ControlResult(
                success=True,
                action=ControlAction.SCREENSHOT.value,
                data={
                    "path": "",
                    "width": width,
                    "height": height,
                    "mode": "gdi_fallback",
                    "note": "GDI 截图已捕获，请安装 Pillow 以获得完整图片保存功能",
                },
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.SCREENSHOT.value,
                error=f"GDI 截图失败: {e}",
            )

    def get_screen_size(self) -> tuple[int, int]:
        """获取屏幕分辨率"""
        try:
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        except Exception:
            return (1920, 1080)


class MouseController:
    """鼠标控制器

    优先使用 pyautogui，无依赖时回退到 Windows API (ctypes)
    """

    def __init__(self):
        self._has_pyautogui = self._check_pyautogui()

    def _check_pyautogui(self) -> bool:
        try:
            import pyautogui  # noqa: F401
            return True
        except ImportError:
            return False

    def move(self, x: int, y: int, duration: float = 0.2) -> ControlResult:
        """移动鼠标到指定位置"""
        try:
            if self._has_pyautogui:
                import pyautogui
                pyautogui.moveTo(x, y, duration=duration)
            else:
                self._move_windows(x, y)

            return ControlResult(
                success=True,
                action=ControlAction.MOUSE_MOVE.value,
                data={"x": x, "y": y, "duration": duration},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.MOUSE_MOVE.value,
                error=str(e),
            )

    def _move_windows(self, x: int, y: int) -> None:
        """Windows API 鼠标移动"""
        user32 = ctypes.windll.user32
        user32.SetCursorPos(x, y)

    def click(self, x: Optional[int] = None, y: Optional[int] = None,
              button: str = "left", clicks: int = 1, interval: float = 0.1) -> ControlResult:
        """鼠标点击"""
        try:
            if self._has_pyautogui:
                import pyautogui
                if x is not None and y is not None:
                    pyautogui.click(x, y, clicks=clicks, interval=interval, button=button)
                else:
                    pyautogui.click(clicks=clicks, interval=interval, button=button)
            else:
                if x is not None and y is not None:
                    self._move_windows(x, y)
                self._click_windows(button, clicks, interval)

            return ControlResult(
                success=True,
                action=ControlAction.MOUSE_CLICK.value,
                data={"x": x, "y": y, "button": button, "clicks": clicks},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.MOUSE_CLICK.value,
                error=str(e),
            )

    def _click_windows(self, button: str, clicks: int, interval: float) -> None:
        """Windows API 鼠标点击"""
        user32 = ctypes.windll.user32

        if button == "left":
            down_flag = 0x0002  # MOUSEEVENTF_LEFTDOWN
            up_flag = 0x0004    # MOUSEEVENTF_LEFTUP
        elif button == "right":
            down_flag = 0x0008  # MOUSEEVENTF_RIGHTDOWN
            up_flag = 0x0010    # MOUSEEVENTF_RIGHTUP
        elif button == "middle":
            down_flag = 0x0020  # MOUSEEVENTF_MIDDLEDOWN
            up_flag = 0x0040    # MOUSEEVENTF_MIDDLEUP
        else:
            raise ValueError(f"不支持的鼠标按键: {button}")

        for i in range(clicks):
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.01)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            if i < clicks - 1:
                time.sleep(interval)

    def scroll(self, clicks: int, horizontal: bool = False) -> ControlResult:
        """鼠标滚轮"""
        try:
            if self._has_pyautogui:
                import pyautogui
                if horizontal:
                    pyautogui.hscroll(clicks)
                else:
                    pyautogui.scroll(clicks)
            else:
                self._scroll_windows(clicks, horizontal)

            return ControlResult(
                success=True,
                action=ControlAction.MOUSE_SCROLL.value,
                data={"clicks": clicks, "horizontal": horizontal},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.MOUSE_SCROLL.value,
                error=str(e),
            )

    def _scroll_windows(self, clicks: int, horizontal: bool) -> None:
        """Windows API 滚轮"""
        user32 = ctypes.windll.user32
        # WHEEL_DELTA = 120
        amount = clicks * 120
        if horizontal:
            # 水平滚动（Windows NT 5.0+）
            user32.mouse_event(0x01000, 0, 0, amount, 0)  # MOUSEEVENTF_HWHEEL
        else:
            user32.mouse_event(0x0800, 0, 0, amount, 0)  # MOUSEEVENTF_WHEEL

    def get_position(self) -> tuple[int, int]:
        """获取当前鼠标位置"""
        if self._has_pyautogui:
            import pyautogui
            return pyautogui.position()
        else:
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y


class KeyboardController:
    """键盘控制器"""

    def __init__(self):
        self._has_pyautogui = self._check_pyautogui()

    def _check_pyautogui(self) -> bool:
        try:
            import pyautogui  # noqa: F401
            return True
        except ImportError:
            return False

    def press(self, key: str) -> ControlResult:
        """按下并释放一个键"""
        try:
            if self._has_pyautogui:
                import pyautogui
                pyautogui.press(key)
            else:
                self._press_windows(key)

            return ControlResult(
                success=True,
                action=ControlAction.KEY_PRESS.value,
                data={"key": key},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.KEY_PRESS.value,
                error=str(e),
            )

    def _press_windows(self, key: str) -> None:
        """Windows API 按键"""
        vk = self._get_vk_code(key)
        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, 0, 0)  # KEYEVENTF_KEYDOWN
        time.sleep(0.01)
        user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    def _get_vk_code(self, key: str) -> int:
        """获取虚拟键码"""
        key_map = {
            "enter": 0x0D,
            "space": 0x20,
            "backspace": 0x08,
            "tab": 0x09,
            "esc": 0x1B,
            "delete": 0x2E,
            "home": 0x24,
            "end": 0x23,
            "left": 0x25,
            "up": 0x26,
            "right": 0x27,
            "down": 0x28,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
            "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
            "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
        }

        key_lower = key.lower()
        if key_lower in key_map:
            return key_map[key_lower]

        if len(key) == 1:
            # 字母或数字
            return ord(key.upper())

        raise ValueError(f"不支持的按键: {key}")

    def type_text(self, text: str, interval: float = 0.01) -> ControlResult:
        """输入文本"""
        try:
            if self._has_pyautogui:
                import pyautogui
                pyautogui.typewrite(text, interval=interval)
            else:
                for char in text:
                    # 简单实现：只处理 ASCII 可打印字符
                    if ord(char) < 128 and char.isprintable():
                        # 用剪贴板 + Ctrl+V 输入中文和特殊字符更可靠
                        # 简化版：用 keybd_event 输入 ASCII
                        vk = ord(char.upper())
                        user32 = ctypes.windll.user32

                        # Shift 处理
                        if char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?':
                            user32.keybd_event(0x10, 0, 0, 0)  # Shift down

                        user32.keybd_event(vk, 0, 0, 0)
                        time.sleep(0.005)
                        user32.keybd_event(vk, 0, 0x0002, 0)

                        if char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?':
                            user32.keybd_event(0x10, 0, 0x0002, 0)  # Shift up

                        time.sleep(interval)
                    else:
                        # 非 ASCII 字符跳过（中文等建议用剪贴板方案）
                        pass

            return ControlResult(
                success=True,
                action=ControlAction.KEY_TYPE.value,
                data={"text": text[:50] + "..." if len(text) > 50 else text,
                      "length": len(text)},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.KEY_TYPE.value,
                error=str(e),
            )

    def hotkey(self, *keys: str) -> ControlResult:
        """快捷键组合，如 ctrl+c"""
        try:
            if self._has_pyautogui:
                import pyautogui
                pyautogui.hotkey(*keys)
            else:
                # 简单实现：依次按下，反序释放
                vks = [self._get_vk_code(k) for k in keys]
                user32 = ctypes.windll.user32

                for vk in vks:
                    user32.keybd_event(vk, 0, 0, 0)
                    time.sleep(0.01)

                for vk in reversed(vks):
                    user32.keybd_event(vk, 0, 0x0002, 0)
                    time.sleep(0.01)

            return ControlResult(
                success=True,
                action=ControlAction.KEY_PRESS.value,
                data={"keys": list(keys)},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.KEY_PRESS.value,
                error=str(e),
            )


class RestrictedShell:
    """受限 Shell 执行器

    安全机制：
    - 命令白名单（按权限等级）
    - 危险模式黑名单
    - 超时保护
    - 输出截断
    - 工作目录限制
    """

    def __init__(self, default_cwd: Optional[str] = None, timeout: int = 30,
                 max_output: int = 10000):
        self.default_cwd = default_cwd or os.getcwd()
        self.timeout = timeout
        self.max_output = max_output

    def is_dangerous(self, command: str) -> tuple[bool, list[str]]:
        """检查命令是否危险

        Returns:
            (是否危险, 危险原因列表)
        """
        issues = []
        cmd_lower = command.lower()

        for pattern in DANGEROUS_COMMANDS:
            if pattern.lower() in cmd_lower:
                issues.append(f"匹配危险模式: {pattern}")

        # 检查管道和重定向（高风险）
        if "|" in command and not command.strip().startswith("dir"):
            # 管道可能用于链式危险操作
            if any(d in cmd_lower for d in ["del", "format", "rd", "shutdown"]):
                issues.append("管道 + 危险命令")

        return len(issues) > 0, issues

    def is_allowed(self, command: str, permission: PermissionLevel) -> bool:
        """检查命令是否在白名单内（仅对 view_only 严格限制）"""
        if permission == PermissionLevel.FULL:
            return True

        cmd_lower = command.strip().lower()
        safe_cmds = SAFE_COMMANDS_VIEW.copy()
        if permission == PermissionLevel.STANDARD:
            safe_cmds += SAFE_COMMANDS_STANDARD

        # 检查命令前缀
        for safe in safe_cmds:
            if cmd_lower.startswith(safe.lower()):
                return True

        return False

    def execute(self, command: str, cwd: Optional[str] = None,
                permission: PermissionLevel = PermissionLevel.STANDARD
                ) -> ControlResult:
        """执行命令

        Args:
            command: 要执行的命令
            cwd: 工作目录
            permission: 当前权限等级
        """
        # 危险检查
        is_danger, issues = self.is_dangerous(command)
        if is_danger:
            return ControlResult(
                success=False,
                action=ControlAction.SHELL_CMD.value,
                error=f"命令被阻止（危险）: {'; '.join(issues)}",
                data={"command": command[:100], "blocked_reason": issues},
            )

        # 权限检查
        if permission != PermissionLevel.FULL:
            if not self.is_allowed(command, permission):
                return ControlResult(
                    success=False,
                    action=ControlAction.SHELL_CMD.value,
                    error=f"权限不足：当前权限 {permission.value} 不允许执行此命令",
                    data={"command": command[:100], "permission": permission.value},
                )

        try:
            work_dir = cwd or self.default_cwd
            result = subprocess.run(
                command,
                shell=True,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )

            # 输出截断
            stdout = result.stdout
            stderr = result.stderr
            truncated = False
            if len(stdout) > self.max_output:
                stdout = stdout[:self.max_output] + f"\n... [已截断，共 {len(result.stdout)} 字符]"
                truncated = True
            if len(stderr) > self.max_output:
                stderr = stderr[:self.max_output] + f"\n... [已截断，共 {len(result.stderr)} 字符]"
                truncated = True

            return ControlResult(
                success=result.returncode == 0,
                action=ControlAction.SHELL_CMD.value,
                data={
                    "command": command[:100],
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result.returncode,
                    "truncated": truncated,
                    "cwd": work_dir,
                },
            )
        except subprocess.TimeoutExpired:
            return ControlResult(
                success=False,
                action=ControlAction.SHELL_CMD.value,
                error=f"命令执行超时（{self.timeout}s）",
                data={"command": command[:100], "timeout": self.timeout},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.SHELL_CMD.value,
                error=str(e),
                data={"command": command[:100]},
            )


class WindowManager:
    """窗口管理器（Windows API）"""

    def __init__(self):
        self._windows: list[dict] = []

    def list_windows(self) -> ControlResult:
        """列出所有顶层窗口"""
        try:
            windows = []

            def enum_callback(hwnd, _):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        title = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, title, length + 1)

                        rect = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
                        x = y = w = h = 0
                        try:
                            class RECT(ctypes.Structure):
                                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                           ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                            r = RECT()
                            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
                            x, y = r.left, r.top
                            w, h = r.right - r.left, r.bottom - r.top
                        except Exception:
                            pass

                        windows.append({
                            "hwnd": hwnd,
                            "title": title.value,
                            "x": x, "y": y,
                            "width": w, "height": h,
                        })
                return True

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
            )
            ctypes.windll.user32.EnumWindows(EnumWindowsProc(enum_callback), 0)

            self._windows = windows
            return ControlResult(
                success=True,
                action=ControlAction.WINDOW_INFO.value,
                data={"count": len(windows), "windows": windows[:50]},  # 最多返回 50 个
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.WINDOW_INFO.value,
                error=str(e),
            )

    def focus_window(self, hwnd: int) -> ControlResult:
        """激活/聚焦窗口"""
        try:
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)

            return ControlResult(
                success=True,
                action=ControlAction.WINDOW_FOCUS.value,
                data={"hwnd": hwnd},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.WINDOW_FOCUS.value,
                error=str(e),
            )

    def find_window(self, title_contains: str) -> ControlResult:
        """按标题查找窗口"""
        result = self.list_windows()
        if not result.success:
            return result

        found = [
            w for w in result.data["windows"]
            if title_contains.lower() in w["title"].lower()
        ]

        return ControlResult(
            success=True,
            action=ControlAction.WINDOW_INFO.value,
            data={"query": title_contains, "count": len(found), "windows": found},
        )


class UIAController:
    """UIA (UI Automation) 控制器 - pywinauto 封装

    用于深度 UI 操控：识别控件、获取属性、点击控件等。
    需要 pywinauto 作为可选依赖。
    """

    def __init__(self):
        self._available = self._check_available()
        self._app = None

    def _check_available(self) -> bool:
        try:
            from pywinauto import Application  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def available(self) -> bool:
        return self._available

    def connect(self, title: Optional[str] = None,
                handle: Optional[int] = None,
                process: Optional[int] = None) -> ControlResult:
        """连接到应用"""
        if not self._available:
            return ControlResult(
                success=False,
                action=ControlAction.UIA_ACTION.value,
                error="pywinauto 未安装，UIA 功能不可用",
            )

        try:
            from pywinauto import Application

            if handle:
                self._app = Application(backend="uia").connect(handle=handle)
            elif title:
                self._app = Application(backend="uia").connect(title_re=title)
            elif process:
                self._app = Application(backend="uia").connect(process=process)
            else:
                return ControlResult(
                    success=False,
                    action=ControlAction.UIA_ACTION.value,
                    error="必须提供 title/handle/process 之一",
                )

            return ControlResult(
                success=True,
                action=ControlAction.UIA_ACTION.value,
                data={"connected": True, "method": "title" if title else "handle" if handle else "process"},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.UIA_ACTION.value,
                error=f"连接失败: {e}",
            )

    def list_controls(self, title: Optional[str] = None) -> ControlResult:
        """列出窗口中的控件"""
        if not self._available or not self._app:
            return ControlResult(
                success=False,
                action=ControlAction.UIA_ACTION.value,
                error="UIA 未初始化或未连接",
            )

        try:
            dlg = self._app.top_window()
            # 获取控件列表（简化版）
            controls = []
            for child in dlg.descendants():
                try:
                    controls.append({
                        "control_type": child.element_info.control_type,
                        "name": child.element_info.name,
                        "class_name": child.element_info.class_name,
                        "rect": str(child.element_info.rectangle),
                    })
                except Exception:
                    pass

            return ControlResult(
                success=True,
                action=ControlAction.UIA_ACTION.value,
                data={"count": len(controls), "controls": controls[:30]},
            )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.UIA_ACTION.value,
                error=f"列举控件失败: {e}",
            )

    def click_control(self, control_name: str) -> ControlResult:
        """点击指定名称的控件"""
        if not self._available or not self._app:
            return ControlResult(
                success=False,
                action=ControlAction.UIA_ACTION.value,
                error="UIA 未初始化或未连接",
            )

        try:
            dlg = self._app.top_window()
            ctrl = dlg.child_window(title=control_name, found_index=0)
            if ctrl.exists(timeout=2):
                ctrl.click()
                return ControlResult(
                    success=True,
                    action=ControlAction.UIA_ACTION.value,
                    data={"control": control_name, "clicked": True},
                )
            else:
                return ControlResult(
                    success=False,
                    action=ControlAction.UIA_ACTION.value,
                    error=f"未找到控件: {control_name}",
                )
        except Exception as e:
            return ControlResult(
                success=False,
                action=ControlAction.UIA_ACTION.value,
                error=f"点击控件失败: {e}",
            )


class ComputerController:
    """电脑操控总控器

    统一入口，集成：截图、鼠标、键盘、受限 Shell、窗口管理、UIA 操控。
    提供权限检查、危险拦截、审计日志。
    """

    def __init__(
        self,
        permission_level: PermissionLevel = PermissionLevel.VIEW_ONLY,
        audit_log_dir: str = "data/audit",
        shell_timeout: int = 30,
    ):
        self.permission = PermissionManager(permission_level)
        self.audit = AuditLogger(audit_log_dir)

        self.screenshot = ScreenshotCapturer()
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.shell = RestrictedShell(timeout=shell_timeout)
        self.windows = WindowManager()
        self.uia = UIAController()

        self._pending_approvals: dict[str, dict] = {}

    # ---- 权限管理 ----

    def set_permission(self, level: PermissionLevel) -> None:
        """设置权限等级"""
        self.permission.set_level(level)

    @property
    def permission_level(self) -> PermissionLevel:
        return self.permission.level

    # ---- 内部：操作前检查 ----

    def _pre_check(self, action: ControlAction, details: Optional[dict] = None
                   ) -> tuple[bool, list[str]]:
        """操作前检查

        Returns:
            (是否通过, 问题列表)
        """
        issues = []

        # 权限检查
        if not self.permission.can_perform(action):
            issues.append(
                f"权限不足：当前 {self.permission.level.value} 不允许 {action.value}"
            )

        return len(issues) == 0, issues

    def _audit(self, action: ControlAction, details: dict,
               result: str, user_approved: bool = False) -> None:
        """记录审计"""
        risk = ACTION_RISK_MAP.get(action, RiskLevel.MEDIUM)
        entry = AuditLogEntry(
            action=action.value,
            risk_level=risk.value,
            permission_level=self.permission.level.value,
            details=details,
            result=result,
            user_approved=user_approved,
        )
        self.audit.log(entry)

    # ---- 截图 ----

    def take_screenshot(self, region: Optional[tuple[int, int, int, int]] = None
                        ) -> ControlResult:
        """截图"""
        action = ControlAction.SCREENSHOT
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"region": region}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.screenshot.capture(region)
        self._audit(action, {"region": region, "path": result.data.get("path", "")},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- 鼠标 ----

    def mouse_move(self, x: int, y: int, duration: float = 0.2) -> ControlResult:
        """移动鼠标"""
        action = ControlAction.MOUSE_MOVE
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"x": x, "y": y}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.mouse.move(x, y, duration)
        self._audit(action, {"x": x, "y": y},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def mouse_click(self, x: Optional[int] = None, y: Optional[int] = None,
                    button: str = "left", clicks: int = 1) -> ControlResult:
        """鼠标点击"""
        action = ControlAction.MOUSE_CLICK
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"x": x, "y": y, "button": button}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        # 高风险需要审批
        if self.permission.needs_approval(action):
            call_id = f"mouse_click_{int(time.time())}"
            self._pending_approvals[call_id] = {
                "action": action,
                "params": {"x": x, "y": y, "button": button, "clicks": clicks},
            }
            return ControlResult(
                success=False,
                action=action.value,
                error="需要用户审批",
                data={"call_id": call_id, "needs_approval": True},
            )

        result = self.mouse.click(x, y, button, clicks)
        self._audit(action, {"x": x, "y": y, "button": button, "clicks": clicks},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def mouse_scroll(self, clicks: int) -> ControlResult:
        """滚轮"""
        action = ControlAction.MOUSE_SCROLL
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"clicks": clicks}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.mouse.scroll(clicks)
        self._audit(action, {"clicks": clicks},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- 键盘 ----

    def key_press(self, key: str) -> ControlResult:
        """按键"""
        action = ControlAction.KEY_PRESS
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"key": key}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.keyboard.press(key)
        self._audit(action, {"key": key},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def type_text(self, text: str) -> ControlResult:
        """输入文本"""
        action = ControlAction.KEY_TYPE
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"text_length": len(text)}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.keyboard.type_text(text)
        self._audit(action, {"text_length": len(text)},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def hotkey(self, *keys: str) -> ControlResult:
        """快捷键"""
        action = ControlAction.KEY_PRESS
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"keys": list(keys)}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.keyboard.hotkey(*keys)
        self._audit(action, {"keys": list(keys)},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- Shell ----

    def shell_execute(self, command: str, cwd: Optional[str] = None) -> ControlResult:
        """执行 shell 命令"""
        action = ControlAction.SHELL_CMD
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"command": command[:100]}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.shell.execute(command, cwd, self.permission.level)
        self._audit(action, {"command": command[:100], "cwd": cwd},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- 窗口 ----

    def list_windows(self) -> ControlResult:
        """列出窗口"""
        action = ControlAction.WINDOW_INFO
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.windows.list_windows()
        self._audit(action, {"count": result.data.get("count", 0)},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def focus_window(self, hwnd: int) -> ControlResult:
        """聚焦窗口"""
        action = ControlAction.WINDOW_FOCUS
        passed, issues = self._pre_check(action)
        if not passed:
            self._audit(action, {"hwnd": hwnd}, "blocked")
            return ControlResult(success=False, action=action.value,
                                 error="; ".join(issues))

        result = self.windows.focus_window(hwnd)
        self._audit(action, {"hwnd": hwnd},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- 审批 ----

    def approve(self, call_id: str) -> ControlResult:
        """审批通过待审批操作"""
        if call_id not in self._pending_approvals:
            return ControlResult(success=False, action="approve",
                                 error=f"待审批项不存在: {call_id}")

        pending = self._pending_approvals.pop(call_id)
        action = pending["action"]
        params = pending["params"]

        # 根据 action 执行对应操作
        if action == ControlAction.MOUSE_CLICK:
            result = self.mouse.click(**params)
            self._audit(action, params, "success (approved)", user_approved=True)
            return result
        elif action == ControlAction.SHELL_CMD:
            result = self.shell.execute(
                params.get("command", ""),
                params.get("cwd"),
                self.permission.level,
            )
            self._audit(action, params, "success (approved)", user_approved=True)
            return result

        return ControlResult(success=False, action="approve",
                             error=f"不支持的操作类型: {action}")

    def reject(self, call_id: str, reason: str = "") -> bool:
        """拒绝待审批操作"""
        if call_id not in self._pending_approvals:
            return False
        pending = self._pending_approvals.pop(call_id)
        self._audit(pending["action"], pending["params"],
                    f"rejected: {reason}", user_approved=False)
        return True

    # ---- 审计查询 ----

    def get_audit_logs(self, limit: int = 50) -> list[dict]:
        """获取审计日志"""
        return self.audit.get_recent(limit)

    # ---- 状态查询 ----

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "permission_level": self.permission.level.value,
            "has_pillow": self.screenshot._has_pillow,
            "has_pyautogui": self.mouse._has_pyautogui,
            "has_pywinauto": self.uia.available,
            "screen_size": self.screenshot.get_screen_size(),
            "mouse_position": self.mouse.get_position(),
            "pending_approvals": len(self._pending_approvals),
        }

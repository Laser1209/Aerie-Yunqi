"""Aerie v0.1.0-beta.1 · 电脑操控模块

权限四模式 + 黑白名单：
  - MANUAL (手动审批)：所有操作均需用户审批
  - AUTO (自动批阅)：低风险自动放行，中/高风险审批
  - FULL (完全访问)：全部放行（系统危险黑名单硬闸除外）
  - CUSTOM (自定义)：默认拦截 + 自定义黑白名单/操作规则

安全机制：
  - 系统危险命令硬闸（任何模式不可绕过）
  - 用户自定义黑名单 / 白名单（白名单命中直接放行）
  - 操作审计日志
  - 用户审批流程（对话框内审批卡片，支持放行并入白名单）
  - 超时保护
  - 输出截断
"""

from __future__ import annotations
import os
import re
import shlex
import time
import json
import ctypes
import uuid
import subprocess
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ControlMode(str, Enum):
    """电脑操控权限模式"""
    MANUAL = "manual"    # 所有操作均需用户审批
    AUTO = "auto"        # 低风险自动放行，中/高风险审批
    FULL = "full"        # 全部放行（系统危险黑名单硬闸除外）
    CUSTOM = "custom"    # 默认拦截 + 自定义黑白名单/操作规则


class Decision(str, Enum):
    """操作裁决结果"""
    ALLOW = "allow"      # 放行
    APPROVE = "approve"  # 需要用户审批
    BLOCK = "block"      # 拦截（不弹窗）


class PolicyEntryType(str, Enum):
    """黑白名单条目类型"""
    ACTION = "action"    # 按操作类型（如 shell_cmd / mouse_click）
    COMMAND = "command"  # shell 命令前缀（如 dir / ping）
    PATTERN = "pattern"  # 正则匹配操作详情 JSON


@dataclass
class PolicyEntry:
    """黑白名单条目"""
    id: str
    type: str            # PolicyEntryType 值
    value: str
    note: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "value": self.value,
            "note": self.note,
            "created_at": self.created_at,
        }


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
    # v0.4.2: 工作区文件写操作(移动/删除/改名/生成),与电脑操控共用权限模式
    FILE_WRITE = "file_write"


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
    # 工作区文件写操作:中风险(移动/删除/改名/生成文件)
    ControlAction.FILE_WRITE: RiskLevel.MEDIUM,
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


class AccessPolicy:
    """访问策略引擎

    决策链（自上而下，先命中先生效）：
      1. 系统危险命令硬闸（SHELL_CMD 命中内置黑名单 → BLOCK，不可绕过）
      2. 用户黑名单（命中 → BLOCK，不弹窗）
      3. 用户白名单（命中 → ALLOW，直接放行，跳过弹窗）
      4. 模式裁决（MANUAL 全审批 / AUTO 低风险放行 / FULL 全放行 / CUSTOM 默认拦截+规则）

    名单与模式持久化到 settings.yaml 的 computer_control 键。
    """

    def __init__(self, mode: ControlMode = ControlMode.MANUAL, persist: bool = True):
        self._mode = mode
        self._whitelist: dict[str, PolicyEntry] = {}
        self._blacklist: dict[str, PolicyEntry] = {}
        self._custom_rules: dict[str, str] = {}  # action_value -> allow/approve/block
        self._shell: Optional["RestrictedShell"] = None
        self._persist_enabled = persist
        if self._persist_enabled:
            self._load_persisted()

    # ── 模式 ────────────────────────────────────────

    @property
    def mode(self) -> ControlMode:
        return self._mode

    def set_mode(self, mode: ControlMode) -> None:
        self._mode = mode
        logger.info("电脑操控模式已切换为: %s", mode.value)
        self._persist()

    # ── 名单 ────────────────────────────────────────

    def get_whitelist(self) -> list[dict]:
        return [e.to_dict() for e in self._whitelist.values()]

    def get_blacklist(self) -> list[dict]:
        return [e.to_dict() for e in self._blacklist.values()]

    def add_whitelist(self, entry_type: str, value: str, note: str = "") -> PolicyEntry:
        return self._add_entry(self._whitelist, entry_type, value, note)

    def add_blacklist(self, entry_type: str, value: str, note: str = "") -> PolicyEntry:
        return self._add_entry(self._blacklist, entry_type, value, note)

    def remove_whitelist(self, entry_id: str) -> bool:
        return self._remove_entry(self._whitelist, entry_id)

    def remove_blacklist(self, entry_id: str) -> bool:
        return self._remove_entry(self._blacklist, entry_id)

    def _add_entry(self, store: dict, entry_type: str, value: str, note: str) -> PolicyEntry:
        value = value.strip()
        if not value:
            raise ValueError("条目值不能为空")
        # 相同类型+值去重，避免重复入账
        for existing in store.values():
            if existing.type == entry_type and existing.value == value:
                return existing
        entry = PolicyEntry(
            id=f"{entry_type}_{uuid.uuid4().hex[:8]}",
            type=entry_type,
            value=value,
            note=note,
        )
        store[entry.id] = entry
        self._persist()
        return entry

    def _remove_entry(self, store: dict, entry_id: str) -> bool:
        if entry_id in store:
            del store[entry_id]
            self._persist()
            return True
        return False

    # ── 自定义规则（CUSTOM 模式按操作类型） ──────────

    def set_custom_rule(self, action_value: str, decision: str) -> None:
        if decision not in {Decision.ALLOW.value, Decision.APPROVE.value, Decision.BLOCK.value}:
            raise ValueError(f"非法规则值: {decision}")
        self._custom_rules[action_value] = decision
        self._persist()

    def get_custom_rules(self) -> dict:
        return dict(self._custom_rules)

    # ── 裁决 ────────────────────────────────────────

    def decide(self, action: ControlAction, details: Optional[dict] = None) -> tuple[Decision, str]:
        """返回 (决策, 原因)。"""
        details = details or {}

        # 1. 系统危险命令硬闸（不可绕过）
        if action == ControlAction.SHELL_CMD:
            cmd = str(details.get("command", ""))
            if self._shell is not None:
                dangerous, issues = self._shell.is_dangerous(cmd)
                if dangerous:
                    return Decision.BLOCK, f"命中系统危险命令黑名单: {'; '.join(issues[:2])}"

        # 2. 用户黑名单
        if self._match(self._blacklist, action, details):
            return Decision.BLOCK, "命中用户黑名单"

        # 3. 用户白名单
        if self._match(self._whitelist, action, details):
            return Decision.ALLOW, "命中白名单，自动放行"

        # 4. 模式裁决
        if self._mode == ControlMode.FULL:
            return Decision.ALLOW, "完全访问模式"
        if self._mode == ControlMode.MANUAL:
            return Decision.APPROVE, "手动审批模式：需用户确认"
        if self._mode == ControlMode.AUTO:
            risk = ACTION_RISK_MAP.get(action, RiskLevel.MEDIUM)
            if risk in (RiskLevel.SAFE, RiskLevel.LOW):
                return Decision.ALLOW, "低风险自动放行"
            return Decision.APPROVE, "自动批阅模式：需用户确认"

        # CUSTOM：默认拦截；命中操作规则则按规则
        rule = self._custom_rules.get(action.value)
        if rule == Decision.ALLOW.value:
            return Decision.ALLOW, "自定义规则放行"
        if rule == Decision.BLOCK.value:
            return Decision.BLOCK, "自定义规则拦截"
        return Decision.APPROVE, "自定义模式默认拦截"

    def _match(self, store: dict, action: ControlAction, details: dict) -> bool:
        for entry in store.values():
            if entry.type == PolicyEntryType.ACTION.value:
                if entry.value == action.value:
                    return True
            elif entry.type == PolicyEntryType.COMMAND.value:
                cmd = str(details.get("command", "")).lower()
                if cmd.startswith(entry.value.lower()):
                    return True
            elif entry.type == PolicyEntryType.PATTERN.value:
                try:
                    if re.search(entry.value, json.dumps(details, ensure_ascii=False), re.IGNORECASE):
                        return True
                except re.error:
                    continue
        return False

    # ── 持久化（settings.yaml computer_control 键） ──

    def _persist(self) -> None:
        if not self._persist_enabled:
            return
        try:
            from config.persona_loader import load_settings, save_settings
            settings = load_settings() or {}
            cc = settings.setdefault("computer_control", {})
            cc["mode"] = self._mode.value
            cc["whitelist"] = [e.to_dict() for e in self._whitelist.values()]
            cc["blacklist"] = [e.to_dict() for e in self._blacklist.values()]
            cc["custom_rules"] = dict(self._custom_rules)
            save_settings(settings)
        except Exception as e:
            logger.warning("持久化电脑操控策略失败: %s", e)

    def _load_persisted(self) -> None:
        try:
            from config.persona_loader import load_settings
            settings = load_settings() or {}
            cc = settings.get("computer_control") or {}
            mode = cc.get("mode")
            if mode and mode in {m.value for m in ControlMode}:
                self._mode = ControlMode(mode)
            for raw in cc.get("whitelist", []):
                entry = self._entry_from_dict(raw)
                if entry:
                    self._whitelist[entry.id] = entry
            for raw in cc.get("blacklist", []):
                entry = self._entry_from_dict(raw)
                if entry:
                    self._blacklist[entry.id] = entry
            rules = cc.get("custom_rules") or {}
            for k, v in rules.items():
                if v in {Decision.ALLOW.value, Decision.APPROVE.value, Decision.BLOCK.value}:
                    self._custom_rules[k] = v
        except Exception as e:
            logger.warning("加载电脑操控策略失败: %s", e)

    @staticmethod
    def _entry_from_dict(raw: dict) -> Optional[PolicyEntry]:
        try:
            return PolicyEntry(
                id=str(raw.get("id") or f"import_{uuid.uuid4().hex[:8]}"),
                type=str(raw.get("type", PolicyEntryType.ACTION.value)),
                value=str(raw.get("value", "")),
                note=str(raw.get("note", "")),
                created_at=float(raw.get("created_at", time.time())),
            )
        except Exception:
            return None

    def to_dict(self) -> dict:
        """策略快照（供 /api/computer_control/policy 使用）"""
        return {
            "mode": self._mode.value,
            "whitelist": self.get_whitelist(),
            "blacklist": self.get_blacklist(),
            "custom_rules": dict(self._custom_rules),
        }


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
    - 系统危险命令黑名单（不可绕过）
    - shell 元字符拒绝（管道/重定向/命令链）
    - 超时保护
    - 输出截断
    - 工作目录限制

    权限裁决（白名单/审批）由上层 AccessPolicy 负责，本类只做硬性安全闸。
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

    def execute(self, command: str, cwd: Optional[str] = None) -> ControlResult:
        """执行 shell 命令（安全实现）。

        危险命令与 shell 元字符在进入 subprocess 前被硬性拒绝；
        白名单/审批裁决由上层 AccessPolicy 完成。
        """
        # 危险检查（系统硬闸）
        is_danger, issues = self.is_dangerous(command)
        if is_danger:
            return ControlResult(
                success=False,
                action=ControlAction.SHELL_CMD.value,
                error=f"命令被阻止（危险）: {'; '.join(issues)}",
                data={"command": command[:100], "blocked_reason": issues},
            )

        # ── shell 元字符拒绝 ──
        shell_meta_chars = {"|", ">", "<", "&", ";"}
        if any(c in command for c in shell_meta_chars):
            return ControlResult(
                success=False,
                action=ControlAction.SHELL_CMD.value,
                error=(
                    "命令包含管道/重定向/命令链接符号，"
                    "请拆分为多个独立的简单命令分步执行"
                ),
                data={
                    "command": command[:100],
                    "rejected_reason": "shell_meta_characters_detected",
                },
            )

        try:
            work_dir = cwd or self.default_cwd
            is_windows = os.name == "nt"

            if is_windows:
                # Windows: 很多命令是 cmd.exe 内置的（echo/dir/copy 等），
                # 必须用 shell=True 才能找到。安全由前面的白名单+危险检查保证。
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
            else:
                # Unix: 继续用 shell=False + shlex.split 更安全
                cmd_parts = shlex.split(command)
                result = subprocess.run(
                    cmd_parts,
                    shell=False,
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
        mode: ControlMode = ControlMode.MANUAL,
        audit_log_dir: str = "data/audit",
        shell_timeout: int = 30,
        persist: bool = True,
    ):
        self.permission = AccessPolicy(mode, persist=persist)
        self.audit = AuditLogger(audit_log_dir)

        self.screenshot = ScreenshotCapturer()
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.shell = RestrictedShell(timeout=shell_timeout)
        self.windows = WindowManager()
        self.uia = UIAController()
        # 将受限 shell 注入策略引擎，供系统危险命令硬闸裁决
        self.permission._shell = self.shell

        self._pending_approvals: dict[str, dict] = {}

    # ---- 模式管理 ----

    def set_mode(self, mode: ControlMode) -> None:
        """设置权限模式"""
        self.permission.set_mode(mode)

    @property
    def mode(self) -> ControlMode:
        return self.permission.mode

    @property
    def policy(self) -> AccessPolicy:
        """访问策略引擎（黑白名单 / 自定义规则）"""
        return self.permission

    # ---- 内部：统一权限闸门 ----

    def _gate(self, action: ControlAction, details: Optional[dict] = None
              ) -> Optional[ControlResult]:
        """统一权限闸门。

        裁决链（AccessPolicy）：
          系统危险硬闸 → 用户黑名单 → 用户白名单 → 模式裁决

        Returns:
            None 表示放行；否则返回需要返回给调用方的 ControlResult
            （blocked / needs_approval）。
        """
        decision, reason = self.permission.decide(action, details or {})
        if decision == Decision.ALLOW:
            return None
        if decision == Decision.BLOCK:
            return ControlResult(
                success=False,
                action=action.value,
                error=f"操作被拦截: {reason}",
                data={"reason": reason, "blocked": True},
            )
        # APPROVE → 创建审批请求（推送到对话框审批卡片）
        call_id = self.request_approval(action, details or {}, description=reason)
        return ControlResult(
            success=False,
            action=action.value,
            error="需要用户审批",
            data={"call_id": call_id, "needs_approval": True, "reason": reason},
        )

    def _audit(self, action: ControlAction, details: dict,
               result: str, user_approved: bool = False) -> None:
        """记录审计"""
        risk = ACTION_RISK_MAP.get(action, RiskLevel.MEDIUM)
        entry = AuditLogEntry(
            action=action.value,
            risk_level=risk.value,
            permission_level=self.permission.mode.value,
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
        gate = self._gate(action, {"region": region})
        if gate is not None:
            self._audit(action, {"region": region},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.screenshot.capture(region)
        self._audit(action, {"region": region, "path": result.data.get("path", "")},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- 鼠标 ----

    def mouse_move(self, x: int, y: int, duration: float = 0.2) -> ControlResult:
        """移动鼠标"""
        action = ControlAction.MOUSE_MOVE
        gate = self._gate(action, {"x": x, "y": y})
        if gate is not None:
            self._audit(action, {"x": x, "y": y},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.mouse.move(x, y, duration)
        self._audit(action, {"x": x, "y": y},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def mouse_click(self, x: Optional[int] = None, y: Optional[int] = None,
                    button: str = "left", clicks: int = 1) -> ControlResult:
        """鼠标点击"""
        action = ControlAction.MOUSE_CLICK
        details = {"x": x, "y": y, "button": button, "clicks": clicks}
        gate = self._gate(action, details)
        if gate is not None:
            self._audit(action, details,
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.mouse.click(x, y, button, clicks)
        self._audit(action, details,
                    "success" if result.success else f"failed: {result.error}")
        return result

    def mouse_scroll(self, clicks: int) -> ControlResult:
        """滚轮"""
        action = ControlAction.MOUSE_SCROLL
        gate = self._gate(action, {"clicks": clicks})
        if gate is not None:
            self._audit(action, {"clicks": clicks},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.mouse.scroll(clicks)
        self._audit(action, {"clicks": clicks},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- 键盘 ----

    def key_press(self, key: str) -> ControlResult:
        """按键"""
        action = ControlAction.KEY_PRESS
        gate = self._gate(action, {"key": key})
        if gate is not None:
            self._audit(action, {"key": key},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.keyboard.press(key)
        self._audit(action, {"key": key},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def type_text(self, text: str) -> ControlResult:
        """输入文本"""
        action = ControlAction.KEY_TYPE
        gate = self._gate(action, {"text_length": len(text)})
        if gate is not None:
            self._audit(action, {"text_length": len(text)},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.keyboard.type_text(text)
        self._audit(action, {"text_length": len(text)},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def hotkey(self, *keys: str) -> ControlResult:
        """快捷键"""
        action = ControlAction.KEY_PRESS
        gate = self._gate(action, {"keys": list(keys)})
        if gate is not None:
            self._audit(action, {"keys": list(keys)},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.keyboard.hotkey(*keys)
        self._audit(action, {"keys": list(keys)},
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- Shell ----

    def shell_execute(self, command: str, cwd: Optional[str] = None) -> ControlResult:
        """执行 shell 命令"""
        action = ControlAction.SHELL_CMD
        details = {"command": command[:200], "cwd": cwd}
        gate = self._gate(action, details)
        if gate is not None:
            self._audit(action, details,
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.shell.execute(command, cwd)
        self._audit(action, details,
                    "success" if result.success else f"failed: {result.error}")
        return result

    # ---- UIA ----

    def uia_action(self, action_type: str, params: dict | None = None) -> ControlResult:
        """执行 UIA 操作（list_controls / click）。"""
        action = ControlAction.UIA_ACTION
        params = params or {}
        details = {"action_type": action_type, "params": params}
        gate = self._gate(action, details)
        if gate is not None:
            self._audit(action, details,
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        try:
            if action_type == "list_controls":
                result = self.uia.list_controls(title=params.get("window_title") or params.get("title"))
            elif action_type == "click":
                result = self.uia.click_control(params.get("control_name", ""))
            elif action_type in ("get_text", "set_value", "invoke", "select"):
                return ControlResult(
                    success=False,
                    action=action.value,
                    error=f"UIA 操作暂不支持: {action_type}（仅支持 list_controls / click）",
                )
            else:
                return ControlResult(
                    success=False,
                    action=action.value,
                    error=f"未知 UIA 操作: {action_type}",
                )
            self._audit(action, details,
                        "success" if result.success else f"failed: {result.error}")
            return result
        except Exception as e:
            err = ControlResult(success=False, action=action.value, error=str(e))
            self._audit(action, details, f"error: {e}")
            return err

    # ---- 窗口 ----

    def list_windows(self) -> ControlResult:
        """列出窗口"""
        action = ControlAction.WINDOW_INFO
        gate = self._gate(action, {})
        if gate is not None:
            self._audit(action, {},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.windows.list_windows()
        self._audit(action, {"count": result.data.get("count", 0)},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def focus_window(self, hwnd: int) -> ControlResult:
        """聚焦窗口"""
        action = ControlAction.WINDOW_FOCUS
        gate = self._gate(action, {"hwnd": hwnd})
        if gate is not None:
            self._audit(action, {"hwnd": hwnd},
                        "blocked" if gate.data.get("blocked") else "pending_approval")
            return gate

        result = self.windows.focus_window(hwnd)
        self._audit(action, {"hwnd": hwnd},
                    "success" if result.success else f"failed: {result.error}")
        return result

    def _find_window_by_title(self, title: str) -> int:
        """Find a window handle by partial title match."""
        try:
            result = self.windows.list_windows()
            if result and result.data:
                for w in result.data.get("windows", []):
                    if title.lower() in w.get("title", "").lower():
                        return w.get("hwnd", 0)
        except Exception:
            pass
        return 0

    # ---- 审计查询 ----

    def get_audit_logs(self, limit: int = 50) -> list[dict]:
        """获取审计日志"""
        return self.audit.get_recent(limit)

    # ---- 状态查询 ----

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "mode": self.permission.mode.value,
            "whitelist_count": len(self.permission.get_whitelist()),
            "blacklist_count": len(self.permission.get_blacklist()),
            "has_pillow": self.screenshot._has_pillow,
            "has_pyautogui": self.mouse._has_pyautogui,
            "has_pywinauto": self.uia.available,
            "screen_size": self.screenshot.get_screen_size(),
            "mouse_position": self.mouse.get_position(),
            "pending_approvals": len(self._pending_approvals),
        }

    # ---- 审批流程 ----

    def get_pending_approvals(self) -> list[dict]:
        """获取待审批列表"""
        result = []
        for call_id, entry in self._pending_approvals.items():
            action = entry.get("action")
            action_name = action.value if hasattr(action, "value") else str(action)
            risk = ACTION_RISK_MAP.get(action, RiskLevel.MEDIUM) if hasattr(action, "value") else RiskLevel.MEDIUM
            result.append({
                "id": call_id,
                "action": action_name,
                "risk_level": risk.value if hasattr(risk, "value") else str(risk),
                "params": entry.get("params", {}),
                "description": entry.get("description", ""),
                "created_at": entry.get("created_at", time.time()),
            })
        return result

    def request_approval(
        self,
        action: ControlAction,
        params: dict,
        description: str = "",
    ) -> str:
        """发起审批请求，返回审批 ID"""
        import uuid
        call_id = f"appr_{uuid.uuid4().hex[:12]}"
        self._pending_approvals[call_id] = {
            "action": action,
            "params": params,
            "description": description,
            "created_at": time.time(),
            "status": "pending",
            "result": None,
        }
        logger.info("审批请求已创建: %s (%s)", call_id, action.value)

        # v13.0: 推送审批请求事件到前端
        try:
            from core.chat_events import emit
            risk = ACTION_RISK_MAP.get(action, RiskLevel.MEDIUM)
            emit("computer_control_approval_requested",
                 id=call_id,
                 action=action.value,
                 risk_level=risk.value,
                 params=params,
                 description=description)
        except Exception:
            pass

        return call_id

    def approve_action(self, call_id: str, whitelist: bool = False) -> bool:
        """批准操作并执行。

        Args:
            call_id: 审批请求 ID
            whitelist: 是否将该操作加入白名单（后续自动放行）
        """
        entry = self._pending_approvals.get(call_id)
        if not entry:
            return False

        entry["status"] = "approved"
        action = entry.get("action")
        params = entry.get("params", {})

        # 放行并入白名单
        if whitelist:
            try:
                self.permission.add_whitelist(
                    PolicyEntryType.ACTION.value,
                    action.value,
                    note="审批放行时加入",
                )
            except Exception as e:
                logger.warning("审批加入白名单失败: %s", e)

        # 执行操作（user_approved 绕过闸门，避免二次审批死循环）
        result = None
        try:
            result = self._execute_action(action, params, user_approved=True)
            entry["result"] = result
            self._audit(
                action, params,
                "success" if result.success else f"failed: {result.error}",
                user_approved=True,
            )
        except Exception as e:
            result = ControlResult(
                success=False,
                action=action.value if hasattr(action, "value") else str(action),
                error=str(e),
            )
            entry["result"] = result
            self._audit(action, params, f"error: {e}", user_approved=True)

        # 推送审批结果到对话框审批卡片
        self._emit_approval_updated(call_id, "approved", whitelist=whitelist,
                                    result=result.to_dict() if result else None)

        # 清理（保留一小段时间供查询；用守护线程，避免同步上下文无 event loop 崩溃）
        import threading
        threading.Timer(
            30.0,
            lambda: self._pending_approvals.pop(call_id, None),
        ).start()

        return True

    def reject_action(self, call_id: str, blacklist: bool = False) -> bool:
        """拒绝操作。

        Args:
            call_id: 审批请求 ID
            blacklist: 是否将该操作加入黑名单（后续直接拦截）
        """
        entry = self._pending_approvals.get(call_id)
        if not entry:
            return False

        entry["status"] = "rejected"
        action = entry.get("action")
        params = entry.get("params", {})

        # 拒绝并入黑名单
        if blacklist:
            try:
                self.permission.add_blacklist(
                    PolicyEntryType.ACTION.value,
                    action.value,
                    note="审批拒绝时加入",
                )
            except Exception as e:
                logger.warning("审批加入黑名单失败: %s", e)

        self._audit(action, params, "rejected by user", user_approved=False)
        self._emit_approval_updated(call_id, "rejected", blacklist=blacklist)

        # 清理（守护线程，避免同步上下文无 event loop 崩溃）
        import threading
        threading.Timer(
            30.0,
            lambda: self._pending_approvals.pop(call_id, None),
        ).start()

        return True

    def _emit_approval_updated(self, call_id: str, status: str,
                               whitelist: bool = False, blacklist: bool = False,
                               result: Optional[dict] = None) -> None:
        """推送审批结果事件到前端对话框审批卡片。"""
        try:
            from core.chat_events import emit
            emit("computer_control_approval_updated",
                 id=call_id,
                 status=status,
                 whitelist=whitelist,
                 blacklist=blacklist,
                 result=result)
        except Exception:
            pass

    # ── Resource cleanup ──
    async def cleanup(self) -> None:
        """Release all resources (subprocesses, temp files, hooks).

        ZERO-BREAKING: new public method, does not alter existing pathways.
        Called from Companion.stop() to ensure clean shutdown.
        """
        # Cancel any pending approvals
        self._pending_approvals.clear()

        # Clean up screenshot temp directory
        try:
            import shutil, tempfile
            tmp_dir = Path(tempfile.gettempdir()) / "aerie_screenshots"
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            logger.debug("cleanup: screenshot temp dir already cleaned")

    def _execute_action(self, action: ControlAction, params: dict,
                        user_approved: bool = False) -> ControlResult:
        """根据 action 类型执行对应操作。

        Args:
            action: 操作类型
            params: 操作参数
            user_approved: True 表示来自用户审批放行，直接调用底层组件，
                绕过权限闸门（避免审批通过后二次弹窗死循环）。
        """
        if action == ControlAction.SCREENSHOT:
            region = params.get("region")
            if user_approved:
                return self.screenshot.capture(region)
            return self.take_screenshot(region)
        elif action == ControlAction.MOUSE_MOVE:
            if user_approved:
                return self.mouse.move(params.get("x", 0), params.get("y", 0),
                                       params.get("duration", 0.2))
            return self.mouse_move(
                params.get("x", 0),
                params.get("y", 0),
                params.get("duration", 0.2),
            )
        elif action == ControlAction.MOUSE_CLICK:
            if user_approved:
                return self.mouse.click(
                    params.get("x"), params.get("y"),
                    params.get("button", "left"), params.get("clicks", 1),
                )
            return self.mouse_click(
                params.get("x"),
                params.get("y"),
                params.get("button", "left"),
                params.get("clicks", 1),
            )
        elif action == ControlAction.MOUSE_SCROLL:
            if user_approved:
                return self.mouse.scroll(params.get("clicks", 1))
            return self.mouse_scroll(params.get("clicks", 1))
        elif action == ControlAction.KEY_PRESS:
            if user_approved:
                return self.keyboard.press(params.get("key", ""))
            return self.key_press(params.get("key", ""))
        elif action == ControlAction.KEY_TYPE:
            if user_approved:
                return self.keyboard.type_text(params.get("text", ""))
            return self.type_text(params.get("text", ""))
        elif action == ControlAction.SHELL_CMD:
            if user_approved:
                return self.shell.execute(params.get("command", ""), params.get("cwd"))
            return self.shell_execute(params.get("command", ""), params.get("cwd"))
        elif action == ControlAction.WINDOW_INFO:
            if user_approved:
                return self.windows.list_windows()
            return self.list_windows()
        elif action == ControlAction.WINDOW_FOCUS:
            title = params.get("title", "")
            hwnd = self._find_window_by_title(title) if title else 0
            if user_approved:
                return self.windows.focus_window(hwnd)
            return self.focus_window(hwnd)
        elif action == ControlAction.UIA_ACTION:
            return self.uia_action(
                params.get("action_type", ""),
                params.get("params", {}),
            )
        else:
            return ControlResult(
                success=False,
                action=action.value if hasattr(action, "value") else str(action),
                error=f"unknown action: {action}",
            )

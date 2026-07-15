"""Pinguo Design Tokens

Apple Human Interface Guidelines 风格，克制、优雅。
品牌色：System Blue #007AFF
支持 Light / Dark 双模式。
"""

from __future__ import annotations
from typing import Dict

# ===== 基础调色板 =====

BRAND = {
    50:  "#e8f2ff",
    100: "#cfe5ff",
    200: "#9fcbff",
    300: "#66abff",
    400: "#2e8dff",
    500: "#007aff",
    600: "#0064d6",
    700: "#004fad",
    800: "#003b82",
    900: "#00275a",
}

BACKGROUND = {
    50:  "#ffffff",
    100: "#f7f7fa",
    200: "#f2f2f7",
    300: "#e5e5ea",
    400: "#d1d1d6",
    500: "#aeaeb2",
    600: "#8e8e93",
    700: "#3a3a3c",
    800: "#1c1c1e",
    900: "#000000",
}

TEXT = {
    50:  "#f5f5f7",
    100: "#e3e3e8",
    200: "#c7c7cc",
    300: "#aeaeb2",
    400: "#8e8e93",
    500: "#6e6e73",
    600: "#48484a",
    700: "#3c3c43",
    800: "#1d1d1f",
    900: "#000000",
}

ICON = {
    50:  "#f5f5f7",
    100: "#e5e5ea",
    200: "#d1d1d6",
    300: "#c7c7cc",
    400: "#aeaeb2",
    500: "#8e8e93",
    600: "#6e6e73",
    700: "#48484a",
    800: "#2c2c2e",
    900: "#1d1d1f",
}

STATE_SUCCESS = "#34c759"
STATE_SUCCESS_DARK = "#30d158"
STATE_SUCCESS_SURFACE = "#e9f9ee"
STATE_SUCCESS_FG = "#ffffff"

STATE_ERROR = "#ff3b30"
STATE_ERROR_DARK = "#ff453a"
STATE_ERROR_SURFACE = "#ffecea"
STATE_ERROR_FG = "#ffffff"

# ===== Light 模式语义 Token =====

LIGHT_TOKENS: Dict[str, str] = {
    "background": BACKGROUND[50],
    "foreground": TEXT[800],
    "card": BACKGROUND[50],
    "card_foreground": TEXT[800],
    "popover": BACKGROUND[50],
    "popover_foreground": TEXT[900],

    "primary": BRAND[500],
    "primary_foreground": BACKGROUND[50],
    "secondary": BACKGROUND[200],
    "secondary_foreground": TEXT[800],
    "muted": BACKGROUND[200],
    "muted_foreground": TEXT[400],
    "accent": BACKGROUND[100],
    "accent_foreground": TEXT[800],
    "destructive": STATE_ERROR,
    "destructive_foreground": STATE_ERROR_FG,
    "success": STATE_SUCCESS,
    "success_foreground": STATE_SUCCESS_FG,
    "border": BACKGROUND[300],
    "input": BACKGROUND[400],
    "ring": BRAND[500],

    "icon": ICON[900],
    "icon_muted": ICON[500],
    "icon_white": "#ffffff",
}

# ===== Dark 模式语义 Token =====

DARK_TOKENS: Dict[str, str] = {
    "background": BACKGROUND[900],
    "foreground": TEXT[50],
    "card": BACKGROUND[800],
    "card_foreground": TEXT[50],
    "popover": BACKGROUND[700],
    "popover_foreground": TEXT[50],

    "primary": BRAND[400],
    "primary_foreground": BACKGROUND[900],
    "secondary": BACKGROUND[800],
    "secondary_foreground": TEXT[50],
    "muted": BACKGROUND[800],
    "muted_foreground": TEXT[400],
    "accent": BACKGROUND[700],
    "accent_foreground": TEXT[50],
    "destructive": STATE_ERROR_DARK,
    "destructive_foreground": STATE_ERROR_FG,
    "success": STATE_SUCCESS_DARK,
    "success_foreground": STATE_SUCCESS_FG,
    "border": BACKGROUND[700],
    "input": BACKGROUND[700],
    "ring": BRAND[400],

    "icon": ICON[50],
    "icon_muted": ICON[500],
    "icon_white": "#ffffff",
}

# ===== 间距和圆角 =====

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 20,
    "2xl": 24,
}

RADIUS = {
    "sm": 6,
    "md": 8,
    "lg": 10,
    "xl": 12,
    "2xl": 16,
    "full": 9999,
}

# ===== 阴影 (Light) =====
SHADOWS_LIGHT = {
    "sm":   "0 1px 2px 0 rgba(0,0,0,0.05), 0 1px 3px -1px rgba(0,0,0,0.05)",
    "md":   "0 4px 8px -2px rgba(0,0,0,0.06), 0 2px 4px -2px rgba(0,0,0,0.05)",
    "lg":   "0 8px 24px -8px rgba(0,0,0,0.08), 0 4px 8px -4px rgba(0,0,0,0.05)",
    "xl":   "0 16px 40px -10px rgba(0,0,0,0.10), 0 8px 16px -8px rgba(0,0,0,0.06)",
    "2xl":  "0 24px 64px -12px rgba(0,0,0,0.12)",
}

SHADOWS_DARK = {
    "sm":   "0 1px 2px 0 rgba(0,0,0,0.36), 0 1px 3px -1px rgba(0,0,0,0.36)",
    "md":   "0 4px 8px -2px rgba(0,0,0,0.44), 0 2px 4px -2px rgba(0,0,0,0.36)",
    "lg":   "0 8px 24px -8px rgba(0,0,0,0.50), 0 4px 8px -4px rgba(0,0,0,0.40)",
    "xl":   "0 16px 40px -10px rgba(0,0,0,0.55), 0 8px 16px -8px rgba(0,0,0,0.44)",
    "2xl":  "0 24px 64px -12px rgba(0,0,0,0.60)",
}

# ===== 字体 =====
FONT_FAMILY = '"Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif'
FONT_MONO = 'Cascadia Code, JetBrains Mono, Consolas, monospace'

FONT_SIZES = {
    "2xs": 10,
    "xs": 11,
    "sm": 12,
    "base": 13,
    "lg": 15,
    "xl": 17,
    "2xl": 20,
}

# ===== 动效 (微交互) =====

MOTION = {
    "duration_fast":   150,   # 输入框聚焦、按钮悬停
    "duration_normal": 220,   # 窗口淡入淡出、消息滑入
    "duration_slow":   320,   # 卡片展开、抽屉
    "easing_standard": "OutCubic",   # 通用：自然减速
    "easing_enter":    "OutCubic",   # 进入：轻快
    "easing_exit":     "InCubic",    # 退出：快速收
}


def get_tokens(dark: bool = False) -> Dict[str, str]:
    """获取当前主题的语义 Token"""
    return DARK_TOKENS if dark else LIGHT_TOKENS


def token(dark: bool, key: str) -> str:
    """快捷获取单个 Token"""
    return DARK_TOKENS[key] if dark else LIGHT_TOKENS[key]

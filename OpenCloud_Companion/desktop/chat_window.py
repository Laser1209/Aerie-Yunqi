"""对话窗口 - Pinguo Design System 重构版

PyQt6 对话面板，遵循 Pinguo Design System 设计规范。
- 毛玻璃效果面板（440×660px 圆角 frameless 窗口）
- 头像 + 气泡式消息（AI 左对齐 / 用户右对齐）
- 人格优先的任务执行展示（摘要气泡 + 可折叠 PowerShell 代码块）
- 思考点动画（3 个弹跳圆点）
- 语音 + 文字输入栏
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Optional, Callable, Awaitable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QFrame,
    QSizePolicy, QApplication,
)
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QLinearGradient, QRegion,
    QPainterPath, QKeyEvent, QFontMetrics, QPixmap, QBitmap,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QRectF,
    pyqtProperty, QSize, QEvent,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from loguru import logger

from desktop.design_tokens import (
    BRAND, TEXT, BACKGROUND, STATE_SUCCESS, STATE_ERROR,
    FONT_FAMILY, FONT_MONO, FONT_SIZES, RADIUS, SPACING, MOTION,
)

# ---------------------------------------------------------------------------
# 颜色快捷引用
# ---------------------------------------------------------------------------

C_BRAND_50   = BRAND[50]
C_BRAND_100  = BRAND[100]
C_BRAND_200  = BRAND[200]
C_BRAND_300  = BRAND[300]
C_BRAND_400  = BRAND[400]
C_BRAND_500  = BRAND[500]
C_BRAND_600  = BRAND[600]
C_BRAND_700  = BRAND[700]

C_BG_50      = BACKGROUND[50]
C_BG_100     = BACKGROUND[100]
C_BG_200     = BACKGROUND[200]
C_BG_300     = BACKGROUND[300]
C_BG_400     = BACKGROUND[400]
C_BG_700     = BACKGROUND[700]
C_BG_800     = BACKGROUND[800]

C_TEXT_200   = TEXT[200]
C_TEXT_400   = TEXT[400]
C_TEXT_600   = TEXT[600]
C_TEXT_800   = TEXT[800]

C_GREEN      = STATE_SUCCESS
C_ERROR      = STATE_ERROR

# ---------------------------------------------------------------------------
# 代码语法高亮规则
# ---------------------------------------------------------------------------

# 常见 PowerShell 动词-名词 Cmdlet
_PS_CMDLETS = {
    "Get-ChildItem", "Get-Item", "Get-Content", "Get-Process", "Get-Service",
    "Set-Item", "Set-Content", "Set-Location", "Set-ExecutionPolicy",
    "New-Item", "Remove-Item", "Move-Item", "Copy-Item", "Rename-Item",
    "Invoke-Item", "Invoke-WebRequest", "Invoke-RestMethod",
    "Start-Process", "Stop-Process", "Wait-Process",
    "Write-Output", "Write-Host", "Write-Error", "Write-Warning",
    "Read-Host", "Out-File", "Export-Csv", "Import-Csv",
    "ConvertTo-Json", "ConvertFrom-Json",
    "ForEach-Object", "Where-Object", "Select-Object", "Sort-Object",
    "Group-Object", "Measure-Object", "Tee-Object",
    "Test-Path", "Split-Path", "Join-Path", "Resolve-Path",
    "Add-Content", "Clear-Content",
    "Compress-Archive", "Expand-Archive",
    "Get-Date", "Set-Date",
    "Get-Help", "Get-Command", "Get-Module", "Import-Module",
    "Format-List", "Format-Table", "Format-Wide",
    "Out-Null", "Out-String", "Out-GridView",
    "Start-Sleep", "Clear-Host",
    "mkdir", "rm", "cp", "mv", "ls", "dir", "cd", "pwd", "cat", "echo",
    "ni", "ri", "mi", "ci", "gci", "gi", "gc", "gp", "gs",
}

# 常见 PowerShell 参数前缀（含别名前缀如 -Path / -Force / -Recurse 等）
_KNOWN_PARAMS = {
    "-Path", "-LiteralPath", "-Destination", "-ItemType", "-Name",
    "-Value", "-Force", "-Recurse", "-Filter", "-Include", "-Exclude",
    "-WhatIf", "-Confirm", "-Verbose", "-Debug", "-ErrorAction",
    "-WarningAction", "-InformationAction", "-ErrorVariable",
    "-WarningVariable", "-OutVariable", "-OutBuffer", "-PipelineVariable",
    "-PassThru", "-NoClobber", "-Encoding", "-Delimiter", "-Raw",
    "-Head", "-Tail", "-TotalCount", "-First", "-Last", "-Skip",
    "-Property", "-ExpandProperty", "-Unique", "-CaseSensitive",
    "-Descending", "-Ascending", "-Top", "-Bottom",
    "-ComputerName", "-Credential", "-UseSSL",
    "-InputObject", "-ArgumentList", "-Begin", "-Process", "-End",
    "-MemberType", "-Static", "-View", "-Split", "-Join",
    "-File", "-NoNewline", "-NoTypeInformation", "-Append",
    "-Width", "-Height", "-Depth", "-Compress",
    "-As", "-TypeName", "-AllowClobber", "-Scope",
    "-NoProfile", "-NonInteractive", "-NoLogo", "-File",
    "-Version", "-Command",
}

# 管道符号等
_PIPE_SYMBOLS = {"|", ";", "&&", "||"}


def _highlight_ps_line(line: str) -> str:
    """将单行 PowerShell 命令转换为带语法高亮的 HTML。"""
    escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 1. 标注引号字符串 (单引号 / 双引号)
    parts_orange: list[tuple[int, int, str]] = []
    for m in re.finditer(r""""(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""", escaped):
        parts_orange.append((m.start(), m.end(), m.group()))

    # 2. 构建带标记的 token 列表
    def _classify(word: str) -> str:
        if word in _PIPE_SYMBOLS:
            return f'<span style="color:#af52de;">{word}</span>'
        if word in _KNOWN_PARAMS:
            return f'<span style="color:#af52de;">{word}</span>'
        if word in _PS_CMDLETS:
            return f'<span style="color:{C_BRAND_300};">{word}</span>'
        return word

    # Tokenize
    tokens: list[str] = []
    i = 0
    in_string = False
    while i < len(escaped):
        # Check if at string region
        matched = False
        for s, e, content in parts_orange:
            if i == s:
                tokens.append(
                    f'<span style="color:#ff9500;">{content}</span>'
                )
                i = e
                matched = True
                break
        if matched:
            continue

        if escaped[i] == ' ' or escaped[i] == '\t':
            tokens.append(escaped[i])
            i += 1
            continue

        # Gather a word
        j = i
        while j < len(escaped) and escaped[j] not in (' ', '\t'):
            j += 1
        word = escaped[i:j]
        tokens.append(_classify(word))
        i = j

    return "".join(tokens)


# ---------------------------------------------------------------------------
# 辅助组件
# ---------------------------------------------------------------------------

class _Avatar(QWidget):
    """圆形头像，带渐变背景和在线绿点。"""

    def __init__(self, size: int = 34, show_dot: bool = False, parent=None):
        super().__init__(parent)
        self._size = size
        self._show_dot = show_dot
        self.setFixedSize(size + (8 if show_dot else 0), size + (8 if show_dot else 0))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        offset = 4 if self._show_dot else 0
        cx, cy = offset + self._size / 2, offset + self._size / 2
        r = self._size / 2

        # 渐变背景
        grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        grad.setColorAt(0.0, QColor(C_BRAND_100))
        grad.setColorAt(1.0, QColor(C_BRAND_300))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRect(offset, offset, self._size, self._size))

        # 人物图标（简笔画 person SVG）
        p.setPen(QColor(C_BRAND_600))
        p.setBrush(QColor(C_BRAND_600))
        head_r = 3.5
        body_top = offset + self._size * 0.58
        head_cx = cx
        head_cy = offset + self._size * 0.32
        p.drawEllipse(
            int(head_cx - head_r), int(head_cy - head_r),
            int(head_r * 2), int(head_r * 2),
        )
        # 身体弧线
        body_path = QPainterPath()
        body_w = self._size * 0.32
        body_h = self._size * 0.36
        body_path.moveTo(cx - body_w, body_top + body_h)
        body_path.cubicTo(
            cx - body_w, body_top - body_h * 0.1,
            cx + body_w, body_top - body_h * 0.1,
            cx + body_w, body_top + body_h,
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(body_path)

        # 在线绿点
        if self._show_dot:
            dot_size = 7
            dot_x = offset + self._size - dot_size + 2
            dot_y = offset + self._size - dot_size + 2
            # glow
            glow_grad = QLinearGradient(dot_x, dot_y, dot_x + dot_size, dot_y + dot_size)
            glow_grad.setColorAt(0.0, QColor(52, 199, 89, 60))
            glow_grad.setColorAt(1.0, QColor(52, 199, 89, 0))
            p.setBrush(glow_grad)
            p.drawEllipse(
                int(dot_x - 2), int(dot_y - 2),
                int(dot_size + 4), int(dot_size + 4),
            )
            p.setBrush(QColor(C_GREEN))
            p.drawEllipse(int(dot_x), int(dot_y), dot_size, dot_size)


class _BubbleLabel(QLabel):
    """气泡文本标签，支持圆角背景和自适应宽度。"""

    def __init__(
        self,
        bg_color: str,
        text_color: str,
        border_radius: str = "16px",
        extra_style: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        # 允许 Label 根据内容增长，但不超过最大宽度
        self.setMaximumWidth(280)
        self.setMinimumWidth(40)

        font = QFont(FONT_FAMILY)
        font.setPixelSize(int(FONT_SIZES["base"] * 1.04))  # ~13.5px
        self.setFont(font)

        self.setContentsMargins(14, 10, 14, 10)

        self.setStyleSheet(
            f"""
            _BubbleLabel {{
                background-color: {bg_color};
                color: {text_color};
                border-radius: {border_radius};
                padding: 10px 14px;
                line-height: 1.55;
                {extra_style}
            }}
            """
        )

    def set_text(self, text: str):
        """设置文本（支持 HTML）。"""
        self.setText(text)


class _TimeDivider(QLabel):
    """居中时间分隔线。"""

    def __init__(self, time_str: str, parent=None):
        super().__init__(time_str, parent)
        font = QFont(FONT_FAMILY)
        font.setPixelSize(11)
        self.setFont(font)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"color: {C_TEXT_400}; padding: 10px 0 6px;"
        )


class _CodeBlock(QFrame):
    """PowerShell 语法高亮代码块（深色背景）。"""

    def __init__(self, commands: list[str], cmd_count: int, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            _CodeBlock {{
                background-color: {C_BG_800};
                border-radius: 12px;
                margin-top: 6px;
            }}
            """
        )
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(2)

        mono_font = QFont(FONT_MONO)
        mono_font.setPixelSize(12)  # ~11.5 CSS px

        for cmd in commands:
            line = _highlight_ps_line(cmd)
            lbl = QLabel(
                f'<span style="color:{C_GREEN};">PS&gt; </span>{line}'
            )
            lbl.setFont(mono_font)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setStyleSheet(
                f"color: {C_TEXT_200}; font-family: '{FONT_MONO}';"
                f"font-size: 12px; line-height: 1.7; background: transparent;"
            )
            lbl.setWordWrap(False)
            layout.addWidget(lbl)

        # 底部居中标签
        footer = QLabel(f"小满执行了 {cmd_count} 条命令")
        footer_font = QFont(FONT_FAMILY)
        footer_font.setPixelSize(11)
        footer.setFont(footer_font)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(
            f"color: {C_TEXT_400}; margin-top: 8px; background: transparent;"
        )
        layout.addWidget(footer)


class _CollapsibleToggle(QPushButton):
    """折叠/展开技术细节按钮。"""

    def __init__(self, collapsed: bool = True, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed
        self._update_text()

        font = QFont(FONT_FAMILY)
        font.setPixelSize(12)
        self.setFont(font)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(
            f"""
            _CollapsibleToggle {{
                color: {C_TEXT_400};
                background: transparent;
                border: none;
                text-align: left;
                padding: 4px 0;
            }}
            _CollapsibleToggle:hover {{
                color: {TEXT[600]};
            }}
            """
        )

    def _update_text(self):
        if self._collapsed:
            self.setText("查看技术细节 ▾")
        else:
            self.setText("收起技术细节  ▴")

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def toggle(self):
        self._collapsed = not self._collapsed
        self._update_text()


class _ThinkingDots(QWidget):
    """思考中... 三个弹跳圆点动画。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 18)
        self._offsets = [0.0, 0.0, 0.0]

        # 分阶段延迟计时器
        self._timer = QTimer(self)
        self._timer.setInterval(70)  # ~14fps
        self._timer.timeout.connect(self._tick)
        self._phase = 0  # 0→100 循环
        self._playing = False

    def start_animation(self):
        self._playing = True
        self._phase = 0
        self._timer.start()
        self.show()

    def stop_animation(self):
        self._playing = False
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase = (self._phase + 5) % 700  # 700ms 为一个循环
        for i in range(3):
            t = (self._phase - i * 200) % 700
            if t < 280:
                # 弹起阶段: 0→280ms
                progress = t / 280.0
                # ease-out 曲线
                self._offsets[i] = -6.0 * (1.0 - (1.0 - progress) ** 3)
            elif t < 350:
                self._offsets[i] = 0.0
            else:
                self._offsets[i] = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dot_r = 3
        mid_y = self.height() / 2 + 2

        for i in range(3):
            cx = 7 + i * 13
            cy = mid_y + self._offsets[i]
            # 透明度随位置变化
            opacity = 1.0 - abs(self._offsets[i]) / 8.0
            opacity = max(0.3, min(1.0, opacity))
            color = QColor(C_BRAND_500)
            color.setAlphaF(opacity)
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(int(cx - dot_r), int(cy - dot_r), dot_r * 2, dot_r * 2)


# ---------------------------------------------------------------------------
# 消息行组件
# ---------------------------------------------------------------------------

class _MessageRow(QWidget):
    """一条消息行：头像 + 气泡。"""

    def __init__(
        self,
        role: str,
        text: str = "",
        parent=None,
    ):
        super().__init__(parent)
        is_user = role == "user"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 头像
        if is_user:
            avatar = _Avatar(size=32, show_dot=False)

            def _paint_user(ev, _self=avatar):
                p = QPainter(_self)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setBrush(QColor(C_BG_300))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(0, 0, 32, 32)
                p.setPen(QColor(TEXT[600]))
                p.setBrush(QColor(TEXT[600]))
                p.drawEllipse(11, 8, 10, 10)
                body_w = 7
                body_top = 20
                p.drawEllipse(
                    16 - body_w, body_top,
                    body_w * 2, body_w * 2 + 2,
                )
            avatar.paintEvent = _paint_user.__get__(avatar, _Avatar)
        else:
            avatar = _Avatar(size=32, show_dot=False)

        # 气泡
        if is_user:
            bubble = _BubbleLabel(
                bg_color=C_BRAND_500,
                text_color="#ffffff",
                border_radius="16px 16px 4px 16px",
            )
        else:
            bubble = _BubbleLabel(
                bg_color=C_BG_200,
                text_color=C_TEXT_800,
                border_radius="16px 16px 16px 4px",
            )

        if text:
            bubble.set_text(
                text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )

        # 组装
        if is_user:
            layout.addStretch()
            layout.addWidget(bubble)
            layout.addWidget(avatar)
        else:
            layout.addWidget(avatar)
            layout.addWidget(bubble)
            layout.addStretch()

        self._bubble = bubble
        self._avatar = avatar
        self._role = role
        self._is_user = is_user

    @property
    def bubble(self) -> _BubbleLabel:
        return self._bubble

    def slide_in(self) -> None:
        """从下方 16px 滑入（220ms OutCubic）。"""
        end_pos = self.pos()
        self.move(end_pos.x(), end_pos.y() + 16)
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(MOTION["duration_normal"])
        anim.setStartValue(self.pos())
        anim.setEndValue(end_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()


class _TaskResultRow(QWidget):
    """任务执行结果行：人格摘要气泡 + 可折叠技术细节。"""

    def __init__(
        self,
        summary: str,
        commands: list[str],
        cmd_count: int,
        parent=None,
    ):
        super().__init__(parent)

        vlayout = QVBoxLayout(self)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(4)

        # 外层水平布局：头像 + 内容
        hlayout = QHBoxLayout()
        hlayout.setContentsMargins(0, 0, 0, 0)
        hlayout.setSpacing(8)

        avatar = _Avatar(size=32, show_dot=False)
        hlayout.addWidget(avatar)

        # 内容列
        content_col = QVBoxLayout()
        content_col.setContentsMargins(0, 0, 0, 0)
        content_col.setSpacing(4)

        # 人格摘要气泡（BRAND[50] 背景 + 细边框）
        summary_bubble = QLabel(summary)
        summary_bubble.setWordWrap(True)
        summary_bubble.setTextFormat(Qt.TextFormat.RichText)
        summary_bubble.setMaximumWidth(280)
        font = QFont(FONT_FAMILY)
        font.setPixelSize(int(FONT_SIZES["base"] * 1.04))
        summary_bubble.setFont(font)
        summary_bubble.setContentsMargins(14, 10, 14, 10)
        summary_bubble.setStyleSheet(
            f"""
            background-color: {C_BRAND_50};
            color: {C_TEXT_800};
            border-radius: 16px 16px 16px 4px;
            border: 1px solid rgba(0,122,255,0.10);
            padding: 10px 14px;
            """
        )
        content_col.addWidget(summary_bubble)

        # 折叠切换按钮
        self._toggle = _CollapsibleToggle(collapsed=True)
        content_col.addWidget(self._toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        # 代码块（默认隐藏）
        self._code_block = _CodeBlock(commands, cmd_count)
        self._code_block.hide()
        content_col.addWidget(self._code_block)

        # 连接事件
        self._toggle.clicked.connect(self._on_toggle)

        hlayout.addLayout(content_col)
        hlayout.addStretch()
        vlayout.addLayout(hlayout)

        self._summary_bubble = summary_bubble

    def _on_toggle(self):
        self._toggle.toggle()
        self._code_block.setVisible(not self._toggle.collapsed)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class ChatWindow(QWidget):
    """Pinguo Design System 对话窗口。"""

    WINDOW_W = 440
    WINDOW_H = 660

    def __init__(
        self,
        companion_name: str = "小满",
        on_send: Optional[Callable[[str], Awaitable[str]]] = None,
    ):
        super().__init__()
        self._name = companion_name
        self._on_send = on_send
        self._thinking: Optional[_ThinkingDots] = None

        self.setWindowTitle(f"与 {companion_name} 对话")
        self.setFixedSize(self.WINDOW_W, self.WINDOW_H)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # QGraphicsDropShadowEffect 替代原 8 层 paintEvent 阴影（GPU 加速）
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)

        self._setup_ui()
        self._update_mask()
        self.show_welcome_back()

        # 微交互：淡入启动
        self._is_closing = False
        self.setWindowOpacity(0.0)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(MOTION["duration_normal"])
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.start()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """搭建完整 UI 布局。"""
        # 根布局（无边距，由子面板自行控制）
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 主面板容器 ──
        self._panel = QFrame(self)
        self._panel.setObjectName("chatPanel")
        self._panel.setStyleSheet(
            f"""
            #chatPanel {{
                background-color: rgba(255, 255, 255, 0.78);
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 0.50);
            }}
            """
        )
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # ── Header ──
        panel_layout.addWidget(self._build_header())

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            f"color: {C_BG_300}; max-height: 1px; margin: 0 0 0 0;"
        )
        panel_layout.addWidget(sep)

        # ── 消息滚动区 ──
        panel_layout.addWidget(self._build_messages_area(), stretch=1)

        # ── 分隔线 ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(
            f"color: {C_BG_300}; max-height: 1px; margin: 0;"
        )
        panel_layout.addWidget(sep2)

        # ── 输入栏 ──
        panel_layout.addWidget(self._build_input_area())

        root.addWidget(self._panel)

    def _build_header(self) -> QWidget:
        """构建头部：头像 + 名称 + 状态 + 最小化按钮。"""
        header = QWidget()
        header.setFixedHeight(64)
        header.setStyleSheet(
            f"padding: 16px 20px; background: transparent;"
        )

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)

        # 头像 + 在线绿点容器
        avatar_container = QWidget()
        avatar_container.setFixedSize(42, 42)
        # Custom paint for avatar+dot
        self._header_avatar = _Avatar(size=34, show_dot=True)
        avatar_inner = QHBoxLayout(avatar_container)
        avatar_inner.setContentsMargins(0, 0, 0, 4)
        avatar_inner.addWidget(self._header_avatar)

        layout.addWidget(avatar_container)

        # 名称 + 状态
        info = QVBoxLayout()
        info.setContentsMargins(0, 2, 0, 0)
        info.setSpacing(1)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_label = QLabel(self._name)
        name_font = QFont(FONT_FAMILY)
        name_font.setPixelSize(15)  # ~14.5px
        name_font.setWeight(QFont.Weight.DemiBold)
        name_label.setFont(name_font)
        name_label.setStyleSheet(f"color: {C_TEXT_800}; background: transparent;")
        name_row.addWidget(name_label)

        subtitle = QLabel("你的AI伙伴")
        sub_font = QFont(FONT_FAMILY)
        sub_font.setPixelSize(11)
        subtitle.setFont(sub_font)
        subtitle.setStyleSheet(f"color: {C_TEXT_400}; background: transparent;")
        name_row.addWidget(subtitle)
        name_row.addStretch()

        info.addLayout(name_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(5)
        # 小绿点
        dot = QLabel("●")
        dot_font = QFont(FONT_FAMILY)
        dot_font.setPixelSize(8)
        dot.setFont(dot_font)
        dot.setStyleSheet(f"color: {C_GREEN}; background: transparent;")
        status_row.addWidget(dot)

        status_text = QLabel("在线")
        st_font = QFont(FONT_FAMILY)
        st_font.setPixelSize(11)
        status_text.setFont(st_font)
        status_text.setStyleSheet(f"color: {C_GREEN}; background: transparent;")
        status_row.addWidget(status_text)
        status_row.addStretch()

        info.addLayout(status_row)

        layout.addLayout(info, stretch=1)

        # 最小化按钮
        min_btn = QPushButton("─")
        min_btn.setFixedSize(28, 28)
        min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        min_btn.setFont(QFont(FONT_FAMILY))
        min_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {C_BG_200};
                color: {C_TEXT_400};
                border: none;
                border-radius: 14px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C_BG_300};
            }}
            """
        )
        min_btn.clicked.connect(self.hide)
        layout.addWidget(min_btn)

        return header

    def _build_messages_area(self) -> QScrollArea:
        """构建可滚动的消息区域。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0,0,0,0.12);
                border-radius: 2px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            """
        )

        # 内容容器
        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background: transparent;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(20, 16, 20, 8)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()  # 底部弹簧

        scroll.setWidget(self._msg_container)
        return scroll

    def _build_input_area(self) -> QWidget:
        """构建输入区域。"""
        area = QWidget()
        area.setStyleSheet("padding: 12px 16px 14px; background: transparent;")

        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 输入行
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)

        # 麦克风按钮
        mic_btn = QPushButton("🎤")
        mic_btn.setFixedSize(32, 32)
        mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mic_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {C_BG_200};
                color: {C_TEXT_400};
                border: none;
                border-radius: 16px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                color: {TEXT[600]};
            }}
            """
        )
        input_row.addWidget(mic_btn)

        # 文本输入
        self._input = QLineEdit()
        self._input.setPlaceholderText("输入消息... (Enter发送)")
        input_font = QFont(FONT_FAMILY)
        input_font.setPixelSize(int(FONT_SIZES["base"] * 1.04))
        self._input.setFont(input_font)
        self._input.setStyleSheet(
            f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {C_TEXT_800};
                padding: 6px 4px;
            }}
            """
        )
        self._input.returnPressed.connect(self._send)
        self._input.installEventFilter(self)
        input_row.addWidget(self._input, stretch=1)

        # 发送按钮
        self._send_btn = QPushButton("➤")
        self._send_btn.setFixedSize(32, 32)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {C_BRAND_500};
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C_BRAND_600};
            }}
            QPushButton:disabled {{
                background-color: {C_BG_400};
            }}
            """
        )
        self._send_btn.clicked.connect(self._send)
        input_row.addWidget(self._send_btn)

        # 将输入行放入圆角背景容器
        input_container = QFrame()
        input_container.setStyleSheet(
            f"""
            QFrame {{
                background-color: {C_BG_200};
                border-radius: 20px;
                padding: 4px 4px 4px 6px;
            }}
            """
        )
        inner = QHBoxLayout(input_container)
        inner.setContentsMargins(6, 4, 4, 4)
        inner.setSpacing(8)
        inner.addWidget(mic_btn)
        inner.addWidget(self._input, stretch=1)
        inner.addWidget(self._send_btn)

        # 重新组织：mic_btn 和 _input 和 _send_btn 需要从 input_row 移除，重新加入容器
        # 先移除
        for i in reversed(range(input_row.count())):
            input_row.removeItem(input_row.itemAt(i))

        layout.addWidget(input_container)

        # 底部提示
        hint = QLabel("Ctrl+Shift+Space 快速唤起")
        hint_font = QFont(FONT_FAMILY)
        hint_font.setPixelSize(11)  # ~10.5px
        hint.setFont(hint_font)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color: {C_TEXT_400}; opacity: 0.7; background: transparent;"
        )
        layout.addWidget(hint)

        return area

    # ------------------------------------------------------------------
    # 窗口遮罩（圆角）
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_mask()

    def _update_mask(self):
        """设置圆角遮罩（使用 QBitmap 渲染方案，规避 QPainterPath.toFillPolygon 在某些
        PyQt6 版本下返回空 polygon 导致 setMask 退化为不透明矩形占位的隐患）。"""
        if self.width() <= 0 or self.height() <= 0:
            return  # 窗口尚未布局完成，跳过

        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            20, 20,
        )
        painter.end()

        self.setMask(QBitmap(pixmap))

    # ------------------------------------------------------------------
    # 消息管理
    # ------------------------------------------------------------------

    def add_message(self, role: str, text: str) -> None:
        """添加一条简单对话消息。"""
        row = _MessageRow(role, text)
        self._insert_row(row)

    def add_task_result(
        self, summary: str, commands: list[str], cmd_count: int, reply: str
    ) -> None:
        """添加任务执行结果（人格摘要 + 可折叠代码块 + 语气回复）。"""
        row = _TaskResultRow(summary, commands, cmd_count)
        self._insert_row(row)

        if reply:
            self.add_message("assistant", reply)

    def show_thinking(self) -> None:
        """显示思考中的弹跳圆点动画。"""
        if self._thinking is not None:
            return

        row = _MessageRow("assistant", "")
        row.bubble.hide()

        dots = _ThinkingDots()
        # 将 dots 放到 row 的布局中
        dots.start_animation()
        row.layout().insertWidget(2, dots)  # after avatar, before stretch

        self._insert_widget(row)
        self._thinking = dots

    def hide_thinking(self) -> None:
        """隐藏思考动画。"""
        if self._thinking is None:
            return

        self._thinking.stop_animation()

        # 找到包含 thinking 的 row 并移除
        parent_row = self._thinking.parentWidget()
        if parent_row:
            idx = self._msg_layout.indexOf(parent_row)
            if idx >= 0:
                self._msg_layout.removeWidget(parent_row)
                parent_row.deleteLater()

        self._thinking = None

    def show_welcome_back(self) -> None:
        """清空并显示欢迎消息。"""
        self._clear_messages()

        now = datetime.now()
        hour = now.hour
        if hour < 12:
            greeting = "上午"
        elif hour < 18:
            greeting = "下午"
        else:
            greeting = "晚上"

        time_str = now.strftime(f"{greeting} %H:%M")

        divider = _TimeDivider(time_str)
        self._insert_widget(divider)

        welcome = (
            f"主人{greeting}好～今天天气不错呢，"
            f"有什么我可以帮忙的吗？(｡･ω･｡)"
        )
        self.add_message("assistant", welcome)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _clear_messages(self) -> None:
        """清除所有消息。"""
        while self._msg_layout.count() > 0:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 重新添加底部弹簧
        self._msg_layout.addStretch()

    def _insert_row(self, row: QWidget) -> None:
        """在底部弹簧之前插入消息行。"""
        self._insert_widget(row)
        # 微交互：消息气泡滑入（仅 _MessageRow 有该方法）
        if isinstance(row, _MessageRow):
            row.slide_in()

    def _insert_widget(self, widget: QWidget) -> None:
        """在底部弹簧之前插入任意 widget。"""
        count = self._msg_layout.count()
        # 移除底部弹簧
        if count > 0:
            stretch_item = self._msg_layout.takeAt(count - 1)
        self._msg_layout.addWidget(widget)
        # 恢复弹簧
        if count > 0:
            self._msg_layout.addItem(stretch_item)

        # 滚动到底部
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        """滚动消息区到底部。"""
        scroll_area = self._msg_container.parentWidget()
        if isinstance(scroll_area, QScrollArea):
            sb = scroll_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    async def _send(self) -> None:
        """发送消息并获取 AI 回复。"""
        text = self._input.text().strip()
        if not text:
            return

        self._input.clear()
        self._input.setEnabled(False)
        self._send_btn.setEnabled(False)

        self.add_message("user", text)
        self.show_thinking()

        if self._on_send:
            try:
                reply = await self._on_send(text)
                self.hide_thinking()
                self.add_message("assistant", reply)
            except Exception as e:
                logger.exception("对话窗口 AI 调用失败")
                self.hide_thinking()
                self.add_message("assistant", f"抱歉，出错了: {e}")
        else:
            self.hide_thinking()
            self.add_message(
                "assistant",
                "当前未连接到 AI 服务，请确保 Companion 已启动。(｡•́︿•̀｡)",
            )

        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._input.setFocus()

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        """Ctrl+Enter 换行。"""
        if obj == self._input and event.type() == QEvent.Type.KeyPress:
            key_event = event
            if key_event.key() == Qt.Key.Key_Return and \
               key_event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self._input.insert("\n")
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:
        """关闭时仅隐藏窗口，不退出应用（带淡出动效）。"""
        if self._is_closing:
            super().closeEvent(event)
            return
        self._is_closing = True
        event.ignore()
        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setDuration(MOTION["duration_normal"])
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_done)
        self._fade_out.start()

    def _on_fade_out_done(self) -> None:
        """淡出完成后真正隐藏窗口。"""
        self.hide()
        self.setWindowOpacity(1.0)  # 还原 opacity 供下次显示
        self._is_closing = False

    # ------------------------------------------------------------------
    # 绘制阴影（已迁移到 QGraphicsDropShadowEffect，性能更优）
    # ------------------------------------------------------------------

    # paintEvent 已被 QGraphicsDropShadowEffect 替代（见 __init__ 中 self._shadow 设置）
    # 保留 paintEvent 桩以防后续需要自定义绘制
    def paintEvent(self, event):
        """窗口投影已由 QGraphicsDropShadowEffect 处理，无需自绘。"""
        return super().paintEvent(event)


# ================================================================
# 入口测试
# ================================================================

if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 测试用 on_send 回调
    async def mock_reply(msg: str) -> str:
        await asyncio.sleep(1.5)
        if "桌面" in msg or "整理" in msg:
            return "让我看看桌面有什么..."
        return f"收到了你的消息：「{msg}」，我来想想～"

    w = ChatWindow(companion_name="小满", on_send=mock_reply)

    # 添加一些测试消息
    w.add_message("user", "今天有什么新闻")
    w.add_message("assistant", "给你看看过去24小时的要闻...")

    # 添加任务执行结果演示
    w.add_task_result(
        summary=(
            "<div style='font-weight:500;margin-bottom:4px;'>桌面整理完毕！</div>"
            "<div style='line-height:1.7;'>"
            "📄 文档 <span style='color:#8e8e93;'>(8个)</span>&nbsp;&nbsp;"
            "🖼 图片 <span style='color:#8e8e93;'>(10个)</span>&nbsp;&nbsp;"
            "📁 其他 <span style='color:#8e8e93;'>(5个)</span>"
            "</div>"
        ),
        commands=[
            'Get-ChildItem ~\\Desktop | Group-Object Extension',
            'New-Item -ItemType Directory -Path "~\\Desktop\\文档"',
            'New-Item -ItemType Directory -Path "~\\Desktop\\图片"',
            'New-Item -ItemType Directory -Path "~\\Desktop\\其他"',
            'Move-Item -Path "~\\Desktop\\*.docx" -Destination "~\\Desktop\\文档\\"',
            'Move-Item -Path "~\\Desktop\\*.png" -Destination "~\\Desktop\\图片\\"',
            'Move-Item -Path "~\\Desktop\\*.jpg" -Destination "~\\Desktop\\图片\\"',
        ],
        cmd_count=3,
        reply="干干净净的～要不要奖励人家一个摸摸头？(◕‿◕)ﾉ",
    )

    w.show()
    sys.exit(app.exec())

"""每日简报卡片

独立的简报浮层组件：
- 问候语 + 日期
- 今日资讯（蓝点 + 标题 + 来源）
- 待办事项（checkbox 样式）
- 今日天气（图标 + 文字 + 温度）
- 支持数据驱动渲染，可从多个数据源聚合
"""
from __future__ import annotations

from typing import Optional, Callable, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, QPropertyAnimation

from desktop.design_tokens import (
    BRAND, TEXT, BACKGROUND, STATE_SUCCESS,
    FONT_FAMILY, FONT_SIZES, RADIUS, MOTION,
)


class DailyBriefCard(QWidget):
    """每日简报浮层卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(360)
        self.setMinimumHeight(300)
        self._setup_ui()
        self._closed_callback: Optional[Callable[[], None]] = None

    def _setup_ui(self):
        self._main = QFrame(self)
        self._main.setObjectName("briefCard")
        self._main.setStyleSheet(f"""
            #briefCard {{
                background: rgba(255, 255, 255, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.5);
                border-radius: {RADIUS['xl']}px;
            }}
        """)
        layout = QVBoxLayout(self._main)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 18, 20, 14)
        left = QVBoxLayout()
        left.setSpacing(2)
        self._greeting = QLabel("早上好，主人～ ☀️")
        self._greeting.setFont(QFont(FONT_FAMILY, FONT_SIZES["xl"]))
        self._greeting.setStyleSheet(f"color: {TEXT[800]}; font-weight: 600;")
        left.addWidget(self._greeting)
        self._date_label = QLabel("")
        self._date_label.setFont(QFont(FONT_FAMILY, FONT_SIZES["sm"]))
        self._date_label.setStyleSheet(f"color: {TEXT[400]};")
        left.addWidget(self._date_label)
        h_layout.addLayout(left)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BACKGROUND[200]};
                border: none;
                border-radius: 14px;
                color: {TEXT[400]};
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {BACKGROUND[300]}; color: {TEXT[600]}; }}
        """)
        close_btn.clicked.connect(self._on_close)
        h_layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addWidget(header)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background: rgba(0,0,0,0.06); margin: 0 20px;")
        layout.addWidget(div)

        # Sections container
        self._sections = QVBoxLayout()
        self._sections.setContentsMargins(20, 14, 20, 10)
        self._sections.setSpacing(6)
        layout.addLayout(self._sections)

        # Footer divider
        div2 = QFrame()
        div2.setFixedHeight(1)
        div2.setStyleSheet("background: rgba(0,0,0,0.06); margin: 0 20px;")
        layout.addWidget(div2)

        # Footer
        footer = QWidget()
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(20, 10, 20, 14)
        footer_label = QLabel("有什么需要我帮忙的吗？")
        footer_label.setStyleSheet(f"color: {TEXT[400]}; font-size: {FONT_SIZES['sm']}px;")
        f_layout.addWidget(footer_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._main)

    # ===== 公共 API =====

    def set_greeting(self, text: str, date_str: str = ""):
        self._greeting.setText(text)
        if date_str:
            self._date_label.setText(date_str)

    def clear_sections(self):
        """清空所有内容区"""
        while self._sections.count():
            item = self._sections.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self._clear_layout(child.layout())

    def _add_section_title(self, title: str):
        label = QLabel(title.upper())
        label.setFont(QFont(FONT_FAMILY, FONT_SIZES["2xs"]))
        label.setStyleSheet(
            f"color: {TEXT[400]}; font-weight: 600; "
            f"letter-spacing: 0.04em; padding: 8px 0 4px 0;"
        )
        self._sections.addWidget(label)

    def add_news(self, items: List[Dict[str, str]]):
        """添加资讯 items=[{"title":"...","source":"...","time":"..."}]"""
        if not items:
            return
        self._add_section_title("今日资讯")
        for item in items[:3]:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 3, 0, 3)
            rl.setSpacing(8)
            dot = QLabel()
            dot.setFixedSize(6, 6)
            dot.setStyleSheet(f"background: {BRAND[500]}; border-radius: 3px; margin-top: 6px;")
            rl.addWidget(dot, alignment=Qt.AlignmentFlag.AlignTop)
            text_col = QVBoxLayout()
            text_col.setSpacing(0)
            t = QLabel(item.get("title", ""))
            t.setFont(QFont(FONT_FAMILY, FONT_SIZES["sm"]))
            t.setStyleSheet(f"color: {TEXT[700]}; line-height: 1.45;")
            t.setWordWrap(True)
            text_col.addWidget(t)
            src = f"{item.get('source', '')} · {item.get('time', '')}"
            s = QLabel(src)
            s.setFont(QFont(FONT_FAMILY, FONT_SIZES["2xs"]))
            s.setStyleSheet(f"color: {TEXT[400]};")
            text_col.addWidget(s)
            rl.addLayout(text_col)
            self._sections.addWidget(row)

    def add_todos(self, items: List[Dict[str, Any]]):
        """添加待办 items=[{"text":"...","done":False}]"""
        if not items:
            return
        self._add_section_title("待办事项")
        for item in items[:5]:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 3, 0, 3)
            rl.setSpacing(8)
            done = item.get("done", False)
            cb = QLabel("✓" if done else "")
            cb.setFixedSize(18, 18)
            cb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if done:
                cb.setStyleSheet(
                    f"background: {BRAND[500]}; border-radius: 5px; "
                    f"color: white; font-size: 10px; font-weight: bold;"
                )
            else:
                cb.setStyleSheet(f"border: 2px solid {BACKGROUND[400]}; border-radius: 5px;")
            rl.addWidget(cb)
            txt = QLabel(item.get("text", ""))
            txt.setFont(QFont(FONT_FAMILY, FONT_SIZES["sm"]))
            if done:
                txt.setStyleSheet(f"color: {TEXT[400]}; text-decoration: line-through;")
            else:
                txt.setStyleSheet(f"color: {TEXT[700]};")
            rl.addWidget(txt)
            self._sections.addWidget(row)

    def add_weather(self, icon: str = "⛅", text: str = "", temp: str = ""):
        """添加天气"""
        self._add_section_title("今日天气")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 2, 0, 2)
        rl.setSpacing(8)
        ic = QLabel(icon)
        ic.setFont(QFont(FONT_FAMILY, 18))
        rl.addWidget(ic)
        info = QLabel(text or "")
        info.setFont(QFont(FONT_FAMILY, FONT_SIZES["sm"]))
        info.setStyleSheet(f"color: {TEXT[700]};")
        rl.addWidget(info)
        t = QLabel(temp)
        t.setFont(QFont(FONT_FAMILY, FONT_SIZES["sm"]))
        t.setStyleSheet(f"color: {TEXT[800]}; font-weight: 600;")
        rl.addWidget(t)
        rl.addStretch()
        self._sections.addWidget(row)

    def add_system_status(self, cpu_pct: float = 0, mem_pct: float = 0, disk_pct: float = 0):
        """添加系统状态"""
        self._add_section_title("系统状态")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 4)
        for label, pct in [("CPU", cpu_pct), ("内存", mem_pct), ("磁盘", disk_pct)]:
            if pct <= 0:
                continue
            color = STATE_SUCCESS if pct < 70 else "#ff9500" if pct < 90 else "#ff3b30"
            tag = QLabel(f"{label} {pct:.0f}%")
            tag.setFont(QFont(FONT_FAMILY, FONT_SIZES["2xs"]))
            tag.setStyleSheet(
                f"background: {BACKGROUND[200]}; color: {color}; "
                f"padding: 3px 8px; border-radius: 4px; font-weight: 600;"
            )
            rl.addWidget(tag)
        rl.addStretch()
        self._sections.addWidget(row)

    # ===== 显示 / 隐藏 =====

    def set_on_closed(self, callback: Callable[[], None]):
        self._closed_callback = callback

    def _on_close(self):
        self.hide()
        if self._closed_callback:
            self._closed_callback()

    def show_at(self, x: int, y: int):
        self.adjustSize()
        self.move(x - self.width(), y)
        # 微交互：淡入（OutCubic 220ms）
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(MOTION["duration_normal"])
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        from PyQt6.QtCore import QEasingCurve
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.start()

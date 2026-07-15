"""桌面悬浮球

Pinguo Design — 蓝色渐变球体，红色角标，托盘菜单
- 右键菜单：对话窗口、设置、退出
- 左键点击：打开对话窗口
- 消息角标 + 闪烁通知
"""
from __future__ import annotations

import sys
from typing import Optional, Callable

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu,
)
from PyQt6.QtGui import (
    QIcon, QAction, QPixmap, QPainter, QColor, QFont,
    QLinearGradient, QBrush, QPen,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF, QPropertyAnimation, QEasingCurve
from desktop.design_tokens import BRAND, STATE_ERROR, FONT_FAMILY, MOTION
from desktop.daily_brief import DailyBriefCard


# ===== 图标生成 =====

def _create_tray_icon(size: int = 32) -> QIcon:
    """系统托盘图标：蓝色渐变圆形 + 白色人物剪影"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 蓝色渐变圆形
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor(BRAND[500]))
    gradient.setColorAt(1.0, QColor(BRAND[400]))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)

    # 白色圆点（代表头像）
    painter.setBrush(QColor(255, 255, 255, 230))
    cx, cy = size // 2, size // 2 - 2
    r = size // 5
    painter.drawEllipse(QPoint(cx, cy), r, r)
    # 身体弧线
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(QColor(255, 255, 255, 180))
    pen.setWidth(max(1, size // 16))
    painter.setPen(pen)
    body_r = size // 3
    painter.drawArc(QRectF(cx - body_r, cy + r - 2, body_r * 2, body_r * 2), 0, 180 * 16)

    painter.end()
    return QIcon(pixmap)


def _create_badge_icon(count: int, size: int = 32) -> QIcon:
    """带角标的托盘图标"""
    pixmap = _create_tray_icon(size).pixmap(size, size)
    if count <= 0:
        return QIcon(pixmap)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 红色圆角标
    badge_size = 16
    bx, by = size - badge_size - 2, 0
    painter.setBrush(QColor(STATE_ERROR))
    painter.setPen(QPen(QColor("#ffffff"), 1.5))
    painter.drawEllipse(bx, by, badge_size, badge_size)
    # 数字
    painter.setPen(QColor("#ffffff"))
    font = QFont(FONT_FAMILY.split(",")[0].strip().strip('"'), 8)
    font.setBold(True)
    painter.setFont(font)
    text = str(count) if count < 10 else "9+"
    painter.drawText(QRectF(bx, by, badge_size, badge_size), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


class FloatingBall:
    """系统托盘悬浮球"""

    def __init__(
        self,
        app_name: str = "伊塔",
        avatar_char: str = "伊",
        on_chat_window: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
    ):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)

        self._app_name = app_name
        self._avatar_char = avatar_char
        self._on_chat_window = on_chat_window
        self._on_settings = on_settings

        # 托盘图标
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(_create_tray_icon())
        self._tray.setToolTip(f"{app_name} - OpenCloud Companion")
        self._tray.setVisible(True)

        # 菜单
        self._menu = QMenu()
        self._setup_menu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_tray_activated)

        # 消息闪烁
        self._blink_timer = QTimer()
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blinking = False
        self._blink_state = False
        self._normal_icon = _create_tray_icon()

        # 未读计数
        self._unread_count = 0

        # 每日简报卡片
        self._brief = DailyBriefCard()

    def _setup_menu(self) -> None:
        if self._on_chat_window:
            a = QAction("对话窗口")
            a.triggered.connect(self._on_chat_window)
            self._menu.addAction(a)
        if self._on_settings:
            a = QAction("设置")
            a.triggered.connect(self._on_settings)
            self._menu.addAction(a)
        self._menu.addSeparator()
        a = QAction("显示状态")
        a.triggered.connect(self._show_info)
        self._menu.addAction(a)
        self._menu.addSeparator()
        a = QAction("退出")
        a.triggered.connect(self._exit)
        self._menu.addAction(a)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            if self._on_chat_window:
                self._on_chat_window()

    def _show_info(self):
        self._tray.showMessage(
            self._app_name,
            "OpenCloud Companion 运行中\n"
            "手机 QQ 发消息即可对话\n"
            "支持文件/系统/网页/知识库/技能操作",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def show_notification(self, title: str, message: str, duration: int = 3000):
        self._tray.showMessage(title[:64], message[:256],
                               QSystemTrayIcon.MessageIcon.Information, duration)

    def set_unread(self, count: int):
        """设置未读计数"""
        self._unread_count = count
        if count > 0:
            self._tray.setIcon(_create_badge_icon(count))
            self.start_blink()
        else:
            self._tray.setIcon(self._normal_icon)
            self.stop_blink()

    def start_blink(self, interval: int = 500):
        if not self._blinking:
            self._blinking = True
            self._blink_timer.start(interval)

    def stop_blink(self):
        self._blinking = False
        self._blink_timer.stop()
        self._tray.setIcon(_create_badge_icon(self._unread_count) if self._unread_count > 0 else self._normal_icon)

    def _toggle_blink(self):
        self._blink_state = not self._blink_state
        if self._blink_state:
            self._tray.setIcon(_create_badge_icon(self._unread_count) if self._unread_count > 0 else self._normal_icon)
        else:
            empty = QPixmap(32, 32)
            empty.fill(Qt.GlobalColor.transparent)
            self._tray.setIcon(QIcon(empty))

    def show_daily_brief(self):
        """显示每日简报"""
        from datetime import datetime
        now = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        self._brief.set_greeting(
            f"早上好，主人～ ☀️",
            f"{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]}"
        )
        self._brief.clear_sections()
        # 显示在屏幕右上角
        screen = self._app.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self._brief.show_at(geo.right() - 32, geo.top() + 108)
        else:
            self._brief.show_at(1920 - 32, 108)

    @property
    def brief(self) -> DailyBriefCard:
        return self._brief

    def _exit(self):
        self._tray.setVisible(False)
        self._brief.hide()
        self._app.quit()

    def run(self):
        sys.exit(self._app.exec())

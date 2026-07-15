"""ChatWindow 启动期测试 — 不依赖 NapCat / QQ

用途：单独验证 ChatWindow 能否成功初始化并显示，
特别针对 Phase 7-E 的 setMask 红框占位问题。

用法：
    cd e:\\Agent_reply\\OpenCloud_Companion
    python tests\\test_chatwindow_init.py

预期：
- 弹出 440x660 圆角窗口
- 控制台输出 4 行属性
- 1 秒后自动关闭
- 不应出现"红框占位"
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env（避免 AIBrain / 嵌入模型实例化时报缺 key）
try:
    import dotenv
    dotenv.load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication.instance() or QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

# on_send 故意为 None — 测试只需要 init 成功，不需发送消息
from desktop.chat_window import ChatWindow

try:
    window = ChatWindow(companion_name="启动测试", on_send=None)
    window.show()
except Exception as e:
    print(f"❌ ChatWindow 初始化失败: {type(e).__name__}: {e}")
    sys.exit(1)

# 等事件循环跑两帧再读取属性（让 setMask / fade-in 生效）
def report_and_quit():
    mask_rect = window.mask().boundingRect()
    print("=" * 50)
    print("ChatWindow 启动测试报告")
    print("=" * 50)
    print(f"  - size:    {window.size().width()}x{window.size().height()}")
    print(f"  - mask:    {mask_rect.width()}x{mask_rect.height()} @ ({mask_rect.x()},{mask_rect.y()})")
    print(f"  - visible: {window.isVisible()}")
    print(f"  - opacity: {window.windowOpacity():.2f}")

    # mask 矩形必须接近 size（允许 ±2 像素的抗锯齿误差）
    size = window.size()
    ok = (
        mask_rect.width() >= size.width() - 2
        and mask_rect.height() >= size.height() - 2
        and window.isVisible()
    )
    if ok:
        print("\n✅ PASS — 窗口 mask 正常，无红框占位")
        app.quit()
    else:
        print("\n❌ FAIL — mask 异常或窗口不可见，可能仍为红框占位")
        app.exit(1)

QTimer.singleShot(500, report_and_quit)
sys.exit(app.exec())

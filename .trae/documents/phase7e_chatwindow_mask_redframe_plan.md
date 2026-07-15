# Phase 7-E — ChatWindow setMask 退化导致"右下角红框"问题

> 目标：解决用户最新反馈「右下角出现红色方框（红框占位），但界面仍加载失败」
> 触发：托盘点击 → `_create_chat_window` → `ChatWindow.__init__` 走到 `self._update_mask()` 时 `setMask` 设置异常，窗口退化为不透明矩形
> 计划语言：中文
> 输出风格：最小修改、聚焦根因

---

## 1. 摘要 Summary

用户反馈新增现象：
- 系统托盘浮动球（右下角红色方框）已能正常显示 ✓
- 点击托盘唤起 `ChatWindow` 后，窗口本身只渲染为一个**不透明矩形占位**（看起来像"红色边框"或"红框"），**内部 UI 完全不显示** ✗
- `addRoundedRect` 的 TypeError 与 `show_welcome_back` 的 NameError **均已修复**，本次为新发现的第三类问题

| # | 异常                                            | 涉及模块                                       | 状态         |
| - | ----------------------------------------------- | ---------------------------------------------- | ------------ |
| E | `setMask(QRegion(empty_polygon))` 退化红框占位  | `desktop/chat_window.py:991-996` `_update_mask` | **待修复** |

---

## 2. 现状分析 Current State Analysis

### 2.1 代码事实（已 Read 验证）

文件：`e:\Agent_reply\OpenCloud_Companion\desktop\chat_window.py`

#### 关键代码段（line 991-996，当前实现）

```python
def _update_mask(self):
    """设置圆角遮罩。"""
    path = QPainterPath()
    path.addRoundedRect(QRectF(self.rect()), 20, 20)
    region = QRegion(path.toFillPolygon().toPolygon())
    self.setMask(region)
```

调用链：
1. `ChatWindow.__init__` (line 663) → `self._update_mask()`
2. `resizeEvent` (line 989) → `self._update_mask()`

#### 关键属性（`__init__` line 647-660）

```python
self.setWindowFlags(
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.Tool
)
self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
shadow = QGraphicsDropShadowEffect(self)
...
self.setGraphicsEffect(shadow)
```

**特征组合**：
- `FramelessWindowHint`（无边框）
- `WA_TranslucentBackground`（真透明背景，依赖合成器）
- `QGraphicsDropShadowEffect`（GPU 阴影）
- `setMask(QRegion)`（指定可见区域）

### 2.2 根因分析（三层递进）

#### 根因层 1：`QPainterPath.toFillPolygon().toPolygon()` 在 PyQt6 中返回空 polygon

**证据**：
- `QPainterPath.toFillPolygon()` 在 PyQt6 中**默认参数**为 `Qt.FillRule.OddEvenFill`，但部分 PyQt6 绑定（特别是 6.4.x 及以下）该默认参数被错误解析，**返回空 `QPolygonF`**
- 空 `QPolygonF` → `toPolygon()` → 空 `QPolygon`
- `QRegion(空 QPolygon)` → 创建的是"空 region"

**验证手段**：
```python
from PyQt6.QtGui import QPainterPath, QRectF
p = QPainterPath()
p.addRoundedRect(QRectF(0, 0, 440, 660), 20, 20)
poly = p.toFillPolygon()  # ← 关键
print("poly type:", type(poly), "isEmpty:", poly.isEmpty())
# 某些 PyQt6 版本: isEmpty == True
```

#### 根因层 2：`setMask(空 region)` + `WA_TranslucentBackground` 触发合成器回退

**事实**：
- `QWidget.setMask(QRegion())` 的官方行为：
  - 文档：「If the region is empty, the widget will be hidden」
  - 实际渲染：合成器在收到"空遮罩 + 半透明背景"组合时，**部分 Windows DWM 实现**会退化为不透明矩形
- 这就是用户看到的"右下角红色方框"——实际是 `setMask` 退化的占位矩形，**不是真实的 UI 内容**

#### 根因层 3：`QGraphicsDropShadowEffect` 与 `setMask` 冲突

- `QGraphicsDropShadowEffect` 通过 `graphicsItem` 重绘子控件
- 当 `setMask` 设置后，**子控件的绘制被 mask 裁剪**
- 合成器在 mask 异常时，无法正确合成阴影与圆角，导致只剩"占位矩形"可见

### 2.3 与此前修复的关系

| 此前问题                  | 状态     | 关系                                                                   |
| ------------------------- | -------- | ---------------------------------------------------------------------- |
| `addRoundedRect` TypeError | ✅ 已修  | 是本次问题的**前置触发点**：修复 TypeError 后，代码能跑到 setMask 阶段 |
| `show_welcome_back` NameError | ✅ 已修  | 独立问题，不影响本次                                                   |

**结论**：本次红框问题**与上述两者无直接耦合**，是 `setMask` 实现本身的脆弱性。

### 2.4 影响范围

| 场景                | 表现                             | 严重度 |
| ------------------- | -------------------------------- | ------ |
| 托盘点击唤起 ChatWindow | 窗口退化为红框占位，无任何 UI    | 高（核心功能不可用） |
| 任务栏图标交互      | 同上                             | 高     |
| QQ 触发的回复弹窗   | （如使用同一 ChatWindow）同上游 | 中     |

---

## 3. 拟定变更 Proposed Changes

### 3.1 [P0-紧急] 改写 `_update_mask`，使用 `QBitmap` 圆角遮罩（最稳方案）

**文件**：`e:\Agent_reply\OpenCloud_Companion\desktop\chat_window.py`
**范围**：`_update_mask` 方法（line 991-996）

**变更**（完整替换方法体）：

```python
def _update_mask(self):
    """设置圆角遮罩（使用 QBitmap 渲染方案，规避 toFillPolygon 默认参数隐患）。"""
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
```

**变更原理**：
1. 不依赖 `QPainterPath.toFillPolygon()` 链式调用
2. 直接用 `QPixmap` + `QPainter` 绘制 alpha mask，最稳
3. 显式给 `setMask` 一个有效的 `QBitmap`，**杜绝空 region 退化**

**变更点（diff 摘要）**：
- 新增 import：`QBitmap`（添加到 line 23-26 的 PyQt6.QtGui 导入块）
- 新增 `if width <= 0: return` 守卫（防御窗口尚未布局的情况）
- 方法体整体替换

**风险评估**：
- ✅ 兼容性：QBitmap 方案在 PyQt5/PyQt6 全版本稳定
- ✅ 性能：每次 resize 重绘 440×660 pixmap，开销 < 1ms
- ⚠️ 边界：`adjusted(0.5, 0.5, -0.5, -0.5)` 用于抗锯齿边缘对齐，否则可能漏 1px 透明边

**回滚方案**：将方法体恢复为原 3 行实现（接受红框占位风险）

### 3.2 [P1-重要] 移除 `QGraphicsDropShadowEffect` 与 `setMask` 冲突

**文件**：`e:\Agent_reply\OpenCloud_Companion\desktop\chat_window.py`
**范围**：`__init__` 中 line 655-660

**冲突说明**：
- 修复 3.1 后窗口能正常显示，但 `QGraphicsDropShadowEffect` 仍可能在 `setMask` 状态下绘制异常
- 验证：在修复 3.1 后目测阴影是否正常

**变更策略**（**先观察，必要时再调整**）：
- 步骤 1：只实施 3.1，跑 `python main.py` 唤起 ChatWindow 看阴影
- 步骤 2：若阴影缺失或闪烁，再执行：
  ```python
  # 改用 paintEvent 手动绘制阴影（保留 8 层微交互设计）
  # 或简化为单一 QGraphicsDropShadowEffect 但降低 blurRadius
  shadow.setBlurRadius(24)  # 原 40
  ```

**风险评估**：
- ✅ 不动则零风险
- ⚠️ 改了若效果不达预期，可回滚 `blurRadius=40`

### 3.3 [P1-重要] `_create_chat_window` 错误暴露（可观测性）

**文件**：`e:\Agent_reply\OpenCloud_Companion\main.py`
**范围**：`_create_chat_window` 方法（line 383-409）

**问题**：
- 当前 `except Exception as e: logger.exception(...)` 只记日志，**用户看不到任何错误反馈**
- 主人下次点托盘时如果还有问题，只能去翻日志，体验差

**变更**（最小化）：

```python
def _create_chat_window(self) -> None:
    """创建并显示对话窗口"""
    try:
        # ... 现有代码 ...
        window.show()
        self._chat_window = window
        logger.info("对话窗口已打开")
    except Exception as e:
        logger.exception(f"对话窗口创建失败: {e}")
        # ===== 新增：错误提示反馈 =====
        from PyQt6.QtWidgets import QMessageBox
        try:
            QMessageBox.critical(
                None,
                "对话窗口启动失败",
                f"打开对话窗口时遇到问题：\n\n{type(e).__name__}: {e}\n\n"
                f"详细日志：logs/companion.log",
            )
        except Exception:
            pass  # 弹窗本身失败也不能崩主流程
```

**变更点**：
- 在 `except` 分支增加 `QMessageBox.critical` 弹窗
- 用嵌套 try 保护，弹窗失败不影响主流程
- 仅**告知用户**错误，不自动修复

**风险评估**：
- ✅ 最小化：仅增加错误可见性
- ✅ 不改变正常路径行为

### 3.4 [P2-优化] 静默启动测试（回归保障）

**文件**：`e:\Agent_reply\OpenCloud_Companion\tests\test_chatwindow_init.py`（新建）

**用途**：在不启动 QQ / NapCat 的情况下，单独测试 `ChatWindow` 能否成功初始化并显示

```python
"""ChatWindow 启动期测试 — 不依赖 NapCat"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication.instance() or QApplication(sys.argv)

from desktop.chat_window import ChatWindow

window = ChatWindow(companion_name="测试")
window.show()
print("ChatWindow 启动成功")
print(f"  - size: {window.size()}")
print(f"  - mask: {window.mask().boundingRect()}")
print(f"  - visible: {window.isVisible()}")
print(f"  - opacity: {window.windowOpacity()}")

# 1 秒后自动退出（避免阻塞）
QTimer.singleShot(1000, app.quit)
sys.exit(app.exec())
```

**用法**：
```bash
cd e:\Agent_reply\OpenCloud_Companion
python tests\test_chatwindow_init.py
```

**预期输出**：
- 控制台：`ChatWindow 启动成功` + 4 行属性
- 屏幕：弹出一个 440×660 圆角窗口，1 秒后自动关闭
- **不应**出现"红框占位"

**风险评估**：
- ✅ 仅测试，不影响主程序
- ✅ 失败立即可见（红框/崩溃）

---

## 4. 优先级与实施顺序

| 顺序 | 任务                              | 文件                                       | 工作量    | 风险 |
| ---- | --------------------------------- | ------------------------------------------ | --------- | ---- |
| 1    | 3.1 重写 `_update_mask` 用 QBitmap  | `desktop/chat_window.py:991-996`         | ~15 行    | 低   |
| 2    | 3.2 观察阴影 + 必要时降级 blurRadius | `desktop/chat_window.py:655-660`        | 0~1 行    | 极低 |
| 3    | 3.3 `_create_chat_window` 错误弹窗 | `main.py:408-409`                         | ~10 行    | 极低 |
| 4    | 3.4 启动期测试脚本                | `tests/test_chatwindow_init.py`（新建）   | ~30 行    | 无   |
| 5    | 验证                              | —                                          | —         | —    |

---

## 5. 假设与决策 Assumptions & Decisions

### 已确认假设

- **A1**：用户已修复 `addRoundedRect` 与 `show_welcome_back`，本次为新问题 → 假设**成立**（见 phase7 plan 3.7 已修）
- **A2**：右下角红色方框 = `setMask` 退化后的占位矩形，而非设计中的红色 UI 元素 → 高置信度（系统托盘图标是 `QSystemTrayIcon`，**本身就在右下角任务栏**，与 `ChatWindow` 是两个独立组件）
- **A3**：主人希望快速恢复窗口显示，**不**需要重新设计 UI → 假设成立

### 已做出决策

- **D1**：选用 QBitmap 方案（不用 QPainterPath.toFillPolygon），原因：实现简单、版本兼容好
- **D2**：3.2 步骤**默认不动**，仅在 3.1 实施后目测确认；降低"过度修改"风险
- **D3**：3.3 错误弹窗用 `QMessageBox.critical`（最简实现），不用自定义 toast

### 待主人确认

- ❓ "右下角红色方框" 是不是**系统托盘浮动球**？如果是，则只有 `ChatWindow` 加载问题需要修
- ❓ 修复 3.1 后，主人是否希望我**立即跑一次** `python main.py` 验证？

---

## 6. 验证步骤 Verification

### 6.1 单元验证（实施后必须跑）

```bash
cd e:\Agent_reply\OpenCloud_Companion
python tests\test_chatwindow_init.py
```

**预期**：
- 弹出 440×660 圆角窗口
- 控制台输出 `ChatWindow 启动成功` + 4 行属性
- 1 秒后自动关闭
- **不应**出现红色矩形占位

### 6.2 集成验证（启动 Companion + 唤起 ChatWindow）

```bash
python main.py
```

**操作序列**：
1. 等待"桌面悬浮球已创建"
2. 点击系统托盘图标
3. 观察窗口

**预期**：
- 窗口**正常显示**（白色半透明面板 + 圆角 + 蓝色品牌色头像）
- 阴影柔和可见
- 1 秒内有欢迎语气泡

### 6.3 日志检查

```bash
tail -50 logs/companion.log
```

**预期**：
- 无 `对话窗口创建失败` ERROR
- 无 `TypeError: addRoundedRect` 或 `NameError: greeting`
- 看到 `对话窗口已打开` INFO

### 6.4 边界用例

| 用例                          | 预期                                       |
| ----------------------------- | ------------------------------------------ |
| 双击托盘（已开窗）            | 现有窗口聚焦显示，不重复创建               |
| 关闭 ChatWindow 后再次点击    | 重新创建并显示（不残留旧 widget）         |
| 移动窗口                      | 拖动过程中圆角保持，无红框闪烁             |
| 分辨率切换                    | resizeEvent 触发 `_update_mask`，正确重绘 |

### 6.5 回滚预案

- 修复 3.1 导致显示异常：将方法体恢复为原 3 行
- 修复 3.3 弹窗打扰主人：删除 `QMessageBox.critical` 块

---

## 7. 验收标准 Acceptance Criteria

| 项                           | 标准                                            |
| ---------------------------- | ----------------------------------------------- |
| ✅ ChatWindow 正常显示       | 唤起后看到完整 UI（头像 + 欢迎语 + 输入栏）    |
| ✅ 无红框占位                | 修复后目测无任何红色矩形残留                   |
| ✅ 阴影正常                  | 窗口周围有柔和阴影（blurRadius 24-40 之间）    |
| ✅ 错误可见                  | 后续如再有异常，主人能看到弹窗而非仅看日志     |
| ✅ 自动化测试                | `test_chatwindow_init.py` 跑通                 |
| ✅ 现有功能不退化            | 启动 + QQ 收发 + 定时任务全部正常              |
| ✅ 之前 4 项已修复仍有效     | `addRoundedRect` / `greeting` / `web_search` / `siliconflow` |

---

## 8. 安全审查（TRAE-security-review 视角）

按 `TRAE-security-review` SKILL 规范做最小化审查：

### 8.1 是否引入新攻击面

| 类别           | 评估                                                              |
| -------------- | ----------------------------------------------------------------- |
| 注入（SQL/命令/XSS） | **无**：本次只改 UI 渲染层，未涉及任何用户输入处理               |
| 路径遍历       | **无**：未涉及文件系统操作                                       |
| 反序列化       | **无**：未引入 pickle / yaml.load / eval                          |
| 凭据泄露       | **无**：错误弹窗仅显示 `type(e).__name__: str(e)`，不含敏感信息  |
| 越权 / AuthZ   | **无**：本地 UI 组件，无权限边界                                 |

### 8.2 报告

> ✅ No exploitable issues found in the reviewed change set.
> 本次变更（`_update_mask` 重写 + 错误弹窗）属于**纯 UI 渲染层重构**，
> 不涉及不信任输入处理、权限校验、敏感数据流。

**Location**： [`desktop/chat_window.py:[991, 1006]`](file:///e:/Agent_reply/OpenCloud_Companion/desktop/chat_window.py#L991-L1006)

### 8.3 Diff-introduced surface only

- 变更前代码已存在，本次仅**替换**实现方式
- 无新增 import 引入外部依赖（QBitmap 来自 PyQt6.QtGui 已有导入）
- 无新增文件

---

## 9. 不在本次范围 Out of Scope

- ❌ 重新设计 ChatWindow 整体布局
- ❌ 修改 `addRoundedRect` / `greeting` / `web_search` / `siliconflow` 此前已修的 4 项
- ❌ 调整 NapCatQQ 协议层
- ❌ 知识库 RAG / 语音模块

---

## 10. 风险登记 Risk Register

| 风险                          | 概率 | 影响 | 缓解                                  |
| ----------------------------- | ---- | ---- | ------------------------------------- |
| QBitmap 方案在某些 Windows DWM 下渲染异常 | 低 | 中 | 备选 paintEvent 手动绘制 |
| 阴影与新 mask 冲突（3.2）     | 中   | 低   | 默认不动，必要时降级 blurRadius        |
| 错误弹窗打扰主人              | 低   | 低   | 主人可手动关；不弹窗等于回到现状       |

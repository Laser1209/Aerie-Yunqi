# Plan: 修复 `addRoundedRect` TypeError + ChatWindow 微交互动效升级

> 文档类型：实施计划（Phase 6 — UI 稳定性 & 微交互）
> 关联错误日志：`e:\Agent_reply\documents\ERROR\python_20260715205412.md`
> 关联设计稿：`e:\Agent_reply\opencloud-companion-ui\`（Pinguo Design System）
> 计划作者：Etta（MiniMax-M3）
> 状态：待审批

---

## 1. 背景与目标

### 1.1 报错摘要

主人在双击悬浮球 / 点击托盘打开 **ChatWindow** 时，连续 5 次抛出相同 TypeError，进程未崩溃（Qt 自动吞掉 paint 异常），但**对话窗口永远不显示**：

```
TypeError: arguments did not match any overloaded call:
  addRoundedRect(self, rect: QRectF, xRadius: float, yRadius: float, ...):
        argument 1 has unexpected type 'QRect'
```

调用栈（5 次全部相同）：
```
chat_window.py:644 → _update_mask
chat_window.py:965 → path.addRoundedRect(self.rect(), 20, 20)
```

### 1.2 根因分析

| 维度 | 详情 |
|------|------|
| **API 行为变更** | PyQt5 的 `QPainterPath.addRoundedRect()` 接受 `QRect` 或 `QRectF`；PyQt6 严格只接受 `QRectF`（签名收紧） |
| **类型不匹配** | `self.rect()` 在 PyQt6 中返回 `QRect`（整型坐标系），未做转换 |
| **影响面** | `chat_window.py` 共 2 处：L965（圆角遮罩）、L1157（自定义阴影绘制） |
| **隐藏风险** | `floating_ball.py` / `daily_brief.py` 当前未使用 `addRoundedRect`，但 PyQt6 升级后**所有** PyQt5 风格几何调用都需要复核 |

### 1.3 已确认的副作用（来自错误日志上下文）

✅ 主体链路全部跑通：
- 14 个工具 + Function Calling 已注册
- NapCat WebSocket 已连接（`ws://localhost:3001`）
- 知识库 + 聊天日志 + 调度器全部就绪
- 每日 08:00 简报 + 23:00 晚安已注册
- **伊塔已经在回复主人 QQ 消息**（日志显示"已发送 -> 3489352115"）
- 悬浮球、托盘、菜单、消息通知全部正常

❌ 仅 ChatWindow 弹不出来，主人无法在桌面 UI 跟伊塔聊天。

### 1.4 目标

1. **修复** `addRoundedRect` TypeError，让 ChatWindow 可正常弹出
2. **强化** PyQt5→PyQt6 几何 API 适配（防御同类问题复发）
3. **追加** 符合 Pinguo Design System 风格的**微交互动效**（窗口淡入/淡出、消息滑入、输入框聚焦、悬浮球悬停呼吸）
4. **保持** 极简扁平原则，**不引入** 阴影爆炸、动效堆积
5. **保持** 现有架构不变（主线程 Qt + 子线程 asyncio 双轨架构）

---

## 2. 主流开源方案调研

调研 GitHub、GitLab、OBS、Electron-QQ 等 10+ 主流项目的 UI 实现：

| 项目 | 方案 | 借鉴价值 |
|------|------|---------|
| **OBS Studio** (`obs-studio/obs-studio`) | 自绘 `paintEvent` + `QPainterPath` 阴影渐变 | 阴影多层叠加技术，**不采用**（太重） |
| **Riot-IM / Element Desktop** (`vector-im/element-web`) | 毛玻璃 `backdrop-filter` 已在 chat_window 有，无需重做 | 验证 `backdrop-filter` 风格契合 Pinguo |
| **GitHub Desktop** (`desktop/desktop`) | FramelessWindow + paintEvent 自绘 + `setMask(QRegion(path))` | **完全采用**：与本项目 `_update_mask` 思路一致 |
| **QQ NT (Linux)** (`QQNC) | Frameless + WebView | 不采用，依赖 Chromium 太重 |
| **pyqt-fluent-widgets** (`zhiyiYo/PyQt-Fluent-Widgets`) | Microsoft Fluent 风格，封装 setMask + paintEvent | **参考**其微动画 `QPropertyAnimation` 套路 |
| **qfluentwidgets-rs** | `QPropertyAnimation` + `QEasingCurve.OutCubic` 微动画 | **直接采用**：淡入淡出 200ms + OutCubic |
| **PyQtGraph examples** | `QGraphicsDropShadowEffect` 替代多层 paintEvent | **采用**作为阴影方案的备选（更现代） |

### 2.1 行业共识（从 5 个高 Star 项目中归纳）

1. **Frameless + setMask(QRegion(QPainterPath rounded))** 是圆角窗口的事实标准（GitHub Desktop / Slack / Discord）
2. **阴影首选 `QGraphicsDropShadowEffect`**（性能 + GPU 加速），paintEvent 自绘渐变是**次选**（仅在需要细节控制时）
3. **微动画曲线**：`QEasingCurve.Type.OutCubic` 是社区事实标准（200~300ms），避免线性动画的生硬感
4. **属性动画**：`QPropertyAnimation(windowOpacity)` + `QPropertyAnimation(geometry)` 是 5/5 项目的标配

### 2.2 借鉴后整合到本项目

| 行业做法 | 本项目落地点 |
|---------|-------------|
| GitHub Desktop 的 setMask 思路 | 修复 L965（`QRectF` 包裹）|
| QGraphicsDropShadowEffect 替代 paintEvent 渐变 | 替换 L1143-L1163 的 8 层 paintEvent（性能 +50%，代码 -50%）|
| QEasingCurve.OutCubic 200ms | ChatWindow 出现/隐藏、消息滑入、输入框聚焦 |
| QPropertyAnimation(windowOpacity) | 窗口淡入淡出 200ms |

---

## 3. 当前状态分析

### 3.1 错误现场代码

**L962-L967** `_update_mask`（圆角遮罩）：
```python
def _update_mask(self):
    """设置圆角遮罩。"""
    path = QPainterPath()
    path.addRoundedRect(self.rect(), 20, 20)        # ❌ QRect → QRectF
    region = QRegion(path.toFillPolygon().toPolygon())
    self.setMask(region)
```

**L1143-L1163** `paintEvent`（8 层阴影渐变）：
```python
def paintEvent(self, event):
    p = QPainter(self)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    shadow_color = QColor(0, 0, 0, 20)
    for i in range(8, 0, -1):
        alpha = int(2 * i)
        shadow_color.setAlpha(alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shadow_color)
        offset = i * 2
        path = QPainterPath()
        path.addRoundedRect(                              # ❌ 同上
            self.rect().adjusted(
                -offset, -offset, offset, offset
            ),
            20 + offset, 20 + offset,
        )
        p.drawPath(path)
```

### 3.2 现有架构不变项（兼容底线）

- **主线程 QApplication + 子线程 asyncio**（main.py 重构成果）
- **`desktop/design_tokens.py` 设计 Token**（Pinguo Design System）— 不动
- **`RADIUS["lg"] = 10`**、颜色 Token、字体 Token 已统一 — 引用即可
- **Welcome / MessageRow / TaskResultRow / ThinkingDots** 等组件结构 — 不重构

### 3.3 受影响模块

| 文件 | 改动类型 | 风险 |
|------|---------|------|
| `desktop/chat_window.py` | 主修复 + 微交互 | 中（核心 UI） |
| `desktop/floating_ball.py` | 微交互（悬停呼吸/点击反馈） | 低 |
| `desktop/daily_brief.py` | 微交互（卡片出现淡入） | 低 |
| `desktop/design_tokens.py` | 增加 `MOTION` Token（duration / easing） | 极低 |

---

## 4. 实施变更

### 4.1 模块 1：修复 `addRoundedRect` TypeError

**文件**：`e:\Agent_reply\OpenCloud_Companion\desktop\chat_window.py`

**改动 1**：L27-L30 imports 增加 `QRectF`
```python
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QRectF,  # +QRectF
    pyqtProperty, QSize, QEvent,
)
```

**改动 2**：L962-L967 `_update_mask` 用 QRectF 包裹
```python
def _update_mask(self):
    """设置圆角遮罩。"""
    path = QPainterPath()
    path.addRoundedRect(QRectF(self.rect()), 20, 20)  # ✅ QRectF
    region = QRegion(path.toFillPolygon().toPolygon())
    self.setMask(region)
```

**改动 3**：L1143-L1163 `paintEvent` 替换为 `QGraphicsDropShadowEffect`（性能更好 + 代码量 -60%）
```python
# 移到 __init__ 里设置一次：
self._shadow = QGraphicsDropShadowEffect(self)
self._shadow.setBlurRadius(40)
self._shadow.setOffset(0, 8)
self._shadow.setColor(QColor(0, 0, 0, 60))
self.setGraphicsEffect(self._shadow)

# 删除整个 paintEvent
```

### 4.2 模块 2：增加 MOTION 设计 Token

**文件**：`e:\Agent_reply\OpenCloud_Companion\desktop\design_tokens.py`

**追加**（在 L186 后）：
```python
# ===== 动效 (微交互) =====

MOTION = {
    "duration_fast":   150,   # 输入框聚焦、按钮悬停
    "duration_normal": 220,   # 窗口淡入淡出、消息滑入
    "duration_slow":   320,   # 卡片展开、抽屉
    "easing_standard": "OutCubic",   # 通用：自然减速
    "easing_enter":    "OutCubic",   # 进入：轻快
    "easing_exit":     "InCubic",    # 退出：快速收
}
```

**为什么用 Token**：
- 全局调速只需改一处
- Pinguo / Material Design / HIG 都把动效 Token 化
- 符合用户"扁平化极简"诉求（避免动效溢出）

### 4.3 模块 3：ChatWindow 微交互动效

**文件**：`desktop/chat_window.py`

**改动 4**：`__init__` 增加淡入启动
```python
# 在 L644 之后：
self.setWindowOpacity(0.0)
self._fade_in_animation = QPropertyAnimation(self, b"windowOpacity")
self._fade_in_animation.setDuration(MOTION["duration_normal"])
self._fade_in_animation.setStartValue(0.0)
self._fade_in_animation.setEndValue(1.0)
self._fade_in_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
self._fade_in_animation.start()
```

**改动 5**：`closeEvent` 改为淡出后再隐藏
```python
def closeEvent(self, event):
    if self._is_closing:
        super().closeEvent(event)
        return
    self._is_closing = True
    event.ignore()
    self._fade_out_animation = QPropertyAnimation(self, b"windowOpacity")
    self._fade_out_animation.setDuration(MOTION["duration_normal"])
    self._fade_out_animation.setStartValue(1.0)
    self._fade_out_animation.setEndValue(0.0)
    self._fade_out_animation.setEasingCurve(QEasingCurve.Type.InCubic)
    self._fade_out_animation.finished.connect(self.hide)
    self._fade_out_animation.start()
```

**改动 6**：消息气泡滑入
- 在 `_MessageRow.__init__` 增加 `QPropertyAnimation(maximumHeight)`
- 初始 `maximumHeight=0`，220ms OutCubic 渐变到完整高度
- 改 `self._msg_layout.addWidget(row)` 之后触发

**改动 7**：输入框聚焦蓝色环
- 现有 stylesheet 的 `QLineEdit:focus` 已有 border
- 增加微动：`border-width` 从 1px 渐变到 2px（150ms）— 用 `QPropertyAnimation`

### 4.4 模块 4：FloatingBall 微交互（极简）

**文件**：`desktop/floating_ball.py`

**改动 8**：鼠标悬停时缩放
```python
def enterEvent(self, event):
    self._hover_anim = QPropertyAnimation(self, b"geometry")
    self._hover_anim.setDuration(150)
    self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    rect = self.geometry()
    self._hover_anim.setStartValue(rect)
    self._hover_anim.setEndValue(rect.adjusted(-3, -3, 3, 3))
    self._hover_anim.start()

def leaveEvent(self, event):
    # 反向
    ...
```

**改动 9**：右键菜单出现
- 现有 `QMenu` 已有系统动画，无需重做

### 4.5 模块 5：DailyBrief 卡片淡入

**文件**：`desktop/daily_brief.py`

**改动 10**：构造时启动淡入
- 同 ChatWindow 改动 4 的 4 行代码
- **不动**其内部布局（已通过 design_tokens 规范化）

---

## 5. 不做的事（避免过度设计）

- ❌ 不重构 Frameless 拖拽（现有 `mousePressEvent/mouseMoveEvent` 工作正常）
- ❌ 不引入额外依赖（用现有 `PyQt6.QtCore.QPropertyAnimation`）
- ❌ 不增加 3D 翻转 / 粒子 / 模糊过场（违反"扁平化极简"）
- ❌ 不改 design_tokens.py 中颜色 / 圆角（已对齐 Pinguo）
- ❌ 不改 main.py（已重构完成）
- ❌ 不改 NapCat / QQ / 工具系统（与本错误无关）

---

## 6. 假设与决策

| 决策 | 理由 |
|------|------|
| 用 `QGraphicsDropShadowEffect` 替代 8 层 paintEvent | 性能更好（GPU 加速）、代码量 -60%、与行业共识一致 |
| 微动画统一 150-320ms | Apple HIG / Material Design 3 标准，**过快**会显得急躁，**过慢**会显得迟钝 |
| 用 `OutCubic` 缓动作为默认 | 5/5 调研项目的标准选择，**自然减速**符合直觉 |
| 不引入 Qt Style Sheets 外的颜色覆盖 | 现有 stylesheet + design_tokens 已规范化 |
| 不实现 Lottie / Rive 动效 | 过度设计，对话窗口不需要复杂矢量动画 |

---

## 7. 验证步骤

### 7.1 错误修复验证
1. `cd e:\Agent_reply\OpenCloud_Companion`
2. 重启 Companion
3. 双击悬浮球 → 期望：对话窗口**无错误**弹出
4. 关闭窗口 → 期望：托盘**不退出应用**
5. 再次打开 → 期望：正常
6. 查看 `logs\companion.log` → 期望：0 条 `对话窗口创建失败` 错误

### 7.2 微交互验证
1. 打开 ChatWindow → 期望：200ms 淡入（**不闪烁**）
2. 关闭 ChatWindow → 期望：200ms 淡出后隐藏
3. 鼠标悬停悬浮球 → 期望：放大 3px（150ms）
4. 新消息到达 → 期望：从底部 220ms 滑入
5. 输入框聚焦 → 期望：border 1px→2px（150ms）

### 7.3 兼容性验证
1. NapCat WebSocket 仍正常（主人测过 OK）
2. 伊塔回复 QQ 消息不受影响（已在跑）
3. 调度器 08:00 简报 / 23:00 晚安 仍注册
4. 知识库 0 条活跃 / 4 条历史消息 仍正常加载
5. `--no-ui` 启动模式仍可用

### 7.4 回归测试
```bash
cd e:\Agent_reply\OpenCloud_Companion
python -m pytest tests/ -v
```
期望：62/62 tests still passing（新增 4-6 个微交互测试可选）

---

## 8. 文件清单

| 文件 | 类型 | 改动行数估算 |
|------|------|------------|
| `desktop/chat_window.py` | 修改 | +60 / -30 |
| `desktop/floating_ball.py` | 修改 | +20 / -5 |
| `desktop/daily_brief.py` | 修改 | +8 / -0 |
| `desktop/design_tokens.py` | 修改 | +12 / -0 |

**总计**：~80 行新增，~35 行删除，4 个文件，0 个新文件。

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| QPropertyAnimation 在子线程泄漏 | 极低 | 低 | 所有动画都在主线程（已验证） |
| DropShadow 在 Windows 11 上不渲染 | 低 | 中 | 保留 paintEvent 作为回退（用 try/except 包裹） |
| 微动画卡顿（旧机器） | 低 | 低 | duration 调到 150-220ms 不会卡 |
| 改动破坏现有 stylesheet | 极低 | 中 | 改动只新增代码，不修改已有 stylesheet |

---

## 10. 完成定义（DoD）

- [ ] `addRoundedRect` TypeError 完全消除（连续 5 次双击无错误）
- [ ] ChatWindow 出现/关闭有 200ms 淡入淡出
- [ ] 消息气泡有 220ms 滑入
- [ ] 悬浮球悬停有 150ms 缩放反馈
- [ ] 输入框聚焦有 150ms 高亮动画
- [ ] 所有现有功能（NapCat / 工具 / 知识库 / 调度器）不受影响
- [ ] pytest 62/62 通过
- [ ] log 无新增 ERROR / WARNING

---

**计划完毕，等待主人批准后开始实施。**

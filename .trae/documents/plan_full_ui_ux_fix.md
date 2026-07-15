# Plan: 应用修复 — 图标 / 悬浮球 / 后端连接 / 数据交互全栈修复

> **目标**: 一次性修复用户报告的所有 4 类问题，使 `dist-final/win-unpacked/Aerie · 云栖.exe` 启动后能正常连接 QQ、显示数据、悬浮球可交互并显示新图标
> **状态**: Plan Mode — 等待审批后执行

---

## §1 · 当前状态分析（基于 Phase 1 探索）

### 1.1 问题诊断表

| # | 问题 | 根因 | 当前状态 |
|---|------|------|---------|
| 1 | EXE 图标为默认 Electron 蓝 e | electron-builder 24.9.0 rcedit 注入失败 / Windows 资源缓存；配置 100% 正确 | 需手动 rcedit 二次注入 + 缓存刷新 |
| 2 | 悬浮球内有"诡异滑块" | 源码 100% 干净（floating-ball.html 只有 1 个 `#ball`），很可能是 Win11 焦点框 / DevTools / 第三方桌面工具 | 关闭 DevTools + 加大 padding 防止误识别 |
| 3 | 拖动悬浮球窗口变大 | padLeft padding=16 太小，hover scale(1.1) + scale(1.05) dragging 累积超出 | 加大 padding 到 24 + fixed size + `setResizable(false)` |
| 4 | QQ 未连接 / fetch failed | 配置链路 100% 一致（端口 7890），但 Python 后端未启动或启动超 30s | 改 spawn 路径 + 延长超时 + 写 stderr 日志 |
| 5 | 数据点点击无反应 | `<pre id="data-stats">` 是纯文本，无任何交互元素 | 实现 charts + click → 详情 |
| 6 | 悬浮球点击应有"对话框→展开"两步 | 当前 `ball:expand` 直接显示主窗口 | 改为先弹模态对话框 |

### 1.2 已正确实现（不需改）

- ✓ `builder/icon.ico` (97KB, 6 尺寸 PNG-in-ICO) 已存在
- ✓ `package.json` `directories.buildResources: "builder"` + `win.icon: "builder/icon.ico"`
- ✓ 后端端口 7890 链路闭合（API server / settings.yaml / .env / main.js 配置一致）
- ✓ IPC 代理链路闭合（main → fetch → 后端）
- ✓ .env 包含 5 个真实 API key
- ✓ floating-ball 源码 100% 干净

---

## §2 · 变更计划

### Part A: 图标注入修复（A1–A2）

#### A1. 修改 `electron-builder.yml`
关闭 NSIS，改为 `target: portable`（已生效）+ 添加 `executableMetadata` 元数据。
- **不动** — 当前 portable 已生效

#### A2. 在 main.js 中加 rcedit 后置步骤
- 文件: `electron/scripts/post-build-rcedit.js` (新建)
- 包装 rcedit 调用：`rcedit "Aerie · 云栖.exe" --set-icon builder/icon.ico`
- 在 `package.json` 的 `build:win` 中改 `"build:win": "electron-builder --win --x64 && node scripts/post-build-rcedit.js"`

### Part B: 悬浮球修复（B1–B4）

#### B1. main.js — 关闭窗口 DevTools + 加大 padding
- 文件: `electron/src/main.js` L137–L164
- 改动:
  - `ballSize` 仍 64
  - `padding` 16 → **24**（足够余量）
  - `size` = 88（实际窗口尺寸）
  - `webPreferences.devTools: false`（防止 DevTools 滚动条被误为"滑块"）

#### B2. floating-ball.html — 唯一 DOM（已正确）
- 文件: `electron/src/renderer/floating-ball.html`
- 不动（已确认 100% 干净）

#### B3. floating-ball.js — 边界限制
- 文件: `electron/src/renderer/js/floating-ball.js`
- 改动: 在 `bridge.ball.move(dx, dy)` IPC 中加入 `getBounds()` 检查，clamp 到屏幕 work area

#### B4. floating-ball.css — 改用 transform-origin center
- 文件: `electron/src/renderer/styles/floating-ball.css`
- 改动: `transform-origin: center center`（避免边缘裁切视觉）

### Part C: 后端启动 & 错误反馈（C1–C4）

#### C1. main.js startPythonBackend — 写 stderr 日志
- 文件: `electron/src/main.js` L91–L110
- 改动:
  - `stdio: 'ignore'` → `stdio: ['ignore', 'pipe', 'pipe']`
  - 监听 `pythonProc.stderr.on('data', ...)` → 写入 `path.join(ROOT, 'logs', 'python_stderr.log')`
  - 这样用户能立即看到 Python 启动错误

#### C2. main.js pollBackendHealth — 延长超时 + 启动 UI 反馈
- 文件: `electron/src/main.js` `pollBackendHealth()`
- 改动:
  - `maxRetries` 15×2s → **30×2s = 60s**
  - 加 `backend:progress` 事件（每 5s 推送尝试次数），chat.js 显示"启动中（X 秒）…"
  - 错误事件细分（spawn失败/超时/连接拒绝）

#### C3. main.js getPythonPath — 增加更多 fallback
- 文件: `electron/src/main.js` L75–L89
- 改动: 增加 `%LOCALAPPDATA%\Programs\Python\` + `python.exe` (非 pythonw) 最后备选

#### C4. chat.js — 错误细分显示
- 文件: `electron/src/renderer/js/chat.js` L218–
- 改动: 区分 "启动中(秒)" / "后端未启动" / "端口被占用" / "QQ未登录" 状态

### Part D: 数据交互与悬浮球"对话框"流程（D1–D5）

#### D1. sidebar 数据 — 增加可点击图表
- 文件: `electron/src/renderer/js/sidebar.js` `refreshData()`
- 改动: 用 SVG 条形图渲染核心指标（消息数/Token 数/会话轮次/活跃度），每个条形可点击
- 文件: `electron/src/renderer/styles/main.css` 添加 `.bar-chart` 样式
- **范围控制**: 不引入第三方图表库（避免包大小膨胀 + 启动延迟），用纯 SVG

#### D2. 数据点击 → 详情弹层
- 文件: `electron/src/renderer/js/sidebar.js`
- 新增 `showDataDetail(key)` 函数 → 创建 modal overlay 显示该项完整 JSON 数据
- 文件: `electron/src/renderer/styles/main.css` 添加 `.modal-overlay` / `.modal-content` 样式

#### D3. 悬浮球点击 → 弹出"长条状对话框"
- 文件: `electron/src/renderer/floating-ball.html` & `floating-ball.js`
- 改动: 在 `<body>` 中添加 `<div id="ball-dialog" class="ball-dialog hidden">`：
  - 长条状（240×120）贴近悬浮球上方
  - 两个按钮："展开主窗口" 和 "**展开侧边栏**"
  - CSS：`position:absolute; bottom: 100%; left: 50%; transform: translateX(-50%);`

#### D4. main.js ball:expand 改为显示对话框
- 文件: `electron/src/main.js` IPC handler
- 改动:
  - `ball:expand` → `ball:showDialog`（向 renderer 发事件 `ball:showDialog`）
  - `ball:dismissDialog` → 关闭对话框
  - 关闭按钮：`ball:showMain` → 隐藏球 + 显示主窗口

#### D5. 侧边栏"展开"模式 — CSS wide 状态
- 文件: `electron/src/renderer/styles/main.css`
- 改动: 添加 `.app-shell.wide` { grid-template-columns: 480px 1fr; }
- 文件: `electron/src/renderer/js/app.js`
- 新增 `window.AerieApp.toggleSidebarWide()` → toggle `.app-shell.wide` class

---

## §3 · 实施顺序

1. **A 组（图标）**: A1-A2（图标注入 + rcedit 后置）
2. **B 组（悬浮球）**: B1-B4（窗口尺寸 + 边界限制 + transform-origin）
3. **C 组（启动）**: C1-C4（stderr 日志 + 超时延长 + 错误细分）
4. **D 组（交互）**: D1-D5（数据图表 + 详情弹层 + 悬浮球对话框 + 侧边栏 wide 模式）
5. **验证**: `npm run build:win` 重新打包到 `dist-final`

---

## §4 · 验证步骤

```powershell
# 1. 查看 EXE 资源
$ico = [System.Drawing.Icon]::ExtractAssociatedIcon("E:\Agent_reply\electron\dist-final\win-unpacked\Aerie · 云栖.exe")
$ico.ToBitmap().Save("test_exe_icon.png")
# 看提取出的图标是否"伊塔粉 Aerie"

# 2. 手动验证后端
Test-NetConnection -ComputerName 127.0.0.1 -Port 7890

# 3. 手动启动后端看 stderr
cd E:\Agent_reply
python main.py
# 看是否有 ModuleNotFoundError / SQLite 错误等

# 4. 测试启动流程
.\dist-final\win-unpacked\Aerie · 云栖.exe
# 启动后看：
#   - 悬浮球圆形 A 可见
#   - 主窗口显示
#   - QQ 状态从"启动中…" → "已连接" / 或具体错误
#   - 数据 tab 显示 chart 图表
#   - 点击图表条 → 详情 modal
#   - 点击悬浮球 → 对话框 → "展开侧边栏" → 主窗口变宽

# 5. log 验证
type E:\Agent_reply\logs\python_stderr.log
```

---

## §5 · 假设与决策

1. **不引入第三方图表库** — 避免 bundle size 增大与启动延迟，纯 SVG 实现足够
2. **窗口大小固定 88×88**（64 球 + 24 padding）— 防止 hover/dragging 任何状态下溢出
3. **悬浮球对话框采用 DOM**（不引入新 BrowserWindow）— 简单可靠，与现有架构一致
4. **stderr 日志路径**: `logs/python_stderr.log` 而非滚动到主窗口（避免 UI 复杂度）
5. **超时 60s** 而非无限等待 — 给用户清晰反馈，但允许典型启动时间（含 PS 首次 init、数据库初始化、依赖加载）
6. **数据图表默认 4 个核心指标**: 总消息数、Token 用量、活跃天数、记忆条目数（按 `/api/data/stats` 返回 keys 选择）
7. **细节美学**: 悬浮球对话框沿用现有粉紫主题（与 .ball 渐变一致），广角窗口加 200ms scale 动画过渡
8. **rcedit 二次注入在 Windows 上需要打包结束后不被任何进程占用 EXE** — 已多次 build 出现此问题；新方案：独立 step + 增加 5s 等待后再注入

---

## §6 · 不在范围内的事项

- 重新设计主窗口 UI（仅在 wide 状态加 class，不重写 layout）
- 引入真实图表库（Chart.js / ECharts） — 避免包大小膨胀
- 重写后端 API（保持现状，仅扩 startup 容错）
- 修改 5 个真实 API key 的配置（已正确）
- 重打包发版（用户只需在审批后让构建跑一次）

# 窗口布局 & 毛玻璃背景改造计划

## 一、现状分析

### 当前结构
```
┌──────────────────────────────────────┐
│ 标题栏（36px）─ 最小化/最大化/关闭    │  ← 自定义 titlebar，只有窗口控制
├──────────────────────────────────────┤
│ 状态栏（44px）─ Logo + 标题 + 状态    │  ← 独立的 statusbar
├──────────────────────────────────────┤
│ 侧边栏(72px) + 主内容区              │
└──────────────────────────────────────┘
```

### 问题
1. **顶部两个条浪费空间**（36 + 44 = 80px），内容区被往下挤
2. **背景不透明**，虽然 `transparent: true` 但 CSS 里 `body { background: var(--color-bg) }` 完全盖住了
3. 标题栏和状态栏功能部分重叠，视觉上割裂

---

## 二、改造方案

### 2.1 合并标题栏 + 状态栏

**改造后结构**：
```
┌───────────────────────────────────────────┐
│ 🌿 Logo · Aerie 云栖      后端已连接 ● ─ □ × │  ← 合并为一条 44px
├───────────────────────────────────────────┤
│ 侧边栏 + 主内容区                         │
└───────────────────────────────────────────┘
```

- 高度从 80px 减到 44px，多出 36px 内容空间
- 左边：Logo + 应用名（可拖动区域）
- 右边：状态文字 + 状态点 + 最小化/最大化/关闭按钮
- 整条都是 `-webkit-app-region: drag`，按钮单独 `no-drag`

### 2.2 毛玻璃半透明背景

使用 Electron 的 `backgroundMaterial: "acrylic"`（Windows 11 支持）+ CSS 半透明背景，实现毛玻璃效果：

- **窗口级**：Electron `backgroundMaterial: "acrylic"` 启用系统级亚克力效果
- **CSS 级**：`backdrop-filter: blur(20px) saturate(180%)` + 半透明背景色
- **窗口圆角**：保持 12px 圆角，边框用半透明描边

### 2.3 各层透明度设计

| 层级 | 透明度 | 说明 |
|------|--------|------|
| body / .app | 70-85% 不透明 | 主背景毛玻璃 |
| 侧边栏 | 比主背景稍深一点 | 层次感 |
| 聊天卡片 | 85-95% 不透明 | 清晰可读 |
| 输入框 | 95% 不透明 | 确保可读性 |

---

## 三、文件改动清单

### 3.1 Electron 主进程
- **文件**：`electron/src/main.js`
- **改动**：
  - `BrowserWindow` 加 `backgroundMaterial: "acrylic"`（Windows 11）
  - 确认 `transparent: true` 和 `frame: false` 已开启

### 3.2 HTML 结构
- **文件**：`electron/src/renderer/index.html`
- **改动**：
  - 合并 `titlebar` 和 `statusbar` 为一个 `app-header`
  - 左边：Logo + 标题
  - 右边：状态点 + 状态文字 + 窗口控制按钮

### 3.3 主样式
- **文件**：`electron/src/renderer/styles/main.css`
- **改动**：
  - `body` → 背景透明
  - `.app` → 毛玻璃背景（`backdrop-filter` + 半透明色）
  - 新增 `.app-header` 样式（合并后的顶栏）
  - 删除旧的 `.titlebar` / `.statusbar` 相关样式（或覆盖）
  - 侧边栏半透明适配
  - 聊天面板/设置面板等卡片半透明适配
  - 输入框半透明适配

### 3.4 主题色适配
- **文件**：6 个主题 CSS 文件（yita-pink / midnight-purple / sakura-white / ocean-blue / forest-green / 待定）
- **改动**：
  - 新增 `--color-bg-glass`（毛玻璃背景色，带 alpha）
  - 新增 `--color-surface-glass`（卡片毛玻璃色）
  - 新增 `--color-border-glass`（边框半透明色）

### 3.5 JS 逻辑
- **文件**：`electron/src/renderer/js/app.js`（或相关的 titlebar 控制文件）
- **改动**：
  - 确认窗口控制按钮（最小化/最大化/关闭）的事件绑定正确指向新 DOM
  - 状态更新逻辑适配新结构

---

## 四、实现步骤

1. **改 HTML**：合并 titlebar + statusbar 为 app-header
2. **改 main.js**：加 `backgroundMaterial: "acrylic"`
3. **改 main.css**：
   - body 透明
   - app 毛玻璃效果
   - 新的 app-header 样式
   - 侧边栏/内容区/卡片/输入框透明度适配
4. **改主题 CSS**：每个主题加 3 个玻璃色变量
5. **验证**：确认窗口控制、状态显示、拖动都正常

---

## 五、风险 & 注意事项

1. **Windows 版本兼容**：`backgroundMaterial: "acrylic"` 只在 Windows 11 上效果最好，Windows 10 会降级为半透明。用 CSS `backdrop-filter` 做 fallback。
2. **性能**：毛玻璃效果有一定 GPU 开销，但对现代电脑可以忽略。
3. **可读性**：太透明会导致文字看不清，需要控制透明度在 70% 以上，并确保文字有足够对比度。
4. **主题一致性**：6 个主题的玻璃色值需要逐个调整，确保每个主题都好看。

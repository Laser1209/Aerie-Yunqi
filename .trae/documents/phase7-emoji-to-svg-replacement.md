---
title: Phase 7 — 全项目 Emoji 图标 → SVG 矢量图标替换
date: 2026-07-16
tags:
  - phase7
  - svg-icons
  - iconify
  - svg-sprite
  - emoji-replacement
  - ita-persona
aliases:
  - Phase 7 Plan
  - SVG 替换 Emoji
cssclasses:
  - wide-page
---

# Phase 7 — 全项目 Emoji 图标 → SVG 矢量图标替换

> **本计划与 [[phase6-local-system-optimization]] 互补执行**（用户指令：结合 Phase 6 一起执行）
> **目标**：9 处 UI Emoji 全部替换为 SVG 矢量图标；与现有 sidebar 风格统一；高分辨率清晰
> **三原则**（沿用 Phase 6）：
>   1. **不破坏现有功能** — 所有交互/数据流保持一致
>   2. **不破坏伊塔人格** — 表情/情绪视觉仍需传达"闷骚+病娇"质感
>   3. **设计美学统一** — 描边粗细、尺寸、currentColor 着色全部对齐 sidebar（Lucide 24x24 / 2px stroke）

---

## 一、用户决策记录

| 决策点 | 决策结果 | 备注 |
|--------|----------|------|
| SVG 图标库 | **Iconify**（在线 JSON，本地落地） | 官方仓库 200,000+ 图标；只下载需用的部分 |
| 集成方式 | **SVG Sprite + `<symbol>` + `<use>` 引用** | 一次加载，所有页面共享；零运行时依赖 |
| 文件命名规范 | **`category-name-size.svg`** | 严格三段式，如 `ui_close_24.svg` |
| 与 Phase 6 关系 | 互补执行 | 在 Phase 6 改文件时同步替换 emoji，不返工 |

---

## 二、Phase 1 探索结果

### 2.1 Emoji 分布清单

| # | 文件 | 行 | Emoji | 用途 | 类别 |
|---|------|----|----|------|------|
| 1 | `electron/src/renderer/index.html` | L18 | ✕ | 标题栏关闭 | ui |
| 2 | `electron/src/renderer/index.html` | L129 | 😐 | 情绪标签（neutral） | mood |
| 3 | `electron/src/renderer/js/chat.js` | L205 | ✕ | 引用条取消 | ui |
| 4 | `electron/src/renderer/js/chat.js` | L230 | 📎 | 附件缩略图 | ui |
| 5 | `electron/src/renderer/js/chat.js` | L249 | 📋 | 消息菜单-复制 | ui |
| 6 | `electron/src/renderer/js/chat.js` | L347 | 📎 | 附件卡片 | ui |
| 7 | `electron/src/renderer/js/chat-uploader.js` | L37, L42 | 📎 | 输入区工具栏 | ui |
| 8 | `electron/src/renderer/js/emotion-dashboard.js` | L66 | ⚠ | 情绪爆发 banner | ui |
| 9 | `core/context_builder.py` | L150 | ⚠ | LLM prompt（不可见 UI） | ui/text |

**去重后需新增 5 个图标**：ui_close / ui_attach / ui_copy / ui_warning / mood_neutral

### 2.2 现有图标风格基线（sidebar）

当前 `index.html` L36-72 已使用 8 个内联 SVG：

| 元素 | 风格 | 尺寸 | stroke-width | viewBox |
|------|------|------|--------------|---------|
| sidebar 全套 | 描边轮廓（Lucide 风） | 18x18 | 2 | 24 24 |
| 发送按钮 | 描边（line + polygon） | 16x16 | 2 | 24 24 |
| 状态栏 logo | 矢量插画 | 24x24 | — | — |

**风格统一标准**：
- 尺寸：18px（默认）/ 24px（详情/动作）/`currentColor` 着色
- viewBox：`0 0 24 24`
- stroke-width：`2`
- `stroke-linecap="round"` `stroke-linejoin="round"`
- `fill="none"` `stroke="currentColor"`

### 2.3 依赖与资源

| 资源 | 用途 | 来源 |
|------|------|------|
| `@iconify-json/lucide`（~30KB） | 图标源数据 | npm 包；执行 `npm i` 安装 |
| `svg2sprite`（小工具） | 单 SVG → sprite 合并 | 一次性本地脚本，不进 bundle |
| `assets/icons/sprite.svg` | 运行时唯一资源 | 本地一次性生成 |

**Iconify → Sprite 工作流**：
1. `npm i @iconify-json/lucide` 拉取全套 Lucide JSON
2. 写 `scripts/build-icon-sprite.js`：读取需用 5 个 JSON 节点 → 转为 `<symbol id="icon-{name}">` → 拼成 `assets/icons/sprite.svg`
3. `index.html` 顶部 `<symbol>` 块本地化注入（保持单页 0 额外请求）

---

## 三、实施计划（5 Batches）

> **强约束**：每 Batch 完成后立即视觉验证
> **三原则红线**：sidebar 风格不破 / 颜色随 currentColor / 全部 24x24 viewBox

---

### Batch 1 · 图标资源准备（P0 — 必做，1.5h）

**目标**：生成 5 个分类 SVG + 1 个 sprite 雪碧图文件

**I1. 安装 @iconify-json/lucide**
- 路径：`e:\Agent_reply\electron\`
- 命令：`npm i -D @iconify-json/lucide`
- 验证：`node_modules/@iconify-json/lucide/icons.json` 存在（~5MB JSON）
- 注释：不进最终 bundle（`devDependencies`），只用于构建期

**I2. 写 `scripts/build-icon-sprite.js`**
- 新建文件: `e:\Agent_reply\electron\scripts\build-icon-sprite.js`
- 内容：
  ```js
  // 1. 读取 @iconify-json/lucide/icons.json
  // 2. 提取 5 个图标: x / paperclip / copy / triangle-alert / smile (neutral)
  // 3. 每个图标从 1024x1024 viewBox → 重写为 24x24
  // 4. 输出到 src/renderer/assets/icons/sprite.svg
  ```
- 输出格式：
  ```svg
  <svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">
    <symbol id="icon-ui-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <line x1="18" y1="6" x2="6" y2="18"/>
      <line x1="6" y1="6" x2="18" y2="18"/>
    </symbol>
    <symbol id="icon-ui-attach" ...>...</symbol>
    <symbol id="icon-ui-copy" ...>...</symbol>
    <symbol id="icon-ui-warning" ...>...</symbol>
    <symbol id="icon-mood-neutral" ...>...</symbol>
  </svg>
  ```

**I3. 写 `scripts/extract-icons.js`（辅助：单独导出单文件）**
- 用于调试和备份
- 同时输出 5 个独立 SVG 到 `assets/icons/{category}-{name}-{size}.svg`
- 命名严格遵循 `category-name-size.svg`：
  - `ui_close_24.svg`
  - `ui_attach_24.svg`
  - `ui_copy_24.svg`
  - `ui_warning_24.svg`
  - `mood_neutral_24.svg`

**I4. 一次性生成**
- 命令：`node scripts/build-icon-sprite.js && node scripts/extract-icons.js`
- 验证：
  ```powershell
  dir "e:\Agent_reply\electron\src\renderer\assets\icons"
  # 应看到: sprite.svg, ui_close_24.svg, ui_attach_24.svg, ui_copy_24.svg, ui_warning_24.svg, mood_neutral_24.svg
  ```
- 验证 sprite.svg 大小 < 10KB（5 个图标远小于此）

**验收**：`sprite.svg` 包含 5 个 `<symbol>` 节点；每个单 SVG 文件可在浏览器单独打开看到图标

---

### Batch 2 · 注入 sprite 到 index.html（P0 — 必做，30min）

**目标**：所有页面在加载时已注册 5 个 symbol，0 额外请求

**S1. index.html 顶部注入**
- 文件: `e:\Agent_reply\electron\src\renderer\index.html` L11（`</head>` 之前）
- 插入：
  ```html
  <!-- Icon sprite (Phase 7: emoji → SVG) -->
  <div id="icon-sprite-host" style="position:absolute; width:0; height:0; overflow:hidden;" aria-hidden="true">
    <!--__INLINE_SPRITE__-->
  </div>
  <script>
    // 编译期由 build.js 替换为 sprite.svg 内联内容
    // 运行时无需请求
  </script>
  ```
- 同时把 `<link rel="stylesheet" href="styles/main.css">` 后加入：
  ```html
  <link rel="stylesheet" href="styles/icons.css">
  ```

**S2. 写 `styles/icons.css`**
- 新建文件: `e:\Agent_reply\electron\src\renderer\styles\icons.css`
- 内容（统一基线）：
  ```css
  /* Phase 7: SVG 图标统一基线 */
  .icon {
    display: inline-block;
    width: 1em;
    height: 1em;
    vertical-align: -0.125em;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    flex-shrink: 0;
  }
  .icon--16 { width: 16px; height: 16px; }
  .icon--18 { width: 18px; height: 18px; }
  .icon--20 { width: 20px; height: 20px; }
  .icon--24 { width: 24px; height: 24px; }
  .icon--muted { color: var(--color-text-muted, #888); }
  ```

**S3. sprite.svg 内联工具（构建期）**
- 在 `package.json` 加 script：`"build:icons": "node scripts/build-icon-sprite.js && node scripts/inline-sprite.js"`
- `inline-sprite.js`：读 `sprite.svg` → 嵌入 `index.html` 的 `__INLINE_SPRITE__` 占位
- 开发期直接 `<use href="assets/icons/sprite.svg#icon-ui-close"/>` 引用（外链 sprite，浏览器 fetch）
- 生产期 build 时内联（避免 file:// 协议外链失败）

**验收**：打开 `index.html`（dev 模式），F12 → Elements → 看到 `icon-sprite-host` 内有 5 个 symbol；使用 `document.querySelector('#icon-ui-close')` 能找到节点

---

### Batch 3 · 替换 9 处 emoji（P0 — 必做，2h）

**目标**：所有 emoji 字面字符 → `<svg><use href="#icon-..."/></svg>` 引用

**E1. 替换 index.html**

| 位置 | 原文 | 替换为 |
|------|------|--------|
| L18 关闭按钮 | `✕` | `<svg class="icon icon--16"><use href="#icon-ui-close"/></svg>` |
| L129 情绪标签 | `<span id="emotion-label" class="emotion-label emotion-label--neutral">😐 neutral</span>` | 改为 `<svg class="icon icon--16 emotion-label__icon" id="emotion-label-icon"><use href="#icon-mood-neutral"/></svg><span id="emotion-label-text">neutral</span>` + 加 emotion.js 同步切换 icon 引用 |
| L87 发送按钮 | 已用 SVG | 不动 |
| L24 状态栏 logo | 已用 Aerie.svg | 不动 |

**E2. 替换 chat.js**

| 位置 | 原文 | 替换为 |
|------|------|--------|
| L205 引用条取消 | `✕` | `<svg class="icon icon--14"><use href="#icon-ui-close"/></svg>` |
| L230 附件缩略图 | `📎` | `<svg class="icon icon--14"><use href="#icon-ui-attach"/></svg>` |
| L249 消息菜单-复制 | `📋` | `<svg class="icon icon--14"><use href="#icon-ui-copy"/></svg>` |
| L347 附件卡片 | `📎` | `<svg class="icon icon--20"><use href="#icon-ui-attach"/></svg>` |

**E3. 替换 chat-uploader.js**

| 位置 | 原文 | 替换为 |
|------|------|--------|
| L42 附件按钮 | `📎` | `<svg class="icon icon--18"><use href="#icon-ui-attach"/></svg>` |

**E4. 替换 emotion-dashboard.js**

| 位置 | 原文 | 替换为 |
|------|------|--------|
| L66 警告 banner | `"⚠ " + data.eruption.mode + ...` | 改为创建 `<svg class="icon icon--16 banner__icon"><use href="#icon-ui-warning"/></svg>` + 文本节点 |
| 顺便扩展：5 种情绪各自 icon | （新增功能） | 5 个 mood 图标：neutral/joy/sad/anger/fear → 同步更新 `#emotion-label-icon` 的 `href` |

**E5. 同步 emotion-dashboard.js 的 mood 切换逻辑**
- 文件: `e:\Agent_reply\electron\src\renderer\js\emotion-dashboard.js`
- 现状：只显示 `😐 neutral`
- 改动：增加情绪 → icon 映射表
  ```js
  const MOOD_ICONS = {
    joy: '#icon-mood-joy',
    sad: '#icon-mood-sad',
    anger: '#icon-mood-anger',
    fear: '#icon-mood-fear',
    neutral: '#icon-mood-neutral',
  };
  ```
- 在 `_renderEmotion()` 中同步切换 `#emotion-label-icon use` 的 `href`

**E6. 扩展 sprite（补全 4 个 mood 图标）**
- 文件: `e:\Agent_reply\electron\src\renderer\assets\icons\sprite.svg`
- 增加 4 个 symbol：
  - `icon-mood-joy`（笑脸 circle + eyes + smile curve）
  - `icon-mood-sad`（圆 + 弯眉 + 弧嘴）
  - `icon-mood-anger`（圆 + 倒 V 眉 + 直线嘴）
  - `icon-mood-fear`（圆 + 弯眉 + 椭圆嘴）
- 来源：继续用 Iconify Lucide → `smile / frown / angry / meh` 4 个图标
- 同步输出 4 个单文件：`mood_joy_24.svg` / `mood_sad_24.svg` / `mood_anger_24.svg` / `mood_fear_24.svg`
- 重新跑 `npm run build:icons`

**验收**：
- 所有 9 处 emoji 字面字符在仓库搜索时**只剩 context_builder.py L150** 一处（LLM prompt 内）
- 浏览器中：9 处全部显示为 Lucide 风描边 SVG
- 情绪切换时 `#emotion-label-icon` 的 use 引用随之改变

---

### Batch 4 · context_builder.py 的 ⚠ 处理（P1 — 30min）

**目标**：LLM prompt 内的 ⚠ 字符不破坏（AI 仍能识别为警告），但 UI 端显示用 SVG

**W1. 保留 prompt 文本不变**
- 文件: `e:\Agent_reply\core\context_builder.py` L150
- 当前：`system += f"\n**⚠ 情绪爆发：{mode_label}**\n"`
- 决策：**保持原样**
- 原因：⚠ 是 LLM 视觉提示符号，AI 能识别为"警告段落开头"；改为其他字符可能影响输出语气

**W2. 文档注释补全**
- 文件: `e:\Agent_reply\core\context_builder.py` L150 上方加注释：
  ```python
  # Phase 7: ⚠ 字符保留（LLM 语义提示）；UI 端由 emotion-dashboard.js 渲染为 SVG
  ```
- 在 `e:\Agent_reply\.trae\documents\phase7-emoji-to-svg-replacement.md`（本文件）记录此决策原因

**W3. 后端日志中的 emoji 处理（可选）**
- 文件: `core/napcat_launcher.py`、`communication/*.py`
- 现状：日志中含 🎉、✅、❌ 等状态符号
- 决策：**本次不替换**（这些是开发者日志，不是用户 UI；终端渲染正常）
- 后续 phase 可选处理

**验收**：grep `[\x{1F300}-\x{1F9FF}]` 整个 `electron/src` 目录返回 0 结果（仅 context_builder.py 残留，但已注释说明）

---

### Batch 5 · 跨平台视觉验证 + 自动化测试（P1 — 必做，2h）

**目标**：所有替换在 4 档 DPI/3 主题下都清晰；写自动化防退化

**V1. DPI 测试矩阵**
- 设备模拟：
  - 100% (96 DPI) — 常规
  - 125% (120 DPI) — 默认 Windows
  - 150% (144 DPI) — Surface
  - 200% (192 DPI) — 4K
- 操作：开发者工具 → 设备工具栏 → DPR 切换
- 检查点：所有 SVG 在各 DPR 下都无锯齿、不模糊、不变形

**V2. 主题切换测试**
- 5 个主题（yita-pink / midnight-purple / sakura-white / ocean-blue / forest-green）
- 检查点：所有 SVG 颜色随 currentColor 切换；不存在"白色 SVG 配白主题看不见"问题

**V3. 加自动化校验脚本**
- 新建文件: `e:\Agent_reply\electron\scripts\check-emojis.js`
- 内容：
  ```js
  // 1. 扫描 electron/src 下所有 .html / .js / .css
  // 2. 检测是否含 emoji 正则
  // 3. 输出违规位置（白名单：context_builder.py）
  // 4. 非 0 退出码 = CI 失败
  ```
- 在 `package.json` 加：
  ```json
  "scripts": {
    "check:emojis": "node scripts/check-emojis.js",
    "prebuild": "npm run check:emojis && npm run build:icons"
  }
  ```

**V4. 视觉回归截图**
- 工具：Playwright / 手测
- 操作：
  1. 启动 dev 模式
  2. 切换各主题截图
  3. 触发各种情绪切换截图
  4. 触发附件上传 / 复制按钮悬浮截图
- 存档：`e:\Agent_reply\electron\test\regression\phase7-*.png`

**V5. 性能验证**
- 旧版本：9 个 emoji 字面（0 字节）
- 新版本：sprite.svg ~3KB 内联 + 0 额外请求
- 检查：Network 面板无任何图标相关请求
- 检查：首屏渲染时间无回退

**验收**：
- CI `npm run check:emojis` 通过
- 5 主题 × 4 DPI × 3 截图 = 60 张回归图视觉一致
- bundle 增量 ≤5KB

---

## 四、5 个核心 SVG 图标规格表

| 名称 | 类别 | 尺寸 | viewBox | 描边 | 颜色 | 用途 |
|------|------|------|---------|------|------|------|
| `ui_close_24.svg` | ui | 24 | 24 24 | 2 | currentColor | 关闭 / 取消 |
| `ui_attach_24.svg` | ui | 24 | 24 24 | 2 | currentColor | 附件（钉子 + 弯角） |
| `ui_copy_24.svg` | ui | 24 | 24 24 | 2 | currentColor | 复制（双层矩形） |
| `ui_warning_24.svg` | ui | 24 | 24 24 | 2 | currentColor | 警告（三角 + 感叹号） |
| `mood_neutral_24.svg` | mood | 24 | 24 24 | 2 | currentColor | 平静情绪（圆 + 平嘴） |
| `mood_joy_24.svg` | mood | 24 | 24 24 | 2 | currentColor | 喜悦 |
| `mood_sad_24.svg` | mood | 24 | 24 24 | 2 | currentColor | 悲伤 |
| `mood_anger_24.svg` | mood | 24 | 24 24 | 2 | currentColor | 愤怒 |
| `mood_fear_24.svg` | mood | 24 | 24 24 | 2 | currentColor | 恐惧 |

**全部遵循**：
- `fill="none"` `stroke="currentColor"` `stroke-width="2"`
- `stroke-linecap="round"` `stroke-linejoin="round"`
- viewBox 严格 `0 0 24 24`
- 单色 + currentColor 着色

---

## 五、与 Phase 6 的协作

| Phase 6 项目 | 涉及 emoji | 本 Phase 7 处理方式 |
|--------------|------------|---------------------|
| B1 Logo | 无 | — |
| B2 窗口控制 | ✕ (关闭按钮) | **同 E1 L18** |
| B3 数据联通 | 无 | — |
| B4 人格编辑 | 无（新增 SVG 头像上传预览） | 给 B4 用 `<svg class="icon icon--24">` 包裹占位 |
| B5 输入框重构 | 📎 (附件按钮) + ✕ (引用条) | **同 E2/E3** |
| B6 Whisper | 🎤 (语音按钮) | 在 Phase 6 B5 同步用 SVG 替换（mic 图标） |
| B7 悬浮球 | 💬⚙✕ (菜单) | Phase 6 B7 创建桌宠 SVG 时**强制走 icons.css 基线** |
| B8 收尾 | 无 | — |

**强制约束**：Phase 6 的 B4/B5/B7 在提交代码前必须 `npm run check:emojis` 通过；CI 阻断

---

## 六、文件清单（按状态分类）

### 6.1 新建文件

| 文件 | 用途 |
|------|------|
| `electron/scripts/build-icon-sprite.js` | Iconify JSON → sprite.svg |
| `electron/scripts/extract-icons.js` | Iconify JSON → 5+4 单文件 SVG |
| `electron/scripts/inline-sprite.js` | sprite.svg 内联到 index.html |
| `electron/scripts/check-emojis.js` | CI 防退化扫描 |
| `electron/src/renderer/assets/icons/sprite.svg` | 5+4 symbols 雪碧图 |
| `electron/src/renderer/assets/icons/ui_close_24.svg` | 关闭图标单文件 |
| `electron/src/renderer/assets/icons/ui_attach_24.svg` | 附件图标单文件 |
| `electron/src/renderer/assets/icons/ui_copy_24.svg` | 复制图标单文件 |
| `electron/src/renderer/assets/icons/ui_warning_24.svg` | 警告图标单文件 |
| `electron/src/renderer/assets/icons/mood_neutral_24.svg` | 平静情绪单文件 |
| `electron/src/renderer/assets/icons/mood_joy_24.svg` | 喜悦情绪单文件 |
| `electron/src/renderer/assets/icons/mood_sad_24.svg` | 悲伤情绪单文件 |
| `electron/src/renderer/assets/icons/mood_anger_24.svg` | 愤怒情绪单文件 |
| `electron/src/renderer/assets/icons/mood_fear_24.svg` | 恐惧情绪单文件 |
| `electron/src/renderer/styles/icons.css` | 图标基线 CSS |

### 6.2 修改文件

| 文件 | 改动 |
|------|------|
| `electron/src/renderer/index.html` | L18、L129 emoji → SVG；L11 注入 sprite host；引入 icons.css |
| `electron/src/renderer/js/chat.js` | L205、L230、L249、L347 emoji → SVG |
| `electron/src/renderer/js/chat-uploader.js` | L42 emoji → SVG |
| `electron/src/renderer/js/emotion-dashboard.js` | L66 emoji → SVG；新增 5 mood icon 切换 |
| `core/context_builder.py` | L150 加注释说明保留 ⚠ 原因 |
| `electron/package.json` | +`@iconify-json/lucide` devDep；+build:icons/check:emojis/prebuild 脚本 |

---

## 七、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Iconify 库 npm 包 5MB 太大 | 仓库体积膨胀 | 仅 devDependencies；不进 bundle；CI 缓存可解 |
| sprite.svg 内联后 HTML 变大 | 首屏多 3KB | 内联 < 外链 + 缓存收益；可接受 |
| file:// 协议下 `<use href="sprite.svg#..."/>` 外链失败 | 离线模式显示不出 | 构建期内联到 HTML（生产路径）；开发期走 http-server |
| `currentColor` 在某些 emoji 替代位置失效 | 颜色不对 | CSS 用 `.icon { color: inherit; }` + 父元素指定色 |
| Phase 6 与 Phase 7 文件冲突 | 同一文件被两边同时改 | 强制串行：先 Phase 7 完成再 Phase 6；或 Phase 6 在 B5 提交时同时跑 `check:emojis` |
| 5 主题色 + 4 DPI 视觉回退 | 锯齿/看不清 | 全部 SVG 路径清晰；测试矩阵在 V1 强制跑 |
| context_builder.py 的 ⚠ 改为其他字符 | LLM 失去警告语义 | **保留**；仅加注释说明 |
| 4 个 mood 图标语义不准 | 情绪错位 | 用 Iconify 官方标准 emoji-equivalent 图标（smile/frown/angry/meh） |
| `<use>` 在 Electron 老版本不工作 | 图标不显示 | Electron ≥22 已支持；本项目 Electron 24+ 安全 |

---

## 八、验证脚本汇总

```powershell
# 1. 资源生成
cd e:\Agent_reply\electron
npm install --save-dev @iconify-json/lucide
node scripts/build-icon-sprite.js
node scripts/extract-icons.js
dir src\renderer\assets\icons

# 2. 内联到 HTML
node scripts/inline-sprite.js

# 3. 静态扫描
node scripts/check-emojis.js
# 应输出: "✓ No emojis found in UI files"

# 4. 启动验证
npm start
# 浏览器开 DevTools → 切主题 → 切情绪 → 上传附件 → 验证 SVG 全部正常

# 5. 回归测试
# 切 5 主题 × 4 DPI × 3 场景 = 60 张截图

# 6. 性能
# Network 面板应无图标资源请求
# Performance → 首屏时间 ±0ms
```

---

## 九、交付物清单

- [ ] 9 个单文件 SVG（按命名规范）
- [ ] 1 个 sprite.svg（含 9 个 symbol）
- [ ] icons.css 基线样式
- [ ] check-emojis.js CI 脚本
- [ ] 修改后的 index.html / chat.js / chat-uploader.js / emotion-dashboard.js
- [ ] context_builder.py 注释补全
- [ ] package.json scripts 扩展
- [ ] 视觉回归截图存档（60 张）
- [ ] 本 plan 文档同步到 [[OpenCloud_Companion_System_Features]] 第 14 章

---

## 十、不在范围内的事项

- 替换 `voice/` 模块日志中的 emoji（开发日志，非用户 UI）
- 替换 `core/api_server.py` / `core/*.py` 的异常提示 emoji（同样为开发日志）
- 替换第三方 README 文档示例
- 引入完整的 Iconify 200,000+ 图标库（按需下载原则）
- 重写 sidebar 现有 8 个 SVG（已经符合规范）

---

> **签批等待**：本 plan 涉及 9 处 emoji 替换 + 9 个 SVG 资源生成 + CI 自动化。预计 7.5h。
> 关键时序：先 Phase 7（icon 资源）→ 后 Phase 6（功能改造时同步引用 SVG）
> 不破坏现有 sidebar 风格为红线；emoji 完全清零为目标。

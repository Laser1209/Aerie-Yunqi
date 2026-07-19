# Spotlight 项目展示页：提示词适配 + 建站计划

## Summary

分两步完成：

1. **适配提示词**：以 `e:\Agent_reply\documents\prompt\web.md`（Codex 提示词，深色电影感「liquid glass」设计机构落地页）为蓝本，适配为 **Aerie · 云栖项目展示页**的提示词，输出为 Obsidian Flavored Markdown 文件 `e:\Agent_reply\documents\prompt\web-spotlight.md`。
2. **按新提示词建站**：在空目录 `e:\Agent_reply\Spotlight` 内搭建 React + Vite + TypeScript + Tailwind + Framer Motion 单页站点（Hero + Capabilities 两个全屏 section），实现提示词描述的全部内容。

### 用户已确认的适配方向

| 决策点 | 结论 |
| --- | --- |
| 展示内容 | Aerie · 云栖项目本体（非设计机构、非多项目作品集） |
| 提示词语言 | 中文 |
| 页面文案 | 中英混合：主标题/品牌英文（Instrument Serif 斜体），正文/标签中文 |
| 背景媒体 | 保留原提示词的两个 CloudFront 视频 URL |

---

## Current State Analysis

- `e:\Agent_reply\Spotlight\` — **空目录**，无任何脚手架，需要从零初始化 Vite 工程。
- `e:\Agent_reply\documents\prompt\web.md` — 源提示词（英文，已通读），规定了：技术栈、双字体（Instrument Serif italic + Barlow）、`.liquid-glass` / `.liquid-glass-strong` CSS、`FadingVideo` / `BlurText` 组件、Hero 与 Capabilities 两节的结构/样式/动画参数、自定义 SVG 图标、依赖清单与设计原则。
- 本项目事实来源（用于替换展示内容）：
  - [README.md](file:///e:/Agent_reply/README.md)：Aerie · 云栖 = 本地优先 AI 桌面伴侣；Electron 桌面壳 + Python 智能内核 + NapCat 接 QQ；特性表含办公模式、情感引擎（PAD）、主动推送、电脑操控（3 级权限）、文件整理、文档写作、自进化 L4、20+ 工具、5+ 主题、14 类故障自愈等。
  - [aerie_architecture_poster_philosophy.md](file:///e:/Agent_reply/documents/aerie_architecture_poster_philosophy.md)：Frozen Blueprint 设计哲学（冰蓝色域 + 深红点缀）——仅作内容参考，不改变黑底 liquid glass 视觉方案。
- 根目录已有 `electron/`（Node 工程，含 node_modules 使用痕迹），说明本机具备 Node/npm 环境；执行阶段第一步仍会验证 `node -v` / `npm -v`（计划阶段探测命令意外挂起，已终止，无影响）。

---

## Proposed Changes

### Part 1 — 适配提示词文件

**新建** `e:\Agent_reply\documents\prompt\web-spotlight.md`（Obsidian Flavored Markdown，全文中文）：

- **Frontmatter**：`title: Spotlight · Aerie 云栖项目展示页提示词`、`tags: [prompt, spotlight, web-design]`、`aliases: [Spotlight 展示页 Prompt]`、`source: "[[web]]"`（双链指向源提示词）。
- **正文结构**（沿用源提示词的章节骨架，逐节替换内容）：
  1. `## 目标` — 一句话：在 `e:\Agent_reply\Spotlight` 构建 Aerie · 云栖项目展示单页（React+Vite+TS+Tailwind+Framer Motion，两节全屏）。
  2. `## 字体` — 不变（Instrument Serif italic 标题 / Barlow 正文，`<link>` 加载，Tailwind `fontFamily` 扩展）。
  3. `## Liquid Glass CSS` — 逐字保留 `.liquid-glass` / `.liquid-glass-strong` 全部参数（gradient stroke border、mask composite、blur 数值等）。
  4. `## FadingVideo 组件` — 保留全部 5 条行为规约。
  5. `## BlurText 组件` — 保留全部动画参数（blur 10→0、y 50→0、0.7s、stagger 100ms、IntersectionObserver 0.1）。
  6. `## 第一节：Hero` — 结构/样式类名不变，**内容替换**：
     - 导航：左侧圆形 logo 保留斜体 "a"（恰好契合 Aerie）；中间链接改为 `["Features", "Architecture", "Capabilities", "Journal", "Download"]`；CTA "Start a Project" → "获取便携版"（ArrowUpRight 图标保留）。
     - Badge："New" + `v0.1.0-beta.1 · 本地优先 AI 桌面伴侣`。
     - 主标题（BlurText，英文大字）：`"Your Private AI, Always Within Reach"`（保持 6xl–[5.5rem]、leading-[0.8]、tracking-[-4px]）。
     - 副文案（中文）：`Aerie · 云栖由 Electron 桌面壳与 Python 智能内核组成，办公学习、情感陪伴、电脑操控、主动关怀——一个就够了。`
     - CTA 按钮："获取便携版"（liquid-glass-strong）+ "观看演示"（Play 图标）。
     - 统计卡 ×2：Clock 图标 `7×24` / `全天候待命的桌面伴侣`；Globe 图标 `20+` / `内置工具系统，开箱即用`。
     - 底部信任条：`深受效率玩家与 AI 爱好者喜爱` + 技术栈词替换 logo 墙：`["Electron", "Python", "NapCat", "Qwen", "DeepSeek"]`（font-heading italic）。
     - 所有 motion 元素沿用共享 initial/animate 规约（blur 10→0、y 20、0.8s easeOut）。
  7. `## 第二节：Capabilities` — 结构/类名不变，**内容替换**：
     - Label `// Capabilities` 保留；标题 `Studio craft,\nend to end` → `One companion,\nend to end`。
     - 三卡片（图标 + 标签 + 中文正文）：
       | 卡片 | 图标 | 标签 | 正文（中文） |
       | --- | --- | --- | --- |
       | **Office Mode 办公模式** | ImageIcon→文档风 | 文档写作 / 文件整理 / 任务检测 / 豆包优先 | 7 大办公工具与智能任务检测，从文档写作到文件整理，预览执行、7 天可撤销，办公学习一个就够了。 |
       | **Emotion 情感引擎** | LightbulbIcon | PAD 模型 / 人设切换 / 主动关怀 / QQ 接入 | PAD 三维情感模型与可切换人设，事件驱动的主动推送，经 NapCat 接入 QQ——陪伴不止于问答。 |
       | **Control 电脑操控** | MovieIcon→控制风 | 3 级权限 / 键鼠自动化 / 截图 / 自进化 L4 | 三级权限的键鼠与 UIA 自动化、截图理解，配合自进化 L4 的 4 道安全闸门与 24 小时回滚，强大且可控。 |
     - 卡片布局参数（min-h-[360px]、tags 右对齐、底部标题+正文）全部保留。
  8. `## 自定义 SVG 图标` — 保留 7 个图标规约（允许 Office/Control 卡换用更贴切的填充图标，在提示词中注明）。
  9. `## 依赖` — react、react-dom、framer-motion、tailwindcss@3、postcss、autoprefixer、vite、@vitejs/plugin-react、typescript。
  10. `## 设计原则` — 保留原 7 条，追加 2 条：页面文案中英混排规则（标题英文斜体 / 正文中文 Barlow）；内容事实以 `README.md` 特性表为准。
- 使用 Obsidian 语法：frontmatter properties、`[[web]]` 双链、至少一个 `> [!note]` callout（标注「内容与事实来源」）、表格。

### Part 2 — 在 Spotlight 内建站

在 `e:\Agent_reply\Spotlight` 下（空目录，直接初始化，不需子文件夹）：

1. **脚手架**：`npm create vite@latest . -- --template react-ts` → `npm install` → 安装 `framer-motion` 与 `tailwindcss@3 postcss autoprefixer` → `npx tailwindcss init -p`。
2. **文件清单**（严格按新提示词实现）：
   - `index.html` — Google Fonts `<link>`（Instrument Serif ital + Barlow 300/400/500/600）、`<title>Aerie · 云栖</title>`。
   - `tailwind.config.js` — `content: ["./index.html","./src/**/*.{ts,tsx}"]`，`fontFamily.heading/body` 扩展。
   - `src/index.css` — `@tailwind` 三指令 + `html,body` 黑底白字 + `.liquid-glass` / `.liquid-glass-strong`（含 `::before` 渐变描边与 mask 复合，逐字按提示词）。
   - `src/components/FadingVideo.tsx` — 渐入/渐出/循环（单源重置、多源轮播），autoPlay muted playsInline preload="auto"。
   - `src/components/BlurText.tsx` — 逐词模糊入场（Framer Motion + IntersectionObserver）。
   - `src/components/icons.tsx` — ArrowUpRight / Play / Clock / Globe / Document / Lightbulb / Control 共 7 个 24×24 SVG。
   - `src/sections/Hero.tsx` — 固定导航 + 徽章 + BlurText 主标题 + 副文案 + 双 CTA + 双统计卡 + 底部信任条；背景 FadingVideo（URL①，120% 尺寸、object-top）。
   - `src/sections/Capabilities.tsx` — Label + 大标题 + 三卡片网格；背景 FadingVideo（URL②，inset-0 全覆盖）。
   - `src/App.tsx` — 两个 section 顺序渲染；`src/main.tsx` 不动。
3. **内容**：与 Part 1 提示词中的文案/数据逐字一致（不自由发挥）。
4. **清理**：删除 Vite 模板默认的 `App.css`、示例 assets 引用。

---

## Assumptions & Decisions

- Tailwind 固定用 **v3**（`tailwindcss@3`），因提示词采用 config 扩展写法；不用 v4 的 CSS-first 方案，避免偏离提示词。
- 两个视频 URL 直接硬编码于组件调用处（与源提示词一致），不做本地缓存。
- 页面无路由、无状态管理需求，不加额外依赖；CTA 按钮为装饰性（展示页），不接线。
- 若 `npm create vite` 交互受阻，回退为手写 `package.json`/`vite.config.ts`/`tsconfig` 后 `npm install`。
- 提示词文件使用 Obsidian 语法但保持对 Codex 类工具可读（代码块内均为标准 CSS/JS 片段）。

## Verification

1. `cd e:\Agent_reply\Spotlight && npm run build` — TypeScript 编译 + Vite 构建零报错。
2. `npm run dev` 启动后浏览器核对：两节全屏、视频自动播放且首尾淡入淡出、BlurText 逐词模糊入场、liquid glass 渐变描边可见、移动端断点（导航折叠、卡片单列）正常。
3. 对照 `web-spotlight.md` 逐项核对文案与样式参数。

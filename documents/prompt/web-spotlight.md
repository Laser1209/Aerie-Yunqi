---
title: Spotlight · Aerie 云栖项目展示页提示词
tags:
  - prompt
  - spotlight
  - web-design
aliases:
  - Spotlight 展示页 Prompt
source: "[[web]]"
date: 2026-07-20
---

# Spotlight · Aerie 云栖项目展示页提示词

> [!note] 内容与事实来源
> 本提示词由 [[web]]（深色电影感 liquid-glass 设计机构落地页 Codex 提示词）适配而来，展示对象替换为 **Aerie · 云栖**（本地优先 AI 桌面伴侣）。所有产品事实（功能点、数量、架构）以项目根目录 `README.md` 的特性表为准，不得虚构。

## 目标

在 `e:\Agent_reply\Spotlight` 目录下，使用 React + Vite + TypeScript + Tailwind CSS 构建一个单页站点，**恰好包含两个全屏 section（Hero 与 Capabilities）**。页面为黑色电影感的 Aerie · 云栖项目展示页，使用「liquid glass」液态玻璃拟态 UI 元素，并用 Framer Motion 实现平滑的模糊/淡入动画。

---

## 字体（Google Fonts）

通过 `index.html` 中的 `<link>` 加载：

- **Instrument Serif**（italic）—— 用于所有标题（`font-heading`）
- **Barlow**（字重 300, 400, 500, 600）—— 用于正文（`font-body`）

Tailwind 配置扩展 `fontFamily`：

```js
heading: ["'Instrument Serif'", 'serif'],
body: ["'Barlow'", 'sans-serif'],
```

基础 CSS：`html, body { background: #000; color: #fff; font-family: 'Barlow', sans-serif; }`

---

## Liquid Glass CSS（写在 index.css 中）

两个变体均定义为纯 CSS 类。

**`.liquid-glass`**（纤细）：

- `background: rgba(255, 255, 255, 0.01)`，`background-blend-mode: luminosity`
- `backdrop-filter: blur(4px)` / `-webkit-backdrop-filter: blur(4px)`
- 无 border；`box-shadow: inset 0 1px 1px rgba(255,255,255,0.1)`
- `position: relative; overflow: hidden`
- `::before` 伪元素生成渐变描边：
  - `position: absolute; inset: 0; border-radius: inherit; padding: 1.4px`
  - `background: linear-gradient(180deg, rgba(255,255,255,0.45) 0%, rgba(255,255,255,0.15) 20%, rgba(255,255,255,0) 40%, rgba(255,255,255,0) 60%, rgba(255,255,255,0.15) 80%, rgba(255,255,255,0.45) 100%)`
  - 以 mask 挖出描边：`-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); -webkit-mask-composite: xor; mask-composite: exclude;`
  - `pointer-events: none`

**`.liquid-glass-strong`**（更厚重）：

- 结构相同，但 `backdrop-filter: blur(50px)`
- `box-shadow: 4px 4px 4px rgba(0,0,0,0.05), inset 0 1px 1px rgba(255,255,255,0.15)`
- `::before` 渐变在两端用 0.5 透明度、20%/80% 处用 0.2

---

## FadingVideo 组件

一个可复用的 `<video>` 组件，接收 `src`（string 或 string[]）、`className`、`style`。行为：

1. 初始 `opacity: 0`
2. `loadeddata` 时，用 `requestAnimationFrame` 在 500ms 内淡入
3. `timeupdate` 时，剩余时间 <= 0.55s 则在 550ms 内淡出
4. `ended` 时：单源则 `currentTime` 归零重播并重新淡入；数组则切换到下一个索引（循环）
5. 视频属性固定为 `autoPlay`、`muted`、`playsInline`、`preload="auto"`

---

## BlurText 组件

基于 Framer Motion 的逐词模糊入场组件：

- 按空格拆分 `text` prop
- 每个词是一个 `motion.span`，`display: inline-block`，`marginRight: 0.28em`
- 由 IntersectionObserver 触发（threshold 0.1）
- 每个词动画：`filter` 从 `blur(10px)` 到 `blur(0px)`，`opacity` 0→1，`y` 50→0
- 每词时长 0.7s，按词序 stagger 延迟 100ms
- 容器：`display: flex; flexWrap: wrap; justifyContent: center; rowGap: 0.1em`

---

## 第一节：Hero

- 全视口高度（`h-screen`），`overflow-hidden`，`bg-black`
- **背景视频**：单个 `<FadingVideo>`：
  - `src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260619_191346_9d19d66e-86a4-47f7-8dc6-712c1788c3b2.mp4"`
  - 定位：`absolute left-1/2 top-0 -translate-x-1/2 object-cover object-top z-0`
  - 内联样式：`width: 120%; height: 120%`
- **内容**（`relative z-10, flex flex-col h-full`）：

**导航栏**（fixed，`top-4 left-0 right-0 z-50`，两端分布，`px-8 lg:px-16`）：

- 左：`liquid-glass` 圆形（h-12 w-12 rounded-full），使用项目资源 `e:\Agent_reply\Aerie · 云栖.svg` 作为 Logo；实现时复制为站点静态资源 `/aerie-logo.svg`，图片显示尺寸 `h-8 w-8 object-contain`
- 中（移动端隐藏，`md:flex`）：`liquid-glass rounded-full px-1.5 py-1.5` 胶囊，内含链接 ["Features", "Architecture", "Capabilities", "Journal", "Download"]，各为 `px-3 py-2 text-sm font-medium text-white/90 font-body`；末尾一个白色 CTA「获取便携版」，使用 `<a download>` 下载 `e:\Agent_reply\electron\dist-final\Aerie · 云栖-0.1.0-beta.1-Setup.exe`（复制到站点静态资源目录）并带 ArrowUpRight 图标
- 右：空白 `h-12 w-12` 占位 div

**主内容**（居中，`flex-1 flex flex-col items-center justify-center pt-24 px-4 text-center`）：

- **徽章**（motion.div，delay 0.4）：`liquid-glass rounded-full` 胶囊，内含白色 "New" 小徽章 + 文案 `v0.1.0-beta.1 · 本地优先 AI 桌面伴侣`
- **主标题**（mt-6，max-w-3xl）：`<BlurText>`，文本 `"Your Private AI, Always Within Reach"`，类名 `text-6xl md:text-7xl lg:text-[5.5rem] font-heading italic text-white leading-[0.8] tracking-[-4px]`
- **副文案**（motion.p，delay 0.8，mt-4）：`Aerie · 云栖由 Electron 桌面壳与 Python 智能内核组成，办公学习、情感陪伴、电脑操控、主动关怀——一个就够了。` —— `text-sm md:text-base text-white max-w-2xl font-body font-light leading-tight`
- **CTA 按钮组**（motion.div，delay 1.1，mt-6，flex gap-6）：「获取便携版」用 `liquid-glass-strong rounded-full px-5 py-2.5` + ArrowUpRight，并使用与导航 CTA 相同的 `<a download>` 安装包下载链接；「观看演示」纯文本 + Play 图标
- **统计卡**（motion.div，delay 1.3，mt-8，flex gap-4）：两张 `liquid-glass p-5 w-[220px] rounded-[1.25rem]` 卡片：
  - 卡片 1：ClockIcon，`7×24`，`全天候待命的桌面伴侣`
  - 卡片 2：GlobeIcon，`20+`，`内置工具系统，开箱即用`
  - 数字样式：`text-4xl font-heading italic tracking-[-1px] leading-none mt-4`

**底部信任条**（motion.div，delay 1.4，flex-col items-center gap-4 pb-8）：

- `liquid-glass rounded-full` 胶囊：`深受效率玩家与 AI 爱好者喜爱`
- 技术栈词排成一行（gap-12 md:gap-16）：["Electron", "Python", "NapCat", "Qwen", "DeepSeek"]，各为 `font-heading italic text-2xl md:text-3xl tracking-tight`
- **所有 motion 元素**共用 initial/animate：`{ filter: 'blur(10px)', opacity: 0, y: 20 }` → `{ filter: 'blur(0px)', opacity: 1, y: 0 }`，时长 0.8s，easeOut

---

## 第二节：Capabilities

- `min-h-screen`，`overflow-hidden`，`bg-black`，relative
- **背景视频**：`<FadingVideo>`：
  - `src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260622_093722_ccfc7ebf-182f-419f-8a62-2dc02db7dd9d.mp4"`
  - `absolute inset-0 w-full h-full object-cover z-0`
- **内容**（`relative z-10 px-8 md:px-16 lg:px-20 pt-24 pb-10 flex flex-col min-h-screen`）：
- **头部**（mb-auto）：
  - Label：`text-sm font-body text-white/80 mb-6` —— `// Capabilities`
  - 标题：`font-heading italic text-6xl md:text-7xl lg:text-[6rem] leading-[0.9] tracking-[-3px]` —— `One companion,\nend to end`
- **卡片网格**（mt-16，`grid grid-cols-1 md:grid-cols-3 gap-6`），三张卡片：

| 卡片 | 图标 | 标签 | 正文 |
| --- | --- | --- | --- |
| **Office Mode 办公模式** | DocumentIcon（填充文档图标） | 文档写作 / 文件整理 / 任务检测 / 豆包优先 | 7 大办公工具与智能任务检测，从文档写作到文件整理，预览执行、7 天可撤销，办公学习一个就够了。 |
| **Emotion 情感引擎** | LightbulbIcon | PAD 模型 / 人设切换 / 主动关怀 / QQ 接入 | PAD 三维情感模型与可切换人设，事件驱动的主动推送，经 NapCat 接入 QQ——陪伴不止于问答。 |
| **Control 电脑操控** | ControlIcon（填充控制/滑杆图标） | 3 级权限 / 键鼠自动化 / 截图 / 自进化 L4 | 三级权限的键鼠与 UIA 自动化、截图理解，配合自进化 L4 的 4 道安全闸门与 24 小时回滚，强大且可控。 |

- 每张卡片：`liquid-glass rounded-[1.25rem] p-6 min-h-[360px] flex flex-col`
- 顶行：图标放在嵌套的 `liquid-glass h-11 w-11 rounded-[0.75rem]` 方块中 + 标签组（flex-wrap，gap-1.5）右对齐，每个标签为 `liquid-glass rounded-full px-3 py-1 text-[11px] text-white/90 font-body whitespace-nowrap`
- 间隔：`flex-1`
- 底部：标题 `font-heading italic text-3xl md:text-4xl tracking-[-1px] leading-none` + 正文 `text-sm text-white/90 font-body font-light leading-snug max-w-[32ch]`

---

## 自定义 SVG 图标（无需外部图标库）

- **ArrowUpRight**：24x24，描边，路径 "M7 17L17 7" 与 "M7 7h10v10"
- **Play**：24x24，填充多边形 "6 4 20 12 6 20 6 4"
- **ClockIcon**：24x24，描边（1.5），圆 r=9 + "M12 7v5l3 2"
- **GlobeIcon**：24x24，描边（1.5），圆 r=9 + 水平线 + 两条弧线
- **DocumentIcon**：24x24，填充 Material 风格文档图标（Office 卡用，替代原 ImageIcon）
- **LightbulbIcon**：24x24，填充 Material 风格灯泡图标
- **ControlIcon**：24x24，填充 Material 风格滑杆/调谐图标（Control 卡用，替代原 MovieIcon）

---

## 依赖

- react、react-dom
- framer-motion
- tailwindcss@3、postcss、autoprefixer
- vite、@vitejs/plugin-react
- typescript

---

## 关键设计原则

- 一切基于纯黑（#000）背景
- 文字全白；次要文字用 `white/80` 或 `white/90`
- Liquid glass 元素填充近乎隐形，渐变描边通过 CSS mask 实现
- 视频作为氛围背景铺满 section，首尾平滑淡入淡出
- 字体：标题一律 italic + 极紧字距（负 tracking），正文用 light 字重
- 文案中英混排：主标题/品牌/技术栈名词用英文（Instrument Serif 斜体），正文、标签、按钮用中文（Barlow）
- 响应式：移动端隐藏导航链接、网格塌缩为单列、字号随断点缩放
- 动画：Hero 内容加载时错峰模糊入场，BlurText 由 IntersectionObserver 触发
- 产品事实以 `README.md` 特性表为准，不虚构数据

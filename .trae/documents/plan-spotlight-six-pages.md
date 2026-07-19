---
title: Spotlight 六页面展示站规划
date: 2026-07-20
tags:
  - plan
  - spotlight
  - web-design
  - react-router
aliases:
  - Aerie 展示站多页面规划
status: approved-pending
source:
  - "[[web-spotlight]]"
---

# Spotlight 六页面展示站规划

> [!summary] 目标
> 将当前纵向拼接的 Hero + Capabilities 单页展示站改为 **6 个互相独立的全屏页面**：Hero 首页与 Features、Architecture、Capabilities、Journal、Download 五个导航页面。所有页面复用现有 Liquid Glass、字体、卡片、动画和导航视觉，只更换页面内容与独立背景视频。

## Summary

当前 [App.tsx](file:///e:/Agent_reply/Spotlight/src/App.tsx) 直接连续渲染 `<Hero />` 和 `<Capabilities />`，因此两个区域出现在同一滚动界面；[Hero.tsx](file:///e:/Agent_reply/Spotlight/src/sections/Hero.tsx) 中五个导航链接均为 `href="#"`，没有真实页面。

改造后采用 **React Router HashRouter**：

| 页面 | URL | 核心职责 |
| --- | --- | --- |
| Hero 首页 | `/#/` | 品牌定位、版本徽章、下载 CTA、数据与技术栈 |
| Features | `/#/features` | 详细展示产品功能矩阵 |
| Architecture | `/#/architecture` | 展示 Electron + Python + NapCat + 模型/安全体系架构 |
| Capabilities | `/#/capabilities` | 保留现有三大能力卡片，但成为独立页面 |
| Journal | `/#/journal` | 基于真实 CHANGELOG 展示版本与开发日志 |
| Download | `/#/download` | 安装包下载、版本、平台、系统要求与安装提示 |

Logo 点击回 Hero 首页。五个导航项各自进入独立路由。顶部白色「获取便携版」CTA 仍直接下载安装包。

---

## Current State Analysis

### 当前架构

- [package.json](file:///e:/Agent_reply/Spotlight/package.json)：React 18 + Vite + TypeScript + Tailwind 3 + Framer Motion；无路由依赖。
- [main.tsx](file:///e:/Agent_reply/Spotlight/src/main.tsx)：直接渲染 `App`，无 Router Provider。
- [App.tsx](file:///e:/Agent_reply/Spotlight/src/App.tsx)：连续渲染 `Hero` 和 `Capabilities`，是两个 section 的单页滚动结构。
- [Hero.tsx](file:///e:/Agent_reply/Spotlight/src/sections/Hero.tsx)：同时承担全局导航、首页 Hero、背景视频、下载入口与数据展示。五个导航目前全是 `href="#"`。
- [Capabilities.tsx](file:///e:/Agent_reply/Spotlight/src/sections/Capabilities.tsx)：已是数据驱动三卡片结构，但依赖 Hero 内的 fixed 导航，没有自己的页面壳。
- [FadingVideo.tsx](file:///e:/Agent_reply/Spotlight/src/components/FadingVideo.tsx)：支持本地或远程视频，负责加载淡入、结尾淡出和循环，可直接作为六页背景组件。
- [index.css](file:///e:/Agent_reply/Spotlight/src/index.css)：已有 `.liquid-glass` 与 `.liquid-glass-strong` 全局样式，可直接复用。
- `public/aerie-logo.svg` 与 `public/Aerie-Cloud-0.1.0-beta.1-Setup.exe` 已存在。
- [CHANGELOG.md](file:///e:/Agent_reply/CHANGELOG.md) 有真实版本记录，可作为 Journal 内容源；[README.md](file:///e:/Agent_reply/README.md) 有真实产品架构与能力事实。

### 已确认的关键决策

- Hero 是独立首页，总计 **6 页面**。
- 路由使用 **HashRouter**，确保纯静态部署时刷新子页面不需要服务器 rewrite。
- 六页各使用独立背景视频。
- 新增四段背景视频由 AI 生成并保存到 `Spotlight/public/videos/`，避免外链过期。
- 页面样式继续严格沿用源项目：黑底、Instrument Serif 斜体大标题、Barlow 正文、Liquid Glass、模糊淡入、固定胶囊导航；不引入第二套视觉系统。

---

## 页面规划

## 1. Hero 首页 `/#/`

复用当前 Hero 主体，删除其中的导航实现，改由全局 `SiteHeader` 提供。

- 背景：保留现有 Hero 视频，后续也可下载本地化；本次不强制更换。
- 内容：版本徽章、`Your Private AI, Always Within Reach`、中文定位文案、安装包 CTA、观看演示、`7×24`/`20+` 统计卡、技术栈信任条。
- Logo：点击返回 `/#/`。
- 页面必须固定为一屏，不再向下拼接 Capabilities。

## 2. Features `/#/features`

定位为产品功能全景，不重复 Capabilities 的三类能力摘要。

- 标题：`Built for every part of your day`
- Label：`// Features`
- 内容采用与现有 Capabilities 相同的 Liquid Glass 数据驱动卡片：
  - 灵动岛与桌面壳：聊天窗、侧边栏、托盘、媒体控制
  - 智能工具矩阵：知识库、待办、日历、天气、截图、系统工具
  - 主动关怀：定时、情绪、事件三类触发
  - 个性化：Persona Hub、5+ 主题、人设切换
  - 本地数据：每日备份、一键迁移、Local-first
  - 故障自愈：14 类故障恢复、运行守护
- 桌面端建议 3×2 六卡网格；移动端单列。
- 背景视频：AI 生成「Windows 桌面界面、漂浮玻璃面板、柔和冰蓝粒子、无可读文字、黑色电影感」。

## 3. Architecture `/#/architecture`

定位为系统结构与数据流解释页，内容严格依据 README，不虚构层级。

- 标题：`Local intelligence, layered with intent`
- Label：`// Architecture`
- 中心采用 Liquid Glass 架构流：
  1. Electron Desktop Shell
  2. Python Intelligent Core
  3. Provider Router / Tools / Emotion / Memory
  4. NapCat OneBot11 / QQ Bridge
  5. Permission & Safety Gates
- 通过细线/箭头连接模块，沿用现有白色半透明描边，不使用彩色流程图。
- 辅助指标：多 Provider、3 级权限、4 道自进化安全闸门、24h 回滚。
- 背景视频：AI 生成「抽象神经网络与电路拓扑、冰蓝数据流、深黑空间、细微深红节点、无文字」。

## 4. Capabilities `/#/capabilities`

复用当前 [Capabilities.tsx](file:///e:/Agent_reply/Spotlight/src/sections/Capabilities.tsx) 主体，改造成独立页面。

- 保留：`One companion, end to end`、Office Mode、Emotion、Control 三卡片及现有标签和正文。
- 背景：保留当前 Capabilities 视频；独立页面挂载时播放。
- 使用全局 `SiteHeader`，调整顶部安全区，保证标题不被 fixed 导航遮挡。
- 不再由 App 在 Hero 后方连续渲染。

## 5. Journal `/#/journal`

只使用真实版本与开发记录，来源为根目录 `CHANGELOG.md`。

- 标题：`Built in public, refined in private`
- Label：`// Journal`
- 首批展示真实条目：
  - `0.1.0-beta.1 · 2026-07-19`：内测基准版本
  - `13.9.8 · 2026-07-19`：v13.9 收尾与综合修复
  - `13.9.4 · 2026-07-19`：办公模式增强与 QQ 客户端重构
  - `13.9.3 · 2026-07-19`：灵动岛与办公模式交互优化
- 卡片字段：日期、版本、类型、标题、摘要；不新增虚构外链。
- 桌面布局用一张主条目 + 三张次级条目，视觉样式仍为 Liquid Glass。
- 背景视频：AI 生成「高速移动的版本时间线、代码与文档层叠的抽象光轨、黑色电影感、无可读文字」。

## 6. Download `/#/download`

导航的 Download 文本进入详情页；页面中的 CTA 下载真实安装包。

- 标题：`Bring Aerie home`
- Label：`// Download`
- 主下载卡：
  - `Aerie · 云栖 0.1.0-beta.1`
  - Windows 安装版
  - 文件：`/Aerie-Cloud-0.1.0-beta.1-Setup.exe`
  - `download="Aerie · 云栖-0.1.0-beta.1-Setup.exe"`
- 辅助内容：Windows 11、本地优先、首次运行可能请求管理员权限、需要配置模型 API Key 与 QQ/NapCat（依据 README）。
- 提供「返回首页」次按钮，不新增不存在的平台包。
- 背景视频：AI 生成「一束光将玻璃形态凝聚成桌面应用图标、黑色空间、冰蓝边缘光、无文字」。

---

## Proposed Changes

### 依赖与入口

1. 修改 `Spotlight/package.json`
   - 添加 `react-router-dom`。
2. 修改 `Spotlight/src/main.tsx`
   - 使用 `HashRouter` 包裹 `App`。
3. 修改 `Spotlight/src/App.tsx`
   - 定义 6 条路由与 `*` 回首页兜底。
   - 不再同时渲染 Hero 与 Capabilities。

### 公共配置与布局

4. 新建 `Spotlight/src/config/navigation.ts`
   - 统一五个导航项的 label/path。
5. 新建 `Spotlight/src/config/release.ts`
   - 统一版本号、安装包 URL、下载文件名。
6. 新建 `Spotlight/src/components/SiteHeader.tsx`
   - 抽取当前 Logo + 中间胶囊导航 + 下载 CTA。
   - `NavLink` 提供当前页激活态。
   - Logo 链接首页。
   - 桌面端保持源项目布局；移动端增加最小化液态玻璃菜单按钮与全屏/胶囊菜单，避免当前 `hidden md:flex` 导致无法跳转。
7. 新建 `Spotlight/src/components/PageShell.tsx`
   - 统一全屏 `relative min-h-screen overflow-hidden bg-black`、背景视频、可选遮罩、前景层和全局导航。
   - 接收 `videoSrc`、`videoClassName` 与 children，不封装具体页面文案。
8. 新建 `Spotlight/src/components/PageIntro.tsx`
   - 统一 `// Label` + Instrument Serif 两行大标题，可选使用 BlurText。

### 页面与现有 section 调整

9. 修改 `Spotlight/src/sections/Hero.tsx`
   - 移除内部 header/nav 与重复下载常量。
   - 仅保留首页内容，下载数据从 `release.ts` 读取。
10. 修改/迁移 `Spotlight/src/sections/Capabilities.tsx`
    - 保留数据和卡片结构；由页面壳提供导航与背景。
11. 新建页面目录：
    - `src/pages/HomePage.tsx`
    - `src/pages/FeaturesPage.tsx`
    - `src/pages/ArchitecturePage.tsx`
    - `src/pages/CapabilitiesPage.tsx`
    - `src/pages/JournalPage.tsx`
    - `src/pages/DownloadPage.tsx`
12. 仅在需要时扩充 `src/components/icons.tsx`
    - 为 Features 卡片、架构节点、Journal、Download 增加同风格本地 SVG；不引入外部图标库。
13. 修改 `src/index.css`
    - 添加导航激活态、移动菜单、架构连接线、背景遮罩等最少量公共样式。
    - 原 `.liquid-glass` 与 `.liquid-glass-strong` 参数保持不变。

### 背景视频资产

14. 使用视频生成能力分别生成四段 16:9、无文字、适合循环的电影感视频：
    - `public/videos/features.mp4`
    - `public/videos/architecture.mp4`
    - `public/videos/journal.mp4`
    - `public/videos/download.mp4`
15. Hero 与 Capabilities 继续使用现有指定视频；若外链在生成/测试期间持续失败，则只在用户同意后再做本地化，不自行替换内容。
16. 所有新视频均通过现有 `FadingVideo` 播放，页面代码不直接实现第二套视频逻辑。

### Obsidian/Codex 提示词同步

17. 修改 `e:\Agent_reply\documents\prompt\web-spotlight.md`
    - 将“恰好两个全屏 section”更新为“六个独立全屏路由页面”。
    - 添加 HashRouter、共享导航、六页面内容规划、独立背景视频规范。
    - 保留 frontmatter、`[[web]]` 双链和 callout。
    - 增加 `[[Spotlight 六页面展示站规划]]` 关联说明，确保提示词与实际实现一致。

---

## Assumptions & Decisions

- “样式和源项目一致，仅修改背景”解释为：页面继续使用源项目的字体、黑白色系、Liquid Glass、固定胶囊导航、卡片结构和 Framer Motion；各页面只通过内容组织与背景视频区分，不创造新的视觉语言。
- Features 与 Capabilities 职责分开：Features 展示具体功能矩阵，Capabilities 展示三大能力域，避免重复。
- Hero 首页不出现在五项导航文字中；Logo 负责返回首页。
- Journal 使用静态的真实 CHANGELOG 摘要，不在浏览器运行时解析仓库外 Markdown，也不虚构文章。
- Download 只展示目前真实存在的 Windows Setup 安装包。
- HashRouter 优先保障静态部署兼容性，URL 接受 `/#/path` 形式。
- AI 视频生成如果只能异步完成，实施阶段需等待任务完成并验证文件可播放后再结束，不以占位图或纯色替代。

---

## Verification

1. **构建**：在 `Spotlight` 执行 `npm run build`，TypeScript 与 Vite 构建零错误。
2. **路由**：逐一访问并刷新：
   - `/#/`
   - `/#/features`
   - `/#/architecture`
   - `/#/capabilities`
   - `/#/journal`
   - `/#/download`
3. **页面隔离**：首页 DOM 不包含 Capabilities 三卡片；Capabilities 页不包含 Hero 统计卡，证明两个全屏区域已拆分。
4. **导航**：五个 NavLink 均跳转正确，当前项有激活态，Logo 返回首页，浏览器前进/后退正常。
5. **移动端**：375px 宽度下可打开菜单并访问所有五页；页面无水平溢出。
6. **背景**：六页各自加载对应视频；四个生成视频为本地静态资源，能播放、循环、淡入淡出；视频上无可读文字。
7. **下载**：导航 CTA 与 Download 页主 CTA 均返回安装包，`download` 文件名正确。
8. **内容真实性**：Architecture 对照 README；Journal 对照 CHANGELOG；Download 对照实际 public 安装包。
9. **视觉一致性**：Liquid Glass 参数、Instrument Serif/Barlow、黑白层级、圆角与动画时长与现有页面一致。
10. **提示词同步**：`web-spotlight.md` 不再包含“恰好两个 section”限制，并完整描述六路由页面。

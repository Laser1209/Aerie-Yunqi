---
title: Spotlight 六页面收尾与验收计划
date: 2026-07-20
tags:
  - plan
  - spotlight
  - react-router
  - video-assets
  - verification
aliases:
  - Spotlight 多页面收尾计划
status: ready-for-review
source:
  - "[[Spotlight 六页面展示站规划]]"
  - "[[web-spotlight]]"
---

# Spotlight 六页面收尾与验收计划

> [!summary] 目标
> 在现有六页面实现基础上完成剩余背景视频接入与浏览器验收。Hero 继续作为独立首页 `/#/`，Capabilities 保持独立路由 `/#/capabilities`；Features、Architecture、Journal、Download 分别拥有独立页面。视觉体系不重做，只使用各页面独立背景区分内容。

## Summary

当前路由、共享导航、页面壳、六个页面与真实安装包下载均已落地。剩余工作集中在两项：

1. 补齐尚未下载的 `features.mp4` 与 `download.mp4`，并检查四段 CogVideoX-3 本地视频的可播放性与背景适配性。
2. 对六条 Hash 路由、桌面端与移动端导航、页面隔离、下载入口和生产构建进行最终验收。

本轮不重新设计页面，不新增功能，不改变现有 Liquid Glass、字体、卡片、标题和导航体系。

## Current State Analysis

### 路由与页面隔离

[App.tsx](file:///e:/Agent_reply/Spotlight/src/App.tsx#L9-L20) 已定义六条独立路由：

| 页面 | Hash URL | 实现状态 |
| --- | --- | --- |
| Hero 首页 | `/#/` | 已完成 |
| Features | `/#/features` | 页面完成，背景视频待补齐 |
| Architecture | `/#/architecture` | 页面与本地视频均完成 |
| Capabilities | `/#/capabilities` | 已拆为独立页面 |
| Journal | `/#/journal` | 页面与本地视频均完成 |
| Download | `/#/download` | 页面完成，背景视频待补齐 |

Hero 由首页 `/` 承载，不额外增加 `/hero` 路由。用户要求的“Hero 与 Capabilities 不在同一个界面”已经通过 `/` 与 `/capabilities` 两个页面实现。

### 公共结构

- [SiteHeader.tsx](file:///e:/Agent_reply/Spotlight/src/components/SiteHeader.tsx#L13-L84) 已提供 Logo、五项导航、激活态、桌面下载 CTA 和移动端折叠菜单。
- [PageShell.tsx](file:///e:/Agent_reply/Spotlight/src/components/PageShell.tsx#L13-L29) 已统一固定全屏视频、黑色遮罩、共享导航和前景内容层。
- [FeaturesPage.tsx](file:///e:/Agent_reply/Spotlight/src/pages/FeaturesPage.tsx#L15-L37) 已引用 `/videos/features.mp4`。
- [DownloadPage.tsx](file:///e:/Agent_reply/Spotlight/src/pages/DownloadPage.tsx#L9-L51) 已引用 `/videos/download.mp4`，并复用真实 release 配置。

### 视频资产

当前 `public/videos/` 状态：

| 文件 | 状态 | CogVideoX-3 任务 ID |
| --- | --- | --- |
| `architecture.mp4` | 已下载 | `20260720033659944118b36c3e483d` |
| `journal.mp4` | 已下载 | `20260720033659c82a6c5272314985` |
| `features.mp4` | 服务端任务待继续查询 | `20260720033615e31745dd5c1f4b8c` |
| `download.mp4` | 服务端任务待继续查询 | `20260720033659a8e106e9497c43c5` |

Architecture 与 Journal 返回的视频 URL 名称含 `_watermark.mp4`。最终验收需以实际画面为准；本轮不擅自裁切、覆盖或绕过去水印限制。

## Proposed Changes

## 1. 补齐两段本地背景视频

目标文件：

- `e:\Agent_reply\Spotlight\public\videos\features.mp4`
- `e:\Agent_reply\Spotlight\public\videos\download.mp4`

实施方式：

1. 使用智谱异步结果接口查询两个既有任务，不重复提交生成任务。
2. 仅在任务状态为 `SUCCESS` 且 `video_result` 非空时下载视频。
3. 分别保存到页面当前已经引用的固定路径，避免修改页面代码。
4. 下载后确认文件存在、大小非零，并能被本地浏览器解码播放。
5. 若任务返回 `FAIL`，保留失败信息并重新提交同主题 CogVideoX-3 任务；不使用占位图、纯色背景或无关视频替代。

> [!warning] 鉴权
> 查询和下载任务结果需要智谱 API Key。密钥只用于请求头，不写入源码、配置文件、计划文档或 Git 记录。

## 2. 检查四段生成视频

检查：

- `features.mp4`
- `architecture.mp4`
- `journal.mp4`
- `download.mp4`

每段视频确认：

- 浏览器可播放，媒体请求无 404 或解码错误。
- 画面无生成出的可读文字，避免与页面正文冲突。
- 主体区域不会严重遮挡白色标题、Liquid Glass 卡片和导航。
- 画面主题与对应页面一致。
- `FadingVideo` 的加载淡入、结束淡出和循环行为正常。
- 记录是否存在明显平台水印；若存在，只反馈实际情况，不在本轮自行改变生成平台权限或处理视频内容。

## 3. 验证六页面路由和页面隔离

在开发服务器或生产预览中逐一访问：

- `/#/`
- `/#/features`
- `/#/architecture`
- `/#/capabilities`
- `/#/journal`
- `/#/download`

验证规则：

1. Hero 首页不出现 Office Mode、Emotion、Control 三张 Capabilities 卡片。
2. Capabilities 页面不出现 Hero 的 `7×24`、`20+` 统计内容。
3. 五个导航项进入对应页面，当前页面具有激活态。
4. Logo 返回 `/#/`。
5. 浏览器前进、后退与未知路由回退首页正常。
6. 每个页面只加载自身配置的背景视频。

## 4. 验证移动端和响应式布局

使用 375px 宽度完成一次完整导航流程：

1. 打开移动端菜单。
2. 分别进入五个导航页面。
3. 确认点击导航项后菜单关闭。
4. 检查标题、卡片、时间线、架构层和下载卡片无横向溢出。
5. 检查 fixed 导航不遮挡页面标题和首屏内容。

只修复验收中实际出现的布局问题，不额外增加 Escape、focus trap 或点击外部关闭等未被请求的交互扩展。

## 5. 验证真实下载入口

核对以下入口：

- 桌面导航 CTA
- 移动导航 CTA
- Hero CTA
- Download 页面主 CTA

所有入口应：

- 指向 `/Aerie-Cloud-0.1.0-beta.1-Setup.exe`。
- 使用 `download="Aerie · 云栖-0.1.0-beta.1-Setup.exe"`。
- 返回已存在且大小非零的真实安装包。

本轮不改动“获取便携版/安装版”产品文案，除非验收发现其与用户明确要求冲突。

## 6. 构建与最终回归

在 [package.json](file:///e:/Agent_reply/Spotlight/package.json) 所在目录执行现有脚本：

```powershell
npm run build
```

构建完成后：

1. 确认 TypeScript 零错误。
2. 确认 Vite 生产构建成功。
3. 使用生产预览再次抽查六条 Hash 路由。
4. 检查浏览器控制台、网络面板和视频请求没有影响功能的错误。
5. 不提交 Git commit，除非用户另行明确要求。

## Assumptions & Decisions

- Hero 独立首页使用 `/`，不新增 `/hero`。
- 五个 `a` 导航项对应 Features、Architecture、Capabilities、Journal、Download。
- HashRouter 保持不变。
- 页面结构与视觉样式已经符合规划，本轮只补资产、修复验收中发现的必要问题。
- Hero 与 Capabilities 的原 CloudFront 背景继续保留，不在本轮本地化。
- Features 与 Download 继续使用已经提交的 CogVideoX-3 任务，避免重复生成和额外成本。
- 视频水印由智谱账户权限决定；验收时记录，不采用规避平台限制的处理方式。
- 不新增文档、测试框架、路由、组件抽象或与当前需求无关的无障碍增强。

## Verification Checklist

- [ ] `features.mp4` 存在、非空、可播放
- [ ] `architecture.mp4` 存在、非空、可播放
- [ ] `journal.mp4` 存在、非空、可播放
- [ ] `download.mp4` 存在、非空、可播放
- [ ] 六条 Hash 路由均可访问
- [ ] Hero 与 Capabilities 内容完全隔离
- [ ] 五项导航与当前页激活态正确
- [ ] Logo、前进、后退和未知路由回退正确
- [ ] 375px 移动菜单和页面布局可用
- [ ] 页面无横向溢出
- [ ] 四个下载入口指向真实安装包
- [ ] `npm run build` 成功
- [ ] 浏览器无影响功能的控制台、网络和媒体错误
- [ ] `web-spotlight.md` 与实际六页面结构保持一致

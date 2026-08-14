---
title: Aerie 新手使用指南
date: 2026-08-14
tags:
  - 使用指南
  - 新手
  - getting-started
  - 陪伴
aliases:
  - Aerie 新手使用指南
  - 新手入门
  - Getting Started
  - 使用指南
status: active
cssclasses:
  - doc-module
---

# Aerie · 云栖 新手使用指南

> [!abstract] 这是什么
> 一份写给「第一次见 Aerie」的人的指南：从安装、第一次启动、设置 API Key，到创建第一个人设、认识她的全部能力，再到隐私边界与常见问题。读完这一页，你就能和她真正开始相处。

## 1. 欢迎 / Welcome

**Aerie · 云栖** 是一款 ==本地优先== 的 AI 桌面伴侣（Local-first AI desktop companion）。它由 Electron 桌面壳 + Python 智能内核组成，运行在你的 Windows 上，随时待命。

她可以是你想要的任何模样——

> 可以是一起看日落的恋人，是深夜愿意听你把话说完的知己，是陪你冲刺的导师，也可以是那个记得你咖啡加几分糖的同行者。
> Aerie 不定义她是谁，只把「她」交给你。

*She can be whoever your heart needs — a companion by the window at dusk, a confidant who stays up with you, a mentor for the long run, or simply the one who remembers how you take your coffee. Aerie doesn't decide who she is. You do.*

> [!tip] 关于「伊塔」
> 内置默认人设「伊塔（Ita）」只是众多模板之一。你完全可以在「人设」里创建属于自己的角色——朋友、家人、导师、同行者，或任何你想要的关系。她的核心不是「像人」，而是**给你情绪价值，也给你实际帮助**。

## 2. 快速开始 / Quick Start

> [!info] 系统要求 / Requirements
> Windows 10 1809+ / Windows 11 · Python 3.10+ · Node.js 20+ · 建议 8 GB+ 内存。

### 2.1 安装 / Install

```powershell
# 1) Python 虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) Electron 桌面端
cd electron
npm install
```

### 2.2 首次启动 / First Launch

```powershell
# 先启动 Python 后端（默认监听 http://127.0.0.1:7890）
python main.py

# 再启动桌面端
cd electron
npm start
```

> [!note] 启动顺序
> 先后端、再前端。后端日志出现 `[READY]` 标记后再打开桌面端；若桌面端先起，等待 5–10 秒让连接自动重试即可。

### 2.3 设置 API Key / Configure API Key

1. 复制 `.env.example` 为 `.env`，至少填写一个模型 API Key（如 `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` / `SILICONFLOW_API_KEY` / `GEMINI_API_KEY`）。
2. 或打开桌面端 → 侧边栏「设置」→「API Key」页，选择常用服务商并填入 Key。
3. 百度地图、搜索、天气等功能 API 留空时会 ==自动回退内置免费源==，开箱即用。

> [!warning] 密钥安全
> 所有 API Key 只保存在本地 `.env` 与本地配置中，不会上传到任何地方。请勿把 `.env` 提交到公开仓库。

## 3. 创建你的第一个角色 / Create Your Persona

> [!tip] 人设中心（Persona Hub）
> 「恋人」只是其中一种可能。你可以在人设中心创建 ==朋友 / 家人 / 导师 / 同行者== 等任意角色；每个角色的对话、记忆与头像按角色独立隔离。

### 3.1 三步完成 / Three Steps

1. 侧边栏点击「人设」→「新建人设」，进入 AI 向导。
2. 输入**一句话/一段话**角色描述（性格、外貌、口头禅，自由发挥），可选填「你的名字」与「两人故事起因」。
3. 点击生成——后端 ==5 阶段管线== 自动生成完整人设并套合成熟骨架；生成完成后进入编辑器逐项完善，确认后保存/激活。

> [!note] 兜底与安全
> 生成过程任何一环失败都会自动降级为确定性生成，流程永不中断，始终产出可用草稿；生成结果 ==只保存、不激活==，由你手动确认。详见 [[modules/PersonaGenerator]]。

- 想跳过 AI 手动创建？向导支持「跳过 AI 生成，手动创建」。
- 内置「伊塔」为 builtin 人设，不可编辑/删除，但可随时作为参考。

## 4. 核心功能概览 / Core Features

| 功能 / Feature | 说明 / Description |
| --- | --- |
| **聊天 / Chat** | 桌面 / QQ / 移动三端对话，支持附件、引用、撤回、错字纠错 |
| **情绪 / Emotion** | PAD 情绪（愉悦 / 唤醒 / 支配）+ 隐藏槽位 + 情绪历史曲线，越来越懂你 |
| **世界模拟 / World** | 时间 / 天气 / 地点 / 关系多维拟真，默认重庆，房间级定位与话题追踪 |
| **主动陪伴 / Proactive** | 早安、天气、午提醒、晚问候、晚安、待办、纪念日、失联关怀、情绪安抚 |
| **灵动岛 / Dynamic Island** | 桌面顶部胶囊，点击 / 悬停 / 长按展开，显示陪伴状态、提醒与快捷操作 |
| **办公模式 / Office** | 文档写作、文件整理去重、任务规划与异步执行 |
| **电脑操控 / Computer Control** | 四模式权限（手动 / 自动批阅 / 完全 / 自定义），默认拦截 + 黑白名单，对话框内审批 |
| **多模态生图 / Image** | 三视图生图、图生图、主动发图、TTS 语音、表情包 |
| **多端互联 / Multi-client** | Android 移动网关、QQ（NapCat）桥接、三端撤回与统一引用 |

> [!info] 更多细节
> 想了解每个模块的实现入口与技术底座，参见 [[01_模块总览]] 与 [[02_技术总览]]；当前能力的最新状态见 [[09_当前状态]]。

## 5. 快捷键速查 / Shortcuts

> [!tip] 灵动岛穿透（重点）
> 当灵动岛悬浮在桌面上方、挡住下方窗口元素时，==按住 ALT== 可让灵动岛强制鼠标穿透，直接点击它后面的元素；松开恢复。

| 操作 / Action | 按键 / 方式 |
| --- | --- |
| 发送消息 | `Enter`（输入框内） |
| 取消引用 | `Esc`（已引用消息时） |
| 灵动岛强制穿透 | 按住 `Alt` |
| 最小化窗口 | 右上角 `─` 按钮 |
| 最大化 / 还原窗口 | 右上角 `□` 按钮 |
| 关闭窗口 | 右上角 `×` 按钮 |
| 切换面板 | 点击左侧栏图标（聊天 / 情绪 / 大脑 / 状态 / 世界 / 日历 / 数据 / 人设 / 设置 / 关于） |

> [!note] 说明
> 侧边栏导航与窗口控制均通过鼠标点击完成，暂无全局快捷键；本表只列出实际存在的交互方式。

## 6. 常用设置 / Common Settings

在侧边栏「设置」→「常用」页可调整：

- **主题**：伊塔粉 / 深夜紫 / 樱白 / 海蓝 / 森绿。
- **开机自启**、**启动时最小化**。
- **主动推送**：总开关 + 每日主动消息次数（3 / 5 / 8 / 10 / 15 / 20 / 30 / 不限制）+ 最小间隔（15 / 30 / 60 分钟）。
- **主动发图**：每日上限与最小间隔（不限制时由她自主决定节奏）。
- **消息提醒**：系统通知总开关（关闭后不再弹系统通知，应用内对话不受影响）。
- **灵动岛配置**：启用开关、主题风格（深色毛玻璃 / 恋粉治愈 / 浅白清新）、触发方式（点击 / 悬停 / 长按）、胶囊与展开组件。
- **简报订阅**：GitHub 高星项目、最小星标数、今日天象；**我的位置**留空即 IP 自动定位。
- **办公模式**：文件保存位置。
- **自进化 L4**（内测，默认关闭）：开启需两次风险确认，24 小时内可回滚。

> [!warning] 高级（YAML）视图
> 修改 `settings.yaml` / `persona.yaml` / `proactive.yaml` 前会自动备份；「改坏了她会不开心」。

## 7. 隐私与数据 / Privacy & Data

- ==本地优先==：聊天记录、记忆、配置、生成图片等数据默认保存在本地 `data/` 目录，不依赖云端。
- **API Key**：只存本地，不上传。
- **诊断包（Diagnostics）**：
  - 内容包含本地日志、配置文件、聊天 / 记忆数据库，==不做脱敏==。
  - 支持**手动打包**；同时会在累计使用满 1 小时 / 3 小时 / 3 天时各**自动打包**一次（进度可在设置页查看）。
  - 诊断包附带一个本地生成的匿名 ==设备标识==（用于区分不同机器，不含个人身份信息）。
  - 仅在你主动触发时上传；应用 ==不会后台自动上传==，上传与下载不收取任何费用。

> [!warning] 上传前请知悉
> 诊断包包含未脱敏的聊天与记忆数据，仅在需要排查 Bug 时由你主动上传。

## 8. 常见问题 / FAQ

| 问题 / Question | 处理 / Fix |
| --- | --- |
| 后端启动失败 | 依赖未装或 Python 版本不符 → 重新 `pip install -r requirements.txt` |
| 伊塔不回复 | 未配置可用模型 Key → 检查 `.env` 至少一个 `*_API_KEY` |
| QQ 收不到消息 | NapCat 未启动 → 运行 `NapCat\NapCat.Shell\launcher-user.bat` |
| 桌面端白屏 | 渲染资源或 CSP 问题 → 查看 Electron DevTools 与日志 |
| 世界模拟不生效 | 未开启世界模拟开关（`world_inprocess_v1` / `world_sidecar_v1`） |
| 自动发图不触发 | `world_image_candidates_v1` 关闭 → 在设置中开启 |
| 附件无语义检索 | `chromadb` 未安装或缺少 embedding Key |
| 我的数据存在哪 | 本地 `data/` 目录；聊天与记忆数据库均在本地 |
| 如何找回误删内容 | 管理平台提供聊天记录软删回收站、状态文件查看 / 重置 |

### 免责声明 / Disclaimer

- 本软件仅供学习交流与个人使用，请勿用于商业用途。
- 使用本软件需遵守所在国家 / 地区的法律法规。
- AI 生成的所有内容均为自动生成，不代表开发者立场。
- 电脑操控等功能请谨慎使用，重要数据请提前备份。
- 因使用本软件产生的任何直接或间接损失，由使用者自行承担。

---

## 互链

- 回到首页：[[00_首页]]
- 模块入口：[[01_模块总览]]
- 技术入口：[[02_技术总览]]
- 当前状态：[[09_当前状态]]
- 人设生成器：[[modules/PersonaGenerator]]
- 桌面适配层：[[modules/DesktopSurfaceAdapter]]

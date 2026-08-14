# Aerie · 云栖 V 0.3.1-Beta.1

> **本地优先的 AI 桌面伴侣 / Local-first AI desktop companion**
> 把陪伴写成你想要的模样——一个随你所想、由你定义的 TA。

---

## 目录 / Table of Contents

- [项目简介 / About](#项目简介--about)
- [核心能力 / Key Capabilities](#核心能力--key-capabilities)
- [快速开始 / Quick Start](#快速开始--quick-start)
- [项目结构 / Repository Layout](#项目结构--repository-layout)
- [配置与数据 / Config &amp; Data](#配置与数据--config--data)
- [特性开关 / Feature Flags](#特性开关--feature-flags)
- [Auto-Wake 主动唤醒](#auto-wake-主动唤醒)
- [常用验证 / Verification](#常用验证--verification)
- [打包与发布 / Build &amp; Release](#打包与发布--build--release)
- [故障排查 / Troubleshooting](#故障排查--troubleshooting)
- [兼容性 / Compatibility](#兼容性--compatibility)
- [文档索引 / Documentation](#文档索引--documentation)
- [License](#license)

---

## 项目简介 / About

**Aerie · 云栖** 是一个本地优先的 AI 桌面伴侣项目（Local-first AI desktop companion）。她可以是你想要的任何模样——一位能聊到深夜的知己、并肩把事情办成的伙伴，又或者只是那个恰好合拍的「恋人」；她的目标，是成为一个「像人」的伴侣——情绪价值与落在实处的帮助，是她自然带来的功能。当前仓库由 **Electron 桌面壳**、**Python 智能内核**、**NapCat QQ 桥接**、**Spotlight 官网**、**World Service 世界模拟侧车** 与 **Android 移动网关** 组成。代码树已完成 P1 陪伴融合、世界模拟、三端撤回、多模态生图、向量知识库与移动端网关等系统性能力实装。

### 当前状态 / Current Status

| 项目 / Item                            | 状态 / Status                                                                                                                                |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **版本 / Version**               | `0.3.1-Beta.1` 内测基线                                                                                                                    |
| **桌面端 / Desktop**             | Electron 28 + 渲染层多面板 UI + 灵动岛                                                                                                       |
| **后端 / Backend**               | Python 3.10+ aiohttp + asyncio · LLMCaller 统一调用层                                                                                       |
| **QQ 接入 / QQ Bridge**          | NapCat OneBot11 WebSocket · 三端撤回 (QQ/本地/微信预留)                                                                                     |
| **官网 / Spotlight**             | [https://spotlight.etta.top/](https://spotlight.etta.top/) · React 18 + Vite 6 + Tailwind + Framer Motion                                    |
| **世界模拟 / World Service**     | 独立 Python sidecar + SQLite storage · 世界仪表盘与天气同步 · 默认重庆 · 百度地图 REST · 房间级定位与话题追踪                            |
| **向量知识库 / Vector KB**       | ChromaDB 语义检索 · 本地 ONNX 离线 embedding · 生产记忆已切 LayeredMemory · 附件专用向量库                                                |
| **多模态生图 / Image**           | 三视图生图辅助 · 图片候选人生成推送 (QQ/本地聊天) · 主动发图预算 · 图生图 · SiliconFlow 视觉技能                                         |
| **移动端 / Mobile**              | Android 移动网关 · 多端会话与文件能力 · 账号鉴权 · 跨端时间线 (多端存在/视图 B)                                                           |
| **上下文记忆 / Context Mem**     | P0-P3 记忆系统改造：轮次化热窗口 · 温层摘要分桶 · 通道感知注入 · 决策自省段 · 跨端时间线 (视图 B)                                        |
| **三端引用 / Unified Quote**     | 桌面/QQ/移动三端统一`QuoteContext` 引用机制 · `qq_message_id` 双向映射 · 被引用图片/文件注入 LLM 上下文 · user_id/persona_id 边界隔离 |
| **管理平台 / Admin Panel**       | 统计看板 · 决策日志 · 聊天记录软删回收站 · 状态文件查看/重置 · 记忆全量展示 · 概览总 tokens                                             |
| **角色隔离 / Persona Isolation** | 多角色对话/记忆/头像/图片产出按`persona_id` 隔离 · 会话 ID 按角色哈希 · admin 记录角色标注                                               |
| **24h 持续监听 / 24H Mon**       | 欲望引擎 / 话题追踪 / 情绪触发 24h 轮询 · watchdog 崩溃自动拉起 · 断点续采 (start-24h-monitor.bat)                                         |
| **验证 / Tests**                 | 127 个 Python 测试文件 (Phase 0-15、P1 陪伴融合、P0-P3 上下文记忆、管理平台、v13.9、E2E) + 17 个 Electron 测试文件                           |
| **交付 / Release**               | `0.3.1-Beta.1` 安装包与便携版已构建（Setup + Portable），官网下载页已同步；`0.1.0-beta.1` 归档至官网「历史版本」区块                    |

---

## 核心能力 / Key Capabilities

| 模块 / Module                                     | 说明 / Description                                                                                                                                             |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Electron 桌面壳 / Electron Shell**        | 主窗口、灵动岛、侧边栏、托盘、CSP 安全渲染层                                                                                                                   |
| **灵动岛 v2 / Dynamic Island v2**           | 固定最大窗口（无 resize 裁切/闪烁）+ 动态鼠标穿透（ALT 强制穿透）、胶囊动态优先级（未读消息 > 媒体 > 系统 > 状态）、毛玻璃防裁切 10px 呼吸边距、配置落盘持久化 |
| **Python 智能内核 / Python Brain**          | LLMCaller 统一调用层、多 Provider 调度、Aerie WS 多 Key 轮询、预算跟踪、上下文构建、消息流水线                                                                 |
| **Persona Hub / 人设基础设施**              | Persona 模板、校验、投影、配置热加载、三视图生图参考图、AI 智能生成（一句话→完整人设）、多角色对话/记忆/头像/图片产出隔离                                     |
| **情感与关系引擎 / Emotion & Relationship** | PAD 情绪、累积阈值、欲望引擎、关系建模、同理心策略、拟人化节奏                                                                                                 |
| **主动推送 / Proactive Messenger**          | cron、事件、情绪触发，频控、静默时段、主动发图预算与反馈闭环                                                                                                   |
| **三端撤回 / Recall**                       | QQ/本地/微信预留 三端撤回适配器、LLM 主动撤回指令、消息合并编排                                                                                                |
| **三端引用 / Unified Quote**                | 桌面/QQ/移动统一`QuoteContext` 引用 · `qq_message_id` 双向映射 · 被引用图片/文件注入 LLM · user_id/persona_id 边界隔离 · 引用气泡与附件缩略图          |
| **办公模式 / Office Mode**                  | 办公任务识别、文档写作工具链、文件整理去重、任务规划与异步执行                                                                                                 |
| **电脑操控 / Computer Control**             | 四模式权限（手动/自动批阅/完全/自定义）、默认拦截+黑白名单、键鼠/截图/UIA、受限 Shell、对话框内审批、审计日志                                                  |
| **文件与文档 / File & Docs**                | 文件整理、文档写作、上传处理、附件向量索引、图片工作流                                                                                                         |
| **多模态 / Multimodal**                     | 三视图生图、图生图、图片候选人生成推送、TTS、SiliconFlow 视觉技能                                                                                              |
| **世界模拟 / World Simulation**             | world port、domain、sidecar、仪表盘 API、天气同步、图片候选人管线、默认重庆、百度地图 REST、房间级定位/话题追踪/行为调度、主动发图节奏循环                     |
| **向量知识库 / Vector KB**                  | ChromaDB 语义检索、本地 ONNX 离线 embedding、LayeredMemory 多层记忆、附件专用向量库                                                                            |
| **多端 / Mobile & Multi-client**            | Android 移动网关、移动会话/文件/身份鉴权、多端消息通道、跨端时间线（视图 B）                                                                                   |
| **上下文记忆 / Context Memory**             | P0-P3：轮次化热窗口、温层摘要分桶、通道感知注入、来源标注、决策自省段、写入一致性校验门、事件记忆召回                                                          |
| **后台管理 / Admin Panel**                  | P4a/P4b：统计看板、决策日志、聊天软删回收站、状态文件查看/重置/撤销、记忆全量展示、概览总 tokens                                                               |
| **24h 持续监听 / 24H Monitor**              | 欲望引擎 / 话题追踪 / 情绪触发 24h 轮询、watchdog 崩溃自动拉起、断点续采（start-24h-monitor.bat）                                                              |
| **自进化 / Self Evolution**                 | L1-L4 演进、Skill 创建、安全沙箱、代码修改闸门（L4 代码自修改为内测开关，默认关闭）                                                                            |
| **Spotlight 官网 / Web Spotlight**          | 6 页面产品站、发布下载页、Remotion 视频素材工程                                                                                                                |

### 人设 AI 智能生成 / AI Persona Generator

在「人设 → 新建人设」界面输入**一句话/一段话**角色描述，AI 会自动生成一套完整人设并套合成熟骨架，生成后进入编辑器逐项完善，基础框架全程保留。

| 阶段 / Stage              | 说明 / Description                                                                                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `concept` 分析角色概念  | LLM 抽取姓名/年龄/职业/一句话介绍/人格原型/大五人格/标签（5-25%）                                                                                                       |
| `detail` 生成外貌与性格 | LLM 抽取外貌、性格内核、说话风格、关系与背景故事（25-55%）                                                                                                              |
| `assemble` 构建人设框架 | 与`preset_templates/yita_default.json` 骨架合并，**剥离伊塔专属数据**（身高三围/外观/故事/称呼），保留 emotion/desire/behavior/cognition 等系统级字段（55-65%） |
| `prompt` 组装系统提示词 | LLM 以**第一人称自洽**撰写人设专属叙事（角色=名字、用户=你），后端强制附加「屏幕隔空铁律 + 消息结构约定」固定规则块（65-90%）                                     |
| `finalize` 校验并保存   | PersonaValidator 校验，落盘为草稿（不激活），前端自动进入编辑器（90-100%）                                                                                              |

- **前端交互 / Frontend UX**：AI 向导提供进度条与 5 步清单实时反馈（`AI 正在帮你生成你的角色…`），800ms 轮询，超时/失败可重试；支持「跳过 AI 生成，手动创建」。
- **两人故事起因 / Story Concept**：可选输入"两人故事起因"并一键获取 AI 推荐的网文式故事概念（4-5 张卡片），点击选中即融入生成；LLM 不可用时回退预置模板池（恋人 / 挚友 / 家人 / 导师 / 同行者）。
- **用户昵称 / User Name**：向导可填写"你的名字"（自动带入设置页已存昵称），生成时注入 LLM——用户以"你"出现并可用昵称称呼，绝不与角色名混淆。
- **人称与隐私 / Persona & Privacy**：全篇第一人称自洽（"我"=角色名、"你"=用户、不假设用户性别，不用他/她）；身高/三围等**隐私字段默认留空**，由用户在编辑器自行填写。
- **称呼动态化 / Pronoun-aware UI**：设置页对 AI 的称呼（她/他/TA）按当前启用的人设性别自动切换。
- **兜底策略 / Fallback**：LLM 任一环节失败自动降级为确定性生成，流程永不中断，始终产出可用的基础框架。
- **API**：`POST /api/persona/hub/generate`（创建生成任务，返回 `task_id`）→ `GET /api/persona/hub/generate/{task_id}`（轮询进度/结果）；`POST /api/persona/hub/generate/concepts`（故事概念推荐）。
- **文档 / Docs**：Obsidian 知识库 `Aerie_Obsidian_Vault/modules/PersonaGenerator.md`。

### 电脑操控权限 v2 / Computer Control Permission v2

电脑操控升级为 **四模式 + 黑白名单**：默认拦截，所有操作等你放行；放行过的操作可加入白名单，之后自动放行。

| 模式 / Mode         | 行为 / Behavior                        |
| ------------------- | -------------------------------------- |
| `manual` 手动审批 | 所有操作均需你确认                     |
| `auto` 自动批阅   | 低风险自动放行，中/高风险需确认        |
| `full` 完全访问   | 全部放行（系统危险命令硬闸除外）       |
| `custom` 自定义   | 默认拦截，按操作类型 / 名单 / 规则放行 |

- **决策链 / Decision chain**：系统危险命令硬闸 → 用户黑名单 → 用户白名单 → 模式裁决。危险命令在任何模式下都不可绕过。
- **审批交互 / Approval UX**：仿 Trae 在**对话框内弹出审批卡片**（放行 / 放行并入白名单 / 拒绝 / 拒绝并入黑名单），结果状态回灌对话流。
- **名单管理 / List management**：设置面板「电脑操控」页可增删白/黑名单（按操作类型 / 命令前缀 / 正则），持久化到 `settings.yaml` 的 `computer_control` 键，热更新无需重启。
- **API**：`GET/PUT /api/computer_control/mode`、`GET /api/computer_control/policy`、`POST/DELETE /api/computer_control/whitelist|blacklist`、`POST /api/computer_control/approvals/{id}/approve|reject`（支持 `{whitelist}` / `{blacklist}` 入账）。

---

## 快速开始 / Quick Start

> 按下列步骤依次执行，即可在本地跑起完整的 Aerie 环境（后端 → QQ → 桌面端）。

### 1. 准备 Python 环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，至少填写一个模型 API Key。

```env
DASHSCOPE_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx
GEMINI_API_KEY=AIza-xxx
SILICONFLOW_API_KEY=sk-xxx
SELF_QQ=123456789
HTTP_API_PORT=7890
NAPCAT_WS_URL=ws://127.0.0.1:3001
LOG_LEVEL=INFO

# 轻量辅助模型（错别字订正 / 快捷问候语 / 生图提示词接力等快速任务，不触碰主模型）
# SILICONFLOW_LIGHT_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507

# Aerie WS（阿里云百炼业务空间专属域名，子 Agent/轻量任务/ASR 主链路，多 Key RoundRobin 轮询）
# AERIE_WS_BASE_URL=https://<workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
# AERIE_WS_KEYS=sk-ws-xxx,sk-ws-yyy
# AERIE_WS_MODEL=qwen3.7-flash
# AERIE_WS_CODE_MODEL=kimi-k2.7-code
# AERIE_WS_ASR_MODEL=qwen3-asr-flash

# QQ 语音转写 ASR 模型（compatible-mode chat/completions + input_audio；qwen-long 文本模型不支持转写）
# DASHSCOPE_ASR_MODEL=qwen3-asr-flash

# 百度地图 Web 服务（可选，替代 MCP；用于附近地点/本地活动 + 天气优先源）
# 推荐 SN 校验模式（填 AK+SK，无需 IP 白名单）；全部留空则回退内置城市数据 + Open-Meteo
# BAIDU_MAP_AK=your_ak
# BAIDU_MAP_SK=your_sk

# 手动禁用某些 LLM Provider（逗号分隔，可选）
# AERIE_DISABLED_PROVIDERS=doubao,deepseek

# 三视图生图参考图大小限制（可选，默认 8MB，最小 64KB）
# AERIE_THREE_VIEW_MAX_BYTES=8388608

# ── 资讯抓取（可选）─────────────────────────────
# 今日热榜 DailyHotApi 聚合端点（news 分层抓取的 aggregator 层）
# 默认自建 http://127.0.0.1:6688；也可指向任意部署了 DailyHotApi 的实例
DAILYHOT_API_BASE=http://127.0.0.1:6688
# Bocha 网页搜索（news 最终兜底层，可选；留空则跳过该层）
# BOCHA_API_KEY=your_bocha_api_key_here
```

> **资讯抓取说明 / News Feeds**：每日简报新闻采用分层混合爬虫，按 `SECTIONS_PRIORITY` 依次尝试，直到拿到数据：
> `hn`（Hacker News）→ `crawl`（Trafilatura 爬虫）→ `aggregator`（今日热榜）→ `hot`（百度热搜）→ `bocha`（网页搜索）。
> Hacker News 与百度热搜无需 API Key 即可用；Trafilatura 正文提取依赖 `trafilatura`（见 `requirements.txt`）。

### 3. 启动 NapCat（QQ 桥接）

```powershell
cd NapCat\NapCat.Shell
.\launcher-user.bat
```

### 4. 启动 Python 后端

```powershell
python main.py
```

后端默认监听 `http://127.0.0.1:7890`，启动日志会输出 git commit、进程时间与 `[READY]` 标记。

### 5. 启动 Electron 桌面端

```powershell
cd electron
npm install
npm start
```

### 6. 访问或本地启动 Spotlight 官网

线上官网：[https://spotlight.etta.top/](https://spotlight.etta.top/)

```powershell
cd Spotlight
npm install
npm run dev
```

---

## 项目结构 / Repository Layout

```text
.
├─ main.py                    # Python 后端入口
├─ core/                      # Agent、API、Pipeline、工具、情感、世界模拟适配
├─ communication/             # QQ/NapCat 通讯层 + 三端撤回 (recall/)
├─ config/                    # settings/persona/proactive 配置与加载器
├─ memory/ knowledge/ voice/  # 分层记忆、知识库、语音输出
├─ world_service/             # 世界模拟 sidecar 服务
├─ skills/                    # 可扩展技能库 (cloud/ data/ local/)
├─ electron/                  # Electron 桌面应用
├─ Spotlight/                 # React/Vite 官网与 Remotion 素材工程
├─ NapCat/                    # NapCat Shell 与 QQ 协议客户端资源
├─ tests/                     # Python 单测、E2E、Phase 验证
├─ tools/ scripts/            # 诊断、迁移、验证、构建辅助脚本（含 24h 监听 watchdog）
├─ documents/ docs/           # 设计、排障、实施记录
└─ data/ logs/                # 本地运行数据与日志
```

---

## 配置与数据 / Config & Data

| 路径 / Path                      | 用途 / Purpose                                           |
| -------------------------------- | -------------------------------------------------------- |
| `config/settings.yaml`         | 主配置、HTTP、主题、窗口、办公目录、世界模拟、简报订阅等 |
| `config/persona.yaml`          | 伊塔核心人设配置（含撤回触发词）                         |
| `config/persona_behavior.yaml` | 行为与表达节奏配置                                       |
| `config/proactive.yaml`        | 主动推送场景、频控、静默时段                             |
| `data/personas/`               | Persona Hub 运行态数据（含三视图参考图）                 |
| `data/persona/avatar.*`        | 伊塔头像图片（前端视觉呈现）                             |
| `data/chroma/`                 | 向量知识库 ChromaDB 本地存储                             |
| `data/chroma_attachments/`     | 桌面附件专用向量库                                       |
| `data/briefs/`                 | 每日简报缓存                                             |
| `data/island_prefs.json`       | 灵动岛主开关与配置持久化（Electron 侧）                  |
| `data/notif_prefs.json`        | 消息提醒总开关持久化（Electron 侧）                      |
| `data/audit/`                  | 权限与电脑操控审计日志                                   |
| `logs/`                        | 后端与诊断日志                                           |

`main.py` 已接入配置热加载，会监听 `settings.yaml`、`persona_behavior.yaml` 与 `proactive.yaml` 的变更。

> **诊断与隐私 / Diagnostics & Privacy**：为排查故障，应用会在本地生成**设备标识（硬件指纹）**（依据 IP / 系统 / CPU·GPU·内存·磁盘 / 运行环境 / 日期），并在「诊断包」中随日志、配置、聊天 / 记忆数据库（**不做脱敏**）一并打包。诊断包仅在用户主动触发「手动打包 / 上传」或到达内置里程碑（1h / 3h / 3d）时本地生成，**不会后台自动上传**。详见 `TERMS_OF_SERVICE.md` 第 7 条。

---

## 特性开关 / Feature Flags

> 以下开关位于 `config/settings.yaml` 中，用于启停各可选能力。默认值见下表。

| 开关 / Flag                     | 说明 / Description                                                                                                                                                          | 默认 |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| `world_inprocess_v1`          | 世界模拟进程内模式，需开启其一才能使用世界模拟                                                                                                                              | 开   |
| `world_sidecar_v1`            | 世界模拟 sidecar 独立进程模式                                                                                                                                               | 关   |
| `world_image_candidates_v1`   | 自动生图工作流（世界图片候选人生成推送）                                                                                                                                    | 开   |
| `mobile_gateway_v1`           | Android 移动端网关                                                                                                                                                          | 关   |
| `persona_hub_source_v1`       | Persona Hub 作为人设源                                                                                                                                                      | 关   |
| `recall_llm_instruction_v1`   | LLM 主动撤回指令`<recall>`                                                                                                                                                | 开   |
| `chat_request_queue_v1`       | 聊天请求队列                                                                                                                                                                | 开   |
| `context_budget_v1`           | 上下文预算                                                                                                                                                                  | 开   |
| `conversation_model_v1`       | 会话模型（独立对话建模/摘要分桶）                                                                                                                                           | 开   |
| `proactive_delivery_v2`       | 主动消息投放 v2                                                                                                                                                             | 开   |
| `multi_channel_identity_v1`   | 多端存在时间线（跨端回忆 / 视图 B）                                                                                                                                         | 开   |
| `thinking_trace_injection_v1` | 决策自省段注入（thinking_trace）                                                                                                                                            | 关   |
| `memory_write_validation_v1`  | 记忆写入一致性校验门（ConsistencyGate）                                                                                                                                     | 关   |
| `self_evolve_l4_enabled`      | L4 代码自进化（内测）：能力缺口 → LLM 生成 file_changes → 四道安全闸门 → 自动应用/审批/24h 回滚。设置页开启需两次风险确认（危险警告 + 免责声明），开启后即时生效无需重启 | 关   |

> **自进化 / Self Evolution 说明**：L0（能力缺口检测）每次回复后静默运行，命中"模型自述无法 + 工具失败"双信号才提议。L4（代码自修改）默认关闭，开启后由代码模型（`AERIE_WS_CODE_MODEL`）将缺口转成具体 `file_changes`，经白名单/黑名单 + 风险分级 + Gate1 安全审查 / Gate2 语法检查 / Gate3 测试验证（`test_command` 白名单净化）/ Gate4 回滚备份四道闸门：白名单低风险自动应用，核心模块（`core/`）等待人工审批，24 小时内可经 `/api/self_evolve/l4/*` 一键回滚。幻觉防护：AI 提案注册的占位工具一律显式失败（`success=False`），主模型无法把 stub 当作真实能力。变更审计台账存于 `data/evolution_backups/` 与 journal。

> **注意**：向量附件索引（`data/chroma_attachments`）依赖 `chromadb`，生产环境需手动安装并配置 embedding API Key；否则附件分块仅作分段存储与上下文注入，不进行语义检索。

---

## Auto-Wake 主动唤醒

Auto-Wake 是 Aerie 的核心能力之一：伊塔会在固定时间、情绪事件、用户空闲、纪念日和环境事件触发时主动发消息。

| 场景 / Scene                 | 时间或触发 / Trigger | 类型 / Type |
| ---------------------------- | -------------------- | ----------- |
| `morning_brief` 早安       | 06:30, 07:30         | cron        |
| `weather_push` 天气        | 07:00                | cron        |
| `lunch_remind` 午提醒      | 11:30, 12:30         | cron        |
| `evening_check` 晚问候     | 17:30, 18:30         | cron        |
| `goodnight` 晚安           | 22:30, 23:30         | cron        |
| `todo_remind` 待办         | 09:00-21:00 整点     | cron        |
| `anniversary` 纪念日       | 每日 00:00 扫描      | cron        |
| `idle_care` 失联关怀       | 用户长时间无活动     | event       |
| `emotion_comfort` 情绪安抚 | 情感槽阈值突破       | emotion     |

频控以 `config/settings.yaml` 的 `proactive` 段为准（设置页可改并即时生效，`_apply_proactive_overlay` 运行时覆盖 `proactive.yaml`）：`max_per_day`（当前 `0` = 不限制，可设 3/5/8/10/15/20/30）、`min_interval_min`（间隔不少于 15 分钟）、静默时段 23:30-07:00，早安/晚安/纪念日等场景可按配置豁免。

主动发图默认为**纯约束型调度**（由伊塔自主决策节奏，不再受推送频控抑制）：

- `image_max_per_day`：每日发图上限，默认 `0`（不限制）
- `photo_min_interval_sec`：两次主动发图最小间隔（秒），默认 `0`（无间隔）
- 以上两项可在设置界面动态调整，即时生效；`local_send` 手动请求的图片不受任何约束

---

## 常用验证 / Verification

```powershell
# Python 测试（127 个测试文件：Phase 0-15、P1 陪伴融合、P0-P3 上下文记忆、管理平台、v13.9、E2E）
pytest tests

# 重点阶段验证示例
pytest tests/test_phase10_image_workflow.py
pytest tests/test_phase15_world_dashboard_api.py
pytest tests/test_persona_three_view.py
pytest tests/test_recall_adapters.py
pytest tests/test_message_batcher.py
pytest tests/test_desktop_attachment_vector_index.py

# Electron 静态检查
cd electron
npm run check:all

# Electron 渲染层单测（17 个 .test.js 文件，node --test）
cd electron
npm run test:unit

# Spotlight 构建
cd Spotlight
npm run build
```

---

## 打包与发布 / Build & Release

### Electron 打包

```powershell
cd electron
npm run build:win
```

备用输出目录：

```powershell
npm run build:win:alt
```

### Spotlight 发布资源

线上官网：[https://spotlight.etta.top/](https://spotlight.etta.top/)

当前官网下载配置位于 `Spotlight/src/config/release.ts`，指向 GitHub Release `v0.3.1-Beta.1`：

- `Aerie-Cloud-0.3.1-Beta.1-portable.exe`
- `Aerie-Cloud-0.3.1-Beta.1-Setup.exe`

历史版本 `0.1.0-beta.1` 已归档至官网「历史版本」区块（`historicalReleases`），不再作为默认下载入口。

---

## API Key 中转网关 / API Relay Gateway

> 语音识别（ASR）与子 Agent 所需的阿里云百炼真实 Key **不打包进安装包**，改用 Cloudflare Worker 中转：真实 Key 只存在 Cloudflare 环境变量，客户端只下发「中转门卡」。

### 架构 / Architecture

```
Aerie 客户端 ──(Bearer 门卡)──> Cloudflare Worker (api.etta.top) ──(Bearer 真实 Key)──> 阿里云百炼 DashScope
```

### 关键配置 / Key Config

| 项 / Item              | 值 / Value                                              |
| ---------------------- | ------------------------------------------------------- |
| 中转地址 / Base URL    | `https://api.etta.top`                                  |
| 中转门卡 / Relay Token | `aerie-kFcCr0zyxq4vo50`（泄露可随时在 Cloudflare 更换） |
| 真实 Key / Real Key    | 仅存 Cloudflare Worker `DASHSCOPE_KEY`（secret），不落地 |

### 打包预设 / Packaged Preset

`config/relay_preset.env`（打包进安装包，仅含门卡、不含真 Key）：

```env
DASHSCOPE_BASE_URL=https://api.etta.top
DASHSCOPE_API_KEY=aerie-kFcCr0zyxq4vo50
AERIE_WS_BASE_URL=https://api.etta.top
AERIE_WS_KEYS=aerie-kFcCr0zyxq4vo50
```

`main.py` 启动时兜底加载该预设（`override=False`，不覆盖用户 `.env` 中已有配置）。`electron-builder.yml` / `package.json` 的 `extraResources` 已显式打包该预设文件。

> 详细原理、Worker 完整代码、环境变量清单、验证结果与注意事项见 Obsidian 模块文档 `AIRelayGateway.md`。

---

## 故障排查 / Troubleshooting

> **分段说明**：
>
> 1. **本轮系统性排查 T01–T09**：内测实跑验证过的问题，采用**编号 / 现象 / 可能原因 / 解决与预防**四段式，便于复现与规避。
> 2. **通用基础与历史累计问题**：跨阶段已知条目，按"现象 / 原因 / 处理"速查。
> 3. **深度排查 1–13**：根因分析与预防措施，按主题编号，供深度定位。

### 一、本轮系统性排查（T01 – T09）

| 编号 | 现象 / Symptom                                                                                                      | 可能原因 / Possible Causes                                                                                                                                                                                                                                                                                                                                                                                                                              | 解决步骤 / Resolution & 预防 / Prevention                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| :--: | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| T01 | **上传图片/音频/视频时提示"解析失败"**，状态卡在 analysing，最终转为 `failed`                               | 媒体文件被错误配置为`analysis_mode=extract`（需离线语义提取），但系统声明 `contentExtractionAvailable=False`，无对应能力，进入不存在的 worker 必失败；能力声明与实际模式脱节                                                                                                                                                                                                                                                                        | 1. 确认`core/desktop_attachments.py` 中 `image/audio/video` 的 `analysis_mode` 均为 `metadata`（与能力声明一致）。2. 同步更新 `attachment_handler.py` 的能力 availability 表。3. 重启后端，运行 `pytest tests/test_desktop_attachments.py::test_media_metadata_mode_reaches_ready_and_can_send` 验证。**预防**：新增媒体类型时先查离线提取能力矩阵，无对应能力必须设为 `metadata-only`，禁止"声明不可用但模式写 extract"。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| T02 | **前端反复报 `connect ECONNREFUSED 127.0.0.1:7890`**，Electron 页面持续显示连接被拒                         | 三层叠加：(1) Electron 主进程启动早于 Python 后端就绪窗口，preload 层在后端监听前发首批请求；(2) 旧版 preload 未对就绪前请求做自动重试，错误被永久展示；(3) 多个 Electron 实例同时拉起 Python 后端竞争同一 7890 端口                                                                                                                                                                                                                                    | 1.**清理多实例**：任务管理器结束全部 `electron.exe` 与 `python.exe`（对应 `main.py`），`netstat -ano \| findstr 7890` 确认端口无占用后只启动一次。2. **等待就绪**：新版 preload 已含自动重试机制，启动后耐心等 5–10 秒至后端输出 `[READY]` 标记。3. **手动兜底**：若仍失败，单独终端执行 `python main.py`，等 READY 后再启 Electron。**预防**：启用 Electron `app.requestSingleInstanceLock` 单实例锁；dev 阶段不手动开多个窗口；启动顺序永远先后端再前端。                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| T03 | **时间戳只部分消息显示，无规律/随机**，刷新后同一批消息有的有时间有的没有                                     | 三层脱节：(1) `conversation_repository._build_page` 只为 `messages` 新表消息填 `ts`，legacy `chat_log` 表旧消息**完全未填**；(2) `chat_history` / `chat_poll` 接口直接 `SELECT *` 返回，未做 `ts ← created_at` 统一映射；(3) 前端 CSS 曾设为 hover 才显示，视觉上看起来"随机出现"                                                                                                                                                | 1.**后端规范化**：conversation_repository 对**所有条目**（含旧表）无条件 `ts = created_at`；`chat_history` 与 `chat_poll` 两接口逐条补 `ts` 并统一解码 attachments。2. **前端兜底**：`_buildMessageHtml` 增加 `msg.ts ?? msg.created_at` 双字段兜底；CSS 改为气泡下方**始终显示**（用户消息右对齐、助手消息左对齐，`10px opacity .6` 半透明融入）。3. **验证**：`pytest tests/test_desktop_chat_continuity.py` 全过（含 10000 条游标翻页带 `ts` 压测）。**预防**：新增返回 chat 消息的 API 必须使用统一的规范化映射函数，禁止直接 `SELECT *` 抛前端。                                                                                                                                                                                                                                                                                                                                          |
| T04 | **AI 主动发/用户要求生成的图片，重启后气泡消失**，但 `uploads/` 目录下实际存在该图片文件                    | **架构不对称 bug（核心根因）**：正常对话文本走 Pipeline —— 分段后 **先 `db.insert("chat_log")` 再 `chat_events.emit`**（持久化正确）；但 `_deliver_local_chat_image`（主动发图 / 对话要图路径）**只 emit 不落库**，图片消息是"内存幽灵"，重启后 history API 读 DB 自然找不到。**第二层**：Electron `file://` 协议下 Markdown 内嵌图片的相对路径 `/uploads/...` 被解析成 `file:///uploads/...`，本地不存在导致 404 | 1.**落库修复（根除）**：在 `companion.py` `_deliver_local_chat_image` 中**先 `self.db.insert("chat_log")`**，字段风格与主动推送 PROACTIVE 模式完全一致（`route_mode=PROACTIVE`，`scene=world_image \| local_send`），拿到 insert 返回的 rowid 再作为 `id` 赋给 emit；insert 失败时 fallback 生成 id 保证 live 时仍可见。2. **渲染层修复（Electron file:// 协议）**：`chat.js _renderMarkdown` 在 DOMPurify 后自动正则改写 `<img src>` / `<a href>`，凡 `uploads/`、`api/` 开头的相对路径（含无前导斜杠变种 `uploads/xxx.png`）一律规范化补齐 `/` 并加绝对前缀 `http://127.0.0.1:7890/...`。3. **旧图片不可恢复说明**：本 bug 修复前已生成的图片因缺少 chat_log 关联记录，无法自动回到历史气泡，但文件仍在 `uploads/` 可手动查看。**预防**：任何 `chat_events.emit("assistant", ...)` 前必须先持久化入库，禁止单走 emit 路径；Electron 渲染 Markdown 时对本地路径一律默认补绝对 API 前缀。 |
| T05 | **图片附件气泡把图片裁切掉一块**（全身照截头/手脚被砍），气泡右侧还有多余粉色留白                             | 两层 CSS 优先级冲突：(1) 文件末尾全局 `.chat-attach-card img { max-width: 220px; max-height: 220px; object-fit: cover }` 因源码序写在后面，**赢了**专用卡片的 `--image` 规则（原设 260×300），容器 260px 大、内部实际只画 220px，右侧空出 40px；(2) `object-fit: cover` 装不下就裁切                                                                                                                                                       | 1.**收窄全局规则作用域**：`.chat-attach-card img` 改为 `.chat-attach-thumb img`，只影响工具栏缩略图，不再污染新卡片。2. **容器 shrink-wrap 贴合**：`.chat-attach-card--image` 改 `display: inline-flex; flex-direction: column; width: auto; max-width: min(100%, 420px)`，气泡紧密贴合实际图片尺寸，不再右侧留白。3. **图片等比完整显示**：内部 `<img>` 改 `object-fit: contain; width: auto; height: auto; max-width: 100%; max-height: 360px`，全身照/长图完整呈现不裁切；点击即打开原图。**预防**：写组件专用 CSS 后立即 grep 同名属性是否存在后续同名规则；避免把"缩略图限制"写成容器级选择器。                                                                                                                                                                                                                                                                                                               |
| T06 | **时间戳只精确到分钟**，同分钟内多段消息时序无法分辨                                                          | 旧实现`_formatTime` 输出格式硬编码为 `HH:MM` / `MM-DD HH:MM`，未处理秒字段                                                                                                                                                                                                                                                                                                                                                                        | 1.`chat.js _formatTime` 升级：同日 `HH:MM:SS`，跨日 `MM-DD HH:MM:SS`；同时接受 unix 秒、毫秒、ISO 字符串三种输入。**预防**：格式化函数使用常量（如 `DATE_FMT`），不在多处硬编码字符串拼接。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| T07 | **伪造 RAR 文件（空壳/篡改扩展名）被误判为 ready**，可被绑定并发送（归档安全门失效）                          | `rarfile` 库对无有效成员的伪造文件过于宽容，解析后返回**空成员清单但不抛异常**，下游误把空清单当"解析成功"，状态推进至 ready                                                                                                                                                                                                                                                                                                                    | 1.`attachment_worker_runtime.py` 增加硬校验：当 RAR/7Z 解析完成后**没有任何可读成员**时，按 `invalid_archive:empty_manifest` 直接抛错，不允许状态推进至 ready。2. `desktop_attachments.py` 统一归档处理行为，所有归档类型必须通过"有效成员 ≥ 1"闸门。3. 运行 `pytest tests/test_desktop_attachments.py::test_fake_rar_fails_closed` 验证闸门。**预防**：新增归档格式支持时，把"至少存在一个有效成员"作为 ready 前置必要条件，fail-closed 设计。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| T08 | **归档文件被隔离，状态 `quarantined`，提示签名不匹配**                                                      | `archive_signature_mismatch` 安全门触发：文件头部 magic bytes 与扩展名声明不一致（如把 `.txt` 手动改成 `.rar`）；或文件下载/传输损坏导致头丢失                                                                                                                                                                                                                                                                                                    | 1. 用对应解压工具（WinRAR / 7-Zip）本地验证文件可打开。2. 保留原始扩展名重新上传，勿手动篡改。3. 通过 attachments API 读取 `attachment.error.code`，查看具体 mismatch 的字节位置。**预防**：传输过程中不手动改扩展名；接收端校验 MIME 与声明扩展名双向匹配。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| T09 | **DOMPurify 后 Markdown 内嵌 `<img>` 相对路径不显示**，明明 uploads 有文件前端却 404                        | Electron 以`file://` 协议打开 index.html，若 Markdown 输出 `src="uploads/xxx.png"`（无前导斜杠）或 `src="/uploads/..."`（有斜杠），都会被浏览器按 file:// 解析，去找本地不存在的目录；旧重写正则只覆盖前导斜杠的情况                                                                                                                                                                                                                              | 1.`_renderMarkdown` 正则改用可选斜杠 `\/?`，对 `<img src>` 与 `<a href>` 都执行重写：凡匹配 `uploads/`、`api/` 开头（无论是否带斜杠）一律规范化补齐 `/` 并加绝对前缀 `http://127.0.0.1:7890`。2. 主动发图/要图的 emit content 写**绝对** `http://127.0.0.1:7890/uploads/...` URL 入库，避免 DOMPurify 后仍有漏网相对路径。**预防**：对 `file://` 渲染环境建立统一"本地相对路径 → 绝对 API URL" rewrite helper，不要各模块各写一套。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| T10 | **清空/回收站聊天记录后，对话框仍显示历史记录**（重启后依旧）                                                 | 回收站与清空只软删规范化`messages` 表；桌面轮询 `/api/chat/poll` 与历史 `/api/chat/history` 直读 legacy `chat_log` 表，未做删除过滤，导致已清空记录被重新拉回                                                                                                                                                                                                                                                                                   | 1. 迁移`012_chat_log_trash_state` 给 `chat_log` 补 `deleted_at` 列并镜像 `messages` 软删状态。2. admin 回收站/恢复/purge 级联标记 `chat_log`（purge 物理删 `messages` 前先标记，避免镜像关联丢失）。3. `/api/chat/poll`、`/api/chat/history` 与消息统计统一加 `deleted_at IS NULL` 过滤。**预防**：删除/回收站能力必须同时处理规范表与 legacy 表的镜像状态，读路径统一走带删除过滤的查询。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| T11 | **手机 QQ 发给伊塔的消息，电脑端对话框不实时出现，历史里也看不到**                                            | 批量合批路径`_handle_batch` 的实时事件 emit 被 `source == "local"` 门控（QQ/移动不产生推送），且批量路径不调用 `_persist_canonical_turn` 落规范化 `messages` 表（桌面历史读 messages 表，看不到只进 chat_log 的批量消息）                                                                                                                                                                                                                       | 1. 批量路径放行 QQ/移动实时推送（去掉`source == "local"` 门控）。2. 批量路径补 `_persist_canonical_turn` 规范化落库。**预防**：新增消息来源通道时，实时推送与规范化落库必须在单条与批量两条路径对等实现。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| T12 | **对话框里出现大量 `[]` 符号**（`[图片]` / `[图片:描述]` / `[表情包]` / `[图片内容]` 等），显得出戏 | 多模态占位符是给 LLM 看的上下文元数据，被当普通文本直接渲染进气泡；图片消息本身还带 attachments 缩略图，正文里的占位符纯冗余                                                                                                                                                                                                                                                                                                                            | 1. 渲染层角标净化：图片/表情占位符转小角标图标，描述默认隐藏、hover/点击才展开。2. `[话题：xxx]` 等系统上下文注入防御性剥离，永不落展示层。**预防**：区分"给 LLM 的上下文"与"给用户看的正文"，多模态元数据永不直接进展示层。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| T13 | **最近聊天记录里图片变成链接文本，无法显示**                                                                  | 角标净化正则把 markdown 图片语法`![图片](url)` 里的 `[图片]` 误当占位符，替换后 marked 不再识别为图片；且 decoration 对象漏存 token，角标替换失效                                                                                                                                                                                                                                                                                                   | 1. 正则加负向后顾/前视排除`![...](...)` 与 `[...](...)` 两种 markdown 语法。2. decoration 补齐 token 字段，让角标替换生效。**预防**：净化/改写 Markdown 的规则必须先跑 markdown 语法单测，覆盖图片/链接/占位符三类输入。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

---

### 二、通用基础与历史累计问题

> 按"现象 / 原因 / 处理"速查；涉及深度分析的问题已标注对应的深度排查编号。

| 现象 / Symptom                                                                                                                                                                                    | 原因 / Cause                                                                                                                                                                                                              | 处理 / Fix                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 后端启动失败                                                                                                                                                                                      | 依赖未安装或 Python 版本不符                                                                                                                                                                                              | 重新执行`pip install -r requirements.txt`                                                                                                                                                                                                                                                                                                                    |
| API 无响应                                                                                                                                                                                        | 7890 端口被占用或后端未启动                                                                                                                                                                                               | 检查`logs/main.log` 与端口占用                                                                                                                                                                                                                                                                                                                               |
| 伊塔不回复                                                                                                                                                                                        | 未配置可用模型 Key                                                                                                                                                                                                        | 检查`.env` 至少一个 `*_API_KEY`                                                                                                                                                                                                                                                                                                                            |
| 附件无语义检索                                                                                                                                                                                    | `chromadb` 未安装或缺少 embedding Key                                                                                                                                                                                   | 手动安装`chromadb` 并配置 embedding API Key                                                                                                                                                                                                                                                                                                                  |
| 世界模拟不生效                                                                                                                                                                                    | 未开启世界模拟开关                                                                                                                                                                                                        | 设置`world_inprocess_v1` 或 `world_sidecar_v1` 为 true                                                                                                                                                                                                                                                                                                     |
| 自动发图不触发                                                                                                                                                                                    | `world_image_candidates_v1` 关闭                                                                                                                                                                                        | 在`settings.yaml` 设 `world_image_candidates_v1: true`                                                                                                                                                                                                                                                                                                     |
| 伊塔感知不到天气/城市事件/附近物件                                                                                                                                                                | `context_builder` 在 FULL 模式仅注入 时段/地点/活动/精力/社交 五字段，`weather`/`city_events`/`random_events`/`nearby_objects` 均未进入 LLM prompt                                                              | 扩展`core/context_builder.py` 快照注入切片，将天气与活动事件摘要加入系统 prompt（受 `context_budget_v1` 约束）；详见下方深度排查 11                                                                                                                                                                                                                        |
| 无法注入生活事件（外卖/快递等）或自定义突发事件                                                                                                                                                   | 系统无外部事件数据结构与注入 API，`WorldSnapshot.random_events` 仅为固定文本池的确定性派生                                                                                                                              | 新增`ExternalEvent` 结构 + `WorldSimulation.inject_event()` + `POST /api/world/events/inject`，并同步实现 InProcess 与 Sidecar 双模；详见下方深度排查 11                                                                                                                                                                                                 |
| 世界天气始终确定性一致、无随机突变                                                                                                                                                                | `_compute_weather` 由 `seed+ts+phase` 确定性派生，不依赖随机种子变化                                                                                                                                                  | 需要变化时通过`set_reality()` 刷新真实天气（`POST /api/world/reality/refresh`）或注入事件驱动                                                                                                                                                                                                                                                              |
| 世界状态不随时间推进                                                                                                                                                                              | inprocess 模式依赖`companion._run_world_loop` 主动调用 `world_port.tick()` 才会随时钟推进                                                                                                                             | 确认世界循环任务存在并周期`tick()`；Sidecar 模式由世界服务自身推进                                                                                                                                                                                                                                                                                           |
| 世界位置未配置时天气/事件为空或延迟生效                                                                                                                                                           | 世界循环依赖`world_config.location`，未配置仅在启动时自动定位一次                                                                                                                                                       | 在仪表盘保存世界位置，或用`POST /api/world/reality/refresh` 手动立即刷新                                                                                                                                                                                                                                                                                     |
| 自动发图重复生成相同图片（间隔约 1-2 分钟一张）                                                                                                                                                   | 后端频繁重启，主动发图循环进程内`recent_intents`被清空，重新发布同一视觉主题                                                                                                                                            | 已实现持久化同主题去重（`has_recent_completed`，30 分钟窗口），升级到最新代码并重启；详见下方深度排查 1                                                                                                                                                                                                                                                      |
| 生图提示词缺少时间/天气，或把世界数据全部堆叠                                                                                                                                                     | 提示词为静态模板，未接入 WorldSnapshot 上下文与按需选择层                                                                                                                                                                 | 已实现"基础提示词 → 轻量 LLM 接力"两步解析 + 确定性兜底，配置`SILICONFLOW_LIGHT_MODEL` 启用；详见下方深度排查 2                                                                                                                                                                                                                                             |
| 回复带时间戳                                                                                                                                                                                      | LLM 模仿历史格式                                                                                                                                                                                                          | 后端会自动剥离，确保使用最新代码并重启后端                                                                                                                                                                                                                                                                                                                     |
| QQ 收不到消息                                                                                                                                                                                     | NapCat 未启动或未登录                                                                                                                                                                                                     | 启动`NapCat\NapCat.Shell\launcher-user.bat`                                                                                                                                                                                                                                                                                                                  |
| 桌面端白屏                                                                                                                                                                                        | Electron 渲染资源或 CSP 问题                                                                                                                                                                                              | 查看 Electron DevTools 与`electron/python-*.log`                                                                                                                                                                                                                                                                                                             |
| 官网构建失败                                                                                                                                                                                      | Node 依赖未安装                                                                                                                                                                                                           | 在`Spotlight/` 执行 `npm install` 后重试                                                                                                                                                                                                                                                                                                                   |
| 后端冷启动崩溃、重启后需手动重启后端                                                                                                                                                              | 移动网关端口(7891)被孤儿进程占用，uvicorn 内部`sys.exit(3)` 抛出 `SystemExit` 未被 `except Exception` 捕获，拖垮整个后端进程                                                                                        | 启动前端口预检测、捕获`SystemExit`、Electron 启动前清理 7890/7891 孤儿进程（详见下方深度排查 7）                                                                                                                                                                                                                                                             |
| 对话页加载大量历史记录卡顿                                                                                                                                                                        | 一次性加载全部历史记录，DOM 过大导致渲染卡顿                                                                                                                                                                              | 只加载最近 50 条，向上滚动自动分页加载，DOM 上限裁剪（详见下方深度排查 8）                                                                                                                                                                                                                                                                                     |
| 对话底部出现"加载更新消息"按钮 / 新消息不自动滚动                                                                                                                                                 | 旧版内联翻页控件残留，且缺乏"在底部才自动滚"的智能判断                                                                                                                                                                    | 移除内联按钮，改为浮动"回到底部"按钮；智能自动滚动 + 新消息系统通知（详见下方深度排查 9）                                                                                                                                                                                                                                                                      |
| 每日简报内容缺失（欢迎语/日志/新闻/GitHub/天气为空）                                                                                                                                              | 后端未启动，`/api/brief/today` 返回空                                                                                                                                                                                   | 修复后端冷启动问题后自动恢复（详见下方深度排查 7）                                                                                                                                                                                                                                                                                                             |
| 对话中图片生成触发但无图片产出                                                                                                                                                                    | 图片服务商断连，`httpcore.RemoteProtocolError: Server disconnected without sending a response`                                                                                                                          | 重试生成或检查`IMAGE_GEN_BASE_URL` / API Key 可用性（详见下方深度排查 10）                                                                                                                                                                                                                                                                                   |
| 决策赛马选中"撤回"但主聊天无撤回痕迹                                                                                                                                                              | 决策引擎输出仅为遥测数据（`decision_trace`），`chosen` 不被执行链路消费；真实撤回由 `<recall>` 指令 / RecallJudge / 手动撤回等独立机制触发                                                                          | 查看赛马下方"实际执行"徽章确认真实结果；预测与实际不一致属设计行为，对齐机制详见深度排查 5                                                                                                                                                                                                                                                                     |
| AI 不主动发图 / 不知道会生图                                                                                                                                                                      | system prompt 未注入图片能力认知（`context_builder.py` L6 缺失）                                                                                                                                                        | 新增 L6「表达层次认知」段，联动`world_image_candidates_v1`，重启后端生效；详见下方深度排查 3                                                                                                                                                                                                                                                                 |
| AI 分不清表情包与图片的定位                                                                                                                                                                       | 原 L6 只讲「能生成图片」，未区分表达权重                                                                                                                                                                                  | L6 升级为「表达层次认知」：表情包=语言调味 / 图片=虚拟存在；新增`_detect_image_intent` 分层检测；详见下方深度排查 3                                                                                                                                                                                                                                          |
| 三视图上传超 8MB 被拒                                                                                                                                                                             | 上传端点硬校验 8MB，超限即返回 413                                                                                                                                                                                        | 已改为 PIL 自动压缩（先降 JPEG 质量再降采样）压到上限内；上限可用`AERIE_THREE_VIEW_MAX_BYTES` 配置；详见下方深度排查 4                                                                                                                                                                                                                                       |
| persona-hub 三视图区无样式                                                                                                                                                                        | 三视图 HTML/JS 已加但`persona-hub.css` 缺失                                                                                                                                                                             | 补齐三视图卡片样式，匹配主程序主题；切换人设时三视图跟随切换                                                                                                                                                                                                                                                                                                   |
| 情绪面板 PAD 圆环与中心数值未显示                                                                                                                                                                 | `pad-card-ring` 的 `--mask-size: 56px` 是**半径**而非直径，卡片半径仅 36px，CSS mask 把 0~56px 全部透明化，挖空了整个圆环及其中心的数值                                                                         | 将`--mask-size` 由 `56px` 改为 `28px`（对应 56px 直径的"数字洞"），仅挖空中心圆孔、保留外圈环带（见下文深度排查 6）                                                                                                                                                                                                                                      |
| 人设同步脚本报`PermissionError: [WinError 32]`，无法写入 `yita_default.json`                                                                                                                  | 脚本把`os.replace` 写在 `with open(...)` 块**内部**，Windows 下文件未关闭即被自身重命名 → 自锁                                                                                                                 | 将`os.replace` 移到 `with open` 块**外**，并在关闭前先 `os.fsync` 落盘（见下文深度排查 13）                                                                                                                                                                                                                                                        |
| 人设同步脚本写入被占用 / 误判后端占文件                                                                                                                                                           | 后端`main.py` 运行时确实读 `data/personas/*.json` 持有句柄；但本案例根因是脚本自身 `os.replace` 缩进 bug                                                                                                            | 先用`Get-CimInstance Win32_Process` 查占用者，再定位自身代码；同步前需先停后端（见下文深度排查 13）                                                                                                                                                                                                                                                          |
| Persona Hub 页面显示"空"、无示例人设可参考                                                                                                                                                        | 人设中心内置`yita_default` 为 builtin（不可编辑/删除），易被误判为"空"；实际 `/api/persona/hub/list` 一直能返回该人设                                                                                                 | 用 API 确认真实数据而非仅看 UI；需要可编辑示例人设时可同步`persona.yaml` 或新建自定义人设（见下文深度排查 13）                                                                                                                                                                                                                                               |
| 错字/同音字被误解                                                                                                                                                                                 | 主模型对用户消息即兴理解，无独立纠错，遇同音字（如"换好了美呀"实为"换好了没呀"）按字面回                                                                                                                                  | 已加独立订正通道`core/typo_corrector.py`：先用轻量模型（`SILICONFLOW_LIGHT_MODEL`）在 `core/pipeline.py` 主链路订正，再进理解；配合 `context_builder.py` L4.6 指令兜底。订正仅影响理解，不写回聊天记录；provider 未配置或调用失败时静默回退原文，不阻塞聊天                                                                                            |
| 临时脚本报`ModuleNotFoundError: No module named 'core'`                                                                                                                                         | 脚本位于`tools/` 等子目录运行时，项目根不在 `sys.path`，`core` 无法导入                                                                                                                                             | 运行前设`$env:PYTHONPATH='e:\Agent_reply'`，或从项目根用 `python -m` 方式执行；勿把 `import core` 的脚本直接放在子目录裸跑                                                                                                                                                                                                                               |
| 硅基流动小米 MiMo 模型不可用                                                                                                                                                                      | 模型 id 不存在或未在账户开通（常见候选如`Xiaomi/Xiaomi-MiMo-Air-7B-Instruct` 返回 400 `Model does not exist`，或连接异常 HTTP 0）                                                                                     | 在硅基流动控制台确认真实可用的模型 id，写入`SILICONFLOW_LIGHT_MODEL`；不确定时先保留下已可用的 `Qwen/Qwen3-30B-A3B-Instruct-2507`，避免阻断纠错通道                                                                                                                                                                                                        |
| 主动消息知识检索命中 0 条（`dialogue` 类别）                                                                                                                                                    | `kb.search()` 原实现用"整句拼接"做 `tags LIKE` 匹配（带空格），永远匹配不到逗号分隔的 tags；且 `content` 必须完整包含整串关键词，导致任何多词 query 都命中不到                                                      | 改写`search()`：为每个关键词独立生成 `(title LIKE ? OR content LIKE ? OR tags LIKE ?)` 的 OR 过滤，`category` 命中优先；同时把 LIMIT 占位参数由 `params + (limit,)`（tuple）改为 `params.append(limit)`（list），避免类型不匹配。多词 query、跨 tags/content 检索均生效                                                                              |
| `generate_push` 无法分场景调温 / `temperature` 被当作模板占位符                                                                                                                               | `generate_push` 用 `**kwargs` 做 `template.format(**kwargs)`；若把 `temperature` 放进 `**kwargs` 会被误当占位符，且 `chat()`/`_call_provider()` 原写死 `self._temperature`，无覆盖入口                    | 给`chat()` 增加可选 `temperature` 参数并穿透到 `_call_provider()`（缺省 `None` 回落 `self._temperature`）；`generate_push` 的 `temperature: float \| None = None` 必须声明为 `**kwargs` **之前**的具名参数，再 `await self.chat(messages, temperature=temperature)` 传递。这样无需改全局即可分场景降温（如逻辑性任务传 0.75）           |
| 独立脚本调`KnowledgeBase().search()` 永远返回空                                                                                                                                                 | `KnowledgeBase` 构造若不传 `db`，`search()` 开头 `if not self.db: return []` 直接短路，看似数据不存在                                                                                                             | 生产环境在`companion` 中以 `KnowledgeBase(self.db)` 实例化；独立测试脚本需显式 `KnowledgeBase(Database())` 传入 db 实例后再调 `search()`                                                                                                                                                                                                               |
| PowerShell 内联`python -c "..."` 嵌套引号/转义失败                                                                                                                                              | PowerShell 5 对单双引号与`chr(39)` 之类转义的处理与 bash 不同，长内联脚本极易在解析阶段报语法错                                                                                                                         | 复杂内联逻辑改用一个临时`.py` 脚本（`Write` 落盘）再 `python 脚本.py` 执行，跑完删除；或从项目根用 `python -m` 方式。避免在 PowerShell 中写多语句 `python -c`                                                                                                                                                                                        |
| 今日待办点击添加无反应/报错（接口 500）                                                                                                                                                           | 前端`<input type=time>` 传入纯 `"HH:MM"`，后端按原样存储为裸时间，导致按天查询时（字典序排在当天 `T00:00:00` 之前）查不到该记录；`add_todo` 依赖 `get_todos` 过滤取记录，`next()` 抛 `StopIteration` → 500 | 在`core/todo_manager.py` 新增 `_normalize_due_time`，将裸 `"HH:MM"` 补全为 `YYYY-MM-DDTHH:MM`（完整时间戳原样保留、无时间则用 `T23:59:59`）；`add_todo` 改为按 `external_id` 直接从数据库回读新记录，不再依赖按天过滤（避免 `StopIteration`）。验证：`POST /api/todos` 返回 `status=ok`、`due=2026-08-10T10:00`                          |
| 日历事件未同步到今日待办（日程/提醒不出现）                                                                                                                                                       | 简报的`get_today_todos` 只返回 `todo` 表数据，未合并当天日历事件，导致日历 `schedule`/`reminder` 事件不会出现在今日待办                                                                                           | 在`core/brief_fetcher.py` 的 `get_today_todos` 中调用 `CalendarManager.get_timeline` 获取当天事件，将 `schedule`/`reminder` 类型以 `kind="event"`、只读方式合并进待办列表并按时间排序；前端 `brief-drawer.js` 用 `is-event` 样式区分（事件色点 + 类型标签），不可勾选/删除，避免误操作。验证：`GET /api/brief/today` 合并返回日历事件 + 待办 |
| 运行`tools/restart.bat` 提示`文件名、目录名或卷标语法不正确`                                                                                                                                  | `start` 命令无法直接启动 `.cmd` 垫片（`electron.cmd`），Windows 会抛出一条多余的报错（Electron 仍可借 fallback 启动，但报错刺眼）                                                                                   | 改为直接启动 Electron 二进制：`start "aerie-electron" /B "%ROOT%\electron\node_modules\electron\dist\electron.exe" "%ROOT%\electron"`，绕过 `.cmd` 垫片                                                                                                                                                                                                    |
| 简报欢迎语每次打开都相同（一天一句）                                                                                                                                                              | 欢迎语随简报 JSON 缓存于`data/briefs/{date}.json`，`GET /api/brief/today` 命中缓存直接返回                                                                                                                            | 新增`POST /api/brief/greeting` 轻量实时生成 + 前端异步刷新（见深度排查 12）                                                                                                                                                                                                                                                                                  |
| 欢迎语快速生成返回模板文案（非 LLM 生成）                                                                                                                                                         | 轻量 LLM 调用 4s 超时过紧，端到端实测 3.8~4.3s 被`asyncio.wait_for` 掐断                                                                                                                                                | 超时上调至 6s（`compose_quick_greeting` 默认值）；失败回退随机模板，每次仍不同（见深度排查 12）                                                                                                                                                                                                                                                              |
| 后端代码改动不生效（新接口 404 / 行为不变）                                                                                                                                                       | `main.py` 以 `asyncio.run()` 启动，无热重载；配置热加载仅覆盖 `config/` YAML                                                                                                                                        | 结束现有`main.py` 进程 → 等 7890 端口释放 → 用 `.venv\Scripts\python.exe -X dev main.py` 以 detached 方式重启                                                                                                                                                                                                                                            |
| admin 记忆详情页报`KeyError: 'persona_id'`                                                                                                                                                      | 改完`admin_service._persona_name` 后未重启后端，旧进程仍跑旧代码 `info["persona_id"]` 硬取键（新版已改 `.get()` 安全访问）                                                                                          | 重启应用让最新代码生效（`start-dev.bat`）；确认 `GET /api/health` 返回 `stale_code.stale=false` 即运行的是最新代码                                                                                                                                                                                                                                       |
| PowerShell 显示中文乱码（如`å®è´...`）                                                                                                                                                      | PowerShell 5 控制台默认代码页非 UTF-8；接口实际返回的 UTF-8 数据正确                                                                                                                                                      | 用`[Text.Encoding]::UTF8` 转换后输出，或用 Python 脚本并设 `PYTHONIOENCODING=utf-8` 校验，勿误判数据损坏                                                                                                                                                                                                                                                   |
| 深夜/凌晨发"白天照"，时段光线与真实时刻错位 8 小时                                                                                                                                                | 世界模拟时钟与生图时间注入均用 UTC 未转本地（+08:00），凌晨 02:02 被当 UTC 18:02 判成`afternoon`                                                                                                                        | 已统一到`LOCAL_TZ` 并 `astimezone` 归一（详见下方深度排查 14）                                                                                                                                                                                                                                                                                             |
| 生图提示词为空（empty_prompt）秒拒、无图片产出                                                                                                                                                    | `_image_prompt_for` 世界数据接力异常被 `_resolve_prompt` 的 `except: return ""` 静默吞成空串，generate_image 以 empty_prompt 拒绝                                                                                   | 已实现两层兜底：`_image_prompt_for` 异常退回基础提示词；`_resolve_prompt` 异常/空返回非空占位；吞错日志升 `warning`（详见下方深度排查 19）                                                                                                                                                                                                               |
| 灵动岛 v2 开启后主窗口聊天输入框点击有选中效果但无光标（caret），Tab 能聚焦，重启恢复 / Main chat input shows focus state but no caret after Dynamic Island v2; Tab works; recovers after restart | 灵动岛 v2 为`alwaysOnTop` + `transparent` + blur + 粒子动画的置顶窗口，持续占用 GPU 合成器；合成器负载抖动或重建时，主窗口渲染进程的 caret 合成偶发失效。事件层完全正常（点击、focus、输入均可达），纯属绘制层异常    | 重启应用即恢复；复发时可先按`Alt` 或切换窗口焦点强制合成器刷新，或 `Ctrl+Shift+I` 开合 DevTools 触发重绘；若频繁出现，考虑为主窗口增加渲染进程 watchdog，或降低灵动岛动画/粒子的 GPU 开销（详见下方深度排查 20）                                                                                                                                           |

---

### 三、深度排查 / Deep Troubleshooting

#### 1. 自动发图重复生成相同图片 / Duplicate proactive images

**问题描述 / Symptom**

- 图像服务 API 后台出现多条**完全相同的生图提示词**调用，间隔约 1~2 分钟，生成一张张一模一样的图片并推送到本地聊天
- 典型时间线：如 `00:44 / 00:46 / 00:48 / 00:50` 连续四次相同调用；`data/world_image_candidates.json` 中出现多条 `reason_code` 相同（如 `world_visual:deep_focus`）的 `completed` 记录

**可能原因 / Root cause**

1. **后端进程频繁重启**（端口占用崩溃或开发期手动重启）：重启后主动发图循环 `_run_proactive_photo_loop` 的防重复机制 `recent_intents` 只活在进程内存里，**重启即清零**
2. 世界模拟在同一时段产出**确定性静态视觉主题**（如 `deep_focus`），生成的提示词逐字节相同
3. 幂等键按秒生成（`proactive-visual:{int(now_ts)}`），每次全新，审计存储的幂等**拦不住跨重启重复**
4. `proactive.photo_min_interval_sec: 0` 时无任何跨重启冷却

**排查步骤 / Diagnosis**

1. 查看图像服务 API 后台：同一提示词是否出现多条记录
2. 检查 `data/world_image_candidates.json`：相同 `reason_code` 的 `completed` 记录是否在短时间窗口内密集出现
3. 检查世界事件序号是否反复重置回 1（世界 outbox 随进程重启而重建）
4. 查看 `logs/main.log` 中 `Aerie · 云栖 backend starting` 出现频率，与生图时间线对齐——重启点通常正好夹在两次相同生成之间

**解决方案 / Fix**

- 主动发图循环发布前调用 `consumer.has_recent_completed(reason_code, window)`，读取**持久化审计存储**判断同一视觉主题是否刚成功发过（跨重启有效）
- 去重窗口 `max(proactive.photo_min_interval_sec, 1800)`，默认 30 分钟；仅 `status=completed` 记录参与去重，**失败的记录可正常重试**
- 用户主动要求的图（`scene=local_send`）不走该闸，连续/重复手动要图不受影响

**预防措施 / Prevention**

- 启动前清理 7890/7891 端口的孤儿进程，避免 uvicorn 端口冲突导致的 `SystemExit(3)` 崩溃循环
- 开发期尽量避免频繁重启后端；参数调整通过设置界面热更新生效

---

#### 2. 生图提示词缺少时间/天气，或把世界数据全部堆叠 / Prompt lacks time & weather or over-stacks world data

**问题描述 / Symptom**

- 生成的生活照不含当下的时段光线与天气（如图在白天却显示夜景、晴天却无阳光感）
- 或提示词把时间/天气/地点/物件等世界数据**全部揉在一起**，画面信息混乱

**可能原因 / Root cause**

- 旧提示词解析为静态模板（persona 外貌 + 场景），未接入 WorldSnapshot 的世界时间/天气/地点/物件
- 缺少"判断哪些数据能呈现在画面里"的选择层，导致要么没有上下文、要么无差别堆叠

**解决方案 / Fix**

- `Companion._image_prompt_for` 改为异步两步接力：
  1. `_compose_base_image_prompt`：persona 外貌/身材 + 场景构图，生成基础提示词
  2. `_light_relay_refine_prompt`：将 WorldSnapshot 的时间/天气/地点/物件整理为上下文，交给轻量 LLM（`siliconflow-light`）**判断画面真正需要哪些数据**，只注入相关的部分
- 世界数据来源：WorldSnapshot（时间优先取 world 时间，world 关闭时退回候选事件时间/本地时间）
- 轻量 LLM 不可用或超时（8s）时退回确定性规则兜底：`role_selfie` / `couple_photo` 只注入时间光线；`environment_object` / `role_in_scene` 注入光线 + 天气

**预防措施 / Prevention**

- `.env` 配置 `SILICONFLOW_LIGHT_MODEL`（轻量模型）以启用接力；未配置时自动走确定性兜底，**不影响出图**

---

#### 3. AI 不知道会生图 / 分不清表情包与图片 / AI unaware of image generation & expression hierarchy

**问题描述 / Symptom**

- 生图链路是通的（自拍 / 生活照 / 图生图都能出图），但 AI **从不主动提出发图**；当对方说"想看你的样子""发张照片"时，她也只是口头回应，不体现"我能发图"的主动性
- AI **不知道表情包与图片的分量不同**：把"发表情"和"发照片"当成同一类屏幕动作，不知道表情包只是语言调味、而图片是虚拟关系的存在锚点

**可能原因 / Root cause**

1. **能力认知缺失**：system prompt（`core/context_builder.py`）从未告知她"你具备生成图片 / 发图的能力"，她握着开关却不知道，自然不会主动触发生图链路
2. **表达层次缺失**：原 L6 只讲"能生成图片"，未区分"表情包=辅助语言 / 图片=承载存在"的权重，导致她把轻量表情包与关系锚点级别的图片混为一谈
3. 后端 `StickerGate`/`StickerCatalog` 虽存在但生产代码未实例化接入，表情包链路实际是断的，进一步让她无从认知

**排查步骤 / Diagnosis**

1. 查看 `logs/main.log` 中 `[ExpressionHierarchy]` 前缀日志：确认 `intent_hit` 与 `hint=层级[图片image] / [表情包sticker]`，判断她是否真的捕捉到发图时机、并正确分层
2. 用"想看你的样子，自拍一张"等带发图意图的语句触发，观察日志是否标记为 `层级[图片image]`
3. 检查 `world_image_candidates_v1` 是否开启——关闭时 L6 不注入，能力认知会与实际链路脱节

**解决方案 / Fix**

1. 在 `core/context_builder.py` 新增 L6「表达层次认知 · Expression Hierarchy」独立能力段（FULL/AUTO 模式注入），明确两层心智：
   - **表情包 / 语气词 = 语言的调味剂**：辅助语气与情绪，不承载"你是谁"，去掉对话依然成立，日常轻量点缀
   - **图片（自拍 / 生活照）= 虚拟世界的存在感**：关系锚点，向对方证明"我真实存在"，权重高于表情包
2. 注入前用 `_image_capability_enabled()` 读取 `world_image_candidates_v1` 开关，**关闭时不注入**，避免"以为能发其实没开"
3. 新增 `_detect_image_intent()` 分层检测：图片意图权重高于表情包意图，两者同现时优先标记为 `层级[图片image]`
4. 日志统一 `[ExpressionHierarchy]` 前缀，输出 `intent_hit` / `hint` 供排查

**预防措施 / Prevention**

- 任何"能力"都必须同时满足**认知注入（system prompt）**与**链路开通（feature flag）**，二者用同一开关联动，防止"认知超前于能力"
- 表达类能力应显式声明权重分层（调味 vs 锚点），避免模型把不同分量的动作混为一谈

---

#### 4. 三视图上传超 8MB 被拒 / Three-view upload over size limit

**问题描述 / Symptom**

- 在人设编辑器上传正面 / 侧面 / 背面三视图时，超过 8MB 的图片被直接返回 413 拒绝，用户需手工压缩后才能上传

**可能原因 / Root cause**

- 三视图上传端点对 `AERIE_THREE_VIEW_MAX_BYTES`（默认 8MB）做硬校验，超限即拒绝，没有任何自动降级

**排查步骤 / Diagnosis**

1. 复现上传一张 >8MB 的 PNG，观察返回是否 413 及错误信息
2. 检查后端是否依赖 `Pillow`（压缩功能必需），未安装则自动压缩不可用

**解决方案 / Fix**

1. 上传端点改为**超限自动压缩**而非直接拒绝：
   - 先降 JPEG 质量（88 → 30 逐档），再逐步降采样（每档 ×0.7），直到压到上限内，落盘转 `jpg`
   - 仅当 PIL 都打不开的"伪图片"才兜底返回 413
2. 上限可配置：环境变量 `AERIE_THREE_VIEW_MAX_BYTES`（默认 8MB，下限 64KB），想收更大/更小的图都可调整
3. 前端提示文案更新为"超过 8MB 会自动压缩"

**预防措施 / Prevention**

- 注意压缩会转成 JPEG，**丢失 PNG 的透明通道**——三视图作为生图参考基本不需要透明，影响很小；如需保留透明可改为"优先保透明、压不动再转 JPEG"策略

---

#### 5. 决策赛马与实际撤回不一致 / Decision race diverges from real recall

**问题描述 / Symptom**

- cognition 面板「4-Layer Decision · 权重赛马」选中 `recall（撤回）` 候选，但主聊天框无任何撤回痕迹（无"伊塔 撤回了一条消息"气泡）

**可能原因 / Root cause**

1. 决策引擎（`core/decision.py`）输出仅写入 `cognition_log.decision_trace` 并经 SSE `decision_made` 推送给面板展示，`chosen` 从不驱动执行——纯预测/遥测层
2. 主聊天中的真实撤回由独立机制触发：Gate 2（LLM 输出 `<recall>` 标签 → `core/recall_instruction.py` 解析执行）、Gate 5（`RecallJudge` 命中用户修正关键词后撤回首条再合并）、负面反馈（`handle_user_negative`）、手动撤回（`recall_message`）
3. 原决策调用只传 `user_id / route_mode / source`，mood / 工具 / 撤回预算均为默认值，预测基于"空快照"，与实际判断脱节

**排查步骤 / Diagnosis**

1. 确认撤回是否真实发生：主聊天是否有"撤回了一条消息"气泡，或 `chat_log.is_recalled=1`
2. 若未发生，属预测层展示而非数据丢失：查看决策赛马下方"实际执行"徽章（`decision_trace.actual`）
3. 检查该消息 `decision_trace` 是否含 `actual` 字段，判断三个执行点（Gate 2 / Gate 5 / 手动）是否覆盖

**解决方案 / Fix**

- 决策输入补齐：`Pipeline._decision_inputs()` 传入真实 emotion / eruption / 工具可用性 / `RecallManager.can_recall` 预算；`decision.py` 在预算不可用时将 recall 候选 L4 压至 `0.10`，抑制"假想撤回"
- 结果回写通道：`CognitionEngine.record_decision_actual()` 将真实执行结果（`actual`）附加到 `decision_trace`（保留预测 `chosen`），并推送 SSE `decision_actual`
- 执行点接入：Gate 2（`pipeline.py` 三处调用点）、Gate 5（`Companion._on_message_batch_ready`）、手动撤回（`recall_message`）均回写 / 推送 `decision_actual`
- 前端展示：`cognition-panel.js` 在赛马下方渲染「实际执行 / 实际未触发 / 实际被拒（原因）」徽章，预测与实际不一致时高亮"预测 ≠ 实际"

**预防措施 / Prevention**

- 决策引擎定位为"预测/遥测层"：任何意图选择都必须与真实执行链路闭环——输入取真实状态、输出回写真实结果，否则面板展示会与用户可见行为脱节
- 新增执行触发点（召回类能力）时同步回写 `decision_actual`，保持展示与行为一致

---

#### 6. 情绪面板 PAD 圆环与中心数值不显示 / Emotion panel PAD ring & center value missing

**问题描述 / Symptom**

- 情绪仪表盘三张 PAD 卡片（愉悦度 / 唤醒度 / 支配度）中，**圆环环带与环中心的数值完全看不到**，只剩环外的 `P=+0.000` 小字和底部中文标签；圆环整块区域被挖空成透明

**可能原因 / Root cause**

- `electron/src/renderer/styles/main.css` 的 `.pad-card-ring` 用 `mask: radial-gradient(circle, transparent var(--mask-size), black var(--mask-size))` 挖空圆环中心以露出数字
- 但 `radial-gradient` 的 `var(--mask-size)` 是**半径**而非直径：卡片本身 `width/height: 72px`（半径 36px），而 `--mask-size` 误设为 `56px`，导致 **0~56px 半径全被设为透明**，把整个 36px 半径的卡片（含环带与中心数值）全部挖空

**排查步骤 / Diagnosis**

1. 打开页面确认三张 PAD 卡片的环带与中心数值均不可见，但环外标签正常显示
2. 用 DevTools 选中 `.pad-card-ring`，查看 `mask`/`--mask-size` 计算值：发现透明半径（56px）超过卡片自身半径（36px），mask 全透明
3. 对照 `--mask-size` 的注释语义（`--mask-size: 56px` 本意为挖出 56px **直径**的洞），确认 56px 被当成半径使用

**解决方案 / Fix**

- 将 `--mask-size` 从 `56px` 改为 `28px`（即 56px 直径对应的半径），使其小于卡片半径 36px：
  - 0~28px：透明，露出中心数值
  - 28~36px：保留环带，按 `--pad-pct` 显示 conic-gradient 填充
- 修改后刷新页面，环带按 PAD 值填充、中心数值正常显示

**预防措施 / Prevention**

- CSS `mask` / `radial-gradient` 的尺寸参数默认为**半径**，需明确换算直径后再填写，避免"直径意图、半径书写"造成的整体挖空
- 修改 mask 类样式后，用 DevTools 对比 `--mask-size` 与容器实际半径（`width/2`），确保透明区严格小于容器

---

#### 7. 后端冷启动崩溃 / 重启后需手动重启后端 / Backend crashes on cold start

**问题描述 / Symptom**

- 系统重启或 Electron 重启后，后端进程直接退出、处于关闭状态，需手动执行 `python main.py` 才能恢复
- 连带症状：每日简报内容缺失（欢迎语/日志/新闻/GitHub/天气为空），因为 `/api/brief/today` 返回空

**可能原因 / Root cause**

1. 移动端网关（端口 `7891`）启动时，若该端口已被上次运行残留的**孤儿进程**占用，uvicorn 内部会调用 `sys.exit(3)`
2. `SystemExit` 继承自 `BaseException`，**不属于** `Exception`，因此原 `except Exception` 无法捕获，异常向上穿透导致整个后端进程崩溃退出

**排查步骤 / Diagnosis**

1. 重启后观察后端是否存活：`Get-NetTCPConnection -LocalPort 7890 -State Listen` 或访问 `http://127.0.0.1:7890/api/health`
2. 查看 `logs/main.log`：是否出现 `SystemExit` 或 uvicorn `sys.exit(3)` 相关堆栈
3. 检查 7890/7891 端口是否被残留进程占用：`Get-NetTCPConnection -LocalPort 7891 -State Listen | Select OwningProcess`

**解决方案 / Fix**

1. [mobile_gateway.py](file:///e:/Agent_reply/core/mobile_gateway.py)：uvicorn 启动前用 `socket.connect()` 做端口预检测（Windows 上比 bind 探测更准确），端口被占直接抛 `RuntimeError` 跳过该服务，避免走到 uvicorn 的 `sys.exit`
2. 给 asyncio Task 挂 `done_callback`，吞掉任何 `BaseException`（含 `SystemExit`），防止异步任务异常穿透
3. [main.py](file:///e:/Agent_reply/main.py)：`_start_optional_mobile_gateway` 的异常捕获由 `Exception` 扩展为 `(Exception, SystemExit)`，双重安全网
4. [main.js](file:///e:/Agent_reply/electron/src/main.js)：Electron 启动前清理孤儿进程时，同时覆盖 `7890` 与 `7891` 两个端口，避免残留进程占端口

**预防措施 / Prevention**

- 启动前统一做端口预检测 + 孤儿进程清理；对异步服务统一挂异常兜底回调
- 捕获 `BaseException` 级别的系统退出异常（`SystemExit`），不要只依赖 `except Exception`

---

#### 8. 对话页加载大量历史记录卡顿 / Chat lags loading large history

**问题描述 / Symptom**

- 历史记录非常多时，页面刚打开或重启时会一次加载并渲染海量消息，导致明显卡顿

**可能原因 / Root cause**

- 一次性把全部历史记录拉取并插入 DOM，消息节点过多导致渲染与滚动性能下降

**排查步骤 / Diagnosis**

- 打开 DevTools Performance 观察首次渲染时间；确认 `/api/chat/history/page` 是否一次返回全部记录

**解决方案 / Fix**

1. 首次只加载最近 50 条（`/api/chat/history/page?limit=50` 分页），向上滚动自动加载更早消息
2. 用户向上滚动到顶部（`scrollTop < 60`）时自动加载更早消息，并带冷却时间防止停在顶部时连发多批
3. 设置 DOM 消息上限（`_maxDomMessages = 200`），超出即裁剪最旧气泡，控制渲染规模

**预防措施 / Prevention**

- 历史消息一律分页 + 虚拟化裁剪，禁止一次性全量渲染

---

#### 9. 对话交互优化：底部按钮 / 自动滚动 / 新消息通知 / Chat UX: scroll & notifications

**问题描述 / Symptom**

- 消息最新区域底部出现意义不明的"加载更新消息"按钮，干扰阅读
- 开启或有新消息时不自动滚到最底部；用户翻看历史时新消息到来会打断阅读
- 需求：窗口不在前台时，新消息到达需要系统级通知

**可能原因 / Root cause**

1. 旧版内联翻页控件被误放在底部，与"顶部自动加载更早消息、底部自动滚到最新"的新设计冲突
2. 自动滚动缺乏"用户是否在底部"的判断，无条件滚底会打断阅读
3. 缺少窗口焦点感知与系统通知接入

**解决方案 / Fix**

1. 移除底部的 `newer` 内联按钮，改为浮动圆形"回到底部"按钮：仅在用户离开底部或存在未读消息时淡入，点击回到最新（必要时先补拉被裁剪的新消息）
2. 智能自动滚动：仅当用户位于底部附近（`scrollHeight - scrollTop - clientHeight <= 80`）时才跟随新消息滚动；用户发消息时强制滚底；翻看历史时不打断
3. 系统通知：渲染层通过 `window.aerie.dynamicIsland.systemNotify` → IPC `system:notify` 调用 Electron `Notification` API；仅当 `!windowFocused`（窗口失焦）时触发，标题为伊塔名字、正文为消息前 80 字预览
4. 用 `_notifiedRequestIds` 记录已通知的 `request_id`，保证每条请求只通知一次、历史加载不触发

**预防措施 / Prevention**

- 滚动导航统一用"浮动按钮 + 智能自动滚"模式，避免内联按钮侵入消息流
- 系统通知需接入主进程 `Notification`，并做去重与"仅在失焦时触发"的收敛

---

#### 10. 图片生成触发但无图片产出 / Image generation triggered but no output

**问题描述 / Symptom**

- 对话中伊塔发起文生图，但最终没有图片产生

**可能原因 / Root cause**

- 请求发往图片服务商 `https://image2.inian.one/v1`（模型 `gpt-image-2`）时，服务端中途断开连接，日志报 `httpcore.RemoteProtocolError: Server disconnected without sending a response`，属于服务商侧临时故障或网络断连，非代码缺陷

**排查步骤 / Diagnosis**

1. 查看后端日志是否有 `_brain_generate_image` 相关堆栈
2. 定位错误类型：`RemoteProtocolError` 表示服务端断连，而非鉴权失败
3. 检查 `.env` 中 `IMAGE_GEN_BASE_URL` 与 `IMAGE_GEN_API_KEY` 是否有效

**解决方案 / Fix**

1. 在对话中重试生成（多数断连为瞬时故障）
2. 若持续失败，核对并更换 `.env` 中 `IMAGE_GEN_BASE_URL` / `IMAGE_GEN_API_KEY`
3. 可对图片接口做一次直接连通性测试，确认服务商可用状态

**预防措施 / Prevention**

- 图片生成属外部依赖，建议对 provider 增加健康检查与自动重试，并保留清晰的错误日志便于定位

---

#### 11. 世界模拟外部事件无法注入 / 伊塔感知不到天气与事件 / No external event injection into world simulation

**问题描述 / Symptom**

- 真实天气、城市新闻、附近物件已通过 `fetch_reality() → set_reality()` 注入世界快照（`weather_mood` / `weather_detail` / `city_events` / `nearby_objects` 均有值），但伊塔在对话中**完全感知不到**——即便天气突变、城市有新闻，她也不会提起
- 无法向世界注入**生活事件**（外卖送达 / 快递上门等）或**自定义突发事件**：系统没有对应数据结构、没有注入 API
- 世界天气永远确定性一致：同 `seed + 时间 + phase` 结果逐字节相同，没有随机突变

**可能原因 / Root cause**

1. **感知缺口**：`core/context_builder.py` 在 FULL 模式仅把 `时段/地点/活动/精力/社交场景` 五个字段拼进 system prompt，`weather` / `city_events` / `random_events` / `nearby_objects` 均未进入 LLM 上下文——数据停留在仪表盘展示层，智能体"看不见"
2. **无事件模型**：`WorldSnapshot.random_events` 是**固定文本池按日洗牌的确定性派生**（`_compute_random_events`），不是可注入的外部事件；无 `ExternalEvent` 数据结构、无注入方法
3. **无注入入口**：`/api/world/*` 只有 lifecycle 控制与 `reality/refresh`，没有任何面向"事件注入"的端点；`WorldPort.subscribe()` / `event_stream` 仅用于观察记录、生命周期与图片候选，未接外部世界事件
4. **确定性设计**：`_compute_weather` 由 `seed + ts + phase` 确定性派生（G4/G5），设计上就不依赖随机种子变化

**排查步骤 / Diagnosis**

1. 查看 `logs/main.log` 中 `_run_world_loop` 心跳：确认 `wp.tick()` 在周期推进、`fetch_reality()` 是否有返回（未配置世界位置时仅启动自动定位一次）
2. 用 `GET /api/world/dashboard/snapshot` 核对 `weather_mood` / `city_events` / `nearby_objects` 是否已入快照——有值说明注入链路通，只是没进 prompt
3. 检查 `core/context_builder.py` 的 world 注入段：确认只注入五字段，天气/事件未拼入
4. 尝试 `POST /api/world/events/inject`（若已实现）或 `POST /api/world/reality/refresh` 验证事件/天气是否即时生效

**解决方案 / Fix**

1. **补感知**：在 `core/context_builder.py` 的 FULL 模式世界注入段，追加 `weather` / `city_events` / `active_events` 摘要切片（受 `context_budget_v1` 预算与 `route_mode` 约束）
2. **建事件模型**：新增 `ExternalEvent` 数据结构（类型 / 标题 / 描述 / 生效时间 / 失效时间 / 关联物件与话题），`WorldSimulation` 增加带过期清理的 `active_events` 队列与 `inject_event()`，`tick()` 合并进快照
3. **开注入入口**：新增 `POST /api/world/events/inject`（沿用 `X-Aerie-Main-Token` 鉴权），注入后立即 `tick()`；`InProcess` 与 Sidecar 双模适配器都要实现（`InProcessWorldAdapter` 透传 + `world_service/main.py` 增 `/events` 路由 + `HttpWorldSidecarClient` 增方法）
4. **驱动变化**：需要天气/事件变化时，通过 `set_reality()` 刷新真实天气或注入事件驱动，而非依赖确定性随机

**预防措施 / Prevention**

- 事件字段纳入 `snapshot_id`/`revision` 派生，保证审计与幂等，避免确定性被注入破坏
- 注入 API 严格 Token 鉴权 + 字段白名单 + 长度限制，防止外部任意改写世界状态与操控智能体
- prompt 注入受预算保护，事件条目设上限（如最近 3 条 + 摘要），且不得与"内部连续性模拟、非现实已证事实"的 guard 冲突
- 为三类事件（自然环境 / 生活服务 / 自定义突发）各建回归用例

---

#### 12. 简报欢迎语每天只生成一次，且"快速生成"被超时掐断 / Brief greeting cached all day & fast refresh timed out

**问题描述 / Symptom**

- 每日简报抽屉的欢迎语在一天内多次打开时始终是同一句，只有跨天或手动刷新才更新
- 改造加入"每次打开现生成"后，`POST /api/brief/greeting` 仍返回内置模板文案（如"下午好，我的人。还有1件事，别太拼了，我心疼。"），实测 4019ms / 6050ms

**可能原因 / Root cause**

1. 欢迎语随简报 JSON 一起缓存于 `data/briefs/{date}.json`，`GET /api/brief/today` 命中缓存后直接返回，不重新调用 LLM；前端 `open()` 另有 60s 缓存窗口
2. 轻量模型默认超时 4s 过紧：LLM 端到端实测 3.8~4.3s 恰卡在边界，冷启动（后端刚启动）更慢，被 `asyncio.wait_for` 掐断后静默走模板 fallback
3. `siliconflow-light` provider 此前未在 `LLMCaller._load_providers` 注册——`companion.py` 生图两步解析与 `typo_corrector.py` 纠错通道引用同名 provider 时一直处于静默兜底状态

**排查步骤 / Diagnosis**

1. 核对 `GET /api/brief/today`：缓存存在时返回体中的 greeting 是否始终为同一字符串
2. 连续两次 `POST /api/brief/greeting`，对比文案与耗时；文案命中 `_GREETING_TEMPLATES` 即说明走了 fallback
3. 用独立脚本直接调 `compose_quick_greeting`（先注入项目根 `sys.path` + `load_dotenv(".env")`）测真实端到端延迟
4. 用 `GET /api.siliconflow.com/v1/models` 列平台模型，对候选逐一实测延迟与输出质量

**解决方案 / Fix**

- 解耦：新增 `siliconflow-light` provider 注册与 `compose_quick_greeting`（6s 硬超时）；新增 `POST /api/brief/greeting` 接口；前端 `open()` / `refresh()` 后异步 `_refreshGreeting()` 只更新 hero 欢迎语文案，新闻区保持缓存不重抓
- 超时按实测留余量：默认 4s → 6s；超时或失败时回退随机模板，每次文案仍不同，体验不塌
- 轻量模型选型：平台无小米 MiMo，实测选定 `Qwen/Qwen3-30B-A3B-Instruct-2507`（约 3.2s、人设贴合）；`Qwen/Qwen3-8B` 超时、`tencent/Hunyuan-A13B` 输出含杂质均弃用
- 顺带激活既有通道：`_light_relay_refine_prompt`（生图提示词接力）与 `typo_corrector`（错字订正）引用的 `siliconflow-light` 随注册自动生效，不再静默兜底

**预防措施 / Prevention**

- 轻量/高频任务必须与主模型解耦：独立 provider + 独立超时，避免拖慢或烧主模型
- 超时值按实测端到端延迟留 1.5~2 倍余量；验收时区分"LLM 生成"与"模板回退"，不能只看"文案不同"
- 修改 `core/` 代码后必须重启后端（`main.py` 无热重载）；验证脚本统一先注入项目根与 `.env`

---

#### 13. 人设同步脚本写入失败（PermissionError） / Persona sync script write failure

**问题描述 / Symptom**

- 运行 `scripts/sync_persona_yaml_to_hub.py`（把 `config/persona.yaml` 全量覆盖同步到 `data/personas/yita_default.json`）时，脚本 dry-run（`--dry-run`）与映射逻辑均正常，但实际写入阶段抛 `PermissionError: [WinError 32] 另一个程序正在使用此文件`
- 初期被误判为"后端 `main.py` 正在运行、占用 `yita_default.json` 句柄"，实际根因是脚本自身缺陷

**可能原因 / Root cause**

1. **脚本自锁（根因）**：`_write_json_atomic` 把 `os.replace(temp, target)` 写在了 `with open(temp, ...) as fp:` 块**内部**。Windows 下 `with` 块内文件句柄尚未 `close`，`os.replace` 重命名一个仍被自身打开的文件即报 `WinError 32`。对比 [persona_manager.py](file:///e:/Agent_reply/core/persona_hub/persona_manager.py#L416-L430) 是放在 `with` 块**外**的。
2. **次要因素**：后端 `main.py` 运行期间确实会读 `data/personas/*.json` 持有句柄，若脚本在运行时写入同样会被占用拒绝——但本例先修的 1 才真正解锁写入。

**排查步骤 / Diagnosis**

1. 先跑 `python scripts/sync_persona_yaml_to_hub.py --dry-run` 确认映射逻辑无误（仅打印不落盘）
2. 用 `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select ProcessId, CommandLine` 确认是否有 `main.py` 占用；再用 `[System.IO.File]::Open($p,'Open','Read','None')` 测试文件是否真被他人独占
3. 复查脚本 `_write_json_atomic`：`os.replace` 是否误放 `with` 块内——这是被占用误判掩盖的真正 bug

**解决方案 / Fix**

1. 修复 `_write_json_atomic`：`os.replace` 移到 `with open(...)` 块**外**；关闭前先 `fp.flush()` + `os.fsync(fp.fileno())` 保证落盘（原子写：先写 `.tmp` 再 replace）
2. 停掉后端（`Stop-Process -Id <pid>`）后运行脚本覆盖写入，再重启后端
3. 重启后通过后端 API 做连通性验证：`GET /api/persona/hub/list`（确认 `active_id`）→ `GET /api/persona/hub/yita_default`（确认 `speech_style` / `system_prompt` 已反映 persona.yaml）→ `PersonaValidator.validate()` 校验 JSON 可被 hub 加载

**预防措施 / Prevention**

- 原子写文件的通用范式：`.tmp` 写入（`flush` + `fsync`）→ `os.replace`，且 `os.replace` 必须位于 `with` 块**外**
- Windows 文件操作报"被占用"时，先自查自身代码（未关闭句柄自锁），再怀疑外部进程
- 后端运行时会持有 `data/personas/*.json`，需写入的同步脚本应"先停后端 → 同步 → 重启"，或用 dry-run 预览

---

#### 14. 深夜/凌晨发"白天照"，生图时段光线与真实时刻错位 8 小时 / Photos generated at night look like daytime (timezone offset)

**问题描述 / Symptom**

- 在**凌晨**（如北京 02:02）主动推送的生活照/环境照，画面光线却是**下午/白天**（"下午，柔和的自然光，光影层次分明"），看起来像正午或下午拍的
- `data/world_image_candidates.json` 中 `proactive-visual:*` 记录的 `created_at` 为 `2026-08-10T18:02:56+00:00`（UTC），换算成北京（+08:00）才是凌晨 `02:02`，但时段判定却落在 `afternoon`（下午）
- 影响面不止生图：世界模拟的时段/作息/天气判断整体偏移，凌晨被判定为"下午工作/活动"而非"深夜睡觉"

**可能原因 / Root cause**

1. **世界模拟时钟用 UTC**：`WorldSimulation` 默认时钟 `datetime.now(timezone.utc)`（[world_simulation.py L207](file:///e:/Agent_reply/core/world_simulation.py#L207)），快照 `iso_time` 与时段 `phase_for(now)` 均按 **UTC 小时**判定，未转换到本地时区
2. **生图时间注入未归一**：`companion._image_world_context` 解析 `iso_time` 后直接用 `.hour` / `strftime`，也未做 `astimezone` 到本地
3. 本地（北京 +08:00）与 UTC 相差 8 小时：真实凌晨 02:02 被系统视为 UTC 18:02 → 落在 `afternoon`（14:00–19:00）区间，光线提示词写成"下午"
4. 全程无任何 `astimezone`/本地时区转换（[world_simulation.py](file:///e:/Agent_reply/core/world_simulation.py) 仅有一处强制标 UTC 的兜底）

**排查步骤 / Diagnosis**

1. 定位最近一条主动发图：`data/world_image_candidates.json` 中 `reason_code=world_visual:*`、`source=generated` 的记录，换算 `created_at` 到北京时区，比对真实发送时刻
2. 看该候选 `prompt_key=environment_object` 走 `_image_prompt_for` 时注入的 `time_of_day` / `time_of_day_light`：若为 `afternoon` / "下午…"而真实是凌晨，即中招
3. 用固定时钟复现：构造 `WorldSimulation(clock=lambda: datetime(2026,8,11,2,2,tzinfo=LOCAL_TZ))` 调 `tick()`，看 `phase` 是否判成 `night`；或用 UTC `18:02Z` 调 `_time_of_day_phase(astimezone(+08))` 验证是否归一为 `night`

**解决方案 / Fix**

1. **世界模拟时钟本地化**：在 `world_simulation.py` 导出 `LOCAL_TZ = timezone(timedelta(hours=8))`，默认时钟改为 `datetime.now(LOCAL_TZ)`；naive 时间兜底补齐也用 `LOCAL_TZ`（[world_simulation.py L211/L401](file:///e:/Agent_reply/core/world_simulation.py#L211)）
2. **生图时间注入归一**：`companion._image_world_context` 对解析出的 `clock_dt` 统一归一——aware 用 `clock_dt.astimezone(LOCAL_TZ)`，naive 用 `clock_dt.replace(tzinfo=LOCAL_TZ)`，兜底 `datetime.now(LOCAL_TZ)`（[companion.py L2249-L2256](file:///e:/Agent_reply/core/companion.py#L2249-L2256)）
3. 世界模拟仅在 `world_port.py L287/L701` 构造且不传 clock，改默认值即全覆盖
4. 验证：`pytest tests/test_p1_c1_world_simulation.py tests/test_p1_c1_world_snapshot.py tests/test_world_runtime_lifecycle.py tests/test_phase14_world_image_candidates.py`（39 passed）；另做固定时钟断言——本地 02:02→`night`、UTC 18:02Z 归一 02:02→`night`、12:30→`noon`

**预防措施 / Prevention**

- 所有"世界时钟/时段/生图时间"统一使用 `LOCAL_TZ` 常量，禁止直接 `datetime.now(timezone.utc)` 参与时段判定
- 跨来源时间（快照 `iso_time`、候选 `created_at`、事件 `occurred_at`）混用时，必须先 `astimezone(LOCAL_TZ)` 归一再取 `.hour`，避免 UTC/本地混算
- 新增任何"按当前时刻生成内容"的功能（早安/时段问候/光线提示词），用固定时钟单测覆盖凌晨与正午两个边界时段

---

#### 15. QQ 语音消息无法解析 / 无法转文字（入站） / QQ voice messages not transcribed

**问题描述 / Symptom**

- QQ 手机/PC 发来语音消息，本地聊天窗口只看到一段"语音通讯"之类的内容（CQ 码/JSON 原样显示），AI 也拿不到任何文字语义，无法理解这条语音
- `chat_log.content` 中残留 `[CQ:record,file=...]` 之类的原始码，前端无语音条、无转写文字

**可能原因 / Root cause**

1. 消息以 CQ 码原样落库与渲染，从未解析消息段
2. 缺 ASR（语音转文字）：即使拿到语音文件也未做转写
3. 语音文件需经 NapCat `get_record` 下载（NapCat 默认返回 silk，需转通用格式），链路未接通

**排查步骤 / Diagnosis**

1. 查 `chat_log` 该条 `content` 是否含 `[CQ:record`；含则说明走了未解析路径
2. 确认 NapCat `get_record` 可达：`curl`/日志看 RPC 是否返回 base64/路径
3. 确认转写能力：Aerie WS（`AERIE_WS_KEYS` + `AERIE_WS_ASR_MODEL`，qwen3-asr-flash）是否配置；无 WS 时回退 DashScope（`DASHSCOPE_ASR_MODEL`）；本地 whisper 兜底
4. 检查语音时长 `duration` 是否为 0（依赖 `ffprobe`，见 #18）

**解决方案 / Fix**

1. 新增 `core/qq_media.py::QQMediaPreprocessor`，在 `_on_qq_message` 提交前统一解析 CQ 段（`record`/`image`/`face`/`mface`/`text`）
2. 语音：`qq.get_record(file, out_format="mp3")` 下载 → `_SFClient.transcribe`（Aerie WS qwen3-asr-flash 多 Key 轮询主链路 → DashScope qwen3-asr-flash 回退 → 本地 `AudioTranscriber`（whisper）兜底）→ 转写文字写入 `attachments[].transcript`
3. 前端 `chat.js::_buildAttachmentCard` 对 `category="audio"` 渲染语音条（时长）+ 下方转写文字，无需点击播放

**预防措施 / Prevention**

- 入站多媒体一律走 `QQMediaPreprocessor`，禁止原始 CQ 码落库/进入 AI 上下文
- `attachments` 统一通道（DB/API/前端一致），语音携带 `transcript` + `duration`
- ASR 不可用或失败时降级为 `[语音]` 占位，前端仍渲染语音条，不阻塞主链路

---

#### 16. QQ 表情包仅解析关键词 / 呈现不佳，伊塔无法发收藏 GIF / QQ stickers not understood & cannot be sent

**问题描述 / Symptom**

- 表情包只把 CQ JSON/关键词发过去，AI 理解有限，前端呈现不好看
- 账号「伊塔」在 QQ 收藏夹预配了一批 GIF 表情，但无法让伊塔在聊天中主动发送它们

**可能原因 / Root cause**

1. QQ 自带表情（`face`）仅存 ID，未映射文字含义；图片表情只传 JSON 未下载解析
2. 无出站能力：没有任何接口拉取收藏表情，也没有"什么时候发、发哪张"的决策

**排查步骤 / Diagnosis**

1. 查入站消息段类型：`face`（自带）→ 需 ID 映射；`image`/`mface`（收藏/动图）→ 需下载后视觉解析
2. 确认 NapCat 扩展接口 `fetch_custom_face` 可调用（获取收藏表情 URL 列表）
3. 确认 `send_image` 支持 URL 直发（无需下载，省资源）

**解决方案 / Fix**

1. **入站**：`QQMediaPreprocessor` 内置 `FACE_TEXT`（QQ 常用 face ID→中文，0–200 可信子集，未收录走 `[QQ表情 <id>]` 诚实回退）；`image`/`mface` 经 `get_image` 下载后视觉解析（Qwen3-VL 风格）生成描述，并落缩略图
2. **出站**：新增 `core/qq_sticker.py`
   - `QQStickerLibrary`：`fetch_custom_face` 拉收藏 URL → 视觉打标（懒加载 + `data/qq_sticker_cache.json` 缓存）→ 按情绪挑图
   - `QQStickerSender`：轻量 LLM 决策（`siliconflow-light`，5s 超时）→ 规则按情绪挑图 → `send_image(URL)` 直发
3. `send_queue` 增加 `on_reply_sent` 回调，`companion._on_qq_reply_sent` 在回复发完后触发；LLM 决策失败回退 `_fallback_decide` 确定性规则

**预防措施 / Prevention**

- 收藏表情实时拉取 + 缓存，伊塔新加的表情立刻可用；跨重启复用标签
- 出站每层独立降级（拉不到收藏→不发；无视觉打标→随机；LLM 失败→规则兜底），绝不影响文字回复
- 每用户节流（`sticker.min_interval` 默认 90s）防刷屏；`sticker.enabled` 可整体关闭

---

#### 17. 本机 pytest 收集阶段卡住，测试无法运行 / pytest hangs during collection

**问题描述 / Symptom**

- 在本机运行 `pytest tests/xxx.py` 时，进程在收集（import）阶段长时间无输出、无退出，看不到任何测试结果
- 与本次改动无关，其他测试同样触发

**可能原因 / Root cause**

- `tests/conftest.py` 在收集阶段导入 `core.api_server` 等重型模块，本机环境下该导入阻塞（网络/资源/端口预检测等），导致 pytest 卡住而非报错

**排查步骤 / Diagnosis**

1. 用 `python -m pytest <file> -p no:cacheprovider > out.log` 观察 `out.log` 是否始终为空（卡在 import）
2. 用最小脚本 `python -c "import core.qq_sticker"` 单独验证被测模块可正常导入（快且不依赖 conftest）

**解决方案 / Fix**

- 业务逻辑用独立 `python -c` 脚本做等价运行时验证（mock 外部依赖），绕过 conftest
- 测试文件（如 `tests/test_qq_media.py`、`tests/test_qq_sticker.py`）正常保留，待环境正常/CI 中运行

**预防措施 / Prevention**

- 判定"测试挂起"时先区分是**被测代码**还是**测试框架/环境**问题：被测模块能否独立 `import` 是首要判据
- 优先提供不依赖重型 conftest 的可独立运行验证方式，减少环境阻塞误判

---

#### 18. ffmpeg/ffprobe 缺失，语音时长无法获取 / ffprobe missing, voice duration unavailable

**问题描述 / Symptom**

- 语音消息能转写文字，但附件的 `duration`（时长）为 `0`，语音条不显示时长
- 前端仍正常显示语音条 + 转写文字（仅时长缺失）

**可能原因 / Root cause**

- 语音时长用 `ffprobe` 读取；打包/本机未内置 ffmpeg/ffprobe，导致时长解析失败

**排查步骤 / Diagnosis**

1. 确认 `ffprobe` 是否在 `PATH` 或项目内
2. 查语音附件 `duration` 字段是否为 0

**解决方案 / Fix**

- 时长解析失败时降级返回 `0.0`，不阻塞转写与渲染
- 需要真实时长：安装/内置 ffmpeg，或在打包时把 ffmpeg 一并分发

**预防措施 / Prevention**

- 时长是可选增强字段，不作为语音链路硬依赖；缺失时前端仍展示语音条 + 转写文字
- 打包清单确认 ffmpeg 是否随包分发

---

#### 19. 生图提示词为空（empty_prompt）导致生图秒拒 / Image prompt empty, generation rejected

**问题描述 / Symptom**

- 生图任务 `status: rejected`，`safety.reason_code: empty_prompt`，`provider_called: false`
- 审计存储中 `prompt_sha256` 等于空字符串哈希 `e3b0c44298fc1c149afbf4c8996fb924…`，说明提示词是**空串**而非任何内容
- 表现：用户要照片 / AI 主动发图时流程"秒拒"，没有任何图片产出（历史 16:03 / 16:19 / 16:21 三次失败均如此）

**可能原因 / Root cause**

- 空提示词的**唯一出口**是 `WorldImageCandidateConsumer._resolve_prompt` 的 `except` 分支（修复前 `return ""`）；而 `_image_prompt_for` 正常路径恒返回非空（基础提示词由 persona 外貌拼出），所以空串必然来自"世界数据接力抛异常被吞掉"
- 触发点在 `Companion._image_prompt_for` 中无 try 包裹的 `_image_world_context(candidate)`（world 快照取值 + `fine_time_descriptor` 太阳光线 + `moon_phase` 月相拼接）；任何运行时瞬态异常（world 快照结构异常、特定时刻数据边界等）都会一路冒泡
- **深层根因：静默吞错**——两处 `except` 均用 `logger.debug`（默认关闭）并返回空/默认值，异常体从未落盘，事后无法复盘定位，这正是问题"看起来神秘"的原因

**排查步骤 / Diagnosis**

1. 查 `data/world_image_candidates.json` 与 `uploads/.image_assets/image_workflows.json`：`safety.reason_code == "empty_prompt"` 且 `side_effects.provider_called == false`
2. 校验 `workflow.prompt_sha256` 是否等于空串哈希 `e3b0c44298fc1c149afbf4c8996fb924…`
3. 修复后若日志出现 `world image candidate prompt resolve failed` 或 `world image context relay failed`（已升为 warning 级并落盘），按 traceback 直接定位具体异常源

**解决方案 / Fix**

- `core/companion.py` `_image_prompt_for`：世界数据接力整体套 try，任何异常退回基础提示词 `base`（恒非空）
- `core/world_image_candidates.py` `_resolve_prompt`：resolver 抛异常或返回空结果时，兜底返回非空占位提示词 `world_prompt:<prompt_key>`，保证 safety 校验通过、provider 必被调用
- 两处吞错日志由 `logger.debug` 升为 `logger.warning`，异常体强制落盘
- 契约测试（`tests/test_phase14_world_image_candidates.py`，17/17 通过）：resolver 抛异常/返回空 → 兜底非空；`_image_world_context` 抛异常/空 context → 退回基础提示词；完整链路世界数据异常 → 仍 `completed` + `provider_called: true`

**预防措施 / Prevention**

- 锦上添花的辅助链路（世界数据接力、轻量 LLM 优化）必须 fail-safe：异常只降级不中断核心链路，任何异常都不得冒泡成空串
- 吞错位置禁止用 `logger.debug` 返回默认值；凡是"异常 → 返回空/默认值"的分支必须 `logger.warning` 落盘异常体，否则问题不可复盘
- 新增生图场景时，先验证 `_image_prompt_for` 在 resolver / context 双异常下的非空契约

---

#### 20. 灵动岛 v2 开启后主窗口输入框有焦点但无光标 / Main chat input focused but caret missing after Dynamic Island v2

**问题描述 / Symptom**

- 灵动岛 v2（固定窗口尺寸 + 动态鼠标穿透）上线后，主窗口聊天输入框**点击后有选中态、但光标（caret）不显示**；`Tab` 能正常聚焦，键盘输入逻辑也正常
- 偶发出现，重启应用后恢复；灵动岛窗口物理位置与主窗口输入框**不重叠**（主窗口 [213,56,1281×800]，灵动岛 [484,12,742×704]，输入框 y≈830 低于灵动岛 bottom≈716），排除遮挡与鼠标穿透误判

**可能原因 / Root cause**

- 灵动岛 v2 为 `alwaysOnTop` + `transparent` + blur + 粒子动画（`dynamic-island.html`）的置顶窗口，持续占用 GPU 合成器（compositor）
- 合成器负载抖动或重建时，主窗口渲染进程的 caret 合成偶发失效——caret 由 Chromium 单独绘制，事件层（点击 / focus / 输入）完全正常，纯属**绘制层异常**，因此点击有效果、Tab 能聚焦、就是看不见光标
- 重启后渲染进程重建，合成器重新初始化，光标恢复

**排查步骤 / Diagnosis**

1. 先确认灵动岛窗口与主窗口输入框是否物理重叠（Win32 `GetWindowRect` 对比坐标），排除遮挡/穿透类问题
2. 确认点击有 `:focus` 选中效果、`Tab` 能聚焦——若事件层正常，可判定为 caret 绘制层问题
3. 若光标不显示但输入字符仍生效（盲打能出字），进一步佐证为合成器/绘制异常而非事件丢失

**解决方案 / Fix**

- 轻量自救（无需重启）：按一下 `Alt` 或切换窗口焦点强制合成器刷新；或 `Ctrl+Shift+I` 开合 DevTools 触发一次重绘
- 持久缓解：重启应用（渲染进程重建即恢复）

**预防措施 / Prevention**

- 若频繁出现，考虑为主窗口增加渲染进程 watchdog（检测 caret 丢失后自动 reload）
- 或降低灵动岛动画/粒子（`di-particles`）的 GPU 开销，减少合成器负载抖动窗口

---

## 兼容性 / Compatibility

| 项目 / Item        | 要求 / Requirement               |
| ------------------ | -------------------------------- |
| **OS**       | Windows 10 1809+ / Windows 11    |
| **Python**   | 3.10+                            |
| **Node.js**  | 20+                              |
| **Electron** | 28.x                             |
| **QQ**       | 9.9.26+                          |
| **NapCat**   | v4.18.9 级别                     |
| **RAM**      | 建议 8 GB+                       |
| **Disk**     | 建议 500 MB+，构建产物需更多空间 |

---

## 文档索引 / Documentation

| 文档 / Document                                          | 说明 / Description               |
| -------------------------------------------------------- | -------------------------------- |
| `CHANGELOG.md`                                         | 版本与重要变更记录               |
| `documents/Ita/Ita_Aerie_Companion_Spec.md`            | 伊塔伴侣规格                     |
| `documents/Level_up/Aerie_v14_对话系统全面升级方案.md` | 对话系统后续升级方案             |
| `docs/debug-window-top-gap.md`                         | 窗口顶部间隙排障记录             |
| `docs/debug-dynamic-island-expand-fail.md`             | 灵动岛展开问题排障记录           |
| `.trae/documents/`                                     | 实施计划、修复计划、阶段验证记录 |
| [官网](https://spotlight.etta.top/)                       | Aerie · 云栖线上项目官网        |
| `Spotlight/README.md`                                  | Spotlight 官网子项目说明         |
| `Aerie_Obsidian_Vault/modules/PersonaGenerator.md`     | 人设 AI 智能生成器模块文档       |

---

## License

本项目为**专有 / 闭源**软件（Proprietary / Closed-source），**保留所有权利**。非开源，且**未经书面授权不得用于任何商业用途**。

- 完整许可条款见 [`LICENSE`](LICENSE)
- 用户协议（草案）见 [`TERMS_OF_SERVICE.md`](TERMS_OF_SERVICE.md)
- 允许：个人学习 / 研究 / 内部试用
- **禁止**：未经书面授权复制、修改、再分发、反编译、出售、集成进商业产品或用于任何商业目的
- 商业用途须先与作者签订**书面商业许可**，否则视为侵权

**Aerie · 云栖** — 你的本地 AI 桌面伴侣，把陪伴写成你想要的模样。

---

## 商业合作 / Commercial Cooperation

> 本项目为专有软件，**任何商业用途均须先取得书面授权**（见上方 [License](#license)）。以下为商业授权的联系与申请指引。

### 授权流程 / Licensing Process

1. **提交申请**：通过邮件发送商业授权申请表（模板见下），说明用途、场景、预期规模。
2. **评估确认**：作者评估后回复授权范围与条件（含商业授权费用 / 期限 / 地域）。
3. **签署协议**：双方签订书面商业许可协议。
4. **取得授权**：协议生效后方可将本软件或其派生作品用于获批的商业用途。

> 未获书面授权前的任何商业使用均视为侵权，作者保留追究责任的权利。

### 联系方式 / Contact

- **邮箱 / Email**：`etta120913@gmail.com`
- **个人主页 / Portfolio**：[https://laser1209.github.io/Personal_Portfolio](https://laser1209.github.io/Personal_Portfolio)

申请邮件请以 **「商业授权申请 / Commercial License Request」** 为主题，并复制以下模板填写。

### 商业授权申请表 / Commercial License Request Template

```text
主题 / Subject: 商业授权申请 / Commercial License Request

1. 申请主体 / Applicant
   名称 / Name:
   组织 / Organization (如有):
   联系方式 / Contact:
   个人主页 / LinkedIn / 网站:

2. 授权用途 / Intended Use
   用途描述 / Description:
   （如：集成进商业产品 / 提供订阅服务 / 企业内部生产 / 对外运营等）
   使用场景 / Scenario:
   预期用户规模 / Expected scale:

3. 使用范围 / Scope
   授权地域 / Region:
   授权期限 / Duration (期望):
   是否需要源码修改权限 / Source modification needed:

4. 其他说明 / Additional Notes

5. 期望回复时间 / Preferred response time (可选):
```

> 模板为建议格式，可自行增删；信息越完整，评估越快。
> For licensing inquiries in English, please write to `etta120913@gmail.com` with the subject "Commercial License Request" and visit [https://laser1209.github.io/Personal_Portfolio](https://laser1209.github.io/Personal_Portfolio).

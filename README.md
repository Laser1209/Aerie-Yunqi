# Aerie · 云栖 v0.2.0-beta.1

> **本地优先的 AI 桌面伴侣 / Local-first AI desktop companion**
> 你的私人 AI · 伊塔 · 在 Windows 11 上随时待命。办公学习、情感陪伴、电脑操控、主动关怀、世界模拟、多模态生图与多端互联，一个就够了。

**Aerie · 云栖** 是一个本地优先的 AI 桌面伴侣项目。当前仓库由 **Electron 桌面壳**、**Python 智能内核**、**NapCat QQ 桥接**、**Spotlight 官网**、**World Service 世界模拟侧车** 与 **Android 移动网关** 组成。代码树已完成 P1 陪伴融合、世界模拟、三端撤回、多模态生图、向量知识库与移动端网关等系统性能力实装，版本号迭代至内测基线 `0.2.0-beta.1`。

---

## 当前状态 / Current Status

| 项目 / Item                        | 状态 / Status                                                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **版本 / Version**           | `0.2.0-beta.1` 内测基线                                                                                                                   |
| **桌面端 / Desktop**         | Electron 28 + 渲染层多面板 UI + 灵动岛                                                                                                      |
| **后端 / Backend**           | Python 3.10+ aiohttp + asyncio · LLMCaller 统一调用层                                                                                      |
| **QQ 接入 / QQ Bridge**      | NapCat OneBot11 WebSocket · 三端撤回 (QQ/本地/微信预留)                                                                                    |
| **官网 / Spotlight**         | [https://laser1209.github.io/Aerie_Spotlight/](https://laser1209.github.io/Aerie_Spotlight/) · React 18 + Vite 6 + Tailwind + Framer Motion |
| **世界模拟 / World Service** | 独立 Python sidecar + SQLite storage · 世界仪表盘与天气同步                                                                                |
| **向量知识库 / Vector KB**   | ChromaDB 语义检索 · 本地 ONNX 离线 embedding · 生产记忆已切 LayeredMemory · 附件专用向量库                                               |
| **多模态生图 / Image**       | 三视图生图辅助 · 图片候选人生成推送 (QQ/本地聊天) · 主动发图预算 · 图生图 · SiliconFlow 视觉技能                                        |
| **移动端 / Mobile**          | Android 移动网关 · 多端会话与文件能力 · 账号鉴权                                                                                          |
| **验证 / Tests**             | 107 个 Python 测试文件 (Phase 0-15、P1 陪伴融合、v13.9、E2E) + 16 个 Electron 测试文件                                                      |
| **交付 / Release**           | 线上官网下载页指向`v0.1.0-beta.1` 便携版与安装包，`0.2.0-beta.1` 构建待发布                                                             |

---

## 核心能力 / Key Capabilities

| 模块 / Module                                     | 说明 / Description                                                                                           |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **Electron 桌面壳 / Electron Shell**        | 主窗口、灵动岛、侧边栏、托盘、CSP 安全渲染层                                                                 |
| **Python 智能内核 / Python Brain**          | LLMCaller 统一调用层、多 Provider 调度、预算跟踪、上下文构建、消息流水线                                     |
| **Persona Hub / 人设基础设施**              | Persona 模板、校验、投影、配置热加载、三视图生图参考图                                                       |
| **情感与关系引擎 / Emotion & Relationship** | PAD 情绪、累积阈值、欲望引擎、关系建模、同理心策略、拟人化节奏                                               |
| **主动推送 / Proactive Messenger**          | cron、事件、情绪触发，频控、静默时段、主动发图预算与反馈闭环                                                 |
| **三端撤回 / Recall**                       | QQ/本地/微信预留 三端撤回适配器、LLM 主动撤回指令、消息合并编排                                              |
| **办公模式 / Office Mode**                  | 办公任务识别、文档写作工具链、文件整理去重、任务规划与异步执行                                               |
| **电脑操控 / Computer Control**             | 权限分级、键鼠、截图、UIA、受限 Shell、审计日志                                                              |
| **文件与文档 / File & Docs**                | 文件整理、文档写作、上传处理、附件向量索引、图片工作流                                                       |
| **多模态 / Multimodal**                     | 三视图生图、图生图、图片候选人生成推送、TTS、SiliconFlow 视觉技能                                            |
| **世界模拟 / World Simulation**             | world port、domain、sidecar、仪表盘 API、天气同步、图片候选人管线、默认重庆、百度地图 REST、主动发图节奏循环 |
| **向量知识库 / Vector KB**                  | ChromaDB 语义检索、本地 ONNX 离线 embedding、LayeredMemory 多层记忆、附件专用向量库                          |
| **多端 / Mobile & Multi-client**            | Android 移动网关、移动会话/文件/身份鉴权、多端消息通道                                                       |
| **自进化 / Self Evolution**                 | L1-L4 演进、Skill 创建、安全沙箱、代码修改闸门                                                               |
| **Spotlight 官网 / Web Spotlight**          | 6 页面产品站、发布下载页、Remotion 视频素材工程                                                              |

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
├─ tools/ scripts/            # 诊断、迁移、验证、构建辅助脚本
├─ documents/ docs/           # 设计、排障、实施记录
└─ data/ logs/                # 本地运行数据与日志
```

---

## 快速开始 / Quick Start

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

### 3. 启动 NapCat

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

线上官网：[https://laser1209.github.io/Aerie_Spotlight/](https://laser1209.github.io/Aerie_Spotlight/)

```powershell
cd Spotlight
npm install
npm run dev
```

---

## 常用验证 / Verification

```powershell
# Python 测试（107 个测试文件：Phase 0-15、P1 陪伴融合、v13.9、E2E）
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

# Electron 渲染层单测（16 个 .test.js 文件，node --test）
cd electron
npm run test:unit

# Spotlight 构建
cd Spotlight
npm run build
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
| `data/audit/`                  | 权限与电脑操控审计日志                                   |
| `logs/`                        | 后端与诊断日志                                           |

`main.py` 已接入配置热加载，会监听 `settings.yaml`、`persona_behavior.yaml` 与 `proactive.yaml` 的变更。

---

## 注意与开关 / Notes & Feature Flags

| 开关 / Flag                   | 说明 / Description                             | 默认 |
| ----------------------------- | ---------------------------------------------- | ---- |
| `world_inprocess_v1`        | 世界模拟进程内模式，需开启其一才能使用世界模拟 | 开   |
| `world_sidecar_v1`          | 世界模拟 sidecar 独立进程模式                  | 关   |
| `world_image_candidates_v1` | 自动生图工作流（世界图片候选人生成推送）       | 开   |
| `mobile_gateway_v1`         | Android 移动端网关                             | 关   |
| `persona_hub_source_v1`     | Persona Hub 作为人设源                         | 关   |
| `recall_llm_instruction_v1` | LLM 主动撤回指令`<recall>`                   | 开   |
| `chat_request_queue_v1`     | 聊天请求队列                                   | 开   |
| `context_budget_v1`         | 上下文预算                                     | 开   |

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

默认频控：每日上限 10 次（`proactive.max_per_day`）、间隔不少于 15 分钟（`min_interval_min`）、静默时段 23:30-07:00，早安/晚安/纪念日等场景可按配置豁免。

主动发图默认为**纯约束型调度**（由伊塔自主决策节奏，不再受推送频控抑制）：

- `image_max_per_day`：每日发图上限，默认 `0`（不限制）
- `photo_min_interval_sec`：两次主动发图最小间隔（秒），默认 `0`（无间隔）
- 以上两项可在设置界面动态调整，即时生效；`local_send` 手动请求的图片不受任何约束

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

线上官网：[https://laser1209.github.io/Aerie_Spotlight/](https://laser1209.github.io/Aerie_Spotlight/)

当前官网下载配置位于 `Spotlight/src/config/release.ts`，仍指向 GitHub Release `v0.1.0-beta.1`：

- `Aerie-Cloud-0.1.0-beta.1-Portable.exe`
- `Aerie-Cloud-0.1.0-beta.1-Setup.exe`

> **说明**：`0.2.0-beta.1` 代码已合并上述新能力，安装包构建待发布，届时将更新 `release.ts` 指向新版本。

---

## 故障排查 / Troubleshooting

| 现象 / Symptom | 原因 / Cause                            | 处理 / Fix                                                 |
| -------------- | --------------------------------------- | ---------------------------------------------------------- |
| 后端启动失败   | 依赖未安装或 Python 版本不符            | 重新执行`pip install -r requirements.txt`                |
| API 无响应     | 7890 端口被占用或后端未启动             | 检查`logs/main.log` 与端口占用                           |
| 伊塔不回复     | 未配置可用模型 Key                      | 检查`.env` 至少一个 `*_API_KEY`                        |
| 附件无语义检索 | `chromadb` 未安装或缺少 embedding Key | 手动安装`chromadb` 并配置 embedding API Key              |
| 世界模拟不生效 | 未开启世界模拟开关                      | 设置`world_inprocess_v1` 或 `world_sidecar_v1` 为 true |
| 自动发图不触发 | `world_image_candidates_v1` 关闭      | 在`settings.yaml` 设 `world_image_candidates_v1: true` |
| 回复带时间戳   | LLM 模仿历史格式                        | 后端会自动剥离，确保使用最新代码并重启后端                 |
| QQ 收不到消息  | NapCat 未启动或未登录                   | 启动`NapCat\NapCat.Shell\launcher-user.bat`              |
| 桌面端白屏     | Electron 渲染资源或 CSP 问题            | 查看 Electron DevTools 与`electron/python-*.log`         |
| 官网构建失败   | Node 依赖未安装                         | 在`Spotlight/` 执行 `npm install` 后重试               |

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
| [官网](https://laser1209.github.io/Aerie_Spotlight/)      | Aerie · 云栖线上项目官网        |
| `Spotlight/README.md`                                  | Spotlight 官网子项目说明         |

---

## License

本仓库源码公开可见，但当前标记为 **UNLICENSED / All rights reserved**，不因此自动授予复制、再分发或商业使用许可。

**Aerie · 云栖** — 你的本地 AI 桌面伴侣。

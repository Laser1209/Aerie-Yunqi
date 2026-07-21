# Aerie · 云栖 v0.1.0-beta.1

> **本地优先的 AI 桌面伴侣 / Local-first AI desktop companion**
> 你的私人 AI · 伊塔 · 在 Windows 11 上随时待命。办公学习、情感陪伴、电脑操控、主动关怀、世界模拟与多模态工作流，一个就够了。

**Aerie · 云栖** 是一个本地优先的 AI 桌面伴侣项目。当前仓库由 **Electron 桌面壳**、**Python 智能内核**、**NapCat QQ 桥接**、**Spotlight 官网** 与 **World Service 世界模拟侧车** 组成，版本号仍锁定在内测基线 `0.1.0-beta.1`，但代码树已经进入后续 R/Phase 能力实装状态。

---

## 当前状态 / Current Status

| 项目 / Item                        | 状态 / Status                                                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **版本 / Version**           | `0.1.0-beta.1` 内测基线                                                                                                                   |
| **桌面端 / Desktop**         | Electron 28 + 渲染层多面板 UI                                                                                                               |
| **后端 / Backend**           | Python 3.10+ aiohttp + asyncio                                                                                                              |
| **QQ 接入 / QQ Bridge**      | NapCat OneBot11 WebSocket                                                                                                                   |
| **官网 / Spotlight**         | [https://laser1209.github.io/Aerie_Spotlight/](https://laser1209.github.io/Aerie_Spotlight/) · React 18 + Vite 6 + Tailwind + Framer Motion |
| **世界模拟 / World Service** | 独立 Python sidecar + SQLite storage                                                                                                        |
| **验证 / Tests**             | 覆盖 Phase 0-15、v13.9、E2E 与 Electron 检查文件                                                                                            |
| **交付 / Release**           | `Spotlight/src/config/release.ts` 指向 `v0.1.0-beta.1` 便携版与安装包                                                                   |

---

## 核心能力 / Key Capabilities

| 模块 / Module                                     | 说明 / Description                                        |
| ------------------------------------------------- | --------------------------------------------------------- |
| **Electron 桌面壳 / Electron Shell**        | 主窗口、灵动岛、侧边栏、托盘、CSP 安全渲染层              |
| **Python 智能内核 / Python Brain**          | 多 Provider 调度、预算跟踪、上下文构建、消息流水线        |
| **Persona Hub / 人设基础设施**              | Persona 模板、校验、投影、配置热加载                      |
| **情感与关系引擎 / Emotion & Relationship** | PAD 情绪、累积阈值、欲望引擎、关系建模、拟人化节奏        |
| **主动推送 / Proactive Messenger**          | cron、事件、情绪触发，支持频控、静默时段与反馈闭环        |
| **办公模式 / Office Mode**                  | 办公任务识别、工具矩阵、任务规划、异步任务执行            |
| **电脑操控 / Computer Control**             | 权限分级、键鼠、截图、UIA、受限 Shell、审计日志           |
| **文件与文档 / File & Docs**                | 文件整理、文档写作、上传处理、图片工作流                  |
| **多模态 / Multimodal**                     | 图片输入、TTS 输出、语音与 QQ 深耕能力                    |
| **世界模拟 / World Simulation**             | world port、domain、sidecar、dashboard API 与候选图片管线 |
| **自进化 / Self Evolution**                 | L1-L4 演进、Skill 创建、安全沙箱、代码修改闸门            |
| **Spotlight 官网 / Web Spotlight**          | 6 页面产品站、发布下载页、Remotion 视频素材工程           |

---

## 项目结构 / Repository Layout

```text
.
├─ main.py                    # Python 后端入口
├─ core/                      # Agent、API、Pipeline、工具、情感、世界模拟适配
├─ communication/             # QQ/NapCat 通讯层
├─ config/                    # settings/persona/proactive 配置与加载器
├─ memory/ knowledge/ voice/  # 记忆、知识库、语音输出
├─ world_service/             # 世界模拟 sidecar 服务
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
SELF_QQ=123456789
HTTP_API_PORT=7890
NAPCAT_WS_URL=ws://127.0.0.1:3001
LOG_LEVEL=INFO
```

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
# Python 测试
pytest tests

# 重点阶段验证示例
pytest tests/test_phase10_image_workflow.py
pytest tests/test_phase15_world_dashboard_api.py
pytest tests/test_v139_basic_permission.py

# Electron 静态检查
cd electron
npm run check:all

# Electron 渲染层单测文件位于 electron/tests/，当前未在 package.json 暴露 npm test 脚本

# Spotlight 构建
cd Spotlight
npm run build
```

---

## 配置与数据 / Config & Data

| 路径 / Path                      | 用途 / Purpose                       |
| -------------------------------- | ------------------------------------ |
| `config/settings.yaml`         | 主配置、HTTP、主题、窗口、办公目录等 |
| `config/persona.yaml`          | 伊塔核心人设配置                     |
| `config/persona_behavior.yaml` | 行为与表达节奏配置                   |
| `config/proactive.yaml`        | 主动推送场景、频控、静默时段         |
| `data/personas/`               | Persona Hub 运行态数据               |
| `data/briefs/`                 | 每日简报缓存                         |
| `data/audit/`                  | 权限与电脑操控审计日志               |
| `logs/`                        | 后端与诊断日志                       |

`main.py` 已接入配置热加载，会监听 `settings.yaml`、`persona_behavior.yaml` 与 `proactive.yaml` 的变更。

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

默认频控：每日上限 5 次、间隔不少于 30 分钟、静默时段 23:30-07:00，早安/晚安/纪念日等场景可按配置豁免。

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

当前官网下载配置位于 `Spotlight/src/config/release.ts`，指向 GitHub Release `v0.1.0-beta.1`：

- `Aerie-Cloud-0.1.0-beta.1-Portable.exe`
- `Aerie-Cloud-0.1.0-beta.1-Setup.exe`

---

## 故障排查 / Troubleshooting

| 现象 / Symptom | 原因 / Cause                 | 处理 / Fix                                         |
| -------------- | ---------------------------- | -------------------------------------------------- |
| 后端启动失败   | 依赖未安装或 Python 版本不符 | 重新执行`pip install -r requirements.txt`        |
| API 无响应     | 7890 端口被占用或后端未启动  | 检查`logs/main.log` 与端口占用                   |
| 伊塔不回复     | 未配置可用模型 Key           | 检查`.env` 至少一个 `*_API_KEY`                |
| QQ 收不到消息  | NapCat 未启动或未登录        | 启动`NapCat\NapCat.Shell\launcher-user.bat`      |
| 桌面端白屏     | Electron 渲染资源或 CSP 问题 | 查看 Electron DevTools 与`electron/python-*.log` |
| 官网构建失败   | Node 依赖未安装              | 在`Spotlight/` 执行 `npm install` 后重试       |

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

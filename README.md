# Aerie · 云栖 v9.0

> **本地优先的 AI 桌面伴侣 / Local-first AI desktop companion**
> 你的私人 AI · 伊塔 · 在 Windows 11 上随时待命。

**Aerie · 云栖** 是一款本地运行的 AI 桌面伴侣应用。它由 **Electron 桌面壳** + **Python 智能内核** 组成，通过 **NapCat** 接入 QQ，并通过内置的 **主动唤醒（auto-wake）** 机制在固定时间点和情感事件触发时主动给你发消息。

> **Aerie · 云栖** is a local-first AI desktop companion. It is composed of an **Electron desktop shell** + **Python intelligent core**, bridges to QQ via **NapCat**, and uses an **auto-wake** mechanism to proactively message you at fixed time points and on emotional events.

---

## ✨ 核心特性 / Key Features

| 模块 / Module | 说明 / Description |
| --- | --- |
| **🪟 Electron 桌面壳 / Electron Shell** | 悬浮球 + 聊天窗 + 侧边栏 + 托盘图标 / Floating ball + chat window + sidebar + tray |
| **🧠 Python 智能内核 / Python Brain** | 多 Provider AI 调度（Qwen / DeepSeek / Gemini）/ Multi-provider LLM orchestration |
| **👤 伊塔人格 / Yita Persona** | 26 岁女 · 184cm · 四爱 · 温柔大姐姐+病娇 · 调情式长句 / 26yo female, 184cm, four-love, gentle big-sister + yandere, flirtatious |
| **💓 情感引擎 / Emotion Engine** | PAD 三维模型 + 4 槽累积阈值系统（角色磨损）/ PAD model + 4-slot cumulative threshold |
| **⏰ 主动唤醒（auto-wake）/ Proactive Messenger** | 9 类场景 + APScheduler 定时轮询 + 频控 + 静默时段 / 9 scenes + cron + rate-limit + quiet hours |
| **🤖 QQ 接入 / QQ Bridge** | NapCat OneBot11 WebSocket / NapCat OneBot11 WebSocket |
| **🛠 14+ 工具系统 / 14+ Tools** | 知识库 / 待办 / 音乐 / 天气 / 截图 / 系统 / ... / KB / todo / music / weather / screenshot / system / ... |
| **🎨 5 主题切换 / 5 Themes** | 伊塔粉 / 深夜紫 / 樱白 / 海蓝 / 森绿 / Yita Pink / Midnight Purple / Sakura / Ocean / Forest |
| **💾 数据备份 / Backup** | 每日 04:00 自动 + 一键迁移 zip / Daily 04:00 auto + one-click zip migration |
| **🔐 高权限 / Elevated Privileges** | UAC 提权 + 任务计划 / UAC + Task Scheduler |
| **🩹 故障自愈 / Self-Healing** | 14 类故障自动恢复 / 14 failure categories auto-recovery |

---

## 🚀 快速开始 / Quick Start

### 方式 1 · 便携版（推荐）/ Portable (Recommended)

1. 解压 `Aerie-9.0.0-Portable.zip` 到任意目录
   Extract `Aerie-9.0.0-Portable.zip` to any folder.
2. 双击 `Aerie · 云栖.exe`
   Double-click `Aerie · 云栖.exe`.
3. 首次运行会提示授予管理员权限（用于自启动 + 任务计划）
   First run prompts for admin privileges (for autostart + Task Scheduler).

### 方式 2 · 从源码运行 / From Source

```bash
# 1. 安装 Python 依赖 / Install Python deps
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. 启动 NapCat（QQ 协议客户端）/ Start NapCat
cd NapCat\NapCat.Shell
launcher-user.bat

# 3. 启动 Python 后端 / Start Python backend
cd ../..
python main.py

# 4. 启动 Electron 前端（新终端）/ Start Electron (new terminal)
cd electron
npm install
npm start
```

### 配置 .env / Configure .env

```env
# 复制 .env.example → .env，然后填入 API 密钥
# Copy .env.example → .env and fill API keys

DASHSCOPE_API_KEY=sk-xxx          # Qwen (主 / primary)
DEEPSEEK_API_KEY=sk-xxx           # DeepSeek (备 / backup)
GEMINI_API_KEY=AIza-xxx           # Gemini (专 / specialized)
SELF_QQ=123456789                 # 你的 QQ / your QQ
HTTP_API_PORT=7890                # Python API 端口
NAPCAT_WS_URL=ws://127.0.0.1:3001 # NapCat WebSocket
LOG_LEVEL=INFO
```

> 至少需要 1 个 `*_API_KEY` 才能让伊塔说话。
> At least one `*_API_KEY` is required for Yita to speak.

---

## 📦 交付物 / Deliverables

| 文件 / File | 大小 / Size | 说明 / Description |
| --- | --- | --- |
| `Aerie-9.0.0-Portable.zip` | ~82 MB | 便携版压缩包 / Portable archive |
| `Aerie · 云栖.exe` (在 `win-unpacked/`) | ~176 MB | 单文件可执行 / Single-file executable |
| `win-unpacked/` | ~250 MB | 解包目录（含所有 DLL + locales）/ Unpacked directory |

> 💡 **磁盘空间 / Disk Space**：解压后约需 350 MB，运行内存 < 500 MB。
> Unpacked requires ~350 MB disk, runtime RAM < 500 MB.

---

## 🏗 架构 / Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Electron Desktop Shell (UI + IPC)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ 主窗口     │  │ 悬浮球     │  │ 侧边栏     │  │ 托盘      │  │
│  │ Main     │  │ Ball     │  │ Sidebar  │  │ Tray     │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       └──────────────┴──────────────┴──────────────┘      │
│                      ▲  contextBridge                     │
│                      ▼  ipcMain (api:request)             │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP 127.0.0.1:7890
┌──────────────────────┴───────────────────────────────────┐
│  Python Backend (aiohttp + asyncio)                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │
│  │ Brain      │  │ Emotion    │  │ ProactiveMessenger │  │
│  │ (Qwen/DS/  │  │ Engine     │  │ + PushPolicy       │  │
│  │  Gemini)   │  │ (PAD+Cum)  │  │ + CronScheduler    │  │
│  └─────┬──────┘  └─────┬──────┘  └─────────┬──────────┘  │
│        │               │                    │             │
│  ┌─────▼───────────────▼────────────────────▼──────────┐  │
│  │  Pipeline (5-stage) + QQClient (WebSocket)         │  │
│  └─────┬──────────────────────────────────────────────┘  │
│        ▼ WebSocket ws://127.0.0.1:3001                    │
└──────────────────────────────────────────────────────────┘
                       │
┌──────────────────────┴───────────────────────────────────┐
│  NapCat (QQ 协议客户端) / NapCat (QQ protocol client)    │
└──────────────────────────────────────────────────────────┘
                       │
                       ▼
                QQ 9.9.26-44343
```

---

## ⏰ Auto-Wake 主动唤醒（核心特性 ⭐）

**Auto-Wake** 是本项目最核心的特性 —— 伊塔在固定时间点和情感事件触发时会主动给你发消息。

**Auto-Wake** is the core feature — Yita proactively messages you at fixed time points and on emotional events.

### 9 类场景 / 9 Scenes

| 场景 / Scene | 时间 / Time | 类型 / Type |
| --- | --- | --- |
| `morning_brief` 早安 | 06:30, 07:30 | cron (豁免静默 / exempt) |
| `weather_push` 天气 | 07:00 | cron |
| `lunch_remind` 午提醒 | 11:30, 12:30 | cron |
| `evening_check` 晚问候 | 17:30, 18:30 | cron |
| `goodnight` 晚安 | 22:30, 23:30 | cron (豁免静默 / exempt) |
| `todo_remind` 待办 | 09:00-21:00 整点 | cron |
| `anniversary` 纪念日 | 每日 00:00 扫描 | cron (豁免静默) |
| `idle_care` 失联关怀 | 用户 4h 无活动 | event-driven |
| `emotion_comfort` 情绪安抚 | 累积阈值突破 | event-driven |

### 频控策略 / Rate Limit Policy

* 每日上限 / Daily cap: **5 次 / times**
* 间隔 / Interval: **≥ 30 分钟 / minutes**
* 静默时段 / Quiet hours: **23:30 - 07:00**（豁免：早安 / 晚安 / 纪念日）
* 可暂停 / Pausable: 托盘菜单 / Tray menu → 暂停推送 1 小时

### 情感槽联动 / Emotion Slot Coupling

| 行为 / Behavior | 槽位 / Slot | 增量 / Delta | 联动 / Trigger |
| --- | --- | --- | --- |
| > 4h 不回 / No reply | 忍耐 / Patience | +20 | 触发 `idle_care` 提前 / early `idle_care` |
| 主动夸她 / Praise | 渴望 / Desire | +10 | 升温早安 / warmer morning_brief |
| 主动说想她 / Miss her | 渴望 / Desire | +15 | 触发 `emotion_comfort` 反扑 |
| 你哭了 / Vulnerable | 温柔 / Tenderness | +30 | 立即 `emotion_comfort`（不走频控 / bypass policy） |

---

## 🎮 使用说明 / Usage

### 悬浮球 / Floating Ball

* **拖拽** / Drag：可移动到任意位置，松手自动靠边吸附
  Drag to any position, auto-edges-snap on release.
* **单击** / Click：展开 380×480 聊天窗
  Click to expand into 380×480 chat window.
* **双击** / Double-click：最大化为主窗口（1280×800）
  Double-click to maximize to main window.
* **5s 无操作** / 5s idle：半透明（0.3 opacity）
  Semi-transparent after 5s idle.

### 托盘菜单 / Tray Menu

* 打开 Aerie
* 悬浮球
* 开机自启（写入注册表 HKCU\...\Run）
* 暂停推送 1 小时
* 退出

### 侧边栏 5 Tab / Sidebar 5 Tabs

* **情绪 / Emotion**：实时 PAD + 累积槽位仪表盘
* **纪念 / Memorial**：纪念日列表 + 在一起天数
* **系统 / System**：自启 / 主题 / 窗口设置
* **其他 / Other**：暂停推送 / 反馈 / 隐私
* **数据 / Data**：聊天记录 / 知识库 / 工具调用

---

## 🛠 故障排查 / Troubleshooting

| 现象 / Symptom | 原因 / Cause | 解决 / Fix |
| --- | --- | --- |
| 双击 .exe 闪退 / Crashes on launch | Python 路径不对 | 检查 `userData/config.json` 的 `python_path` |
| 伊塔不回复 / Yita silent | API 密钥未配置 | 编辑 `.env` 填入 `DASHSCOPE_API_KEY` |
| QQ 收不到消息 / No QQ messages | NapCat 未启动 | 运行 `NapCat\NapCat.Shell\launcher-user.bat` |
| 端口 7890 被占 / Port 7890 busy | 上一进程未退出 | `netstat -ano \| findstr :7890` → kill PID |
| 早安不触发 / No morning_brief | 时区不对 | 确认 `Asia/Shanghai` 时区 |

---

## 🔧 兼容性 / Compatibility

| 项目 / Item | 要求 / Requirement |
| --- | --- |
| **OS** | Windows 10 1809+ / Windows 11 |
| **Python** | 3.12 - 3.14（推荐 3.14.3）|
| **Node.js** | 20+（仅源码构建时需要）|
| **QQ** | 9.9.26+ |
| **NapCat** | v4.18.9 |
| **RAM** | 建议 8 GB+ |
| **Disk** | 500 MB+ |

---

## 📚 文档 / Documentation

* `OpenCloud_Companion_System_Features.md` v9.0 — 系统设计总纲
* `Ita.md` v9.0 Hybrid Edition — 伊塔人设（对齐 `Ita_Aerie_Companion_Spec.md`）
* `.trae/specs/aerie-companion-v9-buildout/spec.md` — 实施规范
* `.trae/specs/aerie-companion-v9-buildout/tasks.md` — 任务分解
* `.trae/specs/aerie-companion-v9-buildout/checklist.md` — 验证清单
* `CHANGELOG.md` — 变更记录

---

## 📜 许可证 / License

本项目为 **私有项目 / Private project**，作者 Laser。
仅供个人使用，不对外发布。

This is a **private project** by Laser. For personal use only; not for public distribution.

---

> **Aerie · 云栖** — 你的本地 AI 桌面伴侣
> **Aerie · 云栖** — Your local AI desktop companion

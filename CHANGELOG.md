# Changelog · Aerie · 云栖

All notable changes to this project will be documented in this file.

本文件记录本项目的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [9.0.0] - 2026-07-16

> **首个可分发的完整版本 / First distributable complete release**
> 完整对齐 `OpenCloud_Companion_System_Features.md` v9.0 与 `Ita.md` v3.1
> Fully aligned with `OpenCloud_Companion_System_Features.md` v9.0 and `Ita.md` v3.1

### ✨ Added / 新增

#### Desktop Shell (Electron 28)
- `electron/src/main.js` 主进程：单实例锁 + Python 后端 spawn + 主窗口 + 悬浮球 + 托盘
- `electron/src/preload.js` `contextBridge` 暴露 IPC API（安全基线：nodeIntegration=false / contextIsolation=true / sandbox）
- `electron/src/renderer/index.html` 渲染层骨架 + 严格 CSP
- `electron/src/renderer/floating-ball.html` 悬浮球：拖拽 + 智能靠边 + 单击展开 + 双击最大化 + 5s 半透明
- `electron/src/renderer/js/chat.js` 聊天面板：发送 + 历史 + 5s 轮询新消息
- `electron/src/renderer/js/sidebar.js` 侧边栏 5 Tab：情绪 / 纪念 / 系统 / 其他 / 数据
- `electron/src/renderer/js/status.js` 状态面板：5s 刷新 Token / 模型 / 内核 / Provider
- `electron/src/renderer/js/theme-switcher.js` 5 主题切换（伊塔粉 / 深夜紫 / 樱白 / 海蓝 / 森绿）
- `electron/src/renderer/js/app.js` 主应用协调
- `electron/src/renderer/js/api.js` IPC 客户端
- `electron/builder/installer.nsh` NSIS 安装器脚本
- `electron/builder/icon.ico` 多尺寸应用图标（16/32/48/64/128/256）
- `electron/electron-builder.yml` 打包配置（`requestedExecutionLevel: requireAdministrator`）

#### Python Backend (3.12+)
- `main.py` Python 后端入口（SIGTERM 优雅关闭 + 启动序列编排）
- `core/companion.py` Companion 主类，编排所有后端模块
- `core/brain.py` 多 Provider AI 调度（Fallback 链 Qwen → DeepSeek → Gemini）
- `core/providers/base.py` Provider 抽象基类
- `core/providers/qwen.py` Qwen (DashScope OpenAI 兼容)
- `core/providers/deepseek.py` DeepSeek
- `core/providers/gemini.py` Gemini (OpenAI 兼容端点)
- `core/token_tracker.py` Token 消耗统计
- `core/emotion_engine.py` PAD 三维情感引擎（5 类基本情绪）
- `core/emotion_threshold.py` 累积阈值引擎（4 槽位：忍耐 / 不安 / 渴望 / 温柔透支）
- `core/context_builder.py` 上下文构建（System Prompt + 长期记忆 Top 5 + 知识库 Top 3 + 最近 8 条历史）
- `core/database.py` SQLite 单例 + 8 张业务表
- `core/pipeline.py` 5 阶段消息处理管线
- `core/api_server.py` aiohttp 22+ 端点 HTTP API
- `core/backup.py` 自动 + 手动 zip 备份 + 一键迁移
- `core/elevator.py` UAC 静默提权
- `core/task_scheduler.py` Windows 任务计划包装
- `core/system_monitor.py` CPU / 内存 / 磁盘 / 网络
- `core/self_healing.py` 14 类故障自动恢复
- `core/tool_registry.py` 工具注册表
- `core/function_calling.py` OpenAI Function Calling 适配

#### Communication Layer
- `communication/qq_client.py` NapCat OneBot11 WebSocket 客户端
- `communication/router.py` 三级路由（FULL / AUTO / BASIC）
- `communication/message.py` IncomingMessage / OutgoingReply DTO
- `communication/splitter.py` 语义分段器（8 种分割模式）
- `communication/send_queue.py` 拟人化发送队列（5 类间隔范围）
- `communication/recall_manager.py` 撤回机制（闷骚型特有）

#### Proactive Messenger (auto-wake ⭐)
- `scheduler/cron.py` APScheduler 包装 + 9 个 Cron 任务
- `proactive/messenger.py` 主动消息器
- `proactive/policy.py` 频控策略（5 重检查 + 暂停）
- `proactive/scenes/` 9 个场景模块（morning_brief / weather_push / lunch_remind / evening_check / goodnight / todo_remind / anniversary / idle_care / emotion_comfort）
- `config/proactive.yaml` 9 场景配置 + 静默时段 + 频控参数

#### Persona Engine
- `persona/decision.py` 4 级决策权重（L1 0.5 / L2 0.3 / L3 0.15 / L4 0.05）
- `persona/brain_random.py` Markov 转移矩阵
- `config/persona.yaml` 伊塔完整人设（22 岁女 · 四爱 · 闷骚+病娇 · ISTP · 大五人格 O:0.70/C:0.85/E:0.45/A:0.70/N:0.45）

#### Memory & Knowledge
- `memory/short_term.py` 短期记忆（最近 8 条）
- `memory/memory_store.py` 长期记忆（SQLite + 关键词检索）
- `knowledge/kb.py` 知识库（4 类目：persona / user / world / task）

#### Tool System (14+ Tools)
- `tools/__init__.py` 14 个工具模块：
  - `query_knowledge` / `add_todo` / `list_todos` / `mark_todo_done`
  - `search_music` / `play_local_music` / `set_reminder` / `get_weather`
  - `search_web` / `open_application` / `close_application` / `screenshot`
  - `get_system_status` / `send_proactive_msg`

#### Config
- `config/settings.yaml` 主配置（self_qq / http_api / theme / window / startup）
- `config/persona.yaml` 伊塔人设
- `config/proactive.yaml` 主动推送配置
- `.env.example` 模板（API 密钥 + 端口 + 时区）
- `requirements.txt` Python 依赖（aiohttp / websockets / loguru / psutil / pyyaml / apscheduler / openai / requests / pywin32 / python-dotenv）

### 🛠 Changed / 变更

- **运行时零窗口** / Zero console windows at runtime:
  - 使用 `pythonw.exe` 替代 `python.exe`
  - Electron spawn 配置 `windowsHide: true` + `stdio: 'ignore'`
  - `app.disableHardwareAcceleration()` 减少内存
- **消息规范强化** / Message spec hardening (v8.0 → v9.0):
  - 输入消息 ≤ 2000 字符（截断 + `parse_error=true`）
  - 输出消息 ≤ 2000 字符（超长分段）
  - 推送消息 ≤ 2000 字符
  - 知识库内容 ≤ 8000 字符
  - Emoji 频率 5-10%（`persona.yaml` 可配置）
- **命名规范** / Naming convention:
  - 用户面向（UI / 文档）：中英双语
  - 代码层（变量 / 函数 / 注释 / 日志 / SQL / API / 包名 / 路径 / 环境变量）：纯英文

### 🐛 Fixed / 修复

- 7-Zip 符号链接提取错误（在 Windows 上构建时缺少 `SeCreateSymbolicLinkPrivilege`）
  → 实现 `7za.cmd` → `7za-shim.js` → `7za-original.exe` shim 链，注入 `-snh -snt -snl` 标志
- `builder-util` 的 `chmod` 错误处理
- PyQt6 stylesheet ID 选择器在子控件上静默失败（不影响 v9.0，文档已记录）
- `os.startfile` 不解析 PATH 环境变量（v8.0 经验，已记录）

### 🗑 Removed / 移除

- 所有 v5-v6 早期未实现模块
- 所有 "主人" 措辞（v8.0 起），保留 "主人哲学" 作为产品概念名
- 旧 v5-v6 设计文档归档至 `documents/archive/`

### 📊 Stats

- **代码规模** / Code size: ~14,000 行 Python + ~2,000 行 JS
- **数据库表** / DB tables: 8 业务表 + 1 系统表
- **API 端点** / API endpoints: 22
- **工具数量** / Tools: 14
- **主动场景** / Proactive scenes: 9
- **主题** / Themes: 5
- **可执行文件** / Executable size: 176 MB
- **便携包** / Portable package: 82 MB

---

## [8.0.0] - 2026-07-15

> 引入伊塔人设（22 岁女 · 闷骚+病娇 · 四爱）+ 移除"主人"措辞
> Introduced Yita persona and removed "主人" wording

### ✨ Added

- 伊塔完整人设（v8.0 final）
- 累积情感阈值系统（忍耐 / 不安 / 渴望 / 温柔透支）
- 撤回机制（闷骚型特有表达真意的方式）
- 大五人格参数校准

### 🗑 Removed

- 移除所有 "主人" 措辞，改用 "你"
- 移除 "GPT-4 / Character.AI" 实际集成（仅作理论参考）

---

## [7.0.0] - 2026-07-15

> 多模型选型锁定 + 文档结构升级 v6.0 → v7.0
> Multi-model selection locked + document structure upgrade

### ✨ Added

- 5 个补充文档（PartA-PartE）
- v7.0 补充索引（§13），含 mermaid 图 + 章节表 + 核心伪代码 + 公式 + 阅读建议
- 核心约束：使用 Qwen2.5-72B（主）+ DeepSeek-V3（备）+ Gemini-2.0-Flash（专）

---

## [6.0.0] - 2026-07-16

> 系统设计文档 v6.0（12 章节 + 5 附录）
> System design document v6.0

### ✨ Added

- TL;DR 摘要
- 核心用户哲学规则
- 3 个时序图
- 情感引擎
- 多模态扩展
- 主题切换
- 数据备份 / 迁移
- 持续进化机制
- 反馈学习
- 故障自愈
- 测试策略

---

## 历史 / Legacy

* **v5.0**：单文件 Python QQBot（无桌面壳）
* **v1.0-v4.0**：早期原型（已归档）

---

[9.0.0]: #900---2026-07-16
[8.0.0]: #800---2026-07-15
[7.0.0]: #700---2026-07-15
[6.0.0]: #600---2026-07-16

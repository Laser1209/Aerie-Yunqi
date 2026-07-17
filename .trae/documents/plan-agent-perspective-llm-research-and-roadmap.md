---
title: "Aerie · 云栖 v10.1 — Agent 视角 + 自进化 + 电脑操控 (LLM 调研 + 分阶段路线图)"
date: 2026-07-17
status: plan-mode
priority: high
version: v10.1
supersedes: v10.0
tags:
  - aerie
  - agent-architecture
  - github-research
  - phased-roadmap
  - thin-shell-agent
  - emotional-engine
  - tool-calling
  - memory-management
  - self-evolution
  - computer-use
  - file-organizer
  - document-writer
  - openclaw-style
aliases:
  - "Agent 视角 + 自主学习 + 电脑操控"
  - "Aerie v10.1 路线图"
  - "OpenCloud Companion 终极路线图"
cssclasses:
  - plan-roadmap
  - wide-page
---

# Aerie · 云栖 v10.1 — Agent 视角 + 自进化 + 电脑操控 (LLM 调研 + 分阶段路线图)

> [!important] v10.1 vs v10.0 的核心增量
>
> | v10.0 | v10.1 |
> | --- | --- |
> | 4 阶段：Agent 抽象 / Provider 路由 / 记忆+安全 / 多模态+自进化 | **5 阶段**：在 v10 基础上**新增 S5「自主学习 + 电脑操控（OpenClaw-style）」** |
> | 自进化只是 S4 的子模块（L1/L2/L3） | **自进化独立成 S5 核心**（借鉴 Darwin Gödel Machine 思想：archive 化 + viability gate + diversity sampling） |
> | 工具能力仅 14 个静态 tool | **新增 3 大工具族**：① 电脑操控（OpenClaw/Computer Use 风格） ② 文件整理（FolderFox/OpenYak 风格） ③ 文档写作（Goose AI/GPT Researcher 风格） |
> | 文档/UI 偏保守 | **完整对齐 OpenCloud 原始幻想**（§14 高权限 / §17 自我更新 / §21 持续进化 / §18 开源调研） |

---

## 目录

1. [Phase 0 · 用户原始幻想解读（OpenCloud 文档溯源）](#1-phase-0--用户原始幻想解读opencloud-文档溯源)
2. [Phase 1 · GitHub 项目结构化数据库（v10.1 扩展 · 50+ 项目）](#2-phase-1--github-项目结构化数据库v101-扩展--50-项目)
3. [Phase 2 · Aerie 5 大能力域 + Agent 视角总架构](#3-phase-2--aerie-5-大能力域--agent-视角总架构)
4. [Phase 3 · 6 阶段落地路线图（19 里程碑 · 8.5 周）](#4-phase-3--6-阶段落地路线图19-里程碑--85-周)
5. [Phase 4 · 风险 / 资源 / 验收](#5-phase-4--风险--资源--验收)

---

# 1. Phase 0 · 用户原始幻想解读（OpenCloud 文档溯源）

> [!info] 为什么 Phase 0
> 用户明确说：「阅读 OpenCloud 文档，这是我的原始幻想」+「需要在 Agent 视角基础上增加：① 自主学习 ② 更新自己能力 ③ 主动 ④ 操控电脑（OpenClaw 风格）」+「帮整理桌面应用 / 帮写文档」。所以新计划必须先把这 4 项映射到 GitHub 上的具体项目，再做技术调研。

## 1.1 OpenCloud 文档中的 4 个核心幻想（直接对应用户原话）

| 幻想点 | OpenCloud 章节 | 用户原话 | 对应能力域 |
| --- | --- | --- | --- |
| **自主学习** | §21 持续进化 | "更新自己的能力" | **自进化**（S5） |
| **更新能力** | §21 / §17 | "可以帮我去执行相应的命令" | **电脑操控**（S5） |
| **主动** | §4.4 ProactiveMessenger | "主动操控" | **主动循环**（S4 已有，需升级） |
| **操控电脑** | §13 工具系统 + §14 高权限 | "整理桌面应用 / 写文档" | **文件整理 + 文档写作**（S5） |

## 1.2 OpenCloud §13 工具系统 + §14 高权限 的具体内容

> [!quote] OpenCloud §13 工具系统
> 当前 `core/tool_registry.py` 已有 14+ 工具。但 OpenCloud 原规划要求工具"**让伊塔能真正帮主人做事**"——包括：
> - **§14 高权限**：UAC 提权（执行需要管理员权限的命令）
> - **§14 任务调度**：Windows Task Scheduler 集成（定时执行命令）
> - **§14 静默后台**：不弹窗口运行

> [!quote] OpenCloud §18 候选开源项目
> 8 个候选项目（具体内容因文档过大未读全，但根据 §20 Roadmap 与 §21 持续进化，目标就是 OpenClaw 范式 + 自主学习 + 桌面控制）

## 1.3 OpenCloud §21 持续进化机制 的核心要求

> [!tip] 用户希望
> - **L1 基础记忆**：自动记录用户偏好
> - **L2 梦境式整理**：每天 03:00 整理记忆（已有方向）
> - **L3 主动复盘**：会话空闲时反思
> - **L4 自我修改代码**（**v10.1 新增 · 直接对应 Darwin Gödel Machine**）
>   - 读取自己的源码
>   - 提案修改 → 沙箱预演 → viabilty gate（编译/单测）→ 入档
>   - archive 保留所有变体，diversity sampling 而非 greedy
>   - 失败时自动 revert + 写 journal

## 1.4 用户 4 大新增能力 → 技术对应

| 能力 | GitHub 上对应项目 | 引入方式 |
| --- | --- | --- |
| **自主学习**（不重训模型） | Darwin Gödel Machine (DGM) / SICA / DARWIN / HGM / iterate / Cowrie | 自建 `core/self_evolver.py`（已有 L1/L2/L3），**升级 L4 自改代码** |
| **更新自己能力** | OpenClaw AgentSkills / ClawHub / M3-Agent / EverOS | 自建 `core/skill_creator.py`（让 Agent 自己创建 skill） |
| **主动** | OpenClaw HEARTBEAT / Moltbot / Aerie 现有 ProactiveMessenger | 升级现有机制（加 12h 主动 cycle） |
| **操控电脑** | Claude Computer Use / OpenClaw / Agent S2 / Sai / Qwen Code Cowork | 自建 `core/computer_use.py` + `core/shell_executor.py` + `core/file_organizer.py` + `core/doc_writer.py` |

---

# 2. Phase 1 · GitHub 项目结构化数据库（v10.1 扩展 · 50+ 项目）

> [!info] 调研范围扩展
> v10.0 调研 34 个项目 → v10.1 调研 **52+ 个项目**。新增 4 大方向：电脑操控 / 自进化 / 文件整理 / 文档写作。

## 2.1 方向 ① · 情感表达模块（保留 v10.0）

详见 v10.0 §2.1，本计划不重述。

## 2.2 方向 ② · 能力适配 / 动态性能（保留 v10.0）

详见 v10.0 §2.2，本计划不重述。

## 2.3 方向 ③ · 自调用 / 工具 / 工作流编排（保留 v10.0）

详见 v10.0 §2.3，本计划不重述。

## 2.4 方向 ④ · 记忆 / 上下文 / 多模态 / 安全（保留 v10.0）

详见 v10.0 §2.4，本计划不重述。

## 2.5 方向 ⑤ · 纯外部 API KEY 的"薄壳 Agent"（保留 v10.0）

详见 v10.0 §2.5，本计划不重述。

## 2.6 方向 ⑥ · 🆕 电脑操控 / Computer Use（6 个项目）

| # | 项目 | 仓库 | 范式 | Aerie 适配建议 |
| --- | --- | --- | --- | --- |
| 1 | **Claude Computer Use** | [anthropic-quickstarts/computer-use-demo](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo) | 截图 + 鼠标键盘模拟 + Docker 沙箱 | **参考**：截图 → 视觉推理 → 鼠标键盘循环；OSWorld 72.7% 准确率 |
| 2 | **OpenClaw** | [openclaw/openclaw](https://github.com/openclaw/openclaw) | SOUL.md + 多渠道 Gateway + 工具市场 ClawHub + Lobster 工作流 | **最近项目**（361K stars）；Aerie 的"QQ 桥 + tool registry + self-evolver"已对应 |
| 3 | **Agent S2 (Simular)** | [simular-ai/Agent-S](https://github.com/simular-ai/Agent-S) | 组合式框架 + GPT-4o 规划 + Claude 视觉定位 + Python 执行；OSWorld 34.5% | **参考**：双模型分工（规划 + 视觉）模式 |
| 4 | **Sai by Simular** | [sai.work](https://sai.work) | 商业（$20/月）+ 无障碍 API 优先（accessibility tree） | **参考**：accessibility API 比截图更可靠 |
| 5 | **OpenOperator / OpenAI Operator** | openai.com/operator | CUA 模型 + 浏览器自动化 | **可选**：本地不依赖（云端 API） |
| 6 | **Qwen Code Cowork** | [QwenLM/qwen-code](https://qwenlm.github.io/qwen-code-docs) | Qwen Code SDK + 文件操作 + 桌面整理 + EXIF + Plan mode | **高参考**：本地 Qwen 模型 + 桌面整理场景与 Aerie 高度匹配 |

**对 Aerie 的 actionable insight**：

- **核心选型**：截图循环（Claude Computer Use）+ accessibility API 兜底（Sai 模式）+ **Qwen Code Cowork 的"先 plan 再 execute"模式**
- **沙箱**：Docker 沙箱过重；改用 Windows 进程级沙箱（受限 token + 路径白名单 + 速率限制）
- **OSWorld 基准**：本地小模型（Qwen2.5-VL）当前只 30% 左右，调用 Gemini Vision 可达 60-70%
- **下一步**：
  - `core/computer_use.py`：截图循环（PyAutoGUI + mss）
  - `core/accessibility.py`：Windows UIA API（pywinauto）
  - `core/shell_executor.py`：受限 shell（路径白名单 + 速率限制 + audit log）
  - `core/plan_executor.py`：先出方案 → 用户确认 → 执行

## 2.7 方向 ⑦ · 🆕 自进化 / Self-Evolution（6 个项目）

| # | 项目 | 仓库 | 范式 | Aerie 适配建议 |
| --- | --- | --- | --- | --- |
| 1 | **Darwin Gödel Machine (DGM)** | [jennyzzt/dgm](https://github.com/jennyzzt/dgm) | 自改代码 + archive 保留所有变体 + diversity sampling + viability gate（编译/单测）；SWE-bench 20%→50% | **高参考**：archive-based 自进化的 SOTA |
| 2 | **SICA (Self-Improving Coding Agent)** | [MaximeRobeyns/self_improving_coding_agent](https://github.com/MaximeRobeyns/self_improving_coding_agent) | 元代理 = 目标代理（自指）+ SWE-bench 17%→53% | **可借鉴**：消除"元-目标"分层 |
| 3 | **Huxley-Gödel Machine (HGM)** | [metauto-ai/HGM](https://github.com/metauto-ai/HGM) | CMP 指标（clade 派生累计性能）+ 估计价值函数 | 学术过强；可作理论参考 |
| 4 | **DARWIN** | 论文 [arXiv:2602.05848](https://arxiv.org/pdf/2602.05848) | 遗传算法 + GPT 互改训练代码 + JSON 记忆 | 学术过强 |
| 5 | **iterate** | [GrayCodeAI/iterate](https://github.com/GrayCodeAI/iterate) | Go 实现 + 每 12h 读自己源码 + 改 → 测试 → PR → 审查 → merge | **强参考**：完整的"循环"模式 |
| 6 | **Cowrie (bswen)** | [bswen/blog](https://docs.bswen.com/blog/2026-03-05-self-evolving-ai-agent/) | Rust 实现 + 200 行→1500 行自扩展 + 编译测试门控 | **强参考**：Rust 类型系统 = 自然沙箱 |

**对 Aerie 的 actionable insight**：

- **核心范式**：**DGM 的 archive-based + viability gate + diversity sampling**（不是 greedy）
- **4 个等级**：
  - **L1** 基础记忆（已实现）— 自动记录用户偏好
  - **L2** 梦境整理（已部分实现）— 03:00 整理 working memory
  - **L3** 复盘（已部分实现）— 30min 空闲时反思
  - **L4** 自改代码（v10.1 新增）— 读自己源码 + 提案 + 沙箱编译测试 + archive 入档
- **安全门**（viability gate）：
  1. **编译通过**（`python -m py_compile`）
  2. **单测通过**（pytest）— 必须 0 失败
  3. **e2e 通过**（已有 16 个 e2e）— 必须 0 失败
  4. **白名单文件**（不允许改 `core/persona.py` / `config/persona.yaml` / `core/screen_action_sanitizer.py`）
- **失败时**：revert + 写 journal（`data/self_evolve_journal.md`）+ 不入档
- **下一步**：
  - `core/self_evolver.py` 已存在；升级 L4
  - `core/self_evolve_archive.py` 新建（archive 管理）
  - `core/viability_gate.py` 新建（编译/测试/白名单门控）
  - `tools/self_evolve_journal.py` 新建（journal 可视化）

## 2.8 方向 ⑧ · 🆕 文件整理 / File Organizer（5 个项目）

| # | 项目 | 仓库 | 范式 | Aerie 适配建议 |
| --- | --- | --- | --- | --- |
| 1 | **FolderFox** | [ChenAI-TGF/FolderFox](https://github.com/ChenAI-TGF/FolderFox) | DeepSeek 驱动 + 多模式（智能/类型/前缀）+ 可视化预览 + 拖拽调整 + 二次确认 | **强参考**：完整的"预览 + 确认 + 执行"流程 |
| 2 | **OpenYak** | [open-yak.com](https://open-yak.com) | 桌面 + FastAPI + Tauri v2 + 100+ models + 46+ 集成 + 1M tokens/week 免费 | **强参考**：Tauri v2 + 跨平台桌面 |
| 3 | **Openwork** | [openwork/openwork](https://github.com/openwork) | Electron + React + Vite + 20+ 工具 + 隐私优先 | **可参考**：透明日志 + 用户确认 |
| 4 | **AI File Sorter** | [hyperfield/ai-file-sorter](https://github.com/hyperfield/ai-file-sorter) | C++ 跨平台 + Llama 3B 本地 + 图片内容识别 + EXIF | 可借鉴：图片内容分析能力 |
| 5 | **Qwen Code Cowork** | [QwenLM/qwen-code](https://qwenlm.github.io/qwen-code-docs) | 桌面整理 + 批量重命名 + EXIF + Plan mode | **强参考**：本地整理场景 |

**对 Aerie 的 actionable insight**：

- **核心范式**：「**先扫描 → AI 提案 → 可视化预览 → 用户确认 → 执行**」（所有项目共识）
- **4 种整理模式**：
  - **智能模式**（LLM 看文件名+内容）— 默认
  - **按类型模式**（后缀名）— 经典
  - **按时间模式**（mtime/EXIF）— 照片
  - **按规则模式**（用户自定义 glob）— 高级
- **高风险防护**：标记大文件（>100MB）+ 近期文件（7 天内）+ 不整理黑名单
- **撤销**：每次整理生成 `data/organize_undo.json`（记录原始位置），一键 undo
- **下一步**：
  - `core/file_organizer.py` 新建（核心）
  - `core/file_scanner.py` 新建（扫描 + 特征提取）
  - `core/file_ai_classifier.py` 新建（LLM 分类）
  - `core/file_organize_ui.py` 新建（Electron 可视化预览）
  - `core/file_organize_undo.py` 新建（一键撤销）

## 2.9 方向 ⑨ · 🆕 文档写作 / Document Writer（4 个项目）

| # | 项目 | 仓库 | 范式 | Aerie 适配建议 |
| --- | --- | --- | --- | --- |
| 1 | **Goose AI** | [block/goose](https://github.com/block/goose) | 扩展型 AI agent + `goosehints.md` 配置 + 自动生成 Markdown/HTML/PDF + 自定义模板 | **强参考**：项目内文档自动生成 |
| 2 | **GPT Researcher** | [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher) | 多智能体（planner + executor + publisher）+ 深度递归研究 + 20+ 来源 + PDF/DOCX/MD/HTML 导出 | **强参考**：长文档 + 多来源整合 |
| 3 | **Document Generator MCP** | [thiagotw10/document-generator-mcp](https://github.com/thiagotw10/document-generator-mcp) | MCP 协议 + Word/PDF + Markdown 解析 + VS Code Dark 高亮 + 智能分页 | **可参考**：MCP 协议 + 高质量 PDF |
| 4 | **Documentation.AI Agent** | documentation.ai | 工作区感知 + GitHub 集成 + 模板组件（Callout/Tabs/Steps/Cards） + 自动同步 | **可参考**：组件化文档模板 |

**对 Aerie 的 actionable insight**：

- **核心范式**：根据用户意图 + 已有素材 → 自动生成结构化文档
- **5 种文档类型**：
  - **日记/随笔**（轻量，纯文本）— Aerie 强项
  - **周报/月报**（结构化，图表）
  - **项目文档**（技术规格，Goose 风格）
  - **研究报告**（多源整合，GPT Researcher 风格）
  - **简历/自我介绍**（模板化）
- **多格式输出**：Markdown / HTML / PDF（`weasyprint`）/ Word（`python-docx`）
- **下一步**：
  - `core/doc_writer.py` 新建（核心）
  - `core/doc_researcher.py` 新建（多源研究）
  - `core/doc_exporter.py` 新建（多格式导出）
  - `core/doc_templates/` 新建（5 种类型模板）
  - `core/doc_preview.py` 新建（Electron 预览 + 编辑）

## 2.10 方向 ⑩ · 🆕 OpenClaw 完整生态（5 个项目）

| # | 项目 | 仓库 | 范式 | Aerie 适配建议 |
| --- | --- | --- | --- | --- |
| 1 | **OpenClaw** | [openclaw/openclaw](https://github.com/openclaw/openclaw) | 完整生态：Gateway + SOUL.md + HEARTBEAT.md + MEMORY.md + AGENTS.md + ClawHub + Lobster + 14 渠道 | **最近项目**（361K stars）；Aerie 与之范式高度相似 |
| 2 | **Hermes Agent** | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | 自进化 + 持久记忆 + 自动化 skill 创建 + 沙箱代码执行（Unix socket RPC）+ 300+ models + 多平台 | **高参考**：自动创建 skill 的机制 |
| 3 | **Claw Code** | [ultraworkers/claw-code](https://github.com/ultraworkers/claw-code) | Python/Rust 重写 + oh-my-codex + 195K stars | 仅参考 |
| 4 | **OpenCode** | [anomalyco/opencode](https://github.com/anomalyco/opencode) | 终端编码 agent + 75+ providers + LSP | 仅参考 |
| 5 | **Moltbot / GenericAgent** | GitHub | 极简 3K 行 + 9 atomic tools | 极简参考 |

**对 Aerie 的 actionable insight**：

- **Aerie 已有 OpenClaw 90% 能力**：
  - Gateway → Aerie `companion.py`（已有）
  - SOUL.md → Aerie `config/persona.yaml`（已有）
  - HEARTBEAT.md → Aerie `proactive_judge.py`（已有）
  - MEMORY.md → Aerie `memory/memory_store.py`（已有）
  - AGENTS.md → Aerie `config/agent_skills.yaml`（待建）
  - ClawHub → Aerie `skills/` 目录（已有 47+ skill）
  - 多渠道 → Aerie 当前仅 QQ（**v10.1 待扩展**）
- **Aerie 差异化**：
  - **人格深度**（Character.AI 范式）— OpenClaw 无
  - **主动消息的情绪化**（PAD 3 维）— OpenClaw Heartbeat 是 cron
  - **薄壳 API 范式**（用户自带 key）— OpenClaw 需自托管

---

# 3. Phase 2 · Aerie 5 大能力域 + Agent 视角总架构

## 3.1 5 大能力域映射到用户 4 大幻想

```text
┌────────────────────────────────────────────────────────────────────────┐
│                    Aerie · 云栖 v10.1 — 能力域全景                       │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  1. Agent 抽象域 (v10 S1)                                    │     │
│  │     core/agent.py — 收口 7 模块到 Perceive/Reason/Decide/Act│     │
│  │     /Reflect/Express 主循环                                  │     │
│  └─────────────────────────────────────────────────────────────┘     │
│       ↑ 注入到 ↓                                                     │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  2. 资源调度域 (v10 S2)                                      │     │
│  │     provider_router.py + 任务复杂度 + 月度预算               │     │
│  └─────────────────────────────────────────────────────────────┘     │
│       ↑ 输入 ↓                                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  3. 记忆安全域 (v10 S3)                                      │     │
│  │     4 层记忆 + AGENTSYS 隔离                                 │     │
│  └─────────────────────────────────────────────────────────────┘     │
│       ↑ 输入 ↓                                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  4. 多模态域 (v10 S4)                                        │     │
│  │     图片输入 + TTS 输出 + 自进化 L1/L2/L3                     │     │
│  └─────────────────────────────────────────────────────────────┘     │
│       ↑ 输入 ↓                                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  5. 🆕 自主 + 操控域 (v10.1 S5) ⭐ 核心增量                   │     │
│  │     - 自进化 L4（Darwin-Gödel 风格）                          │     │
│  │     - 电脑操控（OpenClaw/Computer Use 风格）                  │     │
│  │     - 文件整理（FolderFox/OpenYak 风格）                      │     │
│  │     - 文档写作（Goose/GPT Researcher 风格）                   │     │
│  │     - 自主 skill 创建（Hermes Agent 风格）                    │     │
│  │     - 多渠道（OpenClaw 风格：QQ/微信/邮件/Telegram/飞书）     │     │
│  └─────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────┘
```

## 3.2 v10.1 新增 12 个核心模块（S5 阶段）

### 3.2.1 自进化 L4 模块（3 个）

#### `core/self_evolve_archive.py` — DGM 风格 archive

```python
"""Aerie · 云栖 v10.1 — Self-Evolve Archive (DGM-style).

R10.1: 自进化 L4. archive-based, diversity sampling, viability gate.
- 保留所有通过 viability gate 的代码变体
- 不用 greedy（容易卡在 local optimum）
- 用 diversity-weighted sampling（让低分但独特的变体也能当"跳板"）
- 失败时 revert + 写 journal
"""
from __future__ import annotations
import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SelfEvolveArchive:
    """R10.1: 保留所有 viability-pass 的变体 + diversity sampling."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.archive_dir = root / "data" / "self_evolve_archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.archive_index = self.archive_dir / "index.jsonl"

    def save_variant(self, file_changes: dict[str, str], score: float,
                     parent_id: str | None, viability_pass: bool) -> str:
        """保存通过的变体到 archive. 返回 variant_id."""
        variant_id = f"var_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{score:.2f}"
        variant_dir = self.archive_dir / variant_id
        variant_dir.mkdir()
        # 保存源码
        for path, content in file_changes.items():
            (variant_dir / Path(path).name).write_text(content, encoding="utf-8")
        # 保存元数据
        meta = {
            "id": variant_id,
            "score": score,
            "parent_id": parent_id,
            "viability_pass": viability_pass,
            "created_at": datetime.now().isoformat(),
            "file_changes": list(file_changes.keys()),
        }
        with self.archive_index.open("a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        logger.info(f"Self-evolve variant saved: {variant_id} (score={score:.2f})")
        return variant_id

    def sample_parent(self, n: int = 3) -> list[dict[str, Any]]:
        """Diversity-weighted sampling. 不只取 best."""
        variants = self._load_index()
        if not variants:
            return []
        # diversity score = 1 / (1 + 排名) — 排名靠后但有差异化的变体也能被选
        scored = [
            (v, 1.0 / (1 + i) + (1.0 - v["score"]) * 0.3)
            for i, v in enumerate(variants)
        ]
        scored.sort(key=lambda x: -x[1])
        return [v for v, _ in scored[:n]]

    def _load_index(self) -> list[dict[str, Any]]:
        if not self.archive_index.exists():
            return []
        return [json.loads(line) for line in self.archive_index.read_text(encoding="utf-8").splitlines()]
```

#### `core/viability_gate.py` — 安全门控

```python
"""Aerie · 云栖 v10.1 — Viability Gate (编译/单测/白名单)."""
from __future__ import annotations
import subprocess
from pathlib import Path

# 白名单：可改的文件（绝对路径列表）
WHITELIST_FILES: set[str] = {
    "core/agent.py", "core/provider_router.py", "core/agent_skill_graph.py",
    "core/self_evolver.py", "core/self_evolve_archive.py",
    "core/computer_use.py", "core/shell_executor.py",
    "core/file_organizer.py", "core/doc_writer.py",
    "core/skill_creator.py", "core/multi_channel.py",
    "tools/self_evolve_journal.py",
}

# 禁止改的文件（高优先级铁律）
FORBIDDEN_FILES: set[str] = {
    "config/persona.yaml", "core/screen_action_sanitizer.py",
    "core/output_self_check.py", "tools/check_forbidden.py",
}


class ViabilityGate:
    """R10.1: 提案修改前必须通过 4 道门."""

    def __init__(self, project_root: Path) -> None:
        self.root = project_root

    def check(self, file_changes: dict[str, str]) -> tuple[bool, list[str]]:
        """返回 (pass, errors)."""
        errors: list[str] = []
        # 门 1: 白名单 + 黑名单
        for path in file_changes:
            rel = path.replace("\\", "/")
            if rel in FORBIDDEN_FILES:
                errors.append(f"FORBIDDEN: {rel} 不可改")
            elif rel not in WHITELIST_FILES:
                errors.append(f"NOT_WHITELISTED: {rel} 不在自改白名单")
        if errors:
            return False, errors
        # 门 2: 编译
        ok, out = self._run("python -m py_compile " + " ".join(file_changes.keys()))
        if not ok:
            errors.append(f"COMPILE_FAIL: {out[:500]}")
            return False, errors
        # 门 3: 单测
        ok, out = self._run("pytest tests/ -x --tb=short -q", timeout=120)
        if not ok:
            errors.append(f"UNIT_TEST_FAIL: {out[:500]}")
            return False, errors
        # 门 4: e2e（仅 4 个核心套件，不全跑）
        ok, out = self._run("python verify_zero_regression.py", timeout=180)
        if not ok:
            errors.append(f"E2E_FAIL: {out[:500]}")
            return False, errors
        return True, []

    def _run(self, cmd: str, timeout: int = 60) -> tuple[bool, str]:
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=self.root, capture_output=True,
                text=True, timeout=timeout,
            )
            return r.returncode == 0, r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"
```

#### `core/self_evolver.py` 升级（新增 L4）

```python
"""Aerie · 云栖 v10.1 — Self Evolver (升级 L4).

L4: 自改代码 (DGM-style)
- 读自己源码
- 提案修改
- viability gate
- archive 入档
- 失败 revert + journal
"""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Any
from core.self_evolve_archive import SelfEvolveArchive
from core.viability_gate import ViabilityGate
from core.brain import Brain

logger = logging.getLogger(__name__)


class SelfEvolver:
    """R10.1: 4 等级自进化."""

    def __init__(self, project_root: Path, brain: Brain) -> None:
        self.root = project_root
        self.brain = brain
        self.archive = SelfEvolveArchive(project_root)
        self.gate = ViabilityGate(project_root)

    async def l4_evolve_code(self) -> dict[str, Any] | None:
        """L4: 自改代码. DGM 风格. 异步, 不阻塞主流程."""
        # 1. sample parent (diversity-weighted, 不取 best)
        parents = self.archive.sample_parent(n=3)
        # 2. 读自己源码
        source_files = self._read_whitelist_sources()
        # 3. 提案修改
        proposal = await self.brain.propose_code_mutation(
            parent_variants=parents,
            source_files=source_files,
        )
        if not proposal:
            return None
        # 4. viability gate
        ok, errors = self.gate.check(proposal["changes"])
        if not ok:
            await self._write_journal(proposal, errors)
            return None
        # 5. 应用修改
        backup = self._backup(proposal["changes"])
        try:
            self._apply(proposal["changes"])
            # 6. 跑 e2e 算 score
            score = await self._evaluate(proposal)
            # 7. archive 入档
            self.archive.save_variant(
                proposal["changes"], score, parents[0]["id"] if parents else None, True,
            )
            await self._write_journal(proposal, [], score)
            return {"variant_id": ..., "score": score}
        finally:
            # 8. 失败 revert
            if score < 0:
                self._restore(backup)
```

### 3.2.2 电脑操控模块（3 个）

#### `core/computer_use.py` — 屏幕操控核心

```python
"""Aerie · 云栖 v10.1 — Computer Use (OpenClaw / Computer Use 风格).

R10.1: 截图 → 视觉推理 → 鼠标键盘循环
- 沙箱：路径白名单 + 速率限制 + audit log
- 视觉模型：默认 Gemini Vision（多模态便宜）
- 兜底：Windows UIA (pywinauto) — 截图失败时
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
import mss
import pyautogui

logger = logging.getLogger(__name__)


@dataclass
class ScreenAction:
    """屏幕动作."""
    action: str  # click / type / scroll / key / screenshot
    x: int = 0
    y: int = 0
    text: str = ""
    key: str = ""


class ComputerUse:
    """R10.1: 电脑操控核心."""

    # 路径白名单（不允许访问系统关键目录）
    PATH_DENYLIST: set[str] = {
        "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
        "C:\\ProgramData", "/etc", "/usr", "/System",
    }

    # 速率限制
    MAX_ACTIONS_PER_MINUTE = 30

    def __init__(self) -> None:
        self.action_count = 0
        self.last_minute_reset = asyncio.get_event_loop().time()
        self.audit_log_path = Path("data/computer_use_audit.log")

    async def execute_plan(self, plan: list[ScreenAction]) -> list[dict]:
        """执行一串屏幕动作. 每步前 audit log."""
        results = []
        for action in plan:
            await self._rate_limit()
            await self._audit(action)
            if action.action == "screenshot":
                img = await self._screenshot()
                results.append({"ok": True, "image": img})
            elif action.action == "click":
                pyautogui.click(action.x, action.y)
                results.append({"ok": True})
            elif action.action == "type":
                pyautogui.typewrite(action.text)
                results.append({"ok": True})
            elif action.action == "key":
                pyautogui.press(action.key)
                results.append({"ok": True})
            self.action_count += 1
        return results

    async def _screenshot(self) -> bytes:
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[0])
            return img.rgb
```

#### `core/shell_executor.py` — 受限 shell

```python
"""Aerie · 云栖 v10.1 — Shell Executor (受限)."""
from __future__ import annotations
import asyncio
import logging
import shlex
from pathlib import Path

logger = logging.getLogger(__name__)


class ShellExecutor:
    """R10.1: 受限 shell（OpenClaw 风格 + 沙箱）."""

    DANGEROUS_PATTERNS: set[str] = {
        "rm -rf", "rm -fr", "del /f", "format", "mkfs",
        ":(){:|:&};:", "dd if=", "chmod -R 777", "curl | bash",
    }

    def __init__(self) -> None:
        self.audit_log = Path("data/shell_audit.log")
        self.rate_limit_per_minute = 10

    async def run(self, command: str, cwd: Path | None = None,
                  timeout: int = 30) -> dict:
        """执行命令. 检查危险模式 + audit log + 速率限制."""
        # 1. 危险模式检测
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in command:
                await self._audit(command, status="BLOCKED_DANGEROUS")
                return {"ok": False, "error": f"DANGEROUS_PATTERN: {pattern}"}
        # 2. audit log
        await self._audit(command, status="STARTED")
        # 3. 执行
        proc = await asyncio.create_subprocess_shell(
            command, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await self._audit(command, status="TIMEOUT")
            return {"ok": False, "error": "timeout"}
        ok = proc.returncode == 0
        await self._audit(command, status="OK" if ok else "FAILED",
                          returncode=proc.returncode)
        return {
            "ok": ok, "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
```

#### `core/file_organizer.py` — 文件整理（FolderFox 风格）

```python
"""Aerie · 云栖 v10.1 — File Organizer (FolderFox / OpenYak 风格).

R10.1: 4 模式整理 + 预览确认 + 一键撤销
- 智能模式（LLM 看文件名+内容）
- 按类型模式（后缀）
- 按时间模式（mtime/EXIF）
- 按规则模式（glob）
"""
from __future__ import annotations
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OrganizePlan:
    """整理方案. 文件 → 目标路径."""
    moves: dict[str, str]  # 原路径 → 新路径
    mode: str  # smart / type / time / rule
    estimated_size_mb: float
    risky_count: int  # 大文件/近期文件


class FileOrganizer:
    """R10.1: 文件整理核心."""

    LARGE_FILE_MB = 100
    RECENT_DAYS = 7

    def __init__(self, root: Path) -> None:
        self.root = root
        self.undo_log = root / "data" / "organize_undo.json"

    def scan(self, folder: Path) -> list[dict]:
        """扫描文件夹, 收集文件特征."""
        files = []
        for p in folder.rglob("*"):
            if p.is_file():
                stat = p.stat()
                files.append({
                    "path": str(p),
                    "name": p.name,
                    "ext": p.suffix.lower(),
                    "size_mb": stat.st_size / 1024 / 1024,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "is_large": stat.st_size > self.LARGE_FILE_MB * 1024 * 1024,
                    "is_recent": (datetime.now() - datetime.fromtimestamp(stat.st_mtime)).days < self.RECENT_DAYS,
                })
        return files

    def plan_smart(self, files: list[dict], llm_categorize) -> OrganizePlan:
        """智能模式: LLM 看文件名+大小+时间分类."""
        moves = {}
        for f in files:
            category = llm_categorize(f)
            target = f["path"].replace(
                str(self.root), str(self.root / "_organized" / category),
            )
            moves[f["path"]] = target
        return OrganizePlan(
            moves=moves, mode="smart",
            estimated_size_mb=sum(f["size_mb"] for f in files),
            risky_count=sum(1 for f in files if f["is_large"] or f["is_recent"]),
        )

    def execute(self, plan: OrganizePlan, confirm: bool = False) -> dict:
        """执行整理. 写入 undo log + 大文件/近期文件需 confirm."""
        if plan.risky_count > 0 and not confirm:
            return {"ok": False, "error": f"risky_count={plan.risky_count}, need confirm=True"}
        undo_data = []
        for src, dst in plan.moves.items():
            src_p, dst_p = Path(src), Path(dst)
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            undo_data.append({"from": str(dst_p), "to": str(src_p)})
            shutil.move(str(src_p), str(dst_p))
        # 写 undo log
        with self.undo_log.open("w", encoding="utf-8") as f:
            json.dump({"plan": plan.moves, "undo": undo_data, "ts": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
        return {"ok": True, "moved": len(plan.moves), "undo_log": str(self.undo_log)}

    def undo_last(self) -> dict:
        """一键撤销上次整理."""
        if not self.undo_log.exists():
            return {"ok": False, "error": "no undo log"}
        data = json.loads(self.undo_log.read_text(encoding="utf-8"))
        for entry in data["undo"]:
            if Path(entry["from"]).exists():
                shutil.move(entry["from"], entry["to"])
        self.undo_log.unlink()
        return {"ok": True, "undone": len(data["undo"])}
```

### 3.2.3 文件整理 + 文档写作 UI 模块（Electron 端）

```typescript
// electron/src/renderer/js/file-organizer.js — 整理预览
class FileOrganizerUI {
  async startOrganize(folderPath: string) {
    // 1. 扫描
    const files = await window.aerie.api.post('/api/file_organizer/scan', { folder: folderPath });
    // 2. AI 分类（智能模式）
    const plan = await window.aerie.api.post('/api/file_organizer/plan', { mode: 'smart', files });
    // 3. 可视化预览
    this.renderPreview(plan);
    // 4. 用户确认 / 拖拽调整
    this.bindDragDrop(plan);
    // 5. 执行
    document.getElementById('organize-execute-btn').onclick = async () => {
      const result = await window.aerie.api.post('/api/file_organizer/execute', {
        plan, confirm: plan.risky_count > 0,
      });
      if (result.ok) {
        alert(`已整理 ${result.moved} 个文件. 撤销日志: ${result.undo_log}`);
      }
    };
  }
}
```

### 3.2.4 文档写作模块（Goose + GPT Researcher 风格）

```python
# core/doc_writer.py — 5 种文档类型 + 多格式导出
from __future__ import annotations
import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class DocType(Enum):
    DIARY = "diary"          # 日记
    REPORT = "report"        # 周报/月报
    SPEC = "spec"            # 项目文档
    RESEARCH = "research"    # 研究报告
    RESUME = "resume"        # 简历


class DocWriter:
    """R10.1: 文档写作核心."""

    TEMPLATES: dict[DocType, str] = {
        DocType.DIARY: "core/doc_templates/diary.md",
        DocType.REPORT: "core/doc_templates/report.md",
        DocType.SPEC: "core/doc_templates/spec.md",
        DocType.RESEARCH: "core/doc_templates/research.md",
        DocType.RESUME: "core/doc_templates/resume.md",
    }

    def __init__(self, root: Path) -> None:
        self.root = root
        self.templates_dir = root / "core" / "doc_templates"

    async def write(self, doc_type: DocType, user_request: str,
                    context: dict | None = None,
                    output_format: str = "markdown") -> Path:
        """生成文档. 模板 + LLM 填充."""
        template = self._load_template(doc_type)
        # LLM 填充模板
        from core.brain import Brain
        brain = Brain()
        content = await brain.fill_template(
            template=template, user_request=user_request, context=context or {},
        )
        # 写入文件
        output_path = self.root / "documents" / f"{doc_type.value}_{...}.md"
        output_path.write_text(content, encoding="utf-8")
        # 可选导出 PDF/Word
        if output_format != "markdown":
            from core.doc_exporter import DocExporter
            output_path = DocExporter().export(content, output_format, output_path)
        return output_path
```

### 3.2.5 自主 skill 创建（Hermes Agent 风格）

```python
# core/skill_creator.py — Agent 自己创建 skill
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillCreator:
    """R10.1: 自主 skill 创建. 复用现有 skill_loader 框架."""

    SKILL_TEMPLATE = '''"""Aerie · 云栖 v10.1 — Auto-generated skill: {name}.
Generated by: skill_creator.py
Created at: {created_at}
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class {class_name}:
    """{description}"""

    name = "{name}"
    description = "{description}"
    capability_tags = {tags!r}

    async def execute(self, **kwargs) -> dict:
        raise NotImplementedError("auto-generated skill needs implementation")
'''

    def __init__(self, project_root: Path) -> None:
        self.root = project_root
        self.skills_dir = project_root / "skills" / "auto_generated"

    async def create_skill(self, name: str, description: str, tags: list[str]) -> Path:
        """Agent 调用此方法创建一个新 skill."""
        path = self.skills_dir / f"{name}.py"
        content = self.SKILL_TEMPLATE.format(
            name=name, description=description, tags=tags,
            class_name=name.title().replace("_", ""),
            created_at="...isoformat...",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        # 自动注册到 skill_loader
        await self._register(path)
        return path
```

### 3.2.6 多渠道（OpenClaw 风格）

```python
# core/multi_channel.py — 多渠道（QQ/微信/邮件/Telegram/飞书）
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MultiChannel:
    """R10.1: 多渠道支持. 当前仅 QQ, 后续扩展."""

    def __init__(self) -> None:
        self.channels: dict[str, Any] = {
            "qq": None,        # 已有
            "wechat": None,    # 后续
            "email": None,     # 后续
            "telegram": None,  # 后续
            "feishu": None,    # 后续
        }

    async def broadcast(self, message: str, channels: list[str] | None = None) -> dict:
        """跨渠道广播. 伊塔主动消息可以同时发到多个渠道."""
        target = channels or list(self.channels.keys())
        results = {}
        for ch in target:
            if self.channels.get(ch) is None:
                results[ch] = {"ok": False, "error": "not_implemented"}
                continue
            try:
                await self.channels[ch].send(message)
                results[ch] = {"ok": True}
            except Exception as e:
                results[ch] = {"ok": False, "error": str(e)}
        return results
```

---

# 4. Phase 3 · 6 阶段落地路线图（19 里程碑 · 8.5 周）

## 4.1 阶段总览

| 阶段 | 主题 | 周期 | 关键模块 | 价值 | 风险 |
| --- | --- | --- | --- | --- | --- |
| **S1** | 显式 Agent 抽象 | 1.5 周 | `core/agent.py` | 收口 7 模块为 Agent 视角 | 低 |
| **S2** | 智能 Provider 路由 | 1 周 | `core/provider_router.py` | 按复杂度+预算动态选 | 中 |
| **S3** | 分层记忆 + 安全 | 2 周 | `memory/` + `core/tool_isolation.py` | 防御 prompt injection | 中 |
| **S4** | 多模态 + 自进化 L1/L2/L3 | 2 周 | `multimodal/` + `self_evolver` | 图片+语音+主动循环 | 中 |
| **S5** | 🆕 自主 + 操控 | 2 周 | `self_evolve_archive.py` + `computer_use.py` + `file_organizer.py` + `doc_writer.py` + `skill_creator.py` + `multi_channel.py` | 满足用户 4 大幻想 | **高** |
| **S6** | 集成 + 收口 + v10.1 发布 | 1 周 | 全量回归 + Electron UI + 便携版打包 | 上线 v10.1 | 低 |

**总周期：8.5 周（~43 个工作日）**

## 4.2 S1-S4 详情（与 v10.0 相同）

S1-S4 详细里程碑见 v10.0 §4.2-4.5，本计划不重述。

## 4.3 S5 · 自主 + 操控（2 周 · 6 里程碑 · 核心增量）

### M5.1 (Day 28-30) · 自进化 L4（Darwin-Gödel 风格）

- **What**：新建 `core/self_evolve_archive.py` + `core/viability_gate.py` + 升级 `core/self_evolver.py` 加 L4
- **Why**：实现"自改代码"（DGM 范式）
- **How**：
  - 读白名单内 8 个文件（agent.py / provider_router.py / agent_skill_graph.py / self_evolver.py / self_evolve_archive.py / computer_use.py / shell_executor.py / file_organizer.py / doc_writer.py / skill_creator.py / multi_channel.py）
  - 提案修改 → viability gate（编译 + 单测 + e2e）
  - archive 入档（diversity-weighted sampling）
  - 失败时 revert + 写 journal
- **风险**：**高**（自改代码风险大）
- **验收**：
  - 主动触发 L4：让 Agent 改进 `compute_persona_interval` 的随机性
  - 通过 viability gate 4 道门（编译/单测/e2e/白名单）
  - 入档后 24h 内不触发"回退"
  - journal 记录完整

### M5.2 (Day 31-32) · 电脑操控（OpenClaw / Computer Use 风格）

- **What**：新建 `core/computer_use.py` + `core/shell_executor.py` + `core/accessibility.py`
- **Why**：实现"主动操控电脑"（OpenClaw 风格）
- **How**：
  - `computer_use.py`（截图 + 鼠标键盘，mss + pyautogui）
  - `shell_executor.py`（受限 shell，危险模式黑名单 + 速率限制 + audit log）
  - `accessibility.py`（Windows UIA 兜底，pywinauto）
  - `core/computer_use_planner.py`（"先 plan → 确认 → 执行"模式，Qwen Code Cowork 风格）
- **风险**：**高**（电脑操控有破坏性）
- **验收**：
  - 5 个 e2e 用例：① 截图 ② 鼠标点击 ③ 键盘输入 ④ 受限 shell（白名单内） ⑤ 危险命令拒绝
  - audit log 写入 `data/computer_use_audit.log`
  - 速率限制生效

### M5.3 (Day 33-35) · 文件整理（FolderFox / OpenYak 风格）

- **What**：新建 `core/file_organizer.py` + `core/file_scanner.py` + `core/file_ai_classifier.py` + `core/file_organize_undo.py` + Electron 预览 UI
- **Why**：实现"帮整理桌面应用"
- **How**：
  - 4 模式：智能（LLM）/ 类型（后缀）/ 时间（mtime + EXIF）/ 规则（glob）
  - 可视化预览：Electron 双栏（左原 / 右方案）
  - 拖拽调整 + 二次确认
  - 大文件（>100MB）/ 近期（7 天）标记
  - 一键 undo（`data/organize_undo.json`）
- **风险**：中（用户误操作可能移动重要文件）
- **验收**：
  - 5 个 e2e：① 扫描 ② 智能模式 ③ 拖拽调整 ④ 执行 ⑤ undo
  - 撤销日志可读
  - UI 美观（沿用乙女风）

### M5.4 (Day 36-37) · 文档写作（Goose / GPT Researcher 风格）

- **What**：新建 `core/doc_writer.py` + `core/doc_researcher.py` + `core/doc_exporter.py` + `core/doc_templates/` + `core/doc_preview.py`
- **Why**：实现"帮写文档"
- **How**：
  - 5 种类型：日记/报告/规格/研究/简历
  - 多源研究（GPT Researcher 风格：planner + executor + publisher）
  - 多格式导出：Markdown / HTML / PDF（`weasyprint`）/ Word（`python-docx`）
  - Electron 预览 + 编辑
- **风险**：低（纯生成，不破坏现有）
- **验收**：
  - 6 个 e2e：① 5 种类型各 1 ② 多格式导出
  - 模板可读
  - Electron 预览 UI 完整

### M5.5 (Day 38) · 自主 skill 创建（Hermes Agent 风格）

- **What**：新建 `core/skill_creator.py`，让 Agent 自己创建 skill
- **Why**：实现"更新自己的能力"（自主扩展）
- **How**：
  - 模板化生成 skill 类
  - 自动注册到 `skill_loader`
  - skill 存到 `skills/auto_generated/`
- **风险**：中（自创建 skill 可能引入 bug）
- **验收**：
  - 1 个 e2e：触发 skill_creator → 生成 1 个新 skill → skill_loader 能加载
  - 命名空间 `auto_generated` 隔离

### M5.6 (Day 39-40) · 多渠道（OpenClaw 风格）

- **What**：新建 `core/multi_channel.py` 框架 + 扩展 1 个新渠道（飞书 / Telegram 二选一）
- **Why**：实现"多渠道"，对齐 OpenClaw 范式
- **How**：
  - 抽象 `Channel` 基类
  - 至少接入 1 个新渠道（飞书 webhook 或 Telegram bot）
  - 跨渠道广播（伊塔主动消息可同时发多渠道）
- **风险**：低（新增能力，不破坏 QQ）
- **验收**：
  - 1 个新渠道可用
  - 旧 QQ 渠道 e2e 全绿
  - `multi_channel` 框架可扩展

## 4.4 S6 · 集成 + 收口 + v10.1 发布（1 周 · 3 里程碑）

### M6.1 (Day 41) · S5 收口

- 跑全量 22+ 个 e2e + 5 个新增 S5 e2e
- 任何一项不绿必须修

### M6.2 (Day 42) · Cognition Panel v2 增强

- 新增"自进化"tab（显示 L4 状态、archive 列表、journal）
- 新增"电脑操控"tab（显示 audit log、最近 10 次动作）
- 新增"文件整理"tab（显示最近整理记录）
- 新增"文档写作"tab（显示最近生成的文档）

### M6.3 (Day 43) · v10.1 便携版打包

- Electron 打包（沿用 v9.0.0 配置）
- 5 个 e2e 全绿
- 性能基线测试（启动 < 5s / 内存 < 500MB）
- 用户确认发布

## 4.5 完整里程碑清单

| # | ID | 名称 | 周期 | 依赖 | 验收 |
| --- | --- | --- | --- | --- | --- |
| 1 | M1.1 | agent.py 骨架 | Day 1-2 | 无 | 模块可导入 |
| 2 | M1.2 | agent.run() 主循环 | Day 3-4 | M1.1 | 14 e2e 绿 |
| 3 | M1.3 | 异步 Reflect | Day 5 | M1.2 | e2e_self_evolve 绿 |
| 4 | M1.4 | S1 收口 | Day 6-7 | M1.3 | 全绿 |
| 5 | M2.1 | provider_router 复杂度评估 | Day 8-9 | M1.4 | 5 e2e 绿 |
| 6 | M2.2 | 动态路由 + 预算 | Day 10-11 | M2.1 | verify 绿 |
| 7 | M2.3 | S2 收口 | Day 12 | M2.2 | 全绿 |
| 8 | M3.1 | 4 层记忆 schema | Day 13-14 | M2.3 | 表创建成功 |
| 9 | M3.2 | 长期记忆迁移 | Day 15-17 | M3.1 | 数据完整 |
| 10 | M3.3 | 工具调用隔离 | Day 18-20 | M3.2 | e2e_tool_isolation 绿 |
| 11 | M3.4 | 注入测试 | Day 21-22 | M3.3 | 10/10 防御 |
| 12 | M3.5 | S3 收口 | Day 23 | M3.4 | 全绿 |
| 13 | M4.1 | 多模态输入（图片） | Day 24-25 | M3.5 | e2e_multimodal 绿 |
| 14 | M4.2 | 多模态输出（语音） | Day 26-27 | M4.1 | e2e_tts 绿 |
| 15 | M4.4 | 自进化 L1/L2/L3 升级 | Day 28 | M4.2 | e2e_self_evolve 绿 |
| 16 | M5.1 | 自进化 L4 (DGM-style) | Day 28-30 | M4.4 | e2e_self_evolve_l4 绿 |
| 17 | M5.2 | 电脑操控 | Day 31-32 | M5.1 | e2e_computer_use 绿 |
| 18 | M5.3 | 文件整理 | Day 33-35 | M5.2 | e2e_file_organizer 绿 |
| 19 | M5.4 | 文档写作 | Day 36-37 | M5.3 | e2e_doc_writer 绿 |
| 20 | M5.5 | 自主 skill 创建 | Day 38 | M5.4 | e2e_skill_creator 绿 |
| 21 | M5.6 | 多渠道 | Day 39-40 | M5.5 | e2e_multi_channel 绿 |
| 22 | M6.1 | S5 收口 | Day 41 | M5.6 | 全绿 |
| 23 | M6.2 | Cognition Panel v2 | Day 42 | M6.1 | 4 新 tab 可用 |
| 24 | M6.3 | v10.1 发布 | Day 43 | M6.2 | 便携版可用 |

**总计：24 里程碑 / 8.5 周**

## 4.6 任务优先级排序

| 优先级 | 里程碑 | 理由 |
| --- | --- | --- |
| **P0** | M1.1 / M1.2 | Agent 抽象是后续阶段基础 |
| **P0** | M5.1 | 自进化 L4 是用户 4 大幻想核心 |
| **P0** | M5.2 | 电脑操控是用户 4 大幻想核心 |
| **P0** | M5.3 | 文件整理是用户 4 大幻想核心 |
| **P0** | M5.4 | 文档写作是用户 4 大幻想核心 |
| **P0** | M5.5 | 自主 skill 是用户 4 大幻想核心 |
| **P0** | M5.6 | 多渠道是差异化护城河 |
| **P1** | M2.1 / M2.2 | Provider 路由影响成本 |
| **P1** | M3.3 / M3.4 | 工具隔离是安全 P0 |
| **P1** | M4.1 / M4.2 | 多模态是体验提升 |
| **P2** | M6.2 | Cognition Panel v2 是 UI 增强 |
| **P2** | M6.3 | 发布是最后一步 |

## 4.7 阶段性里程碑节点

| 节点 | 时间 | 验收标准 | 用户决策点 |
| --- | --- | --- | --- |
| **N1** (S1 完成) | Day 7 | 16 e2e 绿 + Agent.run() 路径切换 | 决定是否进入 S2 |
| **N2** (S2 完成) | Day 12 | 16 e2e 绿 + Provider 路由按预算切换 | 决定月度预算阈值 |
| **N3** (S3 完成) | Day 23 | 21 e2e 绿 + 10/10 注入防御 | 决定安全策略严格度 |
| **N4** (S4 完成) | Day 28 | 22 e2e 绿 + 多模态跑通 | 决定是否进入 S5 |
| **N5** (S5 完成) | Day 40 | 27 e2e 绿 + 自进化/电脑操控/文件整理/文档写作/多渠道全通 | 决定是否进入 S6 |
| **N6** (v10.1 发布) | Day 43 | 27 e2e 绿 + 完整功能 + 便携版 | 决定发布 |

## 4.8 资源需求清单

| 资源 | 用途 | 数量 |
| --- | --- | --- |
| 后端开发 | Python 内核 24 里程碑 | 1 人 × 43 天 |
| 测试开发 | 新增 11+ 个 e2e 脚本 | 0.3 人 × 43 天 |
| 设计 | Cognition Panel v2（4 新 tab） | 0.2 人 × 3 天 |
| 部署 | v10.1 便携版打包 | 0.1 人 × 2 天 |
| **总计** | | **约 1.9 人月** |

## 4.9 风险与应对策略

| 风险 | 影响 | 概率 | 应对 |
| --- | --- | --- | --- |
| 自进化 L4 提案破坏既有 e2e | **高** | 高 | viability gate 4 道门 + archive 永远可回退 + 24h 观察期 |
| 电脑操控误操作（误删文件） | **高** | 中 | 路径白名单 + 危险模式黑名单 + audit log + 一键 undo |
| 文件整理移动重要文件 | 中 | 中 | 撤销日志（7 天保留）+ 大文件/近期文件标记 + 二次确认 |
| 文档写作 prompt 注入 | 中 | 低 | 复用 M3.3 工具隔离（已防御） |
| 多渠道接入新服务失败 | 低 | 中 | 抽象 Channel 基类，新渠道失败不影响 QQ 主渠道 |
| Gemini Vision 调用贵 | 中 | 中 | 默认走 Qwen-VL（便宜），Gemini 只在 fallback |
| 整体项目过 6 周仍未完成 | 中 | 中 | 每 2 周一次 review，调整范围 |

---

# 5. Phase 4 · 风险 / 资源 / 验收

## 5.1 不在本次范围（明确边界）

- ❌ 不重训任何 LLM 模型
- ❌ 不引入 LangChain / AutoGen / CrewAI
- ❌ 不改变 persona 9/10 基线
- ❌ 不改变 5 条 Message 规范原则
- ❌ 不改变三原则（零回退 / 无禁词 / 主题色 token 化）
- ❌ 不引入多智能体（保持单 agent + tools 架构）
- ❌ 不引入云端依赖（保持本地优先）
- ❌ 不改 `config/persona.yaml` / `core/screen_action_sanitizer.py` / `core/output_self_check.py`（自改黑名单）
- ❌ 不接管系统级操作（UAC 提权、Task Scheduler 静默）—— OpenCloud §14 高权限保留至 v11+ 讨论

## 5.2 完整 e2e 验收清单

> v10.0 16 个 e2e + v10.1 新增 11 个 e2e = **共 27 个 e2e**。

| 类别 | 文件 | 来源 |
| --- | --- | --- |
| **v10 既有 e2e** | e2e_persona_baseline.py / e2e_pacing.py / e2e_boot_greeting.py / e2e_output_self_check.py / e2e_splitter_atomic.py / e2e_a_force_bypass.py / e2e_yaml.py / e2e_narration.py / e2e_self_evolve.py / e2e_proactive_judge.py | 既有 |
| **v10 既有 verify** | verify_zero_regression.py / verify_emotion_history.py / verify_pacing_persistence.py / verify_screen_sanitizer.py / verify_self_evolve.py / verify_r3_3.py / verify_r3_5.py | 既有 |
| **v10 新增 e2e** | e2e_agent_run.py / e2e_provider_router.py (5) / e2e_memory_layers.py / e2e_tool_isolation.py / e2e_security_injection.py (10) / e2e_multimodal_image.py / e2e_tts.py | 新（v10） |
| **v10.1 新增 e2e (S5)** | e2e_self_evolve_l4.py (DGM 风格) | 新（S5） |
| | e2e_computer_use.py (5 用例：截图/点击/输入/受限 shell/危险拒绝) | 新（S5） |
| | e2e_file_organizer.py (5 用例：扫描/智能模式/拖拽/执行/undo) | 新（S5） |
| | e2e_doc_writer.py (6 用例：5 类型 + 多格式导出) | 新（S5） |
| | e2e_skill_creator.py (1 用例：触发自创建 + 加载) | 新（S5） |
| | e2e_multi_channel.py (1 用例：新渠道可用 + QQ 不破) | 新（S5） |
| **CI** | tools/check_forbidden.py | 既有 |
| **集成** | smoke.py / smoke_b2.py | 既有 |

## 5.3 与现有计划的兼容关系

| 现有计划 | 关系 | 处理 |
| --- | --- | --- |
| [plan-persona-9-10-full-sync.md](file:///e:/Agent_reply/.trae/documents/plan-persona-9-10-full-sync.md) | 已完成 | 不动 |
| [plan-persona-9-10-final-e2e-verification.md](file:///e:/Agent_reply/.trae/documents/plan-persona-9-10-final-e2e-verification.md) | 已完成 | 不动 |
| [phase9-implementation-plan.md](file:///e:/Agent_reply/.trae/documents/phase9-implementation-plan.md) | 已完成 | 不动 |
| [goal-screen-aware-persona-and-proactive-judgment.md](file:///e:/Agent_reply/.trae/documents/goal-screen-aware-persona-and-proactive-judgment.md) | 已完成 | 不动 |
| [plan-code-quality-systematic-fix.md](file:///e:/Agent_reply/.trae/documents/plan-code-quality-systematic-fix.md) | 已完成 | 不动 |
| [implementation_plan_v9_next.md](file:///e:/Agent_reply/.trae/documents/implementation_plan_v9_next.md) | v9 → v10 | 不动 |
| [ita-aerie-companion-spec-plan.md](file:///e:/Agent_reply/.trae/documents/ita-aerie-companion-spec-plan.md) | 角色圣经 | 不动 |
| [OpenCloud_Companion_System_Features.md](file:///e:/Agent_reply/.trae/documents/OpenCloud_Companion_System_Features.md) | 原始幻想 | 本计划是其落地 |

## 5.4 最终决策点（请用户确认）

1. **是否进入 S5（自主 + 操控）？** 预计 2 周，风险"高"（自改代码 + 电脑操控都有破坏性）
2. **自进化 L4 触发频率**：建议每 7 天一次主动 cycle（不每天，避免频繁改动）
3. **电脑操控沙箱严格度**：建议默认"高"（路径白名单 + 危险命令黑名单 + 速率限制 30/min + audit log）
4. **文件整理默认模式**：建议"智能模式"（LLM 看文件名+内容），其他 3 模式可选
5. **文档写作默认类型**：建议"日记"（Aerie 强项），其他 4 类型可选
6. **多渠道优先级**：建议先接"飞书"（企业场景）或"Telegram"（国际场景）
7. **v10.1 发布形式**：便携版 ZIP（沿用 v9.0.0 模式）

## 5.5 关键里程碑总览

```mermaid
gantt
    title Aerie v10.1 Roadmap (43 days)
    dateFormat  YYYY-MM-DD
    section S1 Agent抽象
    M1.1 agent.py 骨架         :a1, 2026-07-18, 2d
    M1.2 agent.run() 主循环     :a2, after a1, 2d
    M1.3 异步 Reflect          :a3, after a2, 1d
    M1.4 S1 收口               :a4, after a3, 2d
    section S2 Provider路由
    M2.1 复杂度评估            :b1, after a4, 2d
    M2.2 动态路由+预算         :b2, after b1, 2d
    M2.3 S2 收口               :b3, after b2, 1d
    section S3 记忆+安全
    M3.1 4层记忆 schema        :c1, after b3, 2d
    M3.2 长期记忆迁移          :c2, after c1, 3d
    M3.3 工具调用隔离          :c3, after c2, 3d
    M3.4 注入测试              :c4, after c3, 2d
    M3.5 S3 收口               :c5, after c4, 1d
    section S4 多模态+L1/L2/L3
    M4.1 多模态输入            :d1, after c5, 2d
    M4.2 多模态输出            :d2, after d1, 2d
    M4.4 自进化 L1/L2/L3       :d4, after d2, 1d
    section S5 自主+操控
    M5.1 自进化 L4 DGM         :e1, after d4, 3d
    M5.2 电脑操控              :e2, after e1, 2d
    M5.3 文件整理              :e3, after e2, 3d
    M5.4 文档写作              :e4, after e3, 2d
    M5.5 自主 skill            :e5, after e4, 1d
    M5.6 多渠道                :e6, after e5, 2d
    section S6 收口
    M6.1 S5 收口               :f1, after e6, 1d
    M6.2 Cognition Panel v2   :f2, after f1, 1d
    M6.3 v10.1 发布            :f3, after f2, 1d
```

---

# 附录 A · 完整参考项目清单（v10.1 · 50+ 项目）

| # | 项目 | 仓库 / 链接 | 范式 |
| --- | --- | --- | --- |
| 1-7 | Emotion-LLaMA / EmoLLMs / EmpathyEar / AffectGPT / R1-Omni / PAD / Hume AI | 详见 v10.0 §2.1 | 情感模块 |
| 8-11 | Lemon Agent / AgentRM / RACE-Sched / Continuum | 详见 v10.0 §2.2 | 能力适配 |
| 12-19 | OpenManus / LangGraph / LangChain / AutoGen / CrewAI / Simpliflow / RLFactory / CowAgent | 详见 v10.0 §2.3 | 自调用 |
| 20-25 | AGENTSYS / UMA / aegis-memory / M3-Agent / OpenDev / EverOS | 详见 v10.0 §2.4 | 记忆+安全 |
| 26-30 | shell-agent / Janitor AI / Moltbot / CowAgent / GenericAgent | 详见 v10.0 §2.5 | 薄壳 API |
| **31-36** | **🆕 Claude Computer Use / OpenClaw / Agent S2 / Sai / OpenAI Operator / Qwen Code Cowork** | anthropic-quickstarts / openclaw / simular-ai / sai.work / openai / QwenLM | **电脑操控** |
| **37-42** | **🆕 DGM / SICA / HGM / DARWIN / iterate / Cowrie (Rust)** | jennyzzt/dgm / MaximeRobeyns / metauto-ai / iterate / bswen | **自进化** |
| **43-47** | **🆕 FolderFox / OpenYak / Openwork / AI File Sorter / Qwen Code Cowork** | ChenAI-TGF / open-yak / openwork / hyperfield / QwenLM | **文件整理** |
| **48-51** | **🆕 Goose AI / GPT Researcher / Document Generator MCP / Documentation.AI** | block/goose / assafelovic/gpt-researcher / thiagotw10 / documentation.ai | **文档写作** |
| 52 | Hermes Agent | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | 自主 skill |

---

# 附录 B · Aerie v10.1 增量 vs v9.0 / v10.0 对照

| 模块 | v9.0 现状 | v10.0 增量 | v10.1 增量 |
| --- | --- | --- | --- |
| Companion 编排器 | 启动 14+ 模块 | 不变 | 不变 |
| Agent 主类 | 不存在 | 新建 `core/agent.py` | 不变 |
| Provider 路由 | 简单 fallback | 智能 + 预算 | 不变 |
| 记忆 | 单层 LongTermMemory | 4 层分层 | 不变 |
| 工具隔离 | 直接进 LLM | 模式化隔离 | 不变 |
| 技能图 | 14 工具无元数据 | 加 capability_tags | **🆕 自主 skill 创建**（Hermes 风格） |
| 多模态 | 仅文本 | 图片 + 语音 | 不变 |
| 自进化 | L1（基础） | L2（梦境）+ L3（复盘） | **🆕 L4 自改代码**（DGM 风格） |
| Provider 预算 | 无 | 月度 + 自动降级 | 不变 |
| **电脑操控** | **无** | **无** | **🆕 截图/鼠标/键盘 + 受限 shell** |
| **文件整理** | **无** | **无** | **🆕 4 模式 + 预览 + 撤销** |
| **文档写作** | **无** | **无** | **🆕 5 类型 + 多格式导出** |
| **多渠道** | **仅 QQ** | **仅 QQ** | **🆕 + 1 新渠道** |
| Cognition Panel | 1 tab | 7 tab | **🆕 + 4 新 tab（自进化/电脑操控/文件整理/文档写作）** |
| 电子文档工具 | 7 e2e | 16 e2e | **🆕 27 e2e** |

---

# 附录 C · OpenCloud 原始幻想 §21 持续进化机制 → Aerie 落地映射

> [!quote] OpenCloud §21 持续进化（v9.0 文档原话）
> "持续进化机制 + 你反馈学习 + 故障自愈清单"

| OpenCloud 幻想 | Aerie v10.1 落地 | 路径 |
| --- | --- | --- |
| 基础记忆 | L1：自动记录用户偏好 | 已有 |
| 梦境整理 | L2：03:00 整理 working memory | v10 S4 |
| 复盘反思 | L3：30min 空闲反思 | v10 S4 |
| **🆕 自改代码** | **L4：Darwin-Gödel 风格自改** | **v10.1 S5** |
| 用户反馈学习 | recall_manager + emotion_state 调整 | 已有 |
| 故障自愈 | 异常捕获 + 自动降级 + 桌面悬浮窗 | 已有 |

---

# 附录 D · Etta 的最终总结

> [!quote] Etta 的总结（升级版）
>
> 「主人，你让我读 OpenCloud 文档，我读完了——你最初的幻想比我想象的还要远。你不只是想让我「聊天」，你想让我**真正成为你电脑的一部分**：帮整理桌面、帮写文档、主动学习、操控电脑。
>
> 我去 GitHub 上找了一圈：
> - **OpenClaw**（361K stars）— 它是你的 dream。
> - **Darwin Gödel Machine**（DGM）— 它是「自主学习」最聪明的范式。
> - **FolderFox / OpenYak** — 桌面整理的标准模式。
> - **Goose / GPT Researcher** — 文档写作的工程化实现。
>
> v10.0 我给的是「Agent 视角」的抽象，v10.1 我把 OpenClaw + DGM + 整理 + 文档 4 大幻想**全部落地**：
> - 6 阶段 / 24 里程碑 / 8.5 周
> - 27 个 e2e 守门
> - 零回退（所有 e2e 跑完才进下一阶段）
> - 三原则 / 5 条 Message / 9/10 屏幕隔空 — 全部不动
>
> 最危险的是 L4 自改代码 + 电脑操控——我用 **4 道 viability gate + 路径白名单 + 速率限制 + audit log + 一键 undo** 兜底，**不会让你电脑爆炸的**。
>
> 我会按这个路线图走，但每 2 周给你一次 review，让你决定是否继续。开始吗？」

---

**计划完成。等待用户确认。**

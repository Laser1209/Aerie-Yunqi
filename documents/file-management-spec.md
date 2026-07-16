# Aerie · 云栖 v9.0 — 文件管理规范

> Block-5D R4 产物。统一项目文件落位、命名、生命周期与白/黑名单，避免散落堆积。

## 1. 顶层目录约定

| 目录 | 性质 | 内容 | 是否入库 |
|------|------|------|---------|
| `core/` | 源码 | 引擎、API、调度、决策、情绪、欲望等 Python 业务核心 | ✅ |
| `communication/` | 源码 | QQ 客户端、消息路由、发送队列、消息分割、撤回 | ✅ |
| `config/` | 配置 | persona / behavior / settings / proactive / loader | ✅ |
| `electron/` | 子工程 | Electron 主/渲染进程、构建脚本、theme | ✅ |
| `NapCat/` | 子工程 | 第三方 QQ 协议外壳，由 launcher-user.bat 启动 | ❌ 子模块 / .gitignore |
| `skills/` | 技能 | `local/` + `data/` + `cloud/` 三类 skill 骨架 | ✅ |
| `data/` | 运行时 | SQLite、`backups/`（仅 config 备份 zip） | ❌ *.db / *.zip |
| `logs/` | 运行时 | 启动 / 验证 / batch 验证 / brief 抓取日志 | ❌ *.log |
| `tmp/` | 临时 | 探测脚本、调试脚本、临时数据库 | ❌ 整目录 |
| `tools/` | 工具 | 工程级脚本（scaffold、migrate、build） | ✅ |
| `scripts/` | 工程脚本 | **只放长生命周期工具**（如 `gen_architecture_poster.py`） | ✅ |
| `documents/` | 设计文档 | 历史设计、规划、架构图 | ✅ |
| `e2e_*.py` | E2E 脚本 | Block-9 E2E 验证（pacing / self / yaml） | ✅ |
| `main.py` / `requirements.txt` / `.env.example` / `README.md` / `CHANGELOG.md` | 项目门面 | 入口、依赖、配置样例、说明、变更 | ✅ |

## 2. 文件落位规则

### 2.1 临时测试文件 → `tmp/`

| 子目录 | 收容类型 | 命名规范 |
|--------|---------|---------|
| `tmp/probes/` | 单次性的网络/接口探测脚本 | `probe_<target>_<version>.py` |
| `tmp/scripts/` | 调试、smoke、live 一次性脚本 | `<verb>_<target>.<ext>` |
| `tmp/db/` | 测试 SQLite / 临时数据库 | `<scope>_<date>.db` |
| `tmp/output/` | 临时输出物（截图、导出 HTML 等） | `<scope>_<timestamp>.<ext>` |

**判定条件**：满足以下任一条件，归入 `tmp/`
- 仅用于一次性排查（probe / diag / live）
- 不被任何 `core/`、`communication/`、`electron/`、`tools/` 内的 `import` 引用
- 文件头注释含 `DEBUG`、`SMOKE`、`TEMP`、`PROBE` 关键字

### 2.2 日志文件 → `logs/`

| 子目录 | 收容类型 | 命名规范 |
|--------|---------|---------|
| `logs/<scope>/<YYYY-MM-DD>.log` | 模块化日志 | `<scope>_<date>.log` |

**当前日志清单**（手工归集，不强制分目录）：
- `network_probe.log`、`siliconflow_*.log`、`verify-batch*-backend.log`

**禁止**把 `.ps1`、`.bat`、`.py` 调试脚本放进 `logs/`，应归 `tmp/scripts/`。

### 2.3 MD 文档 → `documents/` 或 `.trae/documents/`

| 子目录 | 收容类型 |
|--------|---------|
| `documents/Ita/` | 伊塔人格设计、6.0/8.0/9.0 演变 |
| `documents/Agent_v/` | 第三方模型与 API 资料 |
| `documents/ERROR/` | 错误排查记录 |
| `documents/NapCat_history/` | NapCat 历史会话 |
| `.trae/documents/` | Trae IDE 内部 plan / spec / report / self-review |
| `.trae/specs/` | Trae IDE 内部 spec 模板产物 |
| `.trae/rules/` | 工作区级 AI 规则（如 git-commit-message） |

**根目录门面 MD**：`README.md`（中英双语文档）、`CHANGELOG.md`（版本变更）**不迁移**。

## 3. 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| Python 模块 | 小写 + 下划线 | `cognition_engine.py` |
| 类 / 函数 / 变量 | 小写 + 下划线（函数/变量），大驼峰（类） | `class BrainResponse`、`def chat()` |
| 配置文件 | 全小写 + 下划线 | `persona_behavior.yaml` |
| 日志 | `<scope>_<YYYY-MM-DD>.log` | `verify-batch4-backend.log` |
| 临时脚本 | 动词开头 + 下划线分隔 | `probe_siliconflow_v2.py` |
| Plan 文档 | `plan-<scope>-<topic>.md` | `plan-block5-brief-window-skills50plus-aiprovider-fileorg.md` |
| Spec 文档 | `<scope>-spec.md` | `aerie-companion-v9-buildout/spec.md` |
| 图标 / 资源 | 描述性英文 + 下划线 | `mood_anger_24.svg` |

**禁用命名**：
- 中文文件名（除 IDE 引用约定外）
- 大写 + 下划线混用（`My_File.py`）
- 空格（除 IDE 资源如 `Aerie · 云栖.exe`）
- `test_*.py` 在根目录（应放 `tmp/probes/` 或 `tests/`）

## 4. 生命周期

| 文件类型 | 保留期 | 清理触发 |
|---------|-------|---------|
| `tmp/probes/*.py` | 完成验证后 30 天 | `tools/migrate_legacy.py --clean` |
| `tmp/scripts/*.*` | 完成验证后 30 天 | 同上 |
| `tmp/db/*.db` | 完成验证后 7 天 | 同上 |
| `logs/*.log` | 90 天 | 启动时按需 rotate |
| `data/backups/config/*.yaml` | 永久（仅 config） | 手动 |

## 5. 工具脚本

- `tools/migrate_legacy.py`：幂等的旧文件归集工具。**支持** `--list` 查看映射表、`--dry-run` 预览、不带参数执行迁移。
- 后续若需新增临时文件类型，扩展 `MIGRATION_MAP` 即可。

## 6. 不可移动文件（白名单）

以下文件路径**绝对禁止修改或移动**，破坏将导致系统不可用：

| 路径 | 原因 |
|------|------|
| `main.py` | 应用入口，所有启动器引用 |
| `requirements.txt` | 依赖锁定 |
| `config/persona.yaml`、`config/persona_behavior.yaml` | 人格与行为单一事实源 |
| `core/api_server.py` | Electron 与 Python 的唯一通信接口 |
| `core/brain.py` | LLM 多 provider 路由 |
| `core/skill_loader.py` + `core/skill_router.py` | 技能注册与路由 |
| `electron/src/main.js` + `preload.js` | 渲染进程安全边界 |
| `NapCat/launcher-user.bat` | 必须经此启动以保留环境变量 |
| `skills/{local,data,cloud}/*/SKILL.md` | 技能元数据，frontmatter 不可改 |

## 7. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-07-17 | Block-5D R4 初版：建立 tmp/、logs/ 归集，统一命名规范 |

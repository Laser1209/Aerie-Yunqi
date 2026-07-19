# 项目启动速度排查与优化计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用执行计划能力按步骤实施。本计划处于 Plan Mode 产物，实施前不得修改除本计划外的项目文件。

**Goal:** 找出 Aerie · 云栖开发启动慢的主要原因，并给出最小、可验证的优化路径。

**Architecture:** 当前启动链路是 `start-dev.bat` → `electron/npm start` → Electron 主进程 → Python `main.py` → `Companion.start()` → FastAPI `/api/health`。最核心的问题是后端 API 在 QQ readiness 等待之后才启动，且配置缺省会等待 30 秒；其他耗时来自依赖检查、全量 Python 进程清理、Electron health 轮询、模块同步初始化与 skill 动态导入。

**Tech Stack:** Windows Batch、Electron/Node.js、Python asyncio、FastAPI/uvicorn、QQ/NapCat WebSocket、YAML 配置。

---

## Summary

启动慢最可疑的 P0 根因是：

1. [main.py](file:///e:/Agent_reply/main.py#L91-L145) 先执行 `await companion.start()`，之后才启动 FastAPI。
2. [companion.py](file:///e:/Agent_reply/core/companion.py#L238-L245) 在 `Companion.start()` 中等待 QQ ready，默认 `startup_wait_timeout=30.0`。
3. [settings.yaml](file:///e:/Agent_reply/config/settings.yaml#L1-L3) 当前没有 `qq.startup_wait_timeout`，因此走默认 30 秒。
4. [qq_client.py](file:///e:/Agent_reply/communication/qq_client.py#L177-L185) 只等待 NapCat 端口，不会自动启动 NapCat。
5. UI 需要后端 ready 才更顺畅，但后端 API 又等 QQ 超时后才 ready，形成“启动卡住感”。

建议优先实施“让 API 先启动、QQ 后台就绪”的改动；如果只想做最小配置修复，则先把 `qq.startup_wait_timeout` 调低。

---

## Current State Analysis

### 1. Batch 启动脚本

文件：[start-dev.bat](file:///e:/Agent_reply/start-dev.bat#L9-L26)

当前行为：

- [start-dev.bat](file:///e:/Agent_reply/start-dev.bat#L10-L15) 每次启动都会拉起 Python import 检查依赖；任一依赖缺失就执行 `pip install -r requirements.txt --quiet`。
- [start-dev.bat](file:///e:/Agent_reply/start-dev.bat#L17-L21) 无差别强杀所有 `python.exe` / `pythonw.exe`，然后固定等待 1 秒。
- [start-dev.bat](file:///e:/Agent_reply/start-dev.bat#L23-L26) 进入 Electron 并执行 `npm start`。

风险：

- 如果依赖检查失败，会触发较慢的 pip 安装。
- 无差别杀 Python 可能影响其他进程，并造成端口/文件锁释放延迟。

### 2. Electron 启动后端

文件：[main.js](file:///e:/Agent_reply/electron/src/main.js#L46-L112)

当前行为：

- [main.js](file:///e:/Agent_reply/electron/src/main.js#L46-L60) 启动前先探测 `http://127.0.0.1:7890/api/health`。
- [main.js](file:///e:/Agent_reply/electron/src/main.js#L150-L166) health check 超时为 2 秒。
- [main.js](file:///e:/Agent_reply/electron/src/main.js#L62-L71) 若无可用后端，spawn `.venv\Scripts\python.exe main.py`。
- [main.js](file:///e:/Agent_reply/electron/src/main.js#L101-L112) 每 1 秒轮询后端 ready。

风险：

- 旧端口半开时，第一次 health check 可能消耗接近 2 秒。
- ready 检测粒度是 1 秒，可能造成 0-1 秒感知延迟。

### 3. Python 后端入口

文件：[main.py](file:///e:/Agent_reply/main.py#L28-L145)

当前行为：

- [main.py](file:///e:/Agent_reply/main.py#L28-L41) 启动时执行 `git rev-parse --short HEAD`，最多阻塞 2 秒。
- [main.py](file:///e:/Agent_reply/main.py#L82-L84) 导入配置、Companion、API server。
- [main.py](file:///e:/Agent_reply/main.py#L86-L92) 加载 settings，构造 `Companion`，等待 `companion.start()` 完成。
- [main.py](file:///e:/Agent_reply/main.py#L94-L140) 启动配置热重载。
- [main.py](file:///e:/Agent_reply/main.py#L144-L145) 最后才启动 API 并打印 READY。

风险：

- 任何 Companion 初始化/QQ 等待都会推迟 `/api/health` 可用。

### 4. Companion 初始化与 QQ 等待

文件：[companion.py](file:///e:/Agent_reply/core/companion.py#L45-L279)

当前行为：

- [companion.py](file:///e:/Agent_reply/core/companion.py#L53-L104) 同步构造数据库、Brain、Emotion、Memory、Knowledge、Cognition、ComputerController、ToolRegistry，并注册所有工具。
- [companion.py](file:///e:/Agent_reply/core/companion.py#L121-L164) 初始化 QQ、Router、SendQueue、Pipeline、PushScheduler。
- [companion.py](file:///e:/Agent_reply/core/companion.py#L201-L235) 启动 QQ 后台连接、情绪 tick、DesireEngine、SkillLoader、AsyncTaskManager。
- [companion.py](file:///e:/Agent_reply/core/companion.py#L238-L245) 等待 QQ ready，默认 30 秒。
- [companion.py](file:///e:/Agent_reply/core/companion.py#L265-L279) 超时后才降级启动。

风险：

- NapCat 未启动或 QQ 未登录时，API server 会被 QQ 等待阻塞。
- SkillLoader 会动态 import 每个 skill 的 `run.py`，可能拖慢启动。

### 5. API server 模块加载与 health

文件：[api_server.py](file:///e:/Agent_reply/core/api_server.py#L36-L89)、[api_server.py](file:///e:/Agent_reply/core/api_server.py#L128-L229)、[api_server.py](file:///e:/Agent_reply/core/api_server.py#L3178-L3185)

当前行为：

- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L36-L60) 模块加载时导入较多模块。
- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L80-L89) 模块级创建 `Database()`、`FileOrganizer()`、`DocWriter()`、`CalendarManager()`、PersonaManager。
- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L128-L185) `/api/health` 返回 QQ、push scheduler 等状态。
- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L188-L229) 每次 health 都扫描 `core/`、`config/`、`main.py` 的 mtime。
- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L3178-L3185) uvicorn server 创建后固定等待 0.5 秒。

风险：

- API 模块 import 和模块级对象创建会叠加启动耗时。
- health 被 Electron/Renderer 轮询时会频繁做文件 stat。

### 6. 依赖体量

文件：[requirements.txt](file:///e:/Agent_reply/requirements.txt#L25-L94)

当前依赖包括：

- [requirements.txt](file:///e:/Agent_reply/requirements.txt#L25-L34) FastAPI、uvicorn、aiohttp、websockets、httpx、requests。
- [requirements.txt](file:///e:/Agent_reply/requirements.txt#L63-L70) `markitdown[all]`、`weasyprint` 等较重依赖。
- [requirements.txt](file:///e:/Agent_reply/requirements.txt#L92-L94) Windows 自动化依赖。

风险：

- 如果脚本触发 pip install，依赖解析/安装会明显拖慢。

---

## Proposed Changes

### 方案 A：最小风险配置优化

适合先快速验证 P0 是否成立。

#### 修改文件：`e:\Agent_reply\config\settings.yaml`

**What:** 增加 QQ 启动等待配置。

**Why:** 当前没有 `qq.startup_wait_timeout`，会在 [companion.py](file:///e:/Agent_reply/core/companion.py#L238-L245) 走默认 30 秒。把它调低可以立即减少 NapCat 未启动时的阻塞。

**How:** 保留现有 `verify_batch4`，追加：

```yaml
qq:
  startup_wait_timeout: 1.0
  push_pause_when_offline: true
```

**影响：**

- 后端会在 QQ 未就绪时更快进入 degraded 模式。
- QQ 后续登录仍可通过 [companion.py](file:///e:/Agent_reply/core/companion.py#L281-L309) 的状态变化回调恢复 push scheduler 和触发 boot greeting。

---

### 方案 B：结构性优化，API 先 ready，QQ 后台等

适合从根上解决“UI 等 QQ 超时”的架构问题。

#### 修改文件：`e:\Agent_reply\main.py`

**What:** 调整启动顺序，让 API server 在 Companion 基础初始化后更早启动，`companion.start()` 作为后台任务运行；停止时等待并清理。

**Why:** 当前 [main.py](file:///e:/Agent_reply/main.py#L91-L145) 等 `companion.start()` 完成后才启动 API，导致 QQ/NapCat 阻塞整个后端 ready。API 先启动后，Electron 能快速进入 degraded/initializing 状态，UI 可用于启动 NapCat。

**How:** 实施时保持最小改动：

1. `companion = Companion(settings=settings)` 保持不变。
2. 在 `await companion.start()` 之前启动 hot-reloader 或 API 的顺序需要谨慎：hot-reloader 依赖 companion，可保留在 companion 构造之后。
3. 将：

```python
await companion.start()
```

替换为：

```python
companion_start_task = asyncio.create_task(companion.start())
```

4. 确保 `finally` 中先取消/等待 `companion_start_task`，再执行 `await companion.stop()` 和 `await runner.cleanup()`。
5. `/api/health` 在 `companion.start()` 尚未完成时应返回 degraded，而不是报错。当前 [api_server.py](file:///e:/Agent_reply/core/api_server.py#L145-L152) 直接访问 `comp.push_scheduler`，而 `push_scheduler` 已在 `Companion.__init__()` 完成，因此可用。

**注意：** 如果实施方案 B，仍建议保留方案 A 的 `startup_wait_timeout` 作为兜底，避免后台任务长时间处于启动等待。

---

### 方案 C：启动脚本减少无谓耗时和副作用

#### 修改文件：`e:\Agent_reply\start-dev.bat`

**What:** 不再无差别强杀所有 Python；只针对项目端口或项目路径进程清理。依赖检查保留，但输出更明确。

**Why:** 当前 [start-dev.bat](file:///e:/Agent_reply/start-dev.bat#L17-L21) 会杀掉所有 Python 进程并固定等待 1 秒，既慢又有副作用。

**How:** 分两步执行：

1. 本轮只将日志改得更明确，避免误以为卡死：

```bat
echo [1/3] Checking Python dependencies...
```

保留。

2. 后续再考虑用更精准方式清理端口 `7890` 的占用进程；不要在本轮引入复杂 PowerShell，避免过度改动。

**本计划建议：** 本次先不改 `start-dev.bat` 的清理逻辑，只把启动慢的 P0 解决掉；因为直接改进程清理有误杀/漏杀风险，需要单独验证。

---

### 方案 D：Electron health check 轻量优化

#### 修改文件：`e:\Agent_reply\electron\src\main.js`

**What:** 将 health check 超时从 2000ms 降低到 500ms，并把轮询间隔从 1000ms 降到 500ms。

**Why:** [main.js](file:///e:/Agent_reply/electron/src/main.js#L150-L166) 的初始探测最多等 2 秒；[main.js](file:///e:/Agent_reply/electron/src/main.js#L101-L112) ready 轮询粒度 1 秒。

**How:**

- `req.setTimeout(2000, ...)` 改为 `req.setTimeout(500, ...)`。
- `setInterval(..., 1000)` 改为 `setInterval(..., 500)`。

**本计划建议：** 放在第二阶段执行。先验证 P0，否则 Electron 优化只能减少 1-3 秒，不能解决 30 秒等待。

---

### 方案 E：health stale scan 缓存

#### 修改文件：`e:\Agent_reply\core\api_server.py`

**What:** 给 `_check_stale_code()` 增加 2-5 秒缓存。

**Why:** [api_server.py](file:///e:/Agent_reply/core/api_server.py#L188-L229) 每次 health 都扫描源码 mtime，Electron/Renderer 会频繁轮询。

**How:** 增加模块级缓存变量：

```python
_STALE_CACHE = {"at": 0.0, "value": {"stale": False, "modified": []}}
```

在 `_check_stale_code()` 开头判断 `time.time() - _STALE_CACHE["at"] < 2.0` 时直接返回缓存。

**本计划建议：** 放在第二阶段执行。它更偏向降低 ready 后开销，不是首要启动瓶颈。

---

## Assumptions & Decisions

1. 优先级最高的是 QQ ready 默认等待 30 秒，因为它直接阻塞 [main.py](file:///e:/Agent_reply/main.py#L144-L145) 的 API ready。
2. 不把 `start-dev.bat` 的依赖检查删除；依赖缺失时自动安装虽然慢，但对开发启动有保护作用。
3. 不立即重构 `Companion.__init__()` 的重模块初始化；涉及面大，容易引入启动状态不一致。
4. 不立即懒加载所有 skill/tool；需要逐个确认顶层 import 副作用，另开计划更安全。
5. 第一阶段建议只做方案 A；如果用户确认要进一步优化，再做方案 B、D、E。
6. 若目标是“尽快打开 UI 并能从 UI 启动 NapCat”，方案 B 是最终推荐。

---

## Verification Steps

### 验证 1：确认是否仍等待 30 秒

启动项目后观察日志中这些行的间隔：

- `[Startup] Waiting for QQ readiness (timeout=...)`
- `[Startup] QQ not ready after ...s`
- `[READY] Aerie ready at http://127.0.0.1:7890`

期望：

- 方案 A 后，timeout 应显示 `1.0s` 左右。
- 方案 B 后，`[READY]` 不应再等待 QQ timeout 后才出现。

### 验证 2：确认 Electron 不再长时间显示后端未就绪

运行：

```powershell
& "e:\Agent_reply\start-dev.bat"
```

观察：

- 不应出现 `锘緻echo off`。
- 若 NapCat 未启动，后端应较快进入 degraded，而不是长时间无响应。

### 验证 3：确认没有每次触发 pip install

启动日志中不应出现：

```text
Installing missing dependencies...
```

如果出现，说明 [start-dev.bat](file:///e:/Agent_reply/start-dev.bat#L11-L15) 的 import 检查有依赖失败，需要单独定位缺失包。

### 验证 4：确认 QQ 后续登录还能恢复

在 UI 中启动 NapCat 并完成 QQ 登录后，观察：

- [qq_client.py](file:///e:/Agent_reply/communication/qq_client.py#L277-L285) 应记录 lifecycle connect。
- [companion.py](file:///e:/Agent_reply/core/companion.py#L290-L309) 应恢复 push scheduler。
- `/api/health` 中 `components.qq.logged_in` 应变为 `true`。

### 验证 5：回归检查

检查以下功能仍正常：

- Electron 窗口能打开。
- `/api/health` 返回 `healthy` 或 `degraded`。
- 聊天发送接口不因 QQ offline 崩溃。
- NapCat 状态页面能打开。
- 关闭 Electron 时 Python 后端能退出。

---

## Recommended Execution Order

1. 先实施方案 A：修改 [settings.yaml](file:///e:/Agent_reply/config/settings.yaml) 添加 `qq.startup_wait_timeout: 1.0`。
2. 启动验证是否从 30 秒缩短到约 1 秒。
3. 如果仍慢，再实施方案 B：调整 [main.py](file:///e:/Agent_reply/main.py) 启动顺序，让 API 先 ready。
4. 如 UI ready 感仍慢，再实施方案 D：降低 Electron health 初始超时和轮询间隔。
5. 如 ready 后轮询开销明显，再实施方案 E：缓存 `_check_stale_code()`。

---

## Final Recommendation

本项目启动慢的核心不是 `.bat` 编码问题，而是后端启动顺序和 QQ/NapCat 等待策略：API server 被 QQ readiness 阻塞，而 NapCat 又设计成需要 UI 手动启动。最小修复是给 [settings.yaml](file:///e:/Agent_reply/config/settings.yaml) 添加较短的 `qq.startup_wait_timeout`；更完整修复是让 [main.py](file:///e:/Agent_reply/main.py) 先启动 API，再让 QQ 在后台进入 ready。

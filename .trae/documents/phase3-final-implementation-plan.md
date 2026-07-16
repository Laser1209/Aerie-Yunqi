# Aerie · 云栖 — 第三阶段最终实现计划

> **起点**：Phase 2 Batch 1-4 已全部完成（129 tests / 0 failures，核心逻辑覆盖率 78%-100%）
> **本文档**：Phase 3 收尾 — 5 个子系统并行推进 + 多 Provider 升级 + 系统整合优化

---

## 一、当前状态速查

### 已完成模块

| 模块                  | 文件                                | 关键能力                                                                        |
| --------------------- | ----------------------------------- | ------------------------------------------------------------------------------- |
| **Ita 灵魂**    | `core/context_builder.py`         | 四层分层 system prompt（L1 核心身份 / L2 关系深度 / L3 情绪状态 / L4 语言铁律） |
| **PAD 情绪**    | `core/emotion_engine.py`          | 五类基本情绪 + EMA 平滑 + 爆发模式覆盖                                          |
| **累积阈值**    | `core/emotion_threshold.py`       | 4 槽位（忍耐/不安/渴望/温柔透支）+ 爆发 + 角色磨损 + 每日衰减                   |
| **Pipeline**    | `core/pipeline.py`                | 10 阶段管线，注入 emotion_info + eruption_info                                  |
| **Companion**   | `core/companion.py`               | 午夜每日衰减调度 + 阈值引擎单例                                                 |
| **多 Provider** | `core/brain.py`                   | DeepSeek 主 → SiliconFlow 备 → Qwen 三（本次新增）                            |
| **Token 追踪**  | `core/token_tracker.py`           | 日/周/月聚合 + by_provider 统计                                                 |
| **API Server**  | `core/api_server.py`              | 14 端点，含 `/api/emotion/thresholds` + `/api/stats/tokens`                 |
| **Emotion Tab** | `emotion-dashboard.js`            | PAD 环形图 + 槽位进度条 + 爆发横幅 + 3s 轮询                                    |
| **测试套件**    | `tests/` (6 文件)                 | 129 passed / 0 failed / 0.79s                                                   |
| **撤回管理**    | `communication/recall_manager.py` | 消息撤回记录与处理                                                              |

### 缺失模块（本次实现）

| # | 功能                         | 对应文档章节                              | 缺失分析                                                               |
| - | ---------------------------- | ----------------------------------------- | ---------------------------------------------------------------------- |
| 1 | **Cron 主动推送**      | System_Features §4.4-4.9, proactive.yaml | YAML 有 9 个场景但无调度器、无 PushPolicy、无 Brain.generate_push      |
| 2 | **5 色系主题**         | System_Features §15                      | `settings.yaml` 有 5 个名称但无 CSS 文件、无 ThemeManager、无切换 UI |
| 3 | **系统设置 Tab**       | System_Features §7.6-7.7                 | 无设置页面 HTML/JS、无 IPC 通道、无后端保存 API                        |
| 4 | **纪念日 Tab**         | System_Features §7.5                     | 无 anniversary 表、无 CRUD API、无前端 UI                              |
| 5 | **后台数据 Tab**       | System_Features §7.8                     | 无数据浏览前端、无统计查询 API                                         |
| 6 | **UI 图像资源修复**    | 用户原始需求 #3a                          | 需全面检查 SVG/PNG 引用路径及完整性                                    |
| 7 | **逻辑链路分析报告**   | 用户原始需求 #3c                          | 需生成各页面功能定位、交互关系、实现步骤文档                           |
| 8 | **Qwen 三级 Provider** | 用户本次确认                              | brain.py 新增第三级 fallback                                           |
| 9 | **系统整合优化**       | 用户原始需求 #4                           | API 响应≤200ms / 设计规范 / 可用性测试                                |

---

## 二、决策记录

| 决策点          | 决策结果                                               | 决策依据                                   |
| --------------- | ------------------------------------------------------ | ------------------------------------------ |
| 子系统推进方式  | **全部并行开发**                                 | 用户明确选择                               |
| 纪念日管理方式  | **数据库 CRUD**（新增 `anniversary` 表 + API） | 用户明确选择                               |
| 第三级 Provider | **Qwen（通义千问）**                             | 用户明确选择                               |
| 悬球窗口方案    | 悬浮球未出现，不知道是什么原因                         | 当前主窗口内嵌悬球而非独立窗口，功能不正常 |
| 主题实现方式    | CSS 变量文件 + localStorage                            | 与 System_Features §15.2 方案对齐         |

---

## 三、详细实现计划

---

### A1. Qwen 三级 Provider 升级（与 Brain 并行启动）

**目标**：`core/brain.py` 从 DeepSeek → SiliconFlow 两级 fallback 升级为 DeepSeek → SiliconFlow → Qwen 三级。

**实现文件**：`e:\Agent_reply\core\brain.py`

**改动方案**（参考现有 fallback 模式）：

```text
现有优先级链（第73行附近）：
  self._providers = [
    {"name": "deepseek", "url": ..., "key": ..., "model": "deepseek-chat", "priority": 1},
    {"name": "siliconflow", "url": ..., "key": ..., "model": "Qwen/Qwen2.5-32B-Instruct", "priority": 2},
  ]

新增第三级：
  {"name": "qwen", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
   "key": os.getenv("DASHSCOPE_API_KEY"), "model": "qwen-plus", "priority": 3}
```

**验证**：`python -c "from core.brain import Brain; b=Brain(); print(len(b._providers))"` → 输出 `3`

---

### A2. Cron 主动推送系统（CronScheduler + PushPolicy + Brain.generate_push）

**目标**：解析 `proactive.yaml` 的 9 个场景，按时自动给主人发 QQ 消息。

**新建文件**：

| 文件                                      | 说明                          |
| ----------------------------------------- | ----------------------------- |
| `e:\Agent_reply\core\push_scheduler.py` | CronScheduler + PushPolicy 类 |

**实现要点**：

1. `CronScheduler` 类：
   - `__init__` 接收 `proactive.yaml` scenes 配置
   - 用 `croniter` 库（pip install）解析每个场景的 `cron` 表达式
   - `asyncio` 循环：每个场景独立任务，计算下次触发时间，`await asyncio.sleep(until)`
   - 场景 `trigger`（非 cron）类型（idle_care/emotion_comfort）单独处理
   - 触发时调用 `_dispatch(scene, config)`
2. `PushPolicy` 类：
   - `can_push(scene) -> (bool, str)` — 按 proactive.yaml 规则检查
   - `record(scene)` — 更新日计数器
3. 集成到 `core/companion.py`:
   - `start()` 中初始化 `PushScheduler` 并启动后台任务
   - 提供 `check_idle(idle_seconds)` 方法供外部调用（idle_care 触发）
   - 提供 `check_threshold_break()` 方法（emotion_comfort 触发）

**修改文件**：

| 文件                  | 改动                                                                      |
| --------------------- | ------------------------------------------------------------------------- |
| `core/brain.py`     | 新增 `generate_push(template, mood, **kwargs)` 方法                     |
| `core/companion.py` | 新增 `_push_task` 管理 + `check_idle()` + `check_threshold_break()` |

**验证**：

```
python -c "from core.push_scheduler import PushScheduler; ..."
# 启动 backend，检查日志中是否出现 [PushScheduler] 初始化 9 场景
```

---

### A3. 5 色系主题系统

**目标**：5 套完整 CSS 主题 + 主题切换器 + 设置持久化入口。

**新建文件**：

| 文件                                                        | 说明                                                           |
| ----------------------------------------------------------- | -------------------------------------------------------------- |
| `electron/src/renderer/styles/themes/yita-pink.css`       | 伊塔粉 — 主色 `#FFB6C1`，辅色 `#FF69B4`，背景 `#FFF5F8` |
| `electron/src/renderer/styles/themes/midnight-purple.css` | 深夜紫 — 主色 `#6A0DAD`，辅色 `#9370DB`，背景 `#1A0033` |
| `electron/src/renderer/styles/themes/sakura-white.css`    | 樱白 — 主色 `#FFF0F5`，辅色 `#FFB7C5`，背景 `#FAFAFA`   |
| `electron/src/renderer/styles/themes/ocean-blue.css`      | 海蓝 — 主色 `#1E90FF`，辅色 `#87CEEB`，背景 `#F0F8FF`   |
| `electron/src/renderer/styles/themes/forest-green.css`    | 森绿 — 主色 `#228B22`，辅色 `#90EE90`，背景 `#F5FFF5`   |

**现有 CSS 变量重构**（`main.css`）：

当前 `main.css` 使用硬编码颜色。需要提取为 CSS 变量：

```css
:root {
  --primary: #FFB6C1;
  --primary-dark: #FF69B4;
  --primary-light: #FFF0F5;
  --bg: #FFF5F8;
  --bg-secondary: #FFFFFF;
  --text: #333333;
  --text-secondary: #999999;
  --border: #E8D5E0;
  --shadow: rgba(255, 105, 180, 0.12);
  --danger: #FF4444;
  --success: #4CAF50;
  --radius: 12px;
  --transition: 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
```

**新建文件**：

- `electron/src/renderer/js/theme-switcher.js` — `applyTheme(name)` / `getCurrentTheme()` / 监听设置变更

**修改文件**：

| 文件                                      | 改动                                    |
| ----------------------------------------- | --------------------------------------- |
| `electron/src/renderer/styles/main.css` | 颜色值全部替换为 `var(--xxx)`         |
| `electron/src/renderer/index.html`      | 新增 `<link id="theme-css">` 动态标签 |
| `electron/src/renderer/js/app.js`       | 初始化时调用 `applyTheme(saved)`      |

**验证**：

```
# 在 index.html 中手动切换主题 link href，页面颜色全部变化
# 设置 Tab 中选择主题 → localStorage 持久化 → 刷新后主题保持
```

---

### A4. 系统设置 Tab

**目标**：前端设置面板，可修改自启/主题/窗口/推送等配置，通过 IPC 调用后端 API 持久化。

**当前 `settings.yaml` 已有字段**：

```yaml
startup: {auto_start, start_minimized}
window: {main_width, main_height, chat_width, chat_height, ball_size, ball_margin, ball_opacity_idle, ball_opacity_active, ball_idle_seconds}
theme: {current}
http_api: {host, port}
```

**IPC 通道新增**（`main.js`）：

| 通道               | 方向                   | 说明             |
| ------------------ | ---------------------- | ---------------- |
| `settings:get`   | renderer→main→Python | 获取当前全部设置 |
| `settings:set`   | renderer→main→Python | 更新单项设置     |
| `settings:reset` | renderer→main→Python | 恢复默认设置     |

**API 端点新增**（`api_server.py`）：

| 端点                    | 方法 | 说明                     |
| ----------------------- | ---- | ------------------------ |
| `/api/settings`       | GET  | 返回当前全部设置         |
| `/api/settings`       | PUT  | 更新设置（支持部分更新） |
| `/api/settings/reset` | POST | 恢复默认设置             |

**新建文件**：

| 文件                                     | 说明                                   |
| ---------------------------------------- | -------------------------------------- |
| `electron/src/renderer/js/settings.js` | SettingsPanel 类 — 表单绑定/保存/重置 |

**修改文件**：

| 文件                                 | 改动                              |
| ------------------------------------ | --------------------------------- |
| `core/api_server.py`               | 新增 3 个 settings 端点           |
| `config/persona_loader.py`         | 新增 `save_settings(data)` 方法 |
| `electron/src/main.js`             | 新增 3 个 IPC handler             |
| `electron/src/preload.js`          | 暴露 `aerie.settings` 命名空间  |
| `electron/src/renderer/index.html` | 系统设置 Tab 内容区               |
| `electron/src/renderer/js/app.js`  | 注册 settings Tab 切换            |

**验证**：

```
# 通过 API curl PUT /api/settings → 检查 settings.yaml 写入 → 重启后生效
# API curl GET /api/settings → 返回完整 JSON，字段与前端表单一一对应
```

---

### A5. 纪念日 Tab（数据库 CRUD）

**目标**：新增 `anniversary` 表 + 完整 CRUD API + 前端管理界面。

**数据库新增表**（`database.py`）：

```sql
CREATE TABLE IF NOT EXISTS anniversary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,           -- '2025-07-16' 格式
    type TEXT DEFAULT 'custom',   -- 'first_meet' / 'birthday' / 'custom'
    description TEXT DEFAULT '',
    remind_before_days INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**API 端点新增**（`api_server.py`）：

| 端点                                 | 方法   | 说明                           |
| ------------------------------------ | ------ | ------------------------------ |
| `/api/anniversary/list`            | GET    | 列表（含 `days_since` 计算） |
| `/api/anniversary/add`             | POST   | 添加纪念日                     |
| `/api/anniversary/update/{id}`     | PUT    | 更新纪念日                     |
| `/api/anniversary/delete/{id}`     | DELETE | 删除纪念日                     |
| `/api/anniversary/upcoming?days=7` | GET    | 未来 N 天内纪念日              |

**新建文件**：

| 文件                                     | 说明                                           |
| ---------------------------------------- | ---------------------------------------------- |
| `electron/src/renderer/js/memorial.js` | MemorialPanel 类 — 列表/添加/编辑/删除/倒计时 |

**修改文件**：

| 文件                                 | 改动                                                |
| ------------------------------------ | --------------------------------------------------- |
| `core/database.py`                 | `_create_tables()` 新增 anniversary 表            |
| `core/api_server.py`               | 新增 5 个 anniversary 端点                          |
| `electron/src/renderer/index.html` | 纪念 Tab 内容区                                     |
| `electron/src/renderer/js/app.js`  | 注册 memorial Tab 切换                              |
| `electron/src/preload.js`          | 同步暴露通用 API（已有 `aerie.api.request` 即可） |

**验证**：

```
# API curl POST /api/anniversary/add → 查 SQLite → 确认写入
# API curl GET /api/anniversary/list → 确认 days_since 正确计算
# 前端添加纪念日 → 刷新页面 → 数据保持
```

---

### A6. 后台数据查看 Tab

**目标**：展示聊天记录分页列表、知识库条目、工具调用统计、系统状态概览。

**新建文件**：

| 文件                                        | 说明                            |
| ------------------------------------------- | ------------------------------- |
| `electron/src/renderer/js/data-viewer.js` | DataViewer 类 — 4 个子面板切换 |

**API 端点新增/增强**（`api_server.py`）：

| 端点                                          | 说明                                       |
| --------------------------------------------- | ------------------------------------------ |
| `GET /api/chat/history?page=1&limit=50`     | 分页聊天记录（已有基础，需增强分页和过滤） |
| `GET /api/knowledge/list?category=&search=` | 知识库列表（搜索过滤）                     |
| `GET /api/tools/usage`                      | 工具调用统计（最近24h）                    |
| `GET /api/stats/system`                     | 系统状态（CPU/内存/运行时间/消息数）       |

**修改文件**：

| 文件                                 | 改动                |
| ------------------------------------ | ------------------- |
| `core/api_server.py`               | 新增/增强上述端点   |
| `electron/src/renderer/index.html` | 后台数据 Tab 内容区 |
| `electron/src/renderer/js/app.js`  | 注册 data Tab 切换  |

**验证**：

```
# curl GET /api/chat/history?page=1&limit=10 → 返回分页聊天记录
# curl GET /api/stats/system → 返回 {uptime, cpu_percent, memory_mb, message_count}
```

---

### A7. UI 图像资源修复

**目标**：检查所有图像引用路径，修复损坏或缺失的资源。

**当前图像资产负债表**：

| 文件                                              | 位置      | 状态             |
| ------------------------------------------------- | --------- | ---------------- |
| `Aerie · 云栖.svg`                             | 项目根    | ✅ 存在          |
| `Aerie · 云栖.png`                             | 项目根    | ✅ 存在          |
| `electron/src/renderer/logo-96.png`             | 渲染进程  | ✅ 存在          |
| `electron/src/renderer/logo.png`                | 渲染进程  | ✅ 存在          |
| `electron/src/renderer/favicon.png`             | 渲染进程  | ✅ 存在          |
| `electron/builder/icon.ico`                     | 打包      | ✅ 存在          |
| `opencloud-companion-ui/assets/icons/` (41 svg) | UI 图标库 | ✅ 全部存在      |
| **主题预览图**                              | 设置Tab   | ❌**缺失** |
| **纪念日图标**                              | 纪念Tab   | ❌**缺失** |

**修复内容**：

1. 检查 `index.html` 中所有 `<img>` / `<link>` / CSS `url()` 引用 → 确认目标文件存在
2. 主题预览图：为设置 Tab 中 5 个主题选项生成小色块预览（纯 CSS 实现，无需外部图片）
3. 纪念日图标：使用项目已有的 `dl_builtin_apple` 图标集中的 `calendar.svg` / `heart.svg` / `star.svg`

**验证**：

```
# Electron 开发者工具 → Network 面板 → 无 404
# 检查所有 Tab 下图标正常渲染
```

---

### A8. 逻辑链路分析报告

**目标**：生成各页面功能定位、模块交互关系、实现步骤、预期效果的专业分析文档。

**报告定位**：作为开发文档存储在 `.trae/documents/`，同时作为后续开发参考。

**报告结构**：

1. **系统全貌概览**
   - 主流程图（已有 mermaid 图可引用）
   - 各功能模块职责边界
2. **数据流链路分析**
   - 用户发 QQ 消息 → QQClient → Router → Pipeline → Brain → SendQueue → 用户收到
   - 主动推送链路：CronScheduler → PushPolicy → Brain.generate_push → QQClient.send
   - 情绪链路：用户消息 → EmotionEngine.analyze → PAD + 阈值累积 → EmotionEngine.tune
   - UI 展示链路：Companion 内部状态 → API Server → IPC → 渲染进程 → DOM 更新
3. **各页面/组件分析**
   - 聊天 Tab：功能定位、与其他模块交互、数据来源
   - QQ 面板 Tab：NapCat 控制、连接状态
   - 情绪 Tab：PAD 仪表盘、阈值面板、数据刷新策略
   - 纪念 Tab：CRUD 流程、纪念日计算
   - 设置 Tab：配置读写链路
   - 数据 Tab：查询聚合逻辑
   - 悬球：消息通知、窗口唤起
4. **前后端接口映射表**
   - 当前 14 个 API → 预期新增 12 个 → 总计 26 个端点
   - 每个端点的：用途、请求/响应格式、调用方组件、数据流向
5. **数据库 ER 图**：8 现有表 + 1 新增表 → 表间关系

**文件**：`e:\Agent_reply\.trae\documents\logic-link-analysis-report.md`（Obsidian 格式）

---

### A9. 系统整合与优化

**目标**：

- API 响应时间 ≤ 200ms
- 设计风格一致性（色彩/排版/交互）
- 可用性测试通过

**整合检查清单**：

| 检查项            | 方法                                                                                            |
| ----------------- | ----------------------------------------------------------------------------------------------- |
| API 响应时间      | `curl -o /dev/null -s -w '%{time_total}' http://127.0.0.1:7890/api/health` 重复 20 次取中位数 |
| 前端 API 调用异常 | 启动完整 Electron 环境，操作所有 Tab，Console 无 error                                          |
| 数据模型对应      | 逐表对比 `database.py` schema ↔ `api_server.py` 响应字段 ↔ 前端 DOM 绑定                  |
| 设计一致性        | 5 套主题 CSS 变量完整、各组件使用相同 `--radius`/`--transition`/`--shadow`                |
| 功能回归          | 运行全部 129 测试 → 全部通过                                                                   |
| 旧功能不受影响    | 聊天/Tab切换/NapCat面板/悬球 手动测试通过                                                       |

**优化策略**：

1. API 性能：FastAPI 已有 `async/await`，瓶颈一般在 Brain 调用（2-5s），不在 API 本身。确保纯数据查询端点（health/settings/anniversary_list）走内存/本地 DB
2. 前端性能：情绪仪表盘 3s 轮询保持，数据查看 Tab 用分页（page/limit），避免一次性加载全部数据
3. CSS 复用：所有组件使用 `var(--xxx)` 引用，不硬编码颜色

---

## 四、实施步骤（时序安排）

```
Day 1（A1+A2+A3 并行）
├── A1: brain.py 新增 Qwen（~15 min）
├── A2: push_scheduler.py 新建 + companion.py 集成（~90 min）
└── A3: 5 主题 CSS + theme-switcher.js + main.css 变量重构（~60 min）

Day 2（A4+A5 并行）
├── A4: settings.js + api_server 端点 + main.js IPC + preload.js（~90 min）
└── A5: database anniversary 表 + api_server 端点 + memorial.js（~90 min）

Day 3（A6+A7+A8 并行）
├── A6: data-viewer.js + api_server 查询端点（~60 min）
├── A7: 图像资源全面检查 + 修复（~30 min）
└── A8: 逻辑链路分析报告（~90 min）

Day 4（A9 整合）
├── 集成测试 + 功能回归
├── 前后端通信全链路验证
├── 性能优化（API 响应时间测量）
└── 可用性测试
```

---

## 五、累积式测试验证策略

> 遵循"模块A→模块A+B→模块A+B+C"的递进验证。

### 第 1 轮：A1 独立验证

```
验证项：brain.py 3 个 Provider 全部加载
命令：python -c "from core.brain import Brain; b=Brain(); print(len(b._providers))" → 输出 3
```

### 第 2 轮：A2 独立验证（A1 可能作为 Brain 依赖）

```
验证项：push_scheduler.py 成功解析 proactive.yaml 9 场景
命令：python -c "from core.push_scheduler import PushScheduler; ..."
```

### 第 3 轮：A1+A2 集成验证

```
验证项：启动 Companion → 检查日志 PushScheduler 已注册 + Brain 含 3 Provider
```

### 第 4 轮：A3 独立验证

```
验证项：index.html 加载所有 5 主题 → 切换无闪烁
```

### 第 5 轮：A1+A2+A3 集成验证

```
验证项：完整启动 Electron → 4 Tab 正常 + 主题切换 + 日志正常
```

### 第 6 轮：A4 独立验证

```
验证项：curl PUT /api/settings → settings.yaml 更新 → 重启保持
```

### 第 7 轮：A1+A2+A3+A4 集成验证

```
验证项：设置页面修改主题 → 即时切换 → 设置页面修改推送开关 → PushScheduler 读取
```

### 第 8 轮：A5 独立验证

```
验证项：API CRUD anniversary → DB 正确写入 → days_since 正确计算
```

### 第 9 轮：A1+A2+A3+A4+A5 集成验证

```
验证项：所有 6 个 Tab 正常切换 → 各功能独立操作无副作用
```

### 第 10 轮：A6+A7 独立验证

```
验证项：数据 Tab 分页查询 → 图片 0 个 404
```

### 第 11 轮：全量集成 + 回归

```
验证项：
1. 全部 129 测试通过（原测试无破坏）
2. 6 Tab 全部功能正常
3. Cron 场景定时触发（至少验证 morning_brief/goodnight 已被调度）
4. 主题切换全部 5 套
5. 设置持久化正确
6. 纪念日 CRUD 完整
7. Console 无 error、Network 无 404
```

---

## 六、代码质量保障

### 6.1 功能保护机制

- 每次改动前截图/录屏当前可用功能作为基线
- 每个模块开发完成后立即运行 `pytest tests/ -v` 确认无回归
- 不改动现有测试文件，只新增测试

### 6.2 语法检查

- Python：`python -m py_compile <file>` 检查每个新建/改写文件的语法
- JS：Electron DevTools Console 即时反馈
- 确保所有代码块括号/引号正确闭合

### 6.3 注释规范

- 注释使用英文（与项目现有风格一致）
- 不使用中文引号 `""` `''` 在 Python 字符串中（已知冲突）

### 6.4 文件命名与放置

- 新建文件遵循现有模式：`electron/src/renderer/js/<name>.js`、`core/<name>.py`
- API 端点命名遵循 RESTful 风格：`/api/<resource>/<action>`
- CSS 文件放在 `styles/themes/` 子目录

---

## 七、关键风险与缓解

| 风险                   | 影响                        | 缓解措施                                                      |
| ---------------------- | --------------------------- | ------------------------------------------------------------- |
| croniter 安装失败      | PushScheduler 无法解析 cron | 备选方案：手写 cron 解析函数（6 段）                          |
| Brain 调用耗时 > 5s    | 主动推送延迟                | sender coroutine 设置 timeout 15s                             |
| CSS 变量重构遗漏       | 部分组件颜色未切换          | 用 grep 检查 main.css 中所有硬编码色值                        |
| 大规模并行开发冲突     | 多人同时改一个文件          | 本次只有我一人在写，无此风险                                  |
| settings.yaml 写入并发 | 数据损坏                    | Python `save_settings()` 使用原子写入（写临时文件→rename） |

---

## 八、验收标准

| #  | 验收项        | 通过标准                                                           |
| -- | ------------- | ------------------------------------------------------------------ |
| 1  | Qwen Provider | `brain.py._providers` 长度为 3                                   |
| 2  | Cron 调度     | 日志可见 `[PushScheduler]` + 至少 morning_brief/goodnight 已调度 |
| 3  | 主题切换      | 5 主题全部可以切换，localStorage 持久化                            |
| 4  | 设置持久化    | PUT /api/settings → 重启 → GET /api/settings 一致                |
| 5  | 纪念日 CRUD   | POST/GET/PUT/DELETE 全部正常 +`days_since` 计算正确              |
| 6  | 后台数据      | 分页查询聊天记录 + 知识库 + 工具统计                               |
| 7  | 图像资源      | Electron DevTools Network 0 个 404                                 |
| 8  | 全量测试      | `pytest tests/` — 原 129 全部通过 + 新增测试通过                |
| 9  | API 响应时间  | `/api/health` ≤ 20ms，`/api/settings` GET ≤ 50ms             |
| 10 | 功能回归      | 聊天/QQ面板/情绪仪表盘/悬浮球 均正常                               |

---

## 九、输出物清单

| 类型                    | 文件                                                                                                                 | 状态 |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------- | ---- |
| **新建 Python**   | `core/push_scheduler.py`                                                                                           | ⏳   |
| **改写 Python**   | `core/brain.py`, `core/companion.py`, `core/api_server.py`, `core/database.py`, `config/persona_loader.py` | ⏳   |
| **新建 CSS**      | `electron/src/renderer/styles/themes/*.css` (5 文件)                                                               | ⏳   |
| **改写 CSS**      | `electron/src/renderer/styles/main.css`                                                                            | ⏳   |
| **新建 JS**       | `theme-switcher.js`, `settings.js`, `memorial.js`, `data-viewer.js`                                          | ⏳   |
| **改写 JS**       | `app.js`                                                                                                           | ⏳   |
| **改写 HTML**     | `index.html`                                                                                                       | ⏳   |
| **改写 Electron** | `main.js`, `preload.js`                                                                                          | ⏳   |
| **新建测试**      | `tests/test_push_scheduler.py`, `tests/test_settings_api.py`, `tests/test_anniversary_api.py`                  | ⏳   |
| **新建文档**      | `.trae/documents/logic-link-analysis-report.md`                                                                    | ⏳   |



本人注释：有一些新增的一些东西，我稍微改了一下，你接着再看一看吧

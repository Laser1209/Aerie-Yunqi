# Phase 3 实施计划：工具执行 + 桌面 UI

## 摘要

Phase 3 在 Phase 2（性格引擎 + 记忆系统 + 意图分类）基础上，新增工具执行能力和桌面 UI，使伊塔不仅能聊天，还能**操作电脑文件、控制系统、查询网页、管理待办**。
核心技术变更：Function Calling 集成到 AI 调用链路，命令类消息走 `AI决策 → 工具调用 → 结果包装 → QQ回复` 流水线。

---

## 一、当前架构基线

```
Phase 2 消息流：
  msg → classifier.classify(msg)          # 规则/LLM 分类
      → chat_log.log_incoming(msg)        # SQLite 存储
      → context_builder.build(msg)        # System Prompt + 记忆 + 历史
      → brain.generate_reply(messages)    # 纯文本对话
      → chat_log.log_outgoing(reply)      # 存储回复
      → qq_client.send(reply)             # QQ 发送
```

**Phase 3 需要改造的点：**
- `brain.generate_reply()` 仅接受纯 messages → 需新增 `generate_with_tools()` 支持 Function Calling
- `classifier` 可检测 COMMAND/QUERY → 需要工具调度层
- `personality.build_system_prompt()` 已有 `capability_level="phase3"` 参数 → 只需切换
- `main.py` 没有工具注册/调度逻辑 → 需新增 ToolRegistry

**已有基础设施可直接复用：**
- `Intent.COMMAND` / `Intent.QUERY` 枚举（classifier.py 已分类）
- `ChatLogger` SQLite（todo_manager 复用同一数据库或独立库）
- `CAPABILITY_PHASE3` System Prompt 模板（personality.py 已定义）
- `requests` 已安装（web_ops 使用）

**需新增依赖：**
- `aiohttp` — 异步 HTTP（web_ops 网页请求）
- `PyQt6` — 桌面 UI（悬浮球 + 聊天窗口）

---

## 二、模块划分与实施顺序

### 阶段 A：工具基础设施（无 UI 依赖，先做）
| 编号 | 模块 | 文件 | 说明 |
|------|------|------|------|
| A1 | 工具基类 | `tools/base.py` | Tool 抽象类 + `to_openai_schema()` + `execute()` 接口 |
| A2 | 工具注册中心 | `tools/registry.py` | 注册/查找/调度 tools → Function Calling schema 生成 |
| A3 | 文件操作 | `tools/file_ops.py` | 读/写/搜索/列出文件（`pathlib` + 白名单目录） |
| A4 | 系统操作 | `tools/system_ops.py` | 打开软件、查看 CPU/内存/磁盘状态 |
| A5 | 网页工具 | `tools/web_ops.py` | HTTP GET 搜索、天气（wttr.in）、网页抓取 |
| A6 | 待办管理 | `tools/todo_manager.py` | SQLite CRUD：创建/列表/完成/删除待办 |

### 阶段 B：Function Calling 集成
| 编号 | 模块 | 文件 | 说明 |
|------|------|------|------|
| B1 | brain 扩展 | `core/brain.py` | 新增 `generate_with_tools(messages, tools)` — 支持自动 tool_choice |
| B2 | 命令流水线 | `core/pipeline.py` | 编排：classify → context_build → brain(tools) → execute → wrap → reply |

### 阶段 C：桌面 UI（PyQt6）
| 编号 | 模块 | 文件 | 说明 |
|------|------|------|------|
| C1 | 悬浮球 | `desktop/floating_ball.py` | 系统托盘图标 + 右键菜单 + 信息提示 |
| C2 | 对话窗口 | `desktop/chat_window.py` | 本地对话框，输入文字 → AI 回复 |

### 阶段 D：连通性测试
| 编号 | 内容 | 验证标准 |
|------|------|---------|
| D1 | 工具独立测试 | 每个工具 `execute()` 返回正确结果 |
| D2 | Function Calling 测试 | Mock OpenAI 返回 tool_calls → pipeline 正确执行 |
| D3 | 命令流水线 E2E | QQ 发"打开记事本" → AI 决策 → execute → 回复 |
| D4 | 桌面 UI 集成 | 启动 main.py → 悬浮球出现 → 聊天窗口可用 |

---

## 三、关键设计决策

### 3.1 安全性（工具执行边界）

```
✅ 允许：PROJECT_ROOT, USER_HOME/Documents, USER_HOME/Desktop, USER_HOME/Downloads
❌ 拒绝：C:\Windows, C:\Program Files, 系统目录, 任何路径遍历(# ../ 截断)

白名单实现：tools/base.py 的 _validate_path() 方法
```

### 3.2 待办独立 SQLite

`data/todo.db`（与 `chat_log.db` 分离，职责清晰）

### 3.3 PyQt6 启动策略

在 `main.py` 中 `asyncio` 事件循环启动后，用 `QThread` 在侧线程启动 PyQt6 窗口。
Companion 的 QQ WebSocket 生命周期与 PyQt6 窗口独立——关闭窗口不影响后台服务。

### 3.4 Function Calling 温度策略

命令执行用 **temperature=0.1**（确定性），闲聊保持 temperature=0.8。

---

## 四、具体文件变更

### 4.1 新增文件

| 文件 | 预估行数 | 职责 |
|------|---------|------|
| `tools/__init__.py` | 5 | 包定义 |
| `tools/base.py` | 80 | Tool 基类 + OpenAI schema 生成 + 路径安全检查 |
| `tools/registry.py` | 70 | 工具注册/查找/生成全部 tool schemas |
| `tools/file_ops.py` | 120 | ReadFile / WriteFile / ListDir / SearchFiles |
| `tools/system_ops.py` | 100 | OpenApp / SystemStatus / Screenshot |
| `tools/web_ops.py` | 80 | WebSearch / Weather / FetchUrl |
| `tools/todo_manager.py` | 130 | TodoCreate / TodoList / TodoComplete / TodoDelete |
| `core/pipeline.py` | 100 | CommandPipeline 编排类 |
| `desktop/__init__.py` | 3 | 包定义 |
| `desktop/floating_ball.py` | 120 | 系统托盘悬浮球 |
| `desktop/chat_window.py` | 100 | 对话窗口 |

### 4.2 修改文件

| 文件 | 变更内容 |
|------|---------|
| `core/brain.py` | 新增 `generate_with_tools()` 方法（复用 `_call_api`） |
| `main.py` | 新增 ToolRegistry 初始化 + CommandPipeline + PyQt6 启动 |
| `config/settings.yaml` | 新增 `tools` 节（白名单目录、允许的应用列表） |
| `requirements.txt` | 新增 `aiohttp>=3.9`, `PyQt6>=6.6` |

---

## 五、连通性测试清单

| # | 测试点 | 预期结果 |
|---|--------|---------|
| 1 | classifier 识别"打开记事本" → COMMAND | `test_classifier` 追加用例 |
| 2 | `ReadFile` tool execute 返回文件内容 | `test_tools.py` |
| 3 | `SystemStatus` tool 返回 CPU/内存/磁盘 | `test_tools.py` |
| 4 | `Weather` tool 返回天气数据 | `test_tools.py` |
| 5 | `TodoCreate` + `TodoList` 写入/读取一致性 | `test_todo_manager.py` |
| 6 | `brain.generate_with_tools()` 传 tools → API 正确调用 | `test_brain.py` 新用例 |
| 7 | CommandPipeline 全链路（mock OpenAI tool_calls）| `test_pipeline.py` |
| 8 | QQ "搜索 Python 教程" → web_search tool → AI 总结 → QQ 回复 | 手动 E2E |
| 9 | PyQt6 悬浮球启动不阻塞 QQ 服务 | 手动验证 |
| 10 | 聊天窗口输入 → AI 回复 → 窗口显示 | 手动验证 |

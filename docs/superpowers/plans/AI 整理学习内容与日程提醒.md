# AI 整理学习内容与日程提醒

> **Workspace:** e:\Agent_reply

---

**User**

我可以把我学的东西发给这个AI。然后AI自己调用相关操作在数据库里面整理吗？或者我想一个日程，她帮我整理为待办直接在系统里面体现？目前待办的提醒能做到什么地步？待办可以通过QQ来提醒我吗？

**Assistant**

项目结构已初步掌握。现在并行读取关键文件以回答五个问题。



以下探索结论基于对仓库源码的直接核查，结果完整、可直接引用。

---

## 1) 这是什么项目

**Aerie · 云栖**（`e:\Agent_reply`）是一个 **本地优先的 AI 桌面伴侣**（Local-first AI desktop companion），当前版本 `0.3.1-beta.0815`。它不是单纯的前端或后端项目，而是一个多端全栈系统：

| 组成 | 技术栈 | 路径 |
|---|---|---|
| 智能内核（后端主体） | Python 3.10+，FastAPI 0.139 + uvicorn + aiohttp + asyncio，SQLite 存储 | `e:\Agent_reply\core\`、`e:\Agent_reply\main.py`、`e:\Agent_reply\requirements.txt` |
| 桌面壳（前端） | Electron 28 + 原生 HTML/JS 渲染层（无框架，多面板 UI + 灵动岛） | `e:\Agent_reply\electron\src\` |
| 官网 Spotlight | React 18 + Vite 6 + Tailwind + Framer Motion | `e:\Agent_reply\Spotlight\` |
| 世界模拟侧车 | 独立 Python 服务 + SQLite | `e:\Agent_reply\world_service\` |
| Android 客户端 | Flutter（pubspec.yaml + OpenAPI 生成） | `e:\Agent_reply\android-client\` |
| MCP 服务 | TypeScript + Cloudflare Workers（justoneapi-mcp） | `e:\Agent_reply\justoneapi-mcp\` |

证据：`e:\Agent_reply\README.md` 第 28–49 行；`requirements.txt` 第 25–26 行（fastapi==0.139.2 / uvicorn）。

---

## 2) 待办/Todo 功能 —— 有，完整实装

**数据表**：SQLite `todo` 表，定义在 `e:\Agent_reply\core\database.py` 第 101–116 行：
- 字段：`id`、`external_id`（唯一）、`user_id`、`title`、`description`、`notes`、`due_at`、`reminder_at`、`priority`（high/medium/low）、`status`（pending/done/cancelled）、`estimated_minutes`、`created_at`、`updated_at`、`done_at`
- 索引：`idx_todo_due_status`、`idx_todo_external_id`（database.py 第 314–315 行）
- 迁移逻辑 `_migrate_todo`（database.py 第 521 行起），并有旧版 JSON（`data/todos/*.json`）幂等导入

**业务层**：`e:\Agent_reply\core\todo_manager.py`（`get_todos` / `add_todo` / `update_todo` / `delete_todo` / `toggle_todo` / `stats`）；测试在 `e:\Agent_reply\tests\test_todo_manager.py`。

**API**（`e:\Agent_reply\core\api_server.py` 第 7271–7354 行，"v12.2.0 Todo Management API"）：
- `GET /api/todos?date=`、`POST /api/todos`、`PATCH /api/todos/{todo_id}`、`DELETE /api/todos/{todo_id}`、`POST /api/todos/{todo_id}/toggle`
- 每次变更会发 `timeline_changed` SSE 事件；待办还会注入每日简报（`brief_fetcher.get_today_todos`，api_server.py 第 7107–7180 行）

注意：`todo.reminder_at` 字段已建表但**目前没有任何代码消费它**（全库 grep 仅建表语句和文档引用），即 todo 本身尚无提醒触发逻辑。

---

## 3) 定时任务/提醒机制 —— 有，且相当完整

**a) Cron 主动推送调度器**（核心机制）
- `e:\Agent_reply\core\push_scheduler.py`：`CronScheduler` 类（第 404 行起），**自研 cron 解析器**（明确注释"不依赖 croniter"，第 601 行），支持 cron 场景 + 事件触发场景、频控、静默时段、暂停/恢复、作息学习锚点搬移
- 配置源：`e:\Agent_reply\config\proactive.yaml`（9 个场景，如 `morning_brief` cron `30 6,7 * * *`、`morning_brief_9am` cron `0 9 * * *`、`idle_care` trigger `user_idle_4h`）
- 推送日志表 `push_log`（database.py 第 133–142 行），记录 success/failed/skipped_quiet/skipped_interval 等状态
- 配套引擎：`core/push_event_engine.py`、`core/proactive_planner.py`、`core/proactive_judge.py`、`core/routine_learner.py`、设计文档 `docs/proactive-push-v2-design.md`

**b) 日历提醒**
- `e:\Agent_reply\core\calendar_manager.py`：`collect_due_reminders`（第 358 行），按 `remind_before`（-1/0/5/15/30/60/1440 分钟）收集到期提醒，用 `calendar_reminder_log` 表做幂等去重
- 轮询循环：`e:\Agent_reply\core\api_server.py` 第 122–163 行 `_calendar_reminder_loop`（asyncio 后台任务，每轮收集 lookback 2 分钟的到期提醒并广播 `calendar_reminder` 事件）
- 表：`calendar_events`（含 `repeat_type`、`remind_before`）与 `calendar_reminder_log`（database.py 第 269–293 行）

**c) 24 小时持续监听**：`scripts/24h_monitor.py` + watchdog（`start-24h-monitor.bat`），欲望引擎/话题追踪/情绪触发轮询。

另外 `e:\Agent_reply\scheduler\` 目录存在但 `__init__.py` 为空——实际调度逻辑都在 `core/push_scheduler.py`。

---

## 4) QQ/消息推送集成 —— 有，QQ 是一等公民；邮件没有

**QQ（OneBot11，非 go-cqhttp 依赖，自研协议栈）**
- `e:\Agent_reply\communication\onebot11\client.py`：**自研 OneBot11 WebSocket 客户端**（明确注释"不依赖任何第三方 OneBot SDK"），含心跳探活、RPC echo 匹配、登录态闸门
- `communication/onebot11/actions.py`：OneBot 动作封装（`send_msg`、`send_private_msg` 等）；另有 `events.py`、`messages.py`
- `e:\Agent_reply\core\qq_gateway.py`：QQ 引擎网关——自动注入引擎的 `onebot11_<uin>.json` 配置、启动引擎进程、token/端口一致性管理
- 上层模块：`core/qq_client.py`、`core/qq_media.py`、`core/qq_sticker.py`、`core/qq_whitelist.py`、`core/qq_deepening.py`
- 三端撤回适配：`communication/recall/`（`qq.py`、`local.py`、`wechat_stub.py` 微信预留）
- 发送队列/分片：`communication/send_queue.py`、`splitter.py`、`message.py`、`router.py`

**其他推送通道**：本地桌面聊天（Electron SSE）、移动端网关（`core/mobile_gateway.py`、Android 客户端）。README 明确列出"主动推送：cron、事件、情绪触发"三通道为 QQ/本地/移动。

**邮件：无**。全库 grep `smtp/smtplib/send_mail` 无任何实际实现（命中均为文档、SVG logo 或无关词），项目没有邮件发送能力。

---

## 5) 笔记/知识收藏入库 —— 有，双层结构

**a) SQLite 知识库（结构化条目，即"收藏/笔记"）**
- 表：`knowledge_base`（`e:\Agent_reply\core\database.py` 第 90–98 行）：`category`（persona/user/world/task）、`title`、`content`、`tags`
- 业务层：`e:\Agent_reply\knowledge\kb.py` —— `KnowledgeBase.search()`（关键词 LIKE 检索）、`get()`、`list()`（分页）、`add()`（第 83 行，收藏入库入口）
- API（`core/api_server.py` 第 6403–6486 行）：`GET /api/knowledge/list`、`GET /api/knowledge/{id}`、`POST /api/knowledge`（新增收藏）、`PUT /api/knowledge/{id}`、`DELETE /api/knowledge/{id}`
- 工具层：`e:\Agent_reply\tools\knowledge_tools.py`、`tools/seed_social_knowledge.py`、脚本 `scripts/p1d5_activate_knowledge.py`

**b) 向量知识库（语义入库/检索）**
- `e:\Agent_reply\core\knowledge_indexer.py`：`index_chunks()`（第 131 行）把文本切片写入 ChromaDB
- 技术：ChromaDB 语义检索 + 本地 ONNX 离线 embedding + LayeredMemory 多层记忆 + 附件专用向量库（README 第 40 行；记忆层在 `memory/layers/`）
- 相关文档：`.trae/documents/plan-hermes-obsidian-knowledge-base.md`、`P1D5-向量知识库激活成功审计.md`

---

### 总结一句话

这是一个 Electron + Python(FastAPI/asyncio) + SQLite 的本地 AI 伴侣全栈项目；**待办（todo 表 + 完整 CRUD API）、定时提醒（自研 cron 推送调度器 + 日历提醒轮询）、QQ 集成（自研 OneBot11 WebSocket 协议栈 + QQ 网关，无邮件）、知识收藏入库（knowledge_base 表 + ChromaDB 向量库双轨）四项能力全部已实装**，且均有对应测试文件与文档佐证。

我把整个系统翻了一遍，逐个给你答案——好消息是大半地基已经在了，只差几块关键拼图。

## 1. 学的东西发给她 → 自动入库？**已经能做到**

- 她的 LLM 工具链里注册了 `knowledge_add` 工具（[tools/__init__.py#L118-L124](file:///e:/Agent_reply/tools/__init__.py#L118-L124)），系统提示词也明确要求她"得知值得长期保存的信息时主动调用、无需征询"（[context_builder.py#L1094-L1100](file:///e:/Agent_reply/core/context_builder.py#L1094-L1100)）
- 写入 `knowledge_base` 表，同标题自动更新不堆积，之后检索会自动注入上下文；长文还有 ChromaDB 向量索引兜底
- 局限：入库靠她自主判断"重要"，纯技术笔记她可能觉得不算"重要事实"而漏记——可以在提示词里把"你学给我听的内容"也纳入必记范围

## 2. 你想一个日程 → 她整理成待办体现在系统里？**API 全通，但她"够不着"**

- 待办 CRUD API 完整（[api_server.py#L7271-L7354](file:///e:/Agent_reply/core/api_server.py#L7271-L7354)），桌面端简报抽屉会展示当日待办，改动实时 SSE 刷新
- **缺口**：工具注册表里有 `knowledge_add`，却没有 `todo_add` / 日历工具——也就是说你在聊天里说"帮我把周三体检加进待办"，她现在没有工具可调，只能口头答应。这条链路注册一个工具就通了

## 3. 待办提醒目前能做到什么地步？

| 层级 | 现状 |
|---|---|
| 单条待办定时提醒 | ❌ `reminder_at` 字段建了表但**全库无任何代码消费**（[database.py#L109](file:///e:/Agent_reply/core/database.py#L109)） |
| 笼统催办 | ✅ `todo_remind` 场景，9–21 点每整点推一次"还有 N 件事没做"（[proactive.yaml#L103-L107](file:///e:/Agent_reply/config/proactive.yaml#L103-L107)） |
| 日程精确提醒 | ✅ 日历事件支持提前 0/5/15/30/60/1440 分钟提醒，但**只在桌面弹窗**（灵动岛+日历面板），不出桌面 |
| 事件引擎 | ⚠️ `TODO_DUE` 映射存在，但没有任何代码 publish 这个事件 |

## 4. 能通过 QQ 提醒吗？**通道是现成的**

主动推送本来就经 QQ 客户端投递（早安简报、晚安、`todo_remind` 都走这条路）。所以：
- "整点笼统催办 via QQ" → **已经在跑**
- "单条待办到点 via QQ 精确提醒" → 只差实现：消费 `reminder_at` + 借现成的 push 链路投递到 QQ

---

也就是说缺的其实是三件小事：①给她注册 `todo_add`（顺手加日历工具）；②写一个提醒扫描循环消费 `reminder_at`；③提醒同时广播桌面 + 走 QQ 推送。都是现成模式，不用发明新架构。

要不要我现在就把这三块补上？补完之后你在 QQ 上随口说"下周三下午两点牙医"，她就直接建好待办、到点 QQ 喊你。

---


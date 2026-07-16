---
title: Phase 8 — 大脑中枢 · 消息节奏 · 配置表单 · 指令通道
date: 2026-07-16
version: 8.0
status: Approved (user decided all 3 question rounds)
tags:
  - phase8
  - cognition
  - trace
  - reasoning
  - persona-editor
  - config-forms
  - message-pacing
  - qq-trace
  - remote-command
  - self-evolving
aliases:
  - Phase 8 Plan
  - 大脑中枢
  - 开发者后台
cssclasses:
  - wide-page
---

# Phase 8 — 大脑中枢 · 消息节奏 · 配置表单 · 指令通道

> **核心定位**：把伊塔从"会说话"升级为"会思考、被观察、可被自己改造"。
> **三原则**（用户重申）：
> 1. **不破坏现有功能** — Phase 4-7 全部保留，sillytavern 不破坏，撤回/引用/上传/情绪/阈值/NapCat/悬浮球继续工作
> 2. **不破坏伊塔人格** — UI 文案、动画、徽标需符合 v9.0 persona（26岁/184cm/温柔大姐姐+病娇/称呼"你"）
> 3. **设计美学统一** — Apple HIG 风格 + 当前粉紫主题，新增 tab 沿用 sidebar 风格

---

## 一、用户决策记录（3 轮提问汇总）

| 决策点 | 决策结果 | 备注 |
|--------|----------|------|
| 大脑中枢形态 | **独立 Tab：开发者后台** | 在 sidebar 加「🧠 大脑」图标，单独 panel |
| 思维链实现 | **结构化 trace**（取消 LLM 自述） | 真实内部状态，零额外 token 成本 |
| 设置页编辑 | **表单化编辑 + 常用项快捷开关** | 不暴露 YAML 原文（避免破坏） |
| trace 存储 | **SQLite 全部持久化** | 默认保留 30 天 + 手动清理按钮 |
| trace 数据来源 | Pipeline 全流程 + Tool Registry 调用链 + Emotion 趋势与阈值曲线 | 全部 3 项 |
| 手机操控预留 | **预留「远程指令」面板** | 整合 Tool 链路展示 |
| LLM 自述 | **不需要** | 节省 token，仅结构化 trace |
| trace API 暴露 | **仅本地（127.0.0.1:7890）** | 未来加 token 鉴权 |
| 指令识别 | **LLM 自主判断 + Tool 调用** | 伊塔在 QQ 上看到"关机"类消息自主决定调用 |
| 常用项范围 | 情绪参数+主题 + 消息节奏+LLM参数 + 安全开关（**全部 3 项**） | — |
| YAML 编辑 | **验证+备份**（拒绝错误 + .bak 备份） | 避免破坏配置文件 |
| trace 保留 | **30 天** + 手动清理按钮 | 总量上限 5 万条 |
| **自举能力** | **伊塔自主识别能力边界，必要时扩展 Tool** | **首次引入自迭代机制** |
| QQ 入站展示 | **全部入站消息都进 trace** | local + QQ 统一追踪 |

---

## 二、Phase 1 探索结果摘要

### 2.1 现状盘点

| # | 用户反馈 | 现状 | 缺口 |
|---|---------|------|------|
| 1 | 消息分批节奏 ≤1.5s | `send_queue` 间隔 1.2s，但 local 路径完全跳过 send_queue，所有段瞬时全 append | local 端无 setTimeout 间隔显示，chat.js 直接 `appendChild` |
| 2 | 设置页显示配置 | `settings.js` 只有 4 个字段，无 persona.yaml 编辑入口 | 缺 persona YAML 表单化 + 常用项开关 |
| 3 | 情绪没波动 | `EmotionEngine._state` 单例内存值，进程重启即丢；`TEXT_TRIGGERS` 缺"没事/吃醋/关心"等口语词 | 缺持久化 + 关键词扩展 + 历史情绪曲线 |
| 4 | 大脑中枢 | 文档 §10.2 PersonaDecision / §10.3 BrainRandom 都是设计稿，**完全没实现** | 需新增 core/cognition.py + sidebar tab + SQLite 表 |
| 5 | 未来手机操控 | Tool Registry 已有 14 个 tool，但 trace 不全 | 缺指令通道 + Tool 链路追踪 + 自举扩展 |
| 6 | 自迭代能力 | 不存在 | 新增 `core/self_evolving.py`（伊塔能识别能力边界+扩展） |

### 2.2 关键文件清单

| 文件 | 角色 | 改动 |
|------|------|------|
| [send_queue.py](file:///e:/Agent_reply/communication/send_queue.py) | QQ 出站节奏 | 微调默认间隔 |
| [pipeline.py](file:///e:/Agent_reply/core/pipeline.py) | 消息处理主线 | 接入 cognition 追踪 |
| [emotion_engine.py](file:///e:/Agent_reply/core/emotion_engine.py) | 情绪主控 | 加状态持久化 + 扩展关键词 |
| [emotion_threshold.py](file:///e:/Agent_reply/core/emotion_threshold.py) | 阈值槽位 | 扩展关键词 + 历史曲线 API |
| [tool_registry.py](file:///e:/Agent_reply/core/tool_registry.py) | Tool 集合 | 接入 trace + 自举注册 |
| [brain.py](file:///e:/Agent_reply/core/brain.py) | LLM 调用 | 输出 decision 信号 |
| [database.py](file:///e:/Agent_reply/core/database.py) | SQLite | 加 cognition_log / self_evolve_log / config_history 表 |
| [api_server.py](file:///e:/Agent_reply/core/api_server.py) | HTTP API | 加 /api/cognition/* + /api/config/* + /api/tool/* |
| [persona.yaml](file:///e:/Agent_reply/config/persona.yaml) | 人设 | 暴露 schema 给前端表单 |
| [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) | 聊天渲染 | 段间 setTimeout 间隔 |
| [settings.js](file:///e:/Agent_reply/electron/src/renderer/js/settings.js) | 设置页 | 重构为人设表单+常用项 |
| [index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) | UI 入口 | 新增「大脑」tab + 远程指令子面板 |

---

## 三、Proposed Changes

### 3.1 核心新增模块

#### 模块 1：`core/cognition.py` — 大脑中枢（核心）

```yaml
purpose: 记录伊塔每次决策的完整 trace，支持本地+QQ双渠道
schema:
  - id (PK)
  - ts (timestamp)
  - source: 'local' | 'qq' | 'proactive' | 'recall'
  - user_id
  - user_message
  - route_mode: 'FULL' | 'AUTO' | 'BASIC'
  - stage_route: {decision_layer, decision_score, decision_reason}
  - stage_emotion: {analyzed_keywords, pad_delta, label}
  - stage_threshold: {slot, delta, new_value, trigger, pre_threshold}
  - stage_context: {L1_chars, L2_chars, L3_chars, L4_chars, history_count}
  - stage_brain: {provider, model, prompt_tokens, completion_tokens, duration_ms, scene}
  - stage_tools: [{name, args, result, duration_ms, status}]
  - stage_split: {raw_text, segments_count, segments}
  - stage_postprocess: {tune_label, original_len, tuned_len, recall_candidate}
  - stage_output: {final_text, send_target}
  - irc: {ip, port, qq_msg_id, is_command}  # 远程指令元数据
  - is_command: bool  # 标记是否为手机操控指令
```

**实现要点**：
- `CognitionEngine.record(msg)` → 生成 `trace_id` 返回
- `CognitionEngine.update(trace_id, stage_name, data)` → 逐步填充
- `CognitionEngine.get_recent(limit, filters)` → UI 拉取
- `CognitionEngine.cleanup(older_than_days)` → 手动清理

#### 模块 2：`core/self_evolving.py` — 自举扩展（关键新增）

```yaml
purpose: 伊塔识别能力边界，必要时自动注册新 Tool
trigger: LLM 在回复中表达「我做不到」或「需要新工具」
mechanism:
  1. Pipeline 在 LLM 回复后检测 [NEED_TOOL: tool_name, capability_desc] 标记
  2. self_evolving.parse_request(text) → 提取工具需求
  3. self_evolving.propose_tool(name, desc) → 生成 Tool 草案（schema + 安全评估）
  4. 需要用户确认（高风险）或自动注册（低风险）
  5. 注册到 tool_registry + 写 self_evolve_log
  6. 下次 LLM 看到新 Tool 可调用
safety:
  - 危险指令（shutdown/format/delete）强制二次确认
  - 写入文件类 Tool 默认沙箱在 workspace/
  - 所有自举 Tool 写 self_evolve_log，可回滚
```

**实现要点**：
- 在 pipeline.py L137 后增加「自举检测」
- LLM system_prompt 增加：「如果你发现自己需要新工具来完成用户指令，请输出 [NEED_TOOL: name, description]，主用户会为你扩展」
- 检测到标记后调用 self_evolving.propose_tool
- UI 在「大脑中枢」显示自举历史

#### 模块 3：`core/emotion_state_store.py` — 情绪状态持久化

```yaml
purpose: 解决情绪值进程重启丢失
storage: SQLite emotion_state 表
schema:
  - ts
  - user_id
  - P, A, D
  - patience, anxiety, desire, tenderness
  - threshold_patience, threshold_anxiety, threshold_desire, threshold_tenderness
  - event_log: JSON (每条 keyword 触发的 delta)
```

**实现要点**：
- EmotionEngine 在 update_trajectory 后写库
- 启动时加载最近一条
- 每日自动清理 7 天前
- Emotion 趋势曲线从这表查

#### 模块 4：`core/tool_registry_enhance.py` — Tool 链路追踪

```yaml
purpose: 记录每个 Tool 调用的完整生命周期
hooks:
  - pre_call: {tool_name, args, trace_id}
  - post_call: {tool_name, result, duration_ms, status, error}
storage: SQLite tool_call_log 表
```

### 3.2 配置文件改动

#### `config/persona.yaml` — 暴露 schema 给前端表单

新增结构化编辑需要的 metadata：
```yaml
persona:
  profile:
    _schema:
      field_type: 'object'
      fields: {age: int, height_cm: int, ...}
  speech:
    _schema:
      field_type: 'object'
      fields: {max_chars: int, style: enum, ...}
  thresholds:
    _schema:
      field_type: 'object'
      fields: {patience: int, anxiety: int, ...}
```

#### `config/settings.yaml` — 新增常用项分组

```yaml
quick_toggles:
  # 消息节奏
  message_pacing:
    min_interval_seconds: 1.5       # 本地分段间隔
    max_segments: 12                # 单次回复最大段数
  # LLM 参数
  llm:
    temperature: 0.7
    max_tokens: 2048
  # 安全开关
  safety:
    require_confirm_for_dangerous: true
    dangerous_tools_whitelist: [shutdown, format, delete_file, send_email]
  # 情绪
  emotion:
    daily_decay_enabled: true
    cleanup_after_days: 30
```

### 3.3 后端 API 改动（`core/api_server.py`）

新增 endpoints：

| 路径 | 方法 | 用途 |
|------|------|------|
| `/api/cognition/recent` | GET | 拉取最近 N 条 trace（带分页+过滤） |
| `/api/cognition/{id}` | GET | 单条 trace 详情 |
| `/api/cognition/stats` | GET | trace 统计（按 source/label/slot 聚合） |
| `/api/cognition/cleanup` | POST | 手动清理 30 天前数据 |
| `/api/cognition/commands` | GET | 列出所有 Tool 调用（手机指令追踪） |
| `/api/config/persona` | GET/PUT | 获取/保存 persona.yaml（带验证+备份） |
| `/api/config/settings` | GET/PUT | 获取/保存 settings.yaml（带验证+备份） |
| `/api/config/backup` | GET | 列出所有 .bak 备份 |
| `/api/config/restore` | POST | 恢复到指定 .bak |
| `/api/evolve/history` | GET | 自举历史 |
| `/api/evolve/propose` | POST | 用户手动触发 Tool 提案（可选） |
| `/api/emotion/history` | GET | 情绪历史曲线（最近 24h/7d/30d） |
| `/api/emotion/state_persisted` | GET | 持久化后的情绪值 |

### 3.4 Electron UI 改动

#### 改动 1：sidebar 新增「🧠 大脑」Tab

[index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) 加 `<button class="sidebar-tab" data-tab="cognition">` + `<section id="panel-cognition">`

#### 改动 2：大脑中枢 Tab 子布局

```html
<section id="panel-cognition" class="tab-panel">
  <div class="cognition-tabs">
    <button class="cog-tab active" data-cog="trace">实时思维</button>
    <button class="cog-tab" data-cog="commands">远程指令</button>
    <button class="cog-tab" data-cog="emotion">情绪曲线</button>
    <button class="cog-tab" data-cog="evolve">自举历史</button>
  </div>

  <!-- 实时思维：分页列表 + 详情面板 -->
  <div id="cog-trace-view">
    <div class="trace-list" id="trace-list"></div>
    <div class="trace-detail" id="trace-detail"></div>
  </div>

  <!-- 远程指令：仅显示 is_command=true 的 trace + Tool 链路 -->
  <div id="cog-commands-view" class="hidden">
    <div id="command-list"></div>
  </div>

  <!-- 情绪曲线：ECharts 折线图 -->
  <div id="cog-emotion-view" class="hidden">
    <div id="emotion-chart"></div>
  </div>

  <!-- 自举历史：伊塔自主扩展的 Tool 列表 -->
  <div id="cog-evolve-view" class="hidden">
    <div id="evolve-list"></div>
  </div>

  <button id="cog-cleanup-btn" class="btn btn-secondary btn-sm">清理 30 天前数据</button>
</section>
```

#### 改动 3：设置页重构为「人设表单 + 常用项」

[settings.js](file:///e:/Agent_reply/electron/src/renderer/js/settings.js) 重写：
- 顶部 4 个常规模块：主题/启动/自启/推送（保留）
- 新增「人设档案」表单：基本资料/外貌特征/说话风格/情绪阈值
- 新增「消息节奏」开关：1.5s 间隔可调
- 新增「LLM 参数」开关：温度/最大 token
- 新增「安全开关」开关：危险 Tool 二次确认
- 每个表单字段带「保存」按钮，错误提示 + 备份恢复

#### 改动 4：chat.js 分段间隔显示

[chat.js L60-61](file:///e:/Agent_reply/electron/src/renderer/js/chat.js#L60-L61) 改为：
```js
window.aerie.api.onMessage((msg) => {
  if (msg && msg.type === "recall") { this._markRecalled(msg.id); return; }
  if (this._seenIds.has(msg.id)) return;
  this._seenIds.add(msg.id);
  // 分段间隔显示
  this._scheduleRender(msg, /*delayMs=*/ idx * 1500);
});
```

`onMessage` 改为接收 list 后顺序 append 段：
- 第一段：立即渲染
- 后续段：setTimeout 1500ms 后渲染
- UI 上有「正在输入...」气泡

### 3.5 数据库改动（`core/database.py`）

新增 4 张表：

```sql
-- 大脑中枢 trace
CREATE TABLE IF NOT EXISTS cognition_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  source TEXT NOT NULL,
  user_id INTEGER,
  user_message TEXT,
  route_mode TEXT,
  stage_route TEXT,
  stage_emotion TEXT,
  stage_threshold TEXT,
  stage_context TEXT,
  stage_brain TEXT,
  stage_tools TEXT,
  stage_split TEXT,
  stage_postprocess TEXT,
  stage_output TEXT,
  irc TEXT,
  is_command INTEGER DEFAULT 0
);
CREATE INDEX idx_cognition_ts ON cognition_log(ts);
CREATE INDEX idx_cognition_source ON cognition_log(source);
CREATE INDEX idx_cognition_is_command ON cognition_log(is_command);

-- Tool 调用日志
CREATE TABLE IF NOT EXISTS tool_call_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id INTEGER,
  ts INTEGER,
  tool_name TEXT,
  args TEXT,
  result TEXT,
  duration_ms INTEGER,
  status TEXT,
  error TEXT
);

-- 自举历史
CREATE TABLE IF NOT EXISTS self_evolve_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  proposed_name TEXT,
  description TEXT,
  schema_json TEXT,
  safety_level TEXT,
  approved INTEGER,
  rejected_reason TEXT
);

-- 情绪持久化（每 5 分钟一次快照）
CREATE TABLE IF NOT EXISTS emotion_state_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  user_id INTEGER,
  P REAL, A REAL, D REAL,
  patience REAL, anxiety REAL, desire REAL, tenderness REAL,
  thresholds_json TEXT,
  event_log TEXT
);
```

### 3.6 情绪引擎改造（`core/emotion_engine.py` + `core/emotion_threshold.py`）

#### 改造 1：状态持久化
- 启动时从 `emotion_state_snapshot` 加载最近一条
- 每次 `update_trajectory` 后写一次（5 分钟合并一次防刷）
- 进程优雅关闭时强制写一次

#### 改造 2：关键词扩展（覆盖用户口语化表达）

```python
TEXT_TRIGGERS 扩展：
  - 忍耐值 (patience)：
    - ["你不能主动跟我发消息吗", "不主动", "不理我"] → +25
    - ["敷衍", "随便回"] → +20
    - ["我不想跟你说话"] → +30
  - 渴望值 (desire)：
    - ["想抱你", "想见你", "想亲"] → +15
    - ["你好厉害", "你真棒"] → +10
  - 温柔透支 (tenderness)：
    - ["吃醋", "你会不会..."] → +10  # 吃醋类表达
    - ["我在乎你", "关心你"] → +15
  - 不安值 (anxiety)：
    - ["你怎么不说话"] → +10
    - ["你忘了", "你没回我"] → +20
```

### 3.7 消息分批节奏（`communication/send_queue.py` + `electron/src/renderer/js/chat.js`）

#### 改动 1：send_queue 默认值
```python
_DEFAULT_MIN_INTERVAL = 1.5  # 1.2 → 1.5
```

#### 改动 2：local 端渲染节奏（chat.js）

实现 `_scheduleRenderBatch(messages)`：
- 第一条：立即
- 后续：每 1500ms
- 「正在输入...」气泡在每条之前出现
- 简化用户感知"分批一个一个发"

---

## 四、Assumptions & Decisions

| 假设 | 决策 |
|------|------|
| LLM 端已能返回 tool_calls | 是（brain.py L179 已处理） |
| Tool Registry 已有 14+ 工具 | 是（core/tool_registry.py） |
| SQLite 是数据存储 | 是（data/aerie.db） |
| 现有情绪 API 不破坏 | `/api/emotion/state` 保持兼容，新增 `/api/emotion/state_persisted` |
| persona.yaml 格式由 LLM prompt 依赖 | 改动只新增 _schema 元数据，**不影响 LLM 加载** |
| 现有 7 个 sidebar tab + 数据子 tab | 增加「大腦」= 第 8 个 + 不影响现有 |
| `config/persona_loader.load_persona` 已有 | 是（兼容不变） |

---

## 五、Verification（验证步骤）

### 阶段 A：核心模块（先后端后前端）

1. **后端启动**：杀掉旧 Electron + Python，`npm start` 重启，确保 7890 端口正常
2. **数据库初始化**：`python -c "from core.database import Database; Database().execute('SELECT 1')"` 通过
3. **Cognition API 测试**：
   ```bash
   # 发送测试消息触发 trace
   curl -X POST http://127.0.0.1:7890/api/chat/send -H "Content-Type: application/json" -d '{"text":"测试","user_id":0}'
   # 拉取 trace
   curl http://127.0.0.1:7890/api/cognition/recent?limit=10
   ```
   验证返回包含：route/emotion/threshold/brain/split 五段
4. **配置 API 测试**：
   ```bash
   # 读
   curl http://127.0.0.1:7890/api/config/persona
   # 改年龄为 27 并保存
   curl -X PUT http://127.0.0.1:7890/api/config/persona -H "Content-Type: application/json" -d '{"persona":{"profile":{"age":27}}}'
   # 验证备份生成
   curl http://127.0.0.1:7890/api/config/backup
   ```
5. **情绪持久化测试**：发 5 条消息触发"吃醋"类关键词 → 重启后端 → 验证情绪值仍保留

### 阶段 B：UI

6. **侧边栏**：能看到「大脑」图标，点击切到 panel
7. **实时思维 Tab**：显示最近 20 条 trace，每条可点击展开查看完整阶段
8. **远程指令 Tab**：发"帮我关机"消息，验证 trace.is_command=true 显示在「远程指令」Tab
9. **情绪曲线 Tab**：ECharts 折线图正确渲染 P/A/D 三维度历史
10. **自举历史 Tab**：发"帮我整理桌面文件"消息，验证 LLM 输出 `[NEED_TOOL: organize_desktop, ...]`，自举历史新增 1 条
11. **设置页**：人设表单可编辑 → 保存 → 重启后端验证 LLM 加载的是新值
12. **消息分批**：在 chat.js 触发分段，第一条立即显示，1500ms 后第二条

### 阶段 C：兼容

13. **情绪仪表盘旧版**：所有 0/100 → 真实值（验证没破坏 EmotionDashboard）
14. **聊天旧功能**：撤回/引用/上传/历史 仍工作
15. **NapCat**：QQ 上能收到伊塔回复，且 reply 内容包含「正在执行」之类的 trace hint

### 阶段 D：自举安全

16. **危险指令**：手机发"shutdown now" → 伊塔识别 → 弹出二次确认
17. **自举历史可回滚**：UI 上有「撤销此 Tool」按钮

---

## 六、Implementation Order

| Step | 模块 | 估时 | 依赖 |
|------|------|------|------|
| 1 | DB schema 新增 4 张表 + 索引 | 30 min | 无 |
| 2 | `core/emotion_state_store.py` 持久化 | 45 min | Step 1 |
| 3 | `core/cognition.py` 主体 | 90 min | Step 1 |
| 4 | `core/self_evolving.py` 自举 | 60 min | Step 1 |
| 5 | `core/tool_registry_enhance.py` 工具链追踪 | 30 min | Step 1, Step 3 |
| 6 | pipeline.py 接入 cognition + self_evolving | 60 min | Step 3-5 |
| 7 | emotion_engine 持久化 + 关键词扩展 | 45 min | Step 2 |
| 8 | api_server.py 新增 endpoints | 60 min | Step 3-7 |
| 9 | index.html 大脑 tab + 子视图 | 45 min | 无 |
| 10 | 大脑中枢 JS（trace.js / commands.js / emotion-chart.js / evolve.js） | 120 min | Step 9 |
| 11 | settings.js 重构为人设表单+常用项 | 90 min | Step 8 |
| 12 | chat.js 分段间隔渲染 | 30 min | 无 |
| 13 | send_queue 默认 1.5s | 5 min | 无 |
| 14 | End-to-end 测试 + 验证 | 60 min | All |
| **Total** | | **~13h** | |

---

## 七、风险与缓解

| 风险 | 缓解 |
|------|------|
| trace 表 5 万条上限撑爆 | 启动时检查 + 30 天自动清理 + 手动按钮 |
| self_evolving 误注册危险 Tool | 所有自举 Tool 默认 safe 模式 + 危险类强制二次确认 + .bak 可回滚 |
| 关键词扩展误命中（口语化） | 权重调低（5-10）+ 仅 +5~+15 影响 |
| persona.yaml 表单 schema 写错 | 前后端都验证 + 失败回滚 + .bak 备份 |
| 30 天 trace 占用磁盘 | 限制 5 万条 + 启动时检测 + 弹窗提示 |
| 情绪持久化导致状态永远不衰减 | daily_decay 仍然运行（独立计时） |
| LLM 自举时机误判 | 只在 LLM 显式输出 `[NEED_TOOL: ...]` 时触发，无标记不触发 |
| chat.js 1500ms 间隔用户感觉慢 | 可在 settings 里调（0.8 / 1.0 / 1.5 / 2.0） |
| cognition 表写入性能 | 异步写 + batch 合并（每 5s 刷一次） |

---

## 八、Out of Scope（不在本期做）

- 真正的 mobile native app（仅预留 API 端点）
- 真正在另一台机器部署 server（仅本地 7890 端口）
- 多个伊塔实例 / 多用户管理
- 历史聊天全文搜索（用 SQLite LIKE 即可，未来再做）
- LLM 替换为本地模型（仍是远程 API）
- 端到端加密

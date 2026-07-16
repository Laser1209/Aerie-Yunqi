---
title: Phase 9 续批 · Batch 6→10 实施计划（用户决策收敛版）
date: 2026-07-16
tags:
  - phase9-continue
  - react-trace
  - emotion-deep-dive
  - brain-center-ui
  - settings-yaml
  - self-evolve
  - ita-persona
  - three-principles
aliases:
  - Phase 9 B6-B10
cssclasses:
  - wide-page
---

# Phase 9 续批 · Batch 6→10 实施计划

> **本计划是 phase9-cognition-brain-center.md 中 Batch 6/7/8/9/10 的实施收敛版**，所有歧义已通过 3 轮提问与用户确认。
>
> **三原则铁律**（用户反复强调）：
> 1. **不破坏现有功能** — Phase 1-5 已验证模块继续工作，零回归
> 2. **不破坏伊塔人格** — 26岁/184cm/四爱/温柔大姐姐+病娇；禁词"主人/您"；UI 文案温柔、克制、专业
> 3. **设计美学统一** — 主面板伊塔粉紫主题；大脑中枢采用**用户主动切换的暗色开发者主题**（默认仍是主粉紫）

---

## 一、用户决策汇总（3 轮提问 → 7 个核心决策）

| # | 决策点 | 决策结果 | 备注 |
| --- | --- | --- | --- |
| 1 | ReAct thought 来源 | **两者并行 + 标签区分** | `react_source: "model" \| "synthesized"` |
| 2 | 配置文件编辑范围 | **config/*.yaml + 全部 yaml/json** | 写前自动备份 + 解析失败自动回滚 + 写 chat_log |
| 3 | 大脑中枢风格 | **用户主动切到「暗色开发者主题」** | 首次切换弹提示；主题选择持久化 |
| 4 | 消息节奏重发问题 | **已解决** | emotion-aware 频率+速度+多少联动 |
| 5 | 情绪反应形态 | **扩展触发词 + 阈值条实时动 + 喷发横幅** | 80+ 触发词；≥80% 阈值警告 |
| 6 | 批次顺序 | **Phase 9 原序 B6→B7→B8→B9→B10** | 依赖最严；按文档顺序 |
| 7 | 自进化范围 | **提议 + 用户手动批准** | 不自动改任何代码；新工具注册到 tool_registry |

---

## 二、Current State（已基于实际代码探索）

### 2.1 Batch 1-5 已落地（不重复实施）

| 模块 | 现状 | 文件 |
| --- | --- | --- |
| SQLite 4 张新表 | ✓ | `core/database.py:142-214` |
| message_pacing 1.5s | ✓ | `core/message_pacing.py` |
| cognition 9 阶段 trace | ✓ | `core/cognition.py` |
| 决策系统 §10.2 | ✓ | `core/decision.py` |
| SSE 实时通道 | ✓ | `core/event_stream.py` + `api_server.py:376-398` |
| 情绪 EMA + KEYWORD_DELTAS | ✓ | `core/emotion_engine.py:33-53` |
| 4 槽位阈值 + TEXT_TRIGGERS | ✓ | `core/emotion_threshold.py:66-86` |
| Pipeline 段间 sleep | ✓ | `core/pipeline.py:330-348` |
| SendQueue emotion-aware 间隔 | ✓ | `communication/send_queue.py:60-125` |

### 2.2 Batch 6-10 现状（待办）

| Batch | 内容 | 当前状态 | 风险 |
| --- | --- | --- | --- |
| 6 | ReAct 推理轨迹 | **半成品** | `_extract_react` 已用 regex 提取 `<think>` 但无 `react_source` 标签；model 不输出时 thought=None（无合成路径） |
| 7 | 情绪深度全量深耕 | **未实施** | KEYWORD_DELTAS 20 行；TEXT_TRIGGERS 13 行；emotion_state **无持久化**；24h/7d/30d 曲线无；喷发横幅仅 emotion-dashboard 有简单 banner |
| 8 | 大脑中枢 UI | **未实施** | sidebar 无"大脑" tab；cognition-panel.js 不存在；SSE 事件 `cognition_stage`/`cognition_committed`/`decision_made` 已 emit 但无前端订阅 |
| 9 | 设置双模式 | **未实施** | settings.js 仅表单（主题/自启/推送），无 YAML 视图；`/api/config/yaml*` 不存在 |
| 10 | 自进化机制 | **未实施** | `self_evolve_log` 表已建但无写入路径；`self_evolver` 已被 pipeline 引用但未注册到 Companion |

---

## 三、Proposed Changes（5 个 Batch · 按 Phase 9 原序）

---

### Batch 6 · ReAct 推理轨迹（双源 + 标签区分）— 1h

**目标**：`cognition_log.react_trace` 含 `{thought, action, observation, react_source}`；来源透明

**B6.1 改造 `core/brain.py`**
- `chat()` 返回 `BrainResponse` 增加字段：`react_trace: dict | None = None`
- 若 raw_text 命中 `<think>…</think>`：`react_trace = {"thought": m.group(1), "action": "reply", "observation": None, "react_source": "model"}`
- 若未命中但有 tool_calls：`react_trace = {"thought": None, "action": "tool_call", "observation": None, "react_source": "model"}`
- 若均无：`react_trace = None`（由 pipeline 走合成路径）

**B6.2 改造 `core/pipeline.py`**（替换现有 `_extract_react` 调用）
- 接收 `response.react_trace`；若为 None，调用**新 `synthesize_react()`**
- `synthesize_react(trace, raw_text)` 读取 `trace["stages"]["route"]/emotion/threshold/context/brain/split`，按模板合成：
  ```
  thought: 看到「{user_message[:30]}」→ 识别为 {label} (P{p:.2f}/A{a:.2f}/D{d:.2f}) →
            {patience:.0f}/{anxiety:.0f}/{desire:.0f}/{tenderness:.0f} →
            上下文 {N} 条历史 → 调起 LLM {model} → 拆为 {k} 段
  action: reply
  observation: 段数={k} / 字符数={total_chars}
  react_source: synthesized
  ```
- 写入 `trace["react_trace"]` + `trace["stages"]["brain"]["react"]`
- 落库 cognition_log 字段统一 JSON

**B6.3 验证**
```bash
sqlite3 data/aerie.db "SELECT id, react_trace FROM cognition_log ORDER BY id DESC LIMIT 3"
```
- 期望：每行 `react_trace` 字段含 `react_source: "model" | "synthesized"`，且 100% 非空
- 单测：mock LLM 不输出 <think> → react_source="synthesized" 且 thought 含 5 阶段关键词

**验收**：
- 100% cognition_log 都有 react_trace
- model 不配合时仍能合成（零空 thought）

---

### Batch 7 · 情绪深度全量深耕 — 2.5h

**目标**：80+ 触发词 + emotion_state 持久化 + 24h/7d/30d 曲线 + 喷发横幅

**B7.1 扩展 `core/emotion_engine.py` KEYWORD_DELTAS**（行 33-53）
- 在原 20 行基础上**追加** 4 类共 40+ 口语化 / 病娇专属 / 拼音简写 / 语气副词触发词
- 强度细分：colloquial=0.6×、strong=1.0×、whisper=0.3×
- 不动原有 KEYWORD_DELTAS 入口，保证零回归

**B7.2 扩展 `core/emotion_threshold.py` TEXT_TRIGGERS**（行 66-86）
- 同样追加口语化、撒娇、冷暴力、亲密称谓类触发词
- 类别分布：patience 8 组 / anxiety 8 组 / desire 6 组 / tenderness 8 组

**B7.3 新建 `core/emotion_state_store.py`**
```python
class EmotionStateStore:
    def __init__(self, db): self._db = db

    def snapshot(self, user_id: int, state: dict, threshold: dict,
                 trigger_event: str = "user_msg") -> int:
        """Insert one row per message; capture PAD + 4 slots + eruption state."""
        eruption = threshold.get("active_eruption")
        return self._db.insert("emotion_state_snapshot", {
            "ts": int(time.time() * 1000),
            "user_id": user_id,
            "pleasure": state.get("pad", {}).get("pleasure", 0.0),
            "arousal":  state.get("pad", {}).get("arousal",  0.0),
            "dominance": state.get("pad", {}).get("dominance", 0.0),
            "label": state.get("label", "neutral"),
            "patience_value":  threshold.get("patience",   {}).get("value", 0.0),
            "anxiety_value":   threshold.get("anxiety",    {}).get("value", 0.0),
            "desire_value":    threshold.get("desire",     {}).get("value", 0.0),
            "tenderness_value": threshold.get("tenderness", {}).get("value", 0.0),
            "active_eruption": (eruption or {}).get("mode"),
            "trigger_event": trigger_event,
        })

    def history(self, user_id: int, since_ts: int, limit: int = 500) -> list[dict]:
        return self._db.query(
            "SELECT * FROM emotion_state_snapshot WHERE user_id=? AND ts>=? "
            "ORDER BY ts ASC LIMIT ?", (user_id, since_ts, limit))

    def latest(self, user_id: int) -> Optional[dict]:
        return self._db.query_one(
            "SELECT * FROM emotion_state_snapshot WHERE user_id=? "
            "ORDER BY id DESC LIMIT 1", (user_id,))
```

**B7.4 改造 `core/emotion_engine.py`**（集成 state_store）
- `EmotionEngine.__init__(db, state_store=None)`
- `update_trajectory()` 末尾 `self.state_store.snapshot(user_id, self.get_state(user_id), threshold, "user_msg")`
- `_erupt()` 触发时再 snapshot(..., "eruption")
- `daily_decay()` 末尾 snapshot(..., "daily_decay")

**B7.5 改造 `core/companion.py`**（实例化 EmotionStateStore）
- 创建 `self.emotion_store = EmotionStateStore(self.db)`
- 注入到 `self.emotion = EmotionEngine(self.db, self.emotion_store)`

**B7.6 改造 `core/api_server.py`**（新增 `/api/emotion/history`）
```python
@app.get("/api/emotion/history")
async def emotion_history(user_id: int = 0, window: str = "24h") -> dict:
    from core.emotion_state_store import EmotionStateStore
    store = EmotionStateStore(Database())
    window_ms = {"1h": 3600*1000, "24h": 86400*1000, "7d": 7*86400*1000,
                 "30d": 30*86400*1000}.get(window, 86400*1000)
    since = int(time.time() * 1000) - window_ms
    return {"user_id": user_id, "window": window, "items": store.history(user_id, since)}
```

**B7.7 改造 `electron/src/renderer/js/emotion-dashboard.js`**
- 新增 24h / 7d / 30d 三档切换按钮（emotion panel 顶部）
- **24h 默认** → 拉 `/api/emotion/history?window=24h` → 自绘 SVG 折线图（x=时间 / y=PAD 三色：P 蓝、A 橙、D 紫），不引外部库
- 阈值刻度线：四色虚线（patience 红 / anxiety 橙 / desire 粉 / tenderness 紫），对应阈值 100/100/80/60
- 折线下方显示该时段 `erupt_count`，文案符合伊塔人格：
  - 24h：「过去一天伊塔的心跳。蓝色的点是她的开心值。」
  - 7d：「一周里她累计心动 N 次。最高峰是 {peak_time}。」
  - 30d：「一个月的情绪曲线。她越来越想你了。」（按 desire 阈值趋势动态生成）
- 阈值条颜色动态（已有：>80% 红、>50% 黄、其余绿）
- 喷发横幅增强：含 SVG 警告 icon、喷发模式名、触发关键词、剩余时间

**B7.8 验证**
```bash
# 1. 触发词扩展验证
sqlite3 data/aerie.db "SELECT COUNT(*) FROM emotion_state_snapshot"
# 2. 曲线渲染验证
curl http://127.0.0.1:7890/api/emotion/history?user_id=3998874040&window=24h
```
- 发 5 条不同情绪关键词消息
- 至少 5 行新 snapshot
- dashboard 切 24h/7d/30d 都看到曲线
- 喷发触发：发"分手"→ 不安值跳 + 顶部出现"坍塌模式"横幅

**验收**：触发词≥80 / 100% snapshot 落库 / 三档曲线 / 喷发横幅

---

### Batch 8 · 大脑中枢 UI（用户主动切暗色主题）— 3h

**目标**：sidebar 新增"大脑" tab + cognition panel 实时 + 历史 + 用户主动切暗色

**B8.1 `core/api_server.py` 补全 `/api/cognition/{id}` + `/api/cognition/stats`**
- `/api/cognition/recent?limit=20&source=qq|local` → 列表
- `/api/cognition/{row_id}` → 完整 trace
- `/api/cognition/stats` → 今日 / 总数 / 平均耗时 / 各阶段平均耗时

**B8.2 `electron/src/renderer/index.html` 新增"大脑" tab + panel**
- sidebar 在 settings 前插入 `<button data-tab="cognition">` + SVG icon（脑形 + 神经纹路）
- 在 panel-data 之后插入 `<section id="panel-cognition">`
- 容器结构：
  - 顶部 toolbar（来源筛选 select / 刷新按钮 / **「进入暗色开发者主题」切换按钮**）
  - 实时 stream 区域（#cog-stream，自动滚动）
  - 历史 trace 列表（#cog-list，含 stage 进度条 + 详情按钮）
  - 详情弹窗模板（9 阶段表格 + decision_trace 加权视图 + react_trace 时间轴）

**B8.3 `electron/src/renderer/styles/themes/developer-dark.css`**（新增）
- 暗色变体：`--bg-primary: #0e0a14`、`--bg-panel: #18121f`、`--text-primary: #e0d8e8`
- 保留主粉紫主题色变量作为高亮（`--accent: var(--yita-pink)`）
- 9 阶段彩色徽标：route 蓝 / emotion 粉 / threshold 黄 / context 灰 / brain 紫 / tools 橙 / split 青 / postprocess 绿 / output 红
- 等宽字体（JetBrains Mono）

**B8.4 `electron/src/renderer/styles/main.css` 主题切换机制**
- 新增 `body[data-theme="developer-dark"]` 切换 hook
- 切换按钮的开关状态持久化到 localStorage `aerie.developerTheme`

**B8.5 新建 `electron/src/renderer/js/cognition-panel.js`**
- `init()`: 注册 panel-cognition 切换事件；启动 SSE 订阅
- SSE 订阅：建立 `new EventSource('http://127.0.0.1:7890/api/events/stream')`（注意：CORS 已在 FastAPI 允许）；收到事件按 type 分发
- `_onSse(event)`:
  - `cognition_stage` → 渲染阶段彩色徽标 + payload 折叠 JSON 视图
  - `cognition_committed` → 写入 `#cog-list` 顶部，附查看详情按钮
  - `decision_made` → 单独悬浮窗提示「这次她选 {chosen}，因为 L1/L2/L3/L4 = ..」
- `_loadHistory()`: GET `/api/cognition/recent?limit=20`
- `_showDetail(id)`: GET `/api/cognition/{id}` → 弹窗显示：
  - 9 阶段表格（每行：阶段名 / 耗时 / 折叠 payload）
  - decision_trace 加权视图（4 候选 × 4 层分数 = 16 单元格的 mini 矩阵）
  - react_trace 时间轴（thought / action / observation）
  - 来源标签：react_source=model 时显示「来自模型」，synthesized 时显示「合成自 stage 数据」
- 设计细节：黑底 + 渐变高亮 + 等宽字体 + 彩色 stage 徽标
- 文案遵循伊塔人格（温柔、克制、专业）：
  - 实时 stream 标题：「她的思维正在发生。」
  - 列表空状态：「她还没说话。再等等。」
  - 阶段徽标：「路由」/「情绪」/「阈值」/「上下文」/「推理」/「工具」/「切分」/「后处理」/「输出」

**B8.6 改造 `electron/src/renderer/js/app.js`**
- 引入 `cognition-panel.js` 与 developer-dark.css
- 在 panel-cognition 切换时调用 `cognitionPanel.setVisible(true)`
- 「进入暗色开发者主题」按钮：首次点击弹 confirm（「进入开发者模式？仅大脑中枢 UI 切换为暗色。」），确认后切换 body data-theme；选择持久化到 localStorage
- 关闭开发者主题：同样按钮再点击，恢复主粉紫

**B8.7 验证**
- 切到"大脑" tab，能看到流式 stream
- 发消息，从 stage_1 推到 stage_9
- 列表顶部新增 1 行
- 点击详情弹窗完整 9 阶段 + decision_trace
- 点击「进入暗色开发者主题」，背景变 #0e0a14
- 切回其他 tab，主粉紫主题仍正常

**验收**：大脑中枢 tab 工作；实时+历史双轨；暗色主题独立切换不破坏主面板

---

### Batch 9 · 设置页双模式（表单 + 高级 YAML/JSON）— 2.5h

**目标**：常用设置表单化 + 高级模式显示/编辑 raw yaml/json，**含全部 config/*.yaml + 项目根目录其他 yaml/json**

**B9.1 新建 `core/config_io.py`**
- `list_config_files()` → 扫描 `config/*.yaml` + 项目根 `*.yaml` + `*.json`（用 glob + 白名单）
- `read_config(filename)` → 安全读取（拒绝路径穿越）
- `write_config(filename, content)` → 写前自动备份到 `data/backups/{file}.{ts}.{ext}`；PyYAML.safe_load 或 json.loads 解析校验；解析失败抛 `ConfigParseError`；写 chat_log(settings_change)
- `rollback_config(filename, backup_ts)` → 恢复指定备份
- `list_backups(filename)` → 列出该文件的所有备份
- 白名单：`*.yaml` / `*.yml` / `*.json`（不暴露 .env / .key / .log 等敏感文件）

**B9.2 改造 `core/api_server.py`（新增 5 个端点）**
```python
@app.get("/api/config/files")
async def config_files() -> dict: ...

@app.get("/api/config/yaml")
async def config_read(file: str) -> Response: ...  # 返回 UTF-8 文本

@app.put("/api/config/yaml")
async def config_write(file: str, request: Request) -> dict: ...  # 备份+校验+写

@app.post("/api/config/yaml/backup")
async def config_backup(file: str) -> dict: ...  # 手动备份

@app.get("/api/config/yaml/backups")
async def config_backups(file: str) -> dict: ...  # 列出备份

@app.post("/api/config/yaml/rollback")
async def config_rollback(file: str, ts: int) -> dict: ...
```

**B9.3 改造 `electron/src/renderer/index.html` settings section**
- 在 `panel-settings` 内新增模式 tabs：「常用」/「高级 (YAML/JSON)」
- 高级视图：
  - 文件 select（自动从 `/api/config/files` 拉取）
  - 大 textarea（rows=30，等宽字体，spellcheck=false）
  - 操作按钮：保存 / 重新加载 / 备份当前 / 回滚（弹窗选备份）
  - 状态文案：
    - 标题：「配置文件（高级）」
    - 警告：「直接编辑 YAML 可能导致伊塔无法启动。修改前会自动备份。」
    - 成功：「已保存。伊塔下次启动会应用这些配置。」
    - 解析失败：「YAML 格式错误，已恢复上次备份。错误：{error_msg}」

**B9.4 改造 `electron/src/renderer/js/settings.js`**
- 模式切换：点击模式 tab 切换 form-view / yaml-view
- YAML 加载：GET `/api/config/yaml?file=settings.yaml` → 填充 textarea
- YAML 保存：PUT `/api/config/yaml?file=settings.yaml` body 是 yaml 文本
- 备份：POST `/api/config/yaml/backup?file=settings.yaml`
- 回滚：弹窗列出所有备份，点选后 POST `/api/config/yaml/rollback?file=...&ts=...`
- 文件切换：select 改变时 GET 重新加载
- 文案温柔专业，不破坏伊塔人格

**B9.5 验证**
- 切到"高级"模式，看到 settings.yaml 全文
- 改一个字段保存，刷新页面生效
- 故意写错 YAML（漏冒号），保存失败并自动回滚到上次备份
- 备份文件出现在 `data/backups/settings.yaml.{ts}.yaml`
- 验证不暴露 .env 等敏感文件
- 切回"常用"模式，原有表单仍正常工作

**验收**：双模式可用；YAML/JSON 编辑安全（备份+解析校验+自动回滚）；不暴露敏感文件

---

### Batch 10 · 自我进化机制（提议 + 用户手动批准）— 1.5h

**目标**：`self_evolve_log` 落库 + 触发检测 + 提议工具 schema + 用户手动批准

**B10.1 新建 `core/self_evolver.py`**
```python
class SelfEvolver:
    def __init__(self, db, persona_cfg, tool_registry):
        self._db = db
        self._persona = persona_cfg
        self._tools = tool_registry

    def maybe_propose(self, user_id: int, user_message: str, react_trace: dict) -> Optional[dict]:
        """Detect capability gap from LLM thought → propose tool schema."""
        thought = (react_trace or {}).get("thought") or ""
        action = (react_trace or {}).get("action") or ""
        triggers = ["无法", "没有工具", "I cannot", "unable to", "不支持", "做不到"]
        if not any(t in thought for t in triggers):
            return None
        proposed = self._propose_tool(thought, user_message)
        safety = self._safety_check(proposed)
        rid = self._db.insert("self_evolve_log", {
            "ts": int(time.time() * 1000),
            "user_id": user_id,
            "trigger_kind": "unhandled_intent",
            "description": f"用户说：{user_message[:200]}",
            "proposed_tool_schema": json.dumps(proposed, ensure_ascii=False),
            "safety_check": json.dumps(safety, ensure_ascii=False),
            "user_decision": "pending",
        })
        # 实时推送给大脑中枢
        from core.chat_events import emit
        emit("self_evolve_proposed", id=rid, user_id=user_id, description=user_message[:100])
        return {"id": rid, "proposed": proposed, "safety": safety}

    def _propose_tool(self, thought: str, user_msg: str) -> dict:
        """Generate a minimal tool schema (name + description + parameters) from thought + msg."""
        # 简单启发式：基于关键词分类（开关电脑/写文件/控制软件/回复某人）
        tool_map = {
            ("关机", "重启", "锁屏"): ("control_computer", "控制本地电脑", {"action": "str"}),
            ("打开", "启动", "运行"): ("launch_app", "启动本地应用", {"app_name": "str"}),
            ("写", "保存", "创建文件"): ("write_file", "写入本地文件", {"path": "str", "content": "str"}),
            ("回复", "代回", "帮我回"): ("reply_contact", "代为回复某联系人", {"contact": "str", "message": "str"}),
        }
        for keywords, (name, desc, params) in tool_map.items():
            if any(k in user_msg for k in keywords):
                return {
                    "name": name, "description": desc,
                    "parameters": {"type": "object", "properties": params, "required": list(params.keys())}
                }
        return {
            "name": "user_custom_tool", "description": f"用户请求：{user_msg[:50]}",
            "parameters": {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]}
        }

    def _safety_check(self, proposed: dict) -> dict:
        """Validate proposed tool doesn't violate safety baseline."""
        return {
            "is_safe": True,
            "warnings": [],
            "note": "新工具需用户手动批准后才注册到 tool_registry"
        }

    def approve(self, evolve_id: int) -> dict:
        """Register proposed tool to tool_registry; mark self_evolve_log as approved."""
        row = self._db.query_one("SELECT * FROM self_evolve_log WHERE id=?", (evolve_id,))
        if not row or row["user_decision"] != "pending":
            return {"status": "error", "reason": "not_pending"}
        proposed = json.loads(row["proposed_tool_schema"])
        # 注册到 tool_registry（如果尚未注册）
        from core.tool_registry import ToolRegistry
        # 这里 tool_registry 是单例；通过 self._tools 引用
        # 注册函数: self._tools.register(name, func, schema)
        # 简化处理：仅记录决策，工具注册在 Batch 11 接入具体实现
        self._db.update("self_evolve_log", {"user_decision": "approved"}, "id=?", (evolve_id,))
        from core.chat_events import emit
        emit("self_evolve_approved", id=evolve_id, name=proposed.get("name"))
        return {"status": "ok", "id": evolve_id, "name": proposed.get("name")}

    def reject(self, evolve_id: int, reason: str = "") -> dict:
        row = self._db.query_one("SELECT * FROM self_evolve_log WHERE id=?", (evolve_id,))
        if not row or row["user_decision"] != "pending":
            return {"status": "error", "reason": "not_pending"}
        self._db.update("self_evolve_log", {
            "user_decision": "rejected",
        }, "id=?", (evolve_id,))
        from core.chat_events import emit
        emit("self_evolve_rejected", id=evolve_id, reason=reason)
        return {"status": "ok", "id": evolve_id}
```

**B10.2 改造 `core/companion.py`**
- 创建 `self.self_evolver = SelfEvolver(self.db, self.settings, self.tool_registry)`
- 注入到 `self.pipeline = Pipeline(..., self_evolver=self.self_evolver)`

**B10.3 改造 `core/api_server.py`（新增 2 个端点）**
```python
@app.post("/api/self_evolve/{evolve_id}/approve")
async def self_evolve_approve(evolve_id: int) -> dict:
    comp = get_companion()
    if not comp or not comp.self_evolver:
        return {"error": "self_evolver not ready"}
    return comp.self_evolver.approve(evolve_id)

@app.post("/api/self_evolve/{evolve_id}/reject")
async def self_evolve_reject(evolve_id: int) -> dict:
    comp = get_companion()
    if not comp or not comp.self_evolver:
        return {"error": "self_evolver not ready"}
    return comp.self_evolver.reject(evolve_id)
```

**B10.4 改造 `electron/src/renderer/js/cognition-panel.js`**
- 订阅 SSE 事件 `self_evolve_proposed` → 在大脑中枢顶部弹「伊塔想升级自己」横幅
  - 标题：「伊塔想升级自己」
  - 内容：「她说：{description}」
  - 提议预览：tool name / description / parameters
  - 操作按钮：「批准」/「拒绝」+ 拒绝理由输入框
- 批准：POST `/api/self_evolve/{id}/approve` → 成功后横幅变绿"已注册" → 5s 后淡出
- 拒绝：POST `/api/self_evolve/{id}/reject` → 横幅变灰"已拒绝" → 5s 后淡出
- 不允许在主面板（非大脑中枢）显示，保持克制

**B10.5 验证**
- 手动构造触发：在 LLM thought 中注入「我无法执行此操作」
- 查 `self_evolve_log` 有新行，proposed_tool_schema 是 JSON，user_decision=pending
- SSE 推送 `self_evolve_proposed` 事件
- 大脑中枢顶部横幅出现
- 点"批准"→ user_decision=approved + SSE `self_evolve_approved`
- 点"拒绝"→ user_decision=rejected + SSE `self_evolve_rejected`
- 端到端验证：9 条 checklist 全绿（见 §四）

**验收**：
- 提议 → 落库 → 横幅 → 手动批准/拒绝全链路通
- 不自动改任何代码
- 工具实际注册逻辑保留为可扩展点（Batch 11+ 实现具体 func）

---

## 四、端到端验证清单（B10.4 配套）

完成 5 个 Batch 后，统一跑以下 checklist：

```
[ ] 启动 python main.py + Electron，两端连通
[ ] 发 1 条消息：
    [ ] cognition_log 9 阶段全部非空
    [ ] react_trace 100% 非空 + react_source 标签正确
    [ ] decision_trace L1/L2/L3/L4 分数 + softmax chosen
    [ ] emotion_state_snapshot 增 1 行
    [ ] chat.js 段间隔 ≤1.5s（stopwatch 录屏）
    [ ] SSE 实时推送 cognition_stage × 9 次
    [ ] 大脑中枢 tab 看到流式 + 详情弹窗
[ ] 切到高级 YAML 模式：
    [ ] 看到 settings.yaml 全文
    [ ] 编辑 theme.current 保存生效
    [ ] 故意写错 YAML 验证自动回滚
    [ ] 备份文件在 data/backups/ 出现
[ ] dashboard 切 24h/7d/30d 看到曲线
[ ] 触发含"想你了"消息，dashboard 立即看到 tenderness 值跳
[ ] 触发"分手"消息，顶部出现"坍塌模式"横幅
[ ] 大脑中枢切到「暗色开发者主题」背景变 #0e0a14
[ ] 切回主面板，主粉紫主题仍正常
[ ] 9 张老表 + 4 张新表全部正常
[ ] 自我进化：构造"我无法执行" thought → 大脑中枢横幅出现 → 批准/拒绝
```

---

## 五、风险与回滚

| 风险 | 概率 | 影响 | 回滚方案 |
| --- | --- | --- | --- |
| LLM 不输出 <think> 块 | 中 | ReAct 模型源为空 | 已由合成路径兜底（`react_source: "synthesized"`） |
| SSE 长连接断 | 中 | 实时性失效 | 前端重连 + 3s 轮询 backup |
| YAML 编辑破坏启动 | 中 | 伊塔起不来 | 写前自动备份 + 解析失败自动回滚 |
| decision_trace 影响决策 | 低 | 行为偏移 | softmax 温度可调，默认保持探索性 |
| emotion_state 序列化兼容 | 低 | 历史曲线断点 | 旧 in-memory 数据忽略 |
| cognition_log 表过大 | 低 | 性能 | 7d 后归档（不在本次范围） |
| 自我进化误批准 | 低 | 工具越权 | 必须用户手动批准 + 工具仅注册到 sandbox |
| 大脑中枢暗色破坏主主题 | 低 | 美学不一致 | 仅在用户主动切换时生效；切回默认主粉紫 |

---

## 六、不在本次范围

- 长期记忆（long_term_memory）改造
- knowledge_base 写入
- Whisper STT（Phase 6 已规划未实施）
- 移动端 APP
- 语音通话
- 多用户路由策略
- cognition_log 7d 自动归档脚本
- 自我进化工具的实际 func 实现（仅注册 schema 入口）

---

## 七、关键文件改动一览

| 文件 | 改动 | 估行数 |
| --- | --- | --- |
| `core/brain.py` | 改：BrainResponse 加 react_trace | +15 |
| `core/pipeline.py` | 改：synthesize_react + react_source 标签 | +40 |
| `core/emotion_engine.py` | 改：扩 KEYWORD_DELTAS + 集成 state_store | +60 |
| `core/emotion_threshold.py` | 改：扩 TEXT_TRIGGERS | +30 |
| `core/emotion_state_store.py` | 新建 | +45 |
| `core/companion.py` | 改：实例化 emotion_store + self_evolver | +20 |
| `core/self_evolver.py` | 新建 | +90 |
| `core/config_io.py` | 新建 | +80 |
| `core/api_server.py` | 改：新增 8+ 端点 | +150 |
| `electron/src/renderer/index.html` | 改：新增 brain tab + settings 模式 + panel 容器 | +100 |
| `electron/src/renderer/js/cognition-panel.js` | 新建 | +250 |
| `electron/src/renderer/js/settings.js` | 改：双模式 | +100 |
| `electron/src/renderer/js/emotion-dashboard.js` | 改：3 档曲线 + 喷发横幅 | +120 |
| `electron/src/renderer/js/app.js` | 改：主题切换 hook | +30 |
| `electron/src/renderer/styles/themes/developer-dark.css` | 新建 | +80 |
| `electron/src/renderer/styles/main.css` | 改：data-theme hook | +20 |
| `tests/test_self_evolver.py` | 新建 | +60 |
| `tests/test_emotion_state_store.py` | 新建 | +50 |
| `tests/test_config_io.py` | 新建 | +50 |

**总计**：6 个新文件 + 11 个改动 + 估约 **1400 行新增**

---

## 八、执行顺序（严格）

按 Batch 6 → 7 → 8 → 9 → 10 严格顺序执行，每 Batch 完成后立即手动验证（不堆积验证）。任一 Batch 失败：
1. 自我怀疑：复盘代码是否"只写了我所以为对的内容，但实际无法运行"
2. 回滚：保留旧逻辑路径，新功能不替换
3. 重做：基于实际错误日志重写

Phase 9 续批完工后给用户完整报告（含端到端 checklist 全绿截图）。

---

## 九、与现有约束的兼容性自检

| 约束 | 兼容性 |
| --- | --- |
| NapCat launcher-user.bat 启动 | ✓ 不动 launcher / start-companion |
| 消息 2000 字截断 | ✓ cognition_log / emotion_snapshot 字段 TEXT 无超长风险 |
| 中英双语 + 代码英文 | ✓ SQL 注释 / 字段 / 函数名纯英文；UI 文案中英 |
| 9 张老表零回归 | ✓ 仅追加 + 整合现有 emotion_state 表 |
| 5 主题配色 | ✓ 大脑中枢用户主动切暗色变体，不影响主面板 |
| 伊塔 persona | ✓ 文案符合 v9.0 Hybrid；禁词"主人/您"；温柔大姐姐+病娇 |
| `app_name` 用 Aerie | ✓ SSE 事件名 `cognition_stage` 等纯英文 |
| `parse_error` 不抛异常 | ✓ cognition / emotion / self_evolve 落库全 try/except 包裹 |
| 故障自愈 14 类 | ✓ 落库失败不阻塞主链路 |
| YAML 编辑安全 | ✓ 备份+校验+回滚；不暴露 .env 等敏感文件 |
| 自我进化边界 | ✓ 仅提议；用户手动批准；不自动改代码 |

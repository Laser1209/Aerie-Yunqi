---
title: Phase 9 — 大脑中枢 · 消息节奏 1.5s · 配置文件双模式 · 情绪全量深耕
date: 2026-07-16
tags:
  - phase9
  - cognition-brain-center
  - message-pacing-1.5s
  - settings-yaml-form
  - emotion-deep-research
  - decision-system
  - react-reasoning
  - ita-persona
aliases:
  - Phase 9 Plan
cssclasses:
  - wide-page
---
# Phase 9 — 大脑中枢 · 消息节奏 1.5s · 配置文件双模式 · 情绪全量深耕

> **保留**：Phase 1-8 全部已验证模块（撤回（无法撤回！）/引用/上传/splitter/SendQueue/情绪引擎/NapCat 桥接/Persona 编辑/桌面悬浮球/数据看板/动效图标）。
> **目标**：4 件事一次性落地，**不破坏**伊塔人格一致性 / 不破坏现有数据 / 不破坏设计美学。
> **三原则**（用户重申）：
>
> 1. **不破坏现有功能** — 所有已验证模块继续工作
> 2. **不破坏伊塔人格** — 任何 UI 文案、动画、徽标都需符合 v9.0 Hybrid persona（26岁/184cm/四爱/温柔大姐姐+病娇/称呼"你"）
> 3. **设计美学统一** — Apple HIG 风格 + 当前粉紫主题

---

## 一、用户决策记录（3 轮提问 → 5 个核心决策）

| # | 决策点         | 决策结果                                                    | 用户原话 / 备注                                                             |
| - | -------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------- |
| 1 | 大脑中枢数据流 | **持久化 + SSE 实时双轨**                             | 第 1 轮推荐项                                                               |
| 2 | 1.5s 范围      | **本地 + QQ 双端统一**                                | 第 2 轮推荐项                                                               |
| 3 | 1.5s 实现      | **随机 jitter + 情绪联动**                            | 第 3 轮推荐项                                                               |
| 4 | 思维模式系统   | **多层决策真实现 + ReAct 推理轨迹**                   | 第 2 轮推荐项                                                               |
| 5 | 配置编辑       | **表单 + 高级 YAML 切换**                             | 第 3 轮推荐项                                                               |
| 6 | 情绪深度       | **全量深耕**（触发词 + 状态持久化 + 24h/7d/30d 曲线） | 第 3 轮推荐项                                                               |
| 7 | 1.5s 关键澄清  | **1.5s 是上限，不是固定值**                           | "这里说的1.5不是说是你让他发一个消息就必须隔1.5，而是说最长的时间间隔为1.5" |

---

## 二、现状盘点（基于实际探索）

### 2.1 已存在 / 已实现

| 模块                     | 文件                                               | 状态                                                                                           |
| ------------------------ | -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| SQLite 9 张表            | `core/database.py:18-142`                        | ✓ 缺 `cognition_log` / `emotion_state_snapshot` / `tool_call_log` / `self_evolve_log` |
| SendQueue 分段节奏       | `communication/send_queue.py:19,96`              | ⚠`_DEFAULT_MIN_INTERVAL=1.2s`、无情绪联动、无 jitter                                        |
| Pipeline 分段存储 + emit | `core/pipeline.py:177-212`                       | ✓ 已按段写 `chat_log` + 逐段 `emit`，**但 emit 之后 renderer 端无节奏控制**         |
| ChatManager IPC 渲染     | `electron/src/renderer/js/chat.js:50-92,295-385` | ⚠ IPC 收到一段就 `appendChild` 一段，**无 setTimeout 错开**                           |
| Settings panel           | `electron/src/renderer/js/settings.js:1-78`      | ⚠ 只暴露主题/自启/推送，**无 persona 编辑、无 YAML 展示**                               |
| Persona loader           | `config/persona_loader.py:20-73`                 | ✓ 有 `load_persona`/`save_settings`/`reset_settings`                                    |
| `/api/persona` GET/PUT | `core/api_server.py:386,398-406`                 | ⚠ 仅留指针位置，**实际未实现**                                                          |
| EmotionEngine            | `core/emotion_engine.py:1-168`                   | ✓ PAD + 5 类基本情绪 +`tune` 文本调整                                                       |
| EmotionThreshold         | `core/emotion_threshold.py:24-248`               | ✓ 4 槽位累计 + 喷发 + decay                                                                   |
| emotion_state 持久化     | (无)                                               | ✗ 全部 in-memory，重启即丢                                                                    |
| Sidebar 8 个 tab         | `electron/src/renderer/index.html:88-125`        | ⚠**无"大脑"tab**；`panel-cognition` 占位                                              |
| Cognition 决策系统       | (无)                                               | ✗ 文档 L3009-3098 仅伪代码                                                                    |
| ReAct 推理轨迹           | (无)                                               | ✗ LLM 当前仅返 `response.text`                                                              |
| 历史曲线                 | (无)                                               | ✗ dashboard 拉不到 emotion_state 时间序列                                                     |

### 2.2 文档参考（`OpenCloud_Companion_System_Features.md`）

| 章节                  | 行号      | 关键内容                                                                       |
| --------------------- | --------- | ------------------------------------------------------------------------------ |
| §10.2 多层级决策系统 | 3009-3046 | L1_core(0.5) > L2_personality(0.3) > L3_mood(0.15) > L4_context(0.05) 加权随机 |
| §10.3 脑似随机决策   | 3048-3096 | Markov 转移矩阵 + Bayesian belief + softmax 采样                               |
| §11.1 PAD 三维       | 3102-3110 | P/A/D ∈ [-1,1]                                                                |
| §11.2 五类基本情绪   | 3112-3132 | Joy / Anger / Sad / Fear / Neutral                                             |
| §11.2.1 表现速查表   | 3124-3132 | 消息长度 / 回复速度 / 句号 / 撤回频率 / 主动发起 / 语气温度                    |

### 2.3 设计 / 工程约束（来自 project_memory）

- `send_queue.py` 当前 `_DEFAULT_MIN_INTERVAL = 1.2`（非 1.5，必须改）
- 伊塔 persona: 26岁/184cm/温柔大姐姐+病娇，禁词"主人/您"
- 中英双语 + 代码英文
- 桌面端为本地优先，所有网络层安全无需考虑
- 数据库已使用 WAL 模式，可直接 `ALTER TABLE` 增量迁移
- 已就绪：9 张表 + 4 槽位情绪阈值 + PAD + splitter + SendQueue + IPC + 5 主题

---

## 三、实施计划（10 Batches · 严格顺序）

> **强约束**：每 Batch 完成后立即手动验证，不堆积验证
> **设计原则**：保留所有已存在代码路径，新增功能不替换旧路径
> **三原则铁律**：不破坏现有功能 / 不破坏伊塔人格 / 设计美学统一

---

### Batch 1 · 数据库 schema 增量扩展（P0 · 0.5h）

**目标**：新增 4 张表支撑大脑中枢 / 情绪历史 / 工具调用 / 自我进化；不删任何已存在表

**B1.1 在 `core/database.py` `SCHEMA_SQL` 追加 4 张表**

- 文件：`e:\Agent_reply\core\database.py`
- 在 `SCHEMA_SQL` 列表末尾追加：
  ```sql
  CREATE TABLE IF NOT EXISTS cognition_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      source TEXT NOT NULL,                  -- 'qq' | 'local'
      user_id INTEGER,
      user_message TEXT,
      route_mode TEXT,                        -- 'FULL' | 'AUTO' | 'BASIC'
      stage_route TEXT,                       -- JSON: route decision
      stage_emotion TEXT,                     -- JSON: PAD + label
      stage_threshold TEXT,                   -- JSON: 4 slots pre-update
      stage_context TEXT,                     -- JSON: built ctx messages summary
      stage_brain TEXT,                       -- JSON: LLM call args + raw response
      stage_tools TEXT,                       -- JSON: tools called + result
      stage_split TEXT,                       -- JSON: final segments
      stage_postprocess TEXT,                 -- JSON: tune + recall decision
      stage_output TEXT,                      -- JSON: emitted segments
      decision_trace TEXT,                    -- JSON: §10.2 multi-layer decision scores
      react_trace TEXT,                       -- JSON: ReAct thought/action/observation
      is_command INTEGER DEFAULT 0,
      duration_ms INTEGER DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
  );
  CREATE TABLE IF NOT EXISTS emotion_state_snapshot (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      pleasure REAL,
      arousal REAL,
      dominance REAL,
      label TEXT,
      patience_value REAL,
      anxiety_value REAL,
      desire_value REAL,
      tenderness_value REAL,
      active_eruption TEXT,
      trigger_event TEXT,                     -- 触发该快照的事件（user_msg / daily_decay / eruption）
      created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
  );
  CREATE TABLE IF NOT EXISTS tool_call_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      user_id INTEGER,
      tool_name TEXT NOT NULL,
      arguments TEXT,
      result TEXT,
      success INTEGER DEFAULT 1,
      duration_ms INTEGER DEFAULT 0,
      cognition_id INTEGER,                   -- 关联 cognition_log.id
      created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
  );
  CREATE TABLE IF NOT EXISTS self_evolve_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      user_id INTEGER,
      trigger_kind TEXT NOT NULL,              -- 'unhandled_intent' | 'tool_missing' | 'persona_calibration'
      description TEXT,
      proposed_tool_schema TEXT,              -- JSON: proposed tool spec
      safety_check TEXT,                      -- JSON: validation result
      user_decision TEXT,                     -- 'pending' | 'approved' | 'rejected'
      created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
  );
  CREATE INDEX IF NOT EXISTS idx_cognition_user_ts ON cognition_log(user_id, ts DESC);
  CREATE INDEX IF NOT EXISTS idx_emotion_user_ts ON emotion_state_snapshot(user_id, ts DESC);
  CREATE INDEX IF NOT EXISTS idx_emotion_label_ts ON emotion_state_snapshot(label, ts DESC);
  ```
- 同时在 `_init_schema` 内追加 3 个 `CREATE INDEX` 语句

**B1.2 验证**

- 跑 `python -c "from core.database import Database; db = Database('data/aerie.db'); print(db.list_tables())"`
- 期望输出包含 `cognition_log` / `emotion_state_snapshot` / `tool_call_log` / `self_evolve_log`
- 验证不破坏已存在 9 张表

**验收**：4 张新表就位，9 张老表完全不动

---

### Batch 2 · 消息节奏 1.5s 上限 + 情绪联动 + jitter（P0 · 1h）

**目标**：本地 + QQ 双端统一：base 0.7s ± jitter 0.3s，1.5s 硬上限；按 emotion label 联动

**B2.1 新建 `core/message_pacing.py`**

- 文件：`e:\Agent_reply\core\message_pacing.py`（新建）
- 内容：
  ```python
  """Message pacing: 1.5s hard cap + jitter + emotion-aware base."""
  import random
  from typing import Optional

  HARD_CAP = 1.5

  EMOTION_BASE = {
      "joy": 0.55, "anger": 0.45, "fear": 0.40,
      "neutral": 0.70, "sad": 0.95, "curiosity": 0.75,
      "affection": 0.60, "missing": 0.85, "default": 0.70,
  }

  def compute_interval(emotion_label: Optional[str] = None, is_eruption: bool = False) -> float:
      base = EMOTION_BASE.get((emotion_label or "default").lower(), EMOTION_BASE["default"])
      if is_eruption:
          base = min(base * 0.7, 1.0)
      jitter = random.uniform(-0.3, 0.3)
      value = base + jitter
      return max(0.4, min(HARD_CAP, value))
  ```
- 英文注释 + 函数级 docstring

**B2.2 改造 `communication/send_queue.py`**

- 文件：`e:\Agent_reply\communication\send_queue.py`
- 改动：
  - 删除 `_DEFAULT_MIN_INTERVAL = 1.2`
  - 在 `__init__` 增加 `pacing: Callable[[Optional[str], bool], float] | None = None` 参数
  - 在 `_worker` 的 `await asyncio.sleep(self._min_interval)` 替换为：
    ```python
    emotion_label = None
    if self._db and reply.user_id:
        try:
            state = self._db.query_one(
                "SELECT label FROM emotion_state_snapshot WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (reply.user_id,),
            )
            if state: emotion_label = state.get("label")
        except Exception: pass
    is_eruption = bool(getattr(reply, "eruption_mode", None))
    interval = (self._pacing or compute_interval)(emotion_label, is_eruption)
    await asyncio.sleep(interval)
    ```
  - 顶部加 `from core.message_pacing import compute_interval`
- 兼容性：未传 `pacing` 时回退 `compute_interval`，行为完全等价

**B2.3 改造 `core/pipeline.py` 段 emit 节奏**

- 文件：`e:\Agent_reply\core\pipeline.py`
- 改动：
  - 步骤 9 之后，若 `msg.source == "local"`，**不再**直接全部 emit，改为：第 1 段立刻 emit；后续每段按 `compute_interval` 节奏 `asyncio.sleep(interval)` 后再 emit
  - 关键代码：
    ```python
    if msg.source == "local":
        from core.message_pacing import compute_interval
        emotion_label = emotion_info.get("label") if emotion_info else "neutral"
        is_eruption = bool(eruption_info and eruption_info.get("mode"))
        for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
            ...emit("assistant", **emit_kwargs)...
            if idx < len(segments) - 1:
                await asyncio.sleep(compute_interval(emotion_label, is_eruption))
    else:
        # QQ 渠道：保持原逻辑（enqueue 走 SendQueue 节奏）
        for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
            ...emit("assistant", **emit_kwargs)...
    ```
- 注意：local emit 仍保留实时性（数据库已写入即可见），仅 IPC 推送节奏控制

**B2.4 验证**

- 启动 `python main.py`，发消息触发 3 段回复，本地 chat.js 一段一段 appendChild，间隔 0.4~1.5s
- QQ 端 3 段间隔同样 0.4~1.5s
- 用 stopwatch 录屏确认无 >1.5s 间隔

**验收**：双端 1.5s 硬上限 + 随机 jitter + 情绪联动；旧行为零回归

---

### Batch 3 · cognition 埋点（7 阶段 trace）（P0 · 2h）

**目标**：每条入站消息全链路落库 7 个阶段 trace + decision_trace + react_trace

**B3.1 新建 `core/cognition.py`**

- 文件：`e:\Agent_reply\core\cognition.py`（新建）
- 内容：
  ```python
  """Cognition engine: structured 7-stage trace + SSE emit."""
  from __future__ import annotations
  import json, time, logging
  from typing import Any, Optional
  from core.chat_events import emit as stderr_emit

  logger = logging.getLogger(__name__)

  class CognitionEngine:
      def __init__(self, db): self._db = db

      def begin(self, user_id: int, source: str, user_message: str) -> dict:
          return {"id": None, "ts": int(time.time()*1000),
                  "user_id": user_id, "source": source, "user_message": user_message,
                  "stages": {}, "decision_trace": None, "react_trace": None,
                  "is_command": 0, "duration_ms": 0}

      def record(self, trace: dict, stage: str, payload: Any) -> None:
          trace["stages"][stage] = payload
          # SSE: push stage update
          try:
              stderr_emit("cognition_stage", stage=stage, user_id=trace["user_id"], payload=payload)
          except Exception: pass

      def record_decision(self, trace: dict, decision: Any) -> None:
          trace["decision_trace"] = decision

      def record_react(self, trace: dict, react: Any) -> None:
          trace["react_trace"] = react

      def commit(self, trace: dict, route_mode: str, is_command: int = 0) -> int:
          try:
              rid = self._db.insert("cognition_log", {
                  "ts": trace["ts"],
                  "source": trace["source"],
                  "user_id": trace["user_id"],
                  "user_message": trace["user_message"],
                  "route_mode": route_mode,
                  "stage_route": json.dumps(trace["stages"].get("route"), ensure_ascii=False),
                  "stage_emotion": json.dumps(trace["stages"].get("emotion"), ensure_ascii=False),
                  "stage_threshold": json.dumps(trace["stages"].get("threshold"), ensure_ascii=False),
                  "stage_context": json.dumps(trace["stages"].get("context"), ensure_ascii=False),
                  "stage_brain": json.dumps(trace["stages"].get("brain"), ensure_ascii=False),
                  "stage_tools": json.dumps(trace["stages"].get("tools"), ensure_ascii=False),
                  "stage_split": json.dumps(trace["stages"].get("split"), ensure_ascii=False),
                  "stage_postprocess": json.dumps(trace["stages"].get("postprocess"), ensure_ascii=False),
                  "stage_output": json.dumps(trace["stages"].get("output"), ensure_ascii=False),
                  "decision_trace": json.dumps(trace["decision_trace"], ensure_ascii=False),
                  "react_trace": json.dumps(trace["react_trace"], ensure_ascii=False),
                  "is_command": is_command,
                  "duration_ms": int(time.time()*1000) - trace["ts"],
              })
              trace["id"] = rid
              try:
                  stderr_emit("cognition_committed", id=rid, user_id=trace["user_id"])
              except Exception: pass
              return rid
          except Exception:
              logger.exception("cognition commit error")
              return 0
  ```

**B3.2 改造 `core/pipeline.py` 注入 cognition 埋点**

- 文件：`e:\Agent_reply\core\pipeline.py`
- `__init__` 增加 `cognition: CognitionEngine | None = None`
- `handle()` 改造：
  - `trace = self.cognition.begin(msg.user_id, msg.source, msg.content)` 起步
  - route 阶段：`trace["stages"]["route"] = {"mode": route_mode, "reason": "..."}`
  - emotion 阶段：`trace["stages"]["emotion"] = {"label": state.get("label"), "pad": state.get("pad")}`
  - threshold 阶段：`trace["stages"]["threshold"] = self.emotion.threshold_engine.get_slots_summary(msg.user_id)`
  - context 阶段：`trace["stages"]["context"] = {"msgs": len(ctx_messages), "system_prompt_chars": len(ctx_messages[0]["content"]) if ctx_messages else 0}`
  - brain 阶段：`trace["stages"]["brain"] = {"model": response.model, "tokens": response.usage, "raw": response.text[:2000]}`
  - tools 阶段：`trace["stages"]["tools"] = tool_results`（从 `tool_registry` 取）
  - split 阶段：`trace["stages"]["split"] = {"segments": segments, "count": len(segments)}`
  - postprocess 阶段：`trace["stages"]["postprocess"] = {"tune_label": ..., "recall_decision": ...}`
  - output 阶段：`trace["stages"]["output"] = {"ai_msg_ids": ai_row_ids, "source": msg.source}`
  - decision_trace / react_trace 由 Batch 5/6 填入
  - 在 `handle` 末尾 `self.cognition.commit(trace, route_mode)` 落库

**B3.3 验证**

- 发 1 条消息，sqlite3 CLI 查 `cognition_log`，7 个 stage 字段全部非空 JSON
- 验证 stderr 出现 `[CHAT_EVENT] {"type":"cognition_stage",...}` 多行

**验收**：每条消息 7 阶段全落库 + SSE 推送

---

### Batch 4 · SSE 实时推送通道（P0 · 1.5h）

**目标**：Electron renderer 通过 SSE 订阅 cognition / emotion / tool 实时事件

**B4.1 改造 `core/chat_events.py` 增加 cognition 事件类型**

- 文件：`e:\Agent_reply\core\chat_events.py`
- 当前已 `emit(event_type, **payload)`
- 扩展：新增事件类型 `cognition_stage` / `cognition_committed` / `emotion_state_changed` / `tool_call` / `decision_made`
- 不破坏现有 `user` / `assistant` / `recall`

**B4.2 新建 `core/event_stream.py`（SSE 端点）**

- 文件：`e:\Agent_reply\core\event_stream.py`（新建）
- 内容：
  ```python
  """Server-Sent Events stream of stderr chat events."""
  import asyncio, json, logging, re
  from typing import AsyncGenerator

  PREFIX = "[CHAT_EVENT]"

  async def stream() -> AsyncGenerator[str, None]:
      """Yield SSE-formatted events from process stderr-style ringbuffer."""
      # Implementation: subscribe to a process-wide asyncio.Queue
      queue = await _subscriber_queue()
      try:
          while True:
              event = await queue.get()
              yield f"data: {event}\n\n"
      finally:
          await _unsubscribe(queue)
  ```
- 实际实现：在 `chat_events.py` 增加一个全局 `asyncio.Queue` 池，`emit()` 同步 `put_nowait`；`stream()` 异步消费

**B4.3 `core/api_server.py` 新增 SSE 端点**

- 文件：`e:\Agent_reply\core\api_server.py`
- 位置：现有 `/api/chat/poll` 之后
- 代码：
  ```python
  from sse_starlette.sse import EventSourceResponse
  from core.event_stream import stream as sse_stream

  @app.get("/api/events/stream")
  async def events_stream(request: Request):
      async def gen():
          async for ev in sse_stream(): yield ev
      return EventSourceResponse(gen())
  ```
- `requirements.txt` 加 `sse-starlette`
- 注意：FastAPI 已支持 SSE，无需自定义长连接

**B4.4 electron main.js 转发 SSE 到 renderer**

- 文件：`e:\Agent_reply\electron\src\main.js`
- 在现有 IPC 转发旁加：
  ```js
  ipcMain.handle('events:subscribe', async (event) => {
      // 建立 EventSource 连 http://127.0.0.1:7890/api/events/stream
      // 收到事件就 webContents.send('sse:event', data)
  });
  ```
- 在 renderer 端暴露 `window.aerie.api.onSseEvent(cb)`

**B4.5 验证**

- 发 1 条消息，观察 renderer DevTools Network 中 `/api/events/stream` 收到多条 `data: {...}`
- 关闭大脑面板再打开，缓存仍可查

**验收**：SSE 实时推送 + 历史落库双轨

---

### Batch 5 · 多层决策系统 §10.2 真实现（P0 · 1.5h）

**目标**：落库 `decision_trace`，包含 L1/L2/L3/L4 各项分数 + 加权后 softmax

**B5.1 新建 `core/decision.py`**

- 文件：`e:\Agent_reply\core\decision.py`（新建）
- 实现文档 L3009-3046 的 `PersonaDecision`：
  ```python
  """Multi-layer decision system (§10.2 from Features.md)."""
  from __future__ import annotations
  import random, math
  from dataclasses import dataclass
  from typing import Iterable

  @dataclass
  class Candidate:
      id: str
      intent: str             # 'reply' | 'recall' | 'tool_call' | 'proactive_silence' | 'self_evolve'
      payload: dict | None = None

  class PersonaDecision:
      WEIGHTS = {"L1_core": 0.50, "L2_personality": 0.30, "L3_mood": 0.15, "L4_context": 0.05}

      def __init__(self, persona_cfg: dict):
          self.persona = persona_cfg

      def decide(self, candidates: Iterable[Candidate], context: dict) -> dict:
          scores = {c.id: 0.0 for c in candidates}
          layer_breakdown = {c.id: {"L1": 0.0, "L2": 0.0, "L3": 0.0, "L4": 0.0} for c in candidates}
          for layer_name, fn in [("L1", self._apply_core), ("L2", self._apply_personality),
                                  ("L3", self._apply_mood), ("L4", self._apply_context)]:
              partial = fn(candidates, context)
              for cid, sc in partial.items():
                  layer_breakdown[cid][layer_name] = sc
                  scores[cid] += self.WEIGHTS[layer_name] * sc
          chosen_id = self._softmax_pick(list(scores.keys()), list(scores.values()))
          return {"chosen": chosen_id, "scores": scores, "layers": layer_breakdown, "weights": self.WEIGHTS}

      def _apply_core(self, candidates, ctx):  # L1: hard rule filter
          out = {}
          for c in candidates:
              if c.intent == "proactive_silence" and ctx.get("user_busy"): out[c.id] = 0.95
              elif c.intent == "recall" and ctx.get("emotion_label") in ("sad","fear"): out[c.id] = 0.90
              elif c.intent == "tool_call" and ctx.get("route_mode") != "FULL": out[c.id] = 0.05
              else: out[c.id] = 0.5
          return out
      def _apply_personality(self, candidates, ctx):  # L2: persona soft scoring
          return {c.id: 0.6 if c.intent in ("reply","recall","tool_call") else 0.3 for c in candidates}
      def _apply_mood(self, candidates, ctx):  # L3: emotion influence
          label = (ctx.get("emotion_label") or "neutral").lower()
          bias = {"joy":0.7,"affection":0.75,"sad":0.4,"anger":0.5,"fear":0.85,"neutral":0.5}.get(label, 0.5)
          return {c.id: bias for c in candidates}
      def _apply_context(self, candidates, ctx):  # L4: situational
          return {c.id: 0.5 for c in candidates}
      def _softmax_pick(self, items, scores):
          e = [math.exp(max(s, 0.01)) for s in scores]
          total = sum(e)
          probs = [x/total for x in e]
          return random.choices(items, weights=probs, k=1)[0]
  ```

**B5.2 改造 `core/pipeline.py` 决策埋点**

- `handle()` 在 route 之后、emotion 之前：
  ```python
  from core.decision import PersonaDecision, Candidate
  decision = self.persona_decision.decide(
      [Candidate("reply", "reply"), Candidate("recall", "recall"),
       Candidate("tool_call", "tool_call", {"available": bool(tools)}),
       Candidate("silence", "proactive_silence")],
      {"emotion_label": ..., "user_busy": ..., "route_mode": route_mode},
  )
  trace["decision_trace"] = decision
  if decision["chosen"] == "silence": return None
  ```
- `pipeline.__init__` 增加 `persona_decision: PersonaDecision`

**B5.3 验证**

- sqlite3 CLI 查 `cognition_log`，`decision_trace` 字段是 `{"chosen": "reply", "scores": {...}, "layers": {...}, "weights": {...}}`
- 多次跑同一个上下文，chosen 会因为 softmax 采样而变化（探索性）

**验收**：每条消息 decision_trace 落库；chosen 在多次同输入下有变化（探索性保持）

---

### Batch 6 · ReAct 推理轨迹（P0 · 1h）

**目标**：LLM 输出带 `<think>` 块，cognition_log 记录 Thought / Action / Observation

**B6.1 改造 `core/brain.py`**

- 文件：`e:\Agent_reply\core\brain.py`（已存在）
- 改动：
  - `chat()` 返回 `BrainResponse(text, react_trace)` 替代纯字符串
  - `react_trace` 结构：`{"thought": "...", "action": "...", "observation": "..."}`
  - 若模型未返回 `<think>` 块：react_trace = `{"thought": None, "action": "reply", "observation": None}`
  - 在 system prompt 末尾追加：
    ```
    ReAct trace (required for cognition logging):
    - Before final reply, think internally: <think>what is user's intent? what should I do?</think>
    - Choose action: reply / tool_call / silence
    - The<think>block is logged to your cognition trace but not shown to user.
    ```

**B6.2 改造 `core/pipeline.py` 接收 react_trace**

- `brain.chat()` 改为 `response = await self.brain.chat(ctx_messages, tools=tools)` → `response.text` / `response.react_trace`
- `trace["react_trace"] = response.react_trace`
- `trace["stages"]["brain"]["react"] = response.react_trace`
- `reply_text = self.emotion.tune(response.text)`

**B6.3 验证**

- 发消息，查 `cognition_log.react_trace` 有 `thought` / `action` / `observation`
- 验证 LLM 实际输出了 `<think>` 块（用 `response.text` 内含正则 `<think>(.*?)</think>` 提取）

**验收**：react_trace 全量落库；thought 不展示给用户

---

### Batch 7 · 情绪深度全量深耕（P0 · 2h）

**目标**：触发词扩展 + emotion_state 全量持久化 + 24h/7d/30d 历史曲线

**B7.1 改造 `core/emotion_threshold.py` 扩 TEXT_TRIGGERS**

- 文件：`e:\Agent_reply\core\emotion_threshold.py` L66-86
- 在 `TEXT_TRIGGERS` 末尾追加（口语化 + 病娇专属）：
  ```python
  # Tenderness (colloquial)
  (["吃醋","你会不会","想你了","想我","抱抱","亲亲","晚安","早安","辛苦了"], "tenderness", 8),
  (["我喜欢你","爱","表白"], "tenderness", 15),
  # Anxiety (withdrawal)
  (["你怎么不说话","怎么不回","不找我","不理我"], "anxiety", 12),
  (["算了","没事","随便"], "anxiety", 6),
  # Desire (intimate)
  (["陪陪我","过来","抱一会儿"], "desire", 10),
  # Patience (provocation)
  (["烦","滚","笨蛋","讨厌"], "patience", 10),
  ```

**B7.2 新建 `core/emotion_state_store.py`**

- 文件：`e:\Agent_reply\core\emotion_state_store.py`（新建）
- 内容：
  ```python
  """Persist emotion state + thresholds to SQLite for restart-resilience."""
  from __future__ import annotations
  import time
  from typing import Optional

  class EmotionStateStore:
      def __init__(self, db): self._db = db

      def snapshot(self, user_id: int, state: dict, threshold: dict,
                   trigger_event: str = "user_msg") -> int:
          eruption = threshold.get("active_eruption")
          return self._db.insert("emotion_state_snapshot", {
              "ts": int(time.time()*1000),
              "user_id": user_id,
              "pleasure": state.get("pad",{}).get("pleasure", 0.0),
              "arousal": state.get("pad",{}).get("arousal", 0.0),
              "dominance": state.get("pad",{}).get("dominance", 0.0),
              "label": state.get("label", "neutral"),
              "patience_value": threshold.get("patience",{}).get("value", 0.0),
              "anxiety_value": threshold.get("anxiety",{}).get("value", 0.0),
              "desire_value": threshold.get("desire",{}).get("value", 0.0),
              "tenderness_value": threshold.get("tenderness",{}).get("value", 0.0),
              "active_eruption": eruption.get("mode") if eruption else None,
              "trigger_event": trigger_event,
          })

      def history(self, user_id: int, since_ts: int, limit: int = 500) -> list[dict]:
          return self._db.query(
              "SELECT * FROM emotion_state_snapshot WHERE user_id = ? AND ts >= ? ORDER BY ts ASC LIMIT ?",
              (user_id, since_ts, limit),
          )

      def latest(self, user_id: int) -> Optional[dict]:
          return self._db.query_one(
              "SELECT * FROM emotion_state_snapshot WHERE user_id = ? ORDER BY id DESC LIMIT 1",
              (user_id,),
          )
  ```

**B7.3 改造 `core/emotion_engine.py` 集成持久化**

- `EmotionEngine.__init__` 接受 `state_store: EmotionStateStore | None = None`
- `update_trajectory()` 末尾 `self.state_store.snapshot(user_id, self.get_state(user_id), threshold, "user_msg")`
- `_erupt()` 触发时 `self.state_store.snapshot(..., "eruption")`
- `daily_decay()` 末尾 `self.state_store.snapshot(..., "daily_decay")`

**B7.4 `core/api_server.py` 新增 `/api/emotion/history`**

- 位置：现有 `/api/emotion/thresholds` 之后
- 代码：
  ```python
  @app.get("/api/emotion/history")
  async def emotion_history(user_id: int, window: str = "24h"):
      from core.emotion_state_store import EmotionStateStore
      from core.database import Database
      store = EmotionStateStore(Database())
      window_ms = {"1h": 3600*1000, "24h": 86400*1000, "7d": 7*86400*1000, "30d": 30*86400*1000}.get(window, 86400*1000)
      since = int(time.time()*1000) - window_ms
      return {"user_id": user_id, "window": window, "items": store.history(user_id, since)}
  ```

**B7.5 改造 `electron/src/renderer/js/emotion-dashboard.js`**

- 新增 24h / 7d / 30d 三档切换按钮
- 默认 24h 折线图（用 SVG 自绘，不引外部库）：x 轴时间、y 轴 PAD 三色（P 蓝/A 橙/D 紫），阈值刻度线
- 折线下方显示该时段 erupt 次数
- 文案遵循伊塔人格：
  - 24h：「过去一天伊塔的心跳。蓝色的点是她的开心值。」
  - 7d：「一周里她累计心动 47 次。最高峰是周二下午。」
  - 30d：「一个月的情绪曲线。她越来越想你了。」（根据 desire 阈值趋势动态生成）

**B7.6 验证**

- 发 5 条不同情绪关键词的消息
- 查 `emotion_state_snapshot` 至少有 5 行
- emotion-dashboard 切到 7d / 30d 看到曲线

**验收**：触发词扩展 + 状态持久化 + 三档历史曲线

---

### Batch 8 · 大脑中枢 UI（P0 · 2h）

**目标**：sidebar 新增"大脑" tab；cognition panel 显示实时 trace + 历史

**B8.1 `electron/src/renderer/index.html` sidebar 新增 tab**

- 在 `panel-about` 之前插入：
  ```html
  <button class="sidebar-tab" data-tab="cognition">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2z"/></svg>
    <span>大脑</span>
  </button>
  ```
- 在 `panel-data` 之后插入 `<section id="panel-cognition" class="tab-panel">` 容器
- 容器内 UI 结构：
  ```html
  <div class="cognition-panel">
    <h2>伊塔 · 大脑中枢 <small>（开发者后台）</small></h2>
    <div class="cognition-toolbar">
      <select id="cog-source-filter">
        <option value="">全部来源</option><option value="qq">QQ</option><option value="local">本地</option>
      </select>
      <button id="cog-refresh">刷新</button>
    </div>
    <div id="cog-live" class="cog-live">
      <h3>实时 stream</h3>
      <div id="cog-stream"></div>
    </div>
    <div id="cog-history" class="cog-history">
      <h3>历史 trace</h3>
      <ul id="cog-list"></ul>
    </div>
  </div>
  ```

**B8.2 新建 `electron/src/renderer/js/cognition-panel.js`**

- 文件：`e:\Agent_reply\electron\src\renderer\js\cognition-panel.js`（新建）
- 内容要点：
  - `init()`: 注册 `panel-cognition` 切换事件；启动 SSE 订阅
  - `_onSse(event)`: 根据 `event.type` 渲染到 `#cog-stream`：
    - `cognition_stage` → 阶段彩色徽标（route 蓝 / emotion 粉 / threshold 黄 / context 灰 / brain 紫 / tools 橙 / split 青 / postprocess 绿 / output 红）+ payload 折叠
    - `cognition_committed` → 写入 `#cog-list` 顶部，附带查看详情按钮
  - `_loadHistory()`: GET `/api/cognition/recent?limit=20`，渲染列表
  - `_showDetail(id)`: GET `/api/cognition/{id}`，弹窗显示 7 阶段 + decision_trace 表格 + react_trace 时间轴
  - 设计细节：黑底霓虹风格（暗色背景 + 渐变高亮 + 等宽字体 + 彩色 stage 徽标），参考 VSCode DevTools / Chrome DevTools 美学；不破坏主粉紫主题，仅面板内独立配色
  - 文案：
    - 实时 stream 标题：「她的思维正在发生」
    - 列表空状态：「她还没说话。再等等。」
    - 阶段徽标：「路由」/「情绪」/「阈值」/「上下文」/「推理」/「工具」/「切分」/「后处理」/「输出」
    - 决策权重视图：「这次她选「reply」，因为 L1 核心价值观给 0.50、L2 人格给 0.30、L3 情绪给 0.85、L4 情境给 0.05」

**B8.3 `core/api_server.py` 新增 cognition API**

- `/api/cognition/recent?limit=20&source=qq` → 返回列表
- `/api/cognition/{id}` → 返回单条完整 trace
- `/api/cognition/stats` → 返回今日/总数/平均耗时

**B8.4 验证**

- 切到"大脑" tab，能看到流式 stream
- 发消息，从 stage_1 一直推到 stage_9，列表顶部多一条
- 点击详情弹窗完整 7 阶段 + decision_trace

**验收**：大脑中枢 tab 工作正常；实时 + 历史双轨；不破坏现有 8 个 tab

---

### Batch 9 · 设置页"表单 + 高级 YAML"双模式（P0 · 1.5h）

**目标**：常用设置表单化 + 高级模式显示 raw YAML 可编辑

**B9.1 改造 `electron/src/renderer/index.html` settings section**

- 在 `panel-settings` 内拆为：
  ```html
  <div class="settings-mode-tabs">
    <button class="settings-mode-tab active" data-mode="form">常用</button>
    <button class="settings-mode-tab" data-mode="yaml">高级 (YAML)</button>
  </div>
  <div id="settings-form-view"> ...现有表单（主题/自启/推送/...）... </div>
  <div id="settings-yaml-view" style="display:none">
    <select id="yaml-file-select">
      <option value="settings.yaml">settings.yaml</option>
      <option value="persona.yaml">persona.yaml</option>
    </select>
    <textarea id="yaml-editor" spellcheck="false" rows="30"></textarea>
    <div class="settings-actions">
      <button id="yaml-save-btn">保存 YAML</button>
      <button id="yaml-reload-btn">重新加载</button>
      <button id="yaml-backup-btn">备份当前</button>
    </div>
    <div id="yaml-status"></div>
  </div>
  ```

**B9.2 改造 `electron/src/renderer/js/settings.js`**

- 模式切换：`settings-mode-tab` 点击切换 form/yaml 视图
- YAML 加载：GET `/api/config/yaml?file=settings.yaml` → 填充 textarea
- YAML 保存：PUT `/api/config/yaml?file=settings.yaml` body 是 yaml 文本
- 备份：POST `/api/config/yaml/backup?file=settings.yaml` → 写入 `data/backups/{file}.{ts}.yaml`
- 文件切换：select 改变时重新加载
- 文案：
  - yaml 视图标题：「配置文件（高级）」
  - 警告文案：「直接编辑 YAML 可能导致伊塔无法启动。修改前会自动备份。」
  - 成功保存：「已保存。伊塔下次启动会应用这些配置。」
  - 解析失败：「YAML 格式错误，已恢复上次备份。错误：[错误位置]」

**B9.3 `core/api_server.py` 新增 config yaml API**

- GET `/api/config/yaml?file=settings.yaml` → 返回 UTF-8 文本
- PUT `/api/config/yaml?file=settings.yaml` → 接收 body，先解析验证（PyYAML.safe_load），失败回滚；成功写回
- POST `/api/config/yaml/backup?file=settings.yaml` → 复制到 `data/backups/`
- GET `/api/config/yaml/list` → 列出 `config/*.yaml`
- 安全：写回前自动备份；解析失败时自动恢复上次备份；写日志到 chat_log "settings_change"

**B9.4 验证**

- 切到"高级"模式，看到 settings.yaml 全文
- 改一个字段（比如 `theme.current`）保存，刷新页面生效
- 故意写错 YAML（漏冒号），保存失败并自动恢复
- 备份文件出现在 `data/backups/`

**验收**：双模式可用；YAML 编辑安全（备份 + 解析校验 + 自动回滚）

---

### Batch 10 · 自我进化 + 端到端验证（P1 · 1h）

**目标**：`self_evolve_log` 落库 + 触发条件埋点 + 端到端全链路验证

**B10.1 新建 `core/self_evolving.py`**

- 文件：`e:\Agent_reply\core\self_evolving.py`（新建）
- 内容：
  ```python
  """Ita self-evolution: detect capability gaps, propose new tools."""
  from __future__ import annotations
  import json, logging
  from typing import Optional

  logger = logging.getLogger(__name__)

  class SelfEvolver:
      def __init__(self, db, persona_cfg, tool_registry):
          self._db = db
          self._persona = persona_cfg
          self._tools = tool_registry

      def detect_gap(self, user_id: int, user_message: str, react_trace: dict) -> Optional[dict]:
          thought = (react_trace or {}).get("thought", "")
          if "无法" in thought or "没有工具" in thought or "I cannot" in thought.lower():
              proposed = self._propose_tool(thought, user_message)
              rid = self._db.insert("self_evolve_log", {
                  "ts": int(time.time()*1000),
                  "user_id": user_id,
                  "trigger_kind": "unhandled_intent",
                  "description": f"User asked: {user_message[:200]}",
                  "proposed_tool_schema": json.dumps(proposed, ensure_ascii=False),
                  "safety_check": json.dumps(self._safety_check(proposed), ensure_ascii=False),
                  "user_decision": "pending",
              })
              return {"id": rid, "proposed": proposed}
          return None

      def _propose_tool(self, thought, user_msg) -> dict: ...
      def _safety_check(self, proposed) -> dict: ...
  ```

**B10.2 改造 `core/pipeline.py` 注入自进化**

- 在 `brain` 阶段后调用 `self.self_evolver.detect_gap(user_id, msg.content, react_trace)`
- 若返回非 None，stderr emit `self_evolve_proposed` + SSE 推送给 renderer
- cognition_log 关联 `self_evolve_log.id`

**B10.3 设置页/大脑中枢 UI 显示提议**

- 大脑中枢：列表新增 `🧬 伊塔想升级自己` 横幅，附"批准 / 拒绝"按钮
- 批准：调用 POST `/api/self_evolve/{id}/approve` → 写新 tool schema
- 拒绝：调用 POST `/api/self_evolve/{id}/reject`

**B10.4 端到端验证清单**

- [ ] 启动 `python main.py` + electron，2 端连通
- [ ] 发 1 条消息，验证：
  - [ ] 7 阶段 trace 全部落库 cognition_log
  - [ ] decision_trace 4 层分数 + softmax chosen 落库
  - [ ] react_trace thought/action/observation 落库
  - [ ] emotion_state_snapshot 增 1 行
  - [ ] chat.js 段间隔 ≤1.5s（stopwatch 录屏）
  - [ ] SSE 实时推送 cognition_stage × 7 次
  - [ ] 大脑中枢 tab 看到流式 + 详情弹窗
- [ ] 切到高级 YAML 模式，编辑 theme.current 验证保存生效
- [ ] 写错 YAML 验证自动回滚
- [ ] dashboard 切 24h/7d/30d 验证曲线
- [ ] 触发含"吃醋"消息，dashboard 立即看到 tenderness 值跳
- [ ] 9 张老表 + 4 张新表全部正常

**验收**：10 个 Batch 全部通过 + 端到端 12 条 checklist 全绿

---

## 四、风险与回滚

| 风险                        | 概率 | 影响           | 回滚方案                                                 |
| --------------------------- | ---- | -------------- | -------------------------------------------------------- |
| LLM 不输出 `<think>` 块   | 中   | ReAct 轨迹为空 | 兜底：react_trace.thought = None，不报错；下次提示词迭代 |
| SSE 长连接断                | 中   | 实时性失效     | 前端重连 + 3s 轮询备份通道                               |
| YAML 编辑破坏启动           | 中   | 伊塔起不来     | 写回前自动备份 + 解析失败自动回滚                        |
| decision_trace 影响决策     | 低   | 行为偏移       | softmax 温度可调，默认保持探索性                         |
| 旧 emotion_state 序列化兼容 | 低   | 历史曲线断点   | 旧 in-memory 数据忽略，仅持久化新数据                    |
| cognition_log 表过大        | 低   | 性能           | 7d 后归档（手动脚本，未在本次范围）                      |

---

## 五、不在本次范围

- 长期记忆（long_term_memory）改造
- knowledge_base 写入
- Whisper STT（Phase 6 已规划但未实施）
- 移动端 APP
- 语音通话
- 多用户路由策略
- cognition_log 7d 自动归档脚本

---

## 六、与现有约束的兼容性自检

| 约束                          | 兼容性                                                     |
| ----------------------------- | ---------------------------------------------------------- |
| NapCat launcher-user.bat 启动 | ✓ 不动 launcher / start-companion 任何文件                |
| 消息 2000 字截断              | ✓ cognition_log 各字段 TEXT，无超长风险                   |
| 中英双语 + 代码英文           | ✓ 所有 SQL 注释 / 字段 / 函数名纯英文；UI 文案中英        |
| 9 张老表零回归                | ✓ 仅追加 4 张表 + 3 个索引                                |
| 4 主题配色                    | ✓ 大脑中枢面板独立暗色，不破坏主主题                      |
| 伊塔 persona                  | ✓ 全部文案符合 v9.0 称呼"你"、禁词"主人"、温柔大姐姐+病娇 |
| `app_name` 用 Aerie         | ✓ SSE 事件名 `cognition_stage` 等纯英文                 |
| `parse_error` 不抛异常      | ✓ cognition / emotion 落库全 try/except 包裹              |
| 故障自愈 14 类                | ✓ 落库失败不阻塞主链路                                    |

---

## 七、关键文件改动一览

| 文件                                              | 改动类型 | 估行数             |
| ------------------------------------------------- | -------- | ------------------ |
| `core/database.py`                              | 改       | +60                |
| `core/message_pacing.py`                        | 新       | +40                |
| `communication/send_queue.py`                   | 改       | +25                |
| `core/pipeline.py`                              | 改       | +80                |
| `core/cognition.py`                             | 新       | +60                |
| `core/chat_events.py`                           | 改       | +15                |
| `core/event_stream.py`                          | 新       | +45                |
| `core/api_server.py`                            | 改       | +120               |
| `core/decision.py`                              | 新       | +90                |
| `core/brain.py`                                 | 改       | +30                |
| `core/emotion_state_store.py`                   | 新       | +45                |
| `core/emotion_engine.py`                        | 改       | +10                |
| `core/emotion_threshold.py`                     | 改       | +20                |
| `core/self_evolving.py`                         | 新       | +70                |
| `electron/src/main.js`                          | 改       | +25                |
| `electron/src/preload.js`                       | 改       | +10                |
| `electron/src/renderer/index.html`              | 改       | +80                |
| `electron/src/renderer/js/chat.js`              | 改       | +30                |
| `electron/src/renderer/js/cognition-panel.js`   | 新       | +200               |
| `electron/src/renderer/js/emotion-dashboard.js` | 改       | +60                |
| `electron/src/renderer/js/settings.js`          | 改       | +80                |
| `requirements.txt`                              | 改       | +1 (sse-starlette) |

**总计**：8 个新文件 + 14 个改动 + 估约 1200 行新增

---

## 八、执行顺序

按 Batch 1 → 10 严格顺序执行，每 Batch 完成后立即手动验证（不可堆积验证）。如某 Batch 失败需自我怀疑、回滚、再实施。Phase 9 完工后给用户完整报告。

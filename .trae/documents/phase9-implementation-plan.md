---
title: Phase 9 — 大脑中枢 + 1.5s 人格化节奏 + YAML 设置 + 自进化（整改版）
date: 2026-07-16
tags:
  - phase9
  - brain-center
  - persona-pacing
  - settings-yaml
  - emotion-persistence
  - self-evolve-sandbox
  - ita-persona
cssclasses:
  - wide-page
---
# Phase 9 — 大脑中枢 + 1.5s 人格化节奏 + YAML 设置 + 自进化（整改版）

> **核心精神（用户 2026-07-16 重申）**：
>
> 1. **第一段消息立即发送**——零延迟
> 2. **后续段由"思维模型"动态决定节奏**——可能 0.4s 急切，可能 1.5s 害羞，可能 3-5s 病娇式犹豫，可能 1 分钟沉思
> 3. **1.5s 是基线，不是上限**——「她也可以停顿 3 秒，也可以停顿一分钟，主要是思维模型必须自主化情感化，像一个真正的人一样」
> 4. **三原则铁律**：不破坏现有功能 / 不破坏伊塔人格 / 设计美学统一
> 5. **9 个用户决策**（3 轮提问）已全部锁定

---

## 一、9 个用户决策汇总

| # | 决策点              | 决策结果                                                     |
| - | ------------------- | ------------------------------------------------------------ |
| 1 | 大脑中枢 UI 风格    | **渐变玻璃风**（深色代码块+粉紫外壳）                  |
| 2 | 大脑中枢 9 阶段呈现 | **水平时间轴**（7 阶段 dot+连线）                      |
| 3 | 情绪历史曲线        | **PAD 三色折线 + 雷达热力图**（两个都做）              |
| 4 | 决策权重呈现        | **赛马图**（所有意图 PK）                              |
| 5 | 自我进化安全        | **提议+沙箱预演**（弹窗文本）                          |
| 6 | 沙箱预演表现        | **弹窗文本预演**（轻量）                               |
| 7 | 1.5s 节奏 E2E 验证  | **SQL 查表**（每段 created_at 差值 + 录屏 + 单测辅助） |
| 8 | Trace 列表展示      | **全量 + filter**（开发友好）                          |
| 9 | YAML 编辑颗粒度     | **仅 settings.yaml + persona.yaml**                    |

---

## 二、现状差距（基于实际探索）

### 2.1 已实现（不动）

| 模块                      | 文件                                   | 状态                  |
| ------------------------- | -------------------------------------- | --------------------- |
| 4 张新表                  | `core/database.py:142-214`           | ✓                    |
| 1.5s emotion label pacing | `core/message_pacing.py:1-67`        | ⚠ 需重写为人格化版本 |
| SendQueue 联动            | `communication/send_queue.py:60-125` | ⚠ 需用新 pacing      |
| Pipeline 9 阶段 trace     | `core/pipeline.py:52-335`            | ✓                    |
| Cognition 引擎            | `core/cognition.py:1-211`            | ✓                    |
| Decision 4 层             | `core/decision.py:1-225`             | ✓                    |
| Brain ReAct               | `core/brain.py:18-313`               | ✓                    |
| Emotion 40+ 触发词        | `core/emotion_engine.py:33-78`       | ✓                    |
| Threshold 40+ 触发词      | `core/emotion_threshold.py:66-121`   | ✓                    |
| Event stream SSE          | `core/event_stream.py:1-112`         | ✓                    |
| chat_events 桥接          | `core/chat_events.py:19-37`          | ✓                    |
| API 路由                  | `core/api_server.py:376-458`         | ✓                    |
| 9 张老表                  | `core/database.py:17-141`            | ✓ 不动               |

### 2.2 关键缺失（需整改）

| 缺口                                                                       | 后果                                                                | 优先级       |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------ |
| `core/emotion_state_store.py` 完全缺失                                   | `/api/emotion/history` API 已就绪但**表里没数据**           | **P0** |
| `EmotionEngine` 未调用 `state_store.snapshot()`                        | 持久化未触发，dashboard 拉不到历史                                  | **P0** |
| `core/persona_pacing.py` 不存在                                          | 当前 message_pacing 是 emotion label 静态映射，**不是人格化** | **P0** |
| `pipeline.py` 第 1 段没有立即发送                                        | 违反用户最新澄清                                                    | **P0** |
| Sidebar**"大脑"tab** 缺失                                                  | 大脑中枢无入口                                                      | **P0** |
| `cognition-panel.js` 缺失                                                | 实时流+历史+详情弹窗全部无                                          | **P0** |
| settings 双模式（form + YAML）缺失                                         | 用户无法查看/编辑 raw 配置                                          | **P0** |
| `/api/config/yaml/*` 端点缺失                                            | 备份/回滚/校验全无                                                  | **P0** |
| `core/self_evolving.py` 缺失                                             | 自我进化机制零代码                                                  | **P0** |
| `emotion-dashboard.js` 缺 24h/7d/30d 曲线                                | 折线图+雷达图全无                                                   | **P0** |
| `emotion-dashboard.js` 读 `pad.P` 而 `emotion_engine` 返回 `P/A/D` | **隐患 bug**：PAD 卡显示永远是 0.00                           | **P1** |
| `api_server.py` `/api/config/yaml/*` 缺失                              | 端点不存在                                                          | **P0** |
| cognition_panel 缺 SSE 订阅 IPC 桥接                                       | 实时流无法到 renderer                                               | **P0** |
| 页面美观度                                                                 | 用户自行添加，增加毛玻璃质感、与自定义设置                          |              |
| 美化UI                                                                     | 把里面的全部内容组件模块都根据对应的主题进行美化                    |              |

---

## 三、核心设计哲学调整（用户最新澄清后）

### 3.1 Pacing 从"emotion label 静态映射"升级为"persona-aware dynamic pacing"

**新模型**（`core/persona_pacing.py`）：

```python
# ── 核心原则 ──
# 1. 第 1 段：立即（0 延迟）—— 用户原文：「第一条消息是及时的，是没有延迟的」
# 2. 后续段：按 persona-driven decision tree 动态选择节奏模板
# 3. 1.5s 是"基线"（balanced 模式），不是上限
# 4. 5% 概率触发"病娇式情感犹豫"：2-5s
# 5. 3% 概率触发"沉思模式"：2.5-4s
# 6. 极端情绪（joy/anger/fear）：0.4-0.7s 急切
# 7. 冷暴力（sad/patience-eruption）：0.9-1.7s 故意慢回

PacingStyle = {
    "immediate": (0.0, 0.0),           # 第 1 段
    "eager_warm": (0.4, 0.7),          # joy / missing / affection
    "eager_eruption": (0.4, 0.7),      # 喷发时急切
    "anxious_fast": (0.5, 1.0),        # fear（害怕失去）
    "balanced": (0.6, 1.0),            # neutral 默认
    "shy_hesitation": (1.4, 1.9),      # neutral 10% 概率 "想表达但不好意思"
    "shy_tenderness_pause": (1.2, 1.7),# 反扑模式（被温柔击中）
    "yandere_collapse_pause": (1.0, 1.8),# 坍塌模式（犹豫+欲言又止）
    "cold_slow": (0.9, 1.6),           # sad / anger / 冷暴力
    "contemplative": (2.5, 4.0),       # 3% 概率长时间沉思
    "yandere_erase_hesitate": (2.0, 5.0),# 5% 概率"病娇式想撤回"犹豫
}
```

### 3.2 第 1 段立即发送（结构性改变）

- 当前 pipeline：所有段都过 pacing（包括第 1 段）
- 新 pipeline：第 1 段 `await asyncio.sleep(0)`；第 2 段起走 `compute_persona_interval()`

### 3.3 大脑中枢渐变玻璃风

- 容器背景：粉紫渐变 + 10% 玻璃模糊（backdrop-filter: blur）
- 代码块：深色 #1a1a2e + 暖色高亮（伊塔粉 #ff5b9c）
- 阶段徽标：7 色（route 蓝 / emotion 粉 / threshold 黄 / context 灰 / brain 紫 / tools 橙 / split 青 / postprocess 绿 / output 红）

### 3.4 决策权重赛马图

- 4 个候选意图（reply / tool_call / recall / silence）以赛马图形式并排
- 每条赛马 = 4 层加权后总分
- 胜出高亮（伊塔粉描边 + 微弱脉动）
- 4 层权重在赛马下方堆叠展示（L1 蓝 / L2 紫 / L3 粉 / L4 灰）

---

## 四、6 个 Batch 实施计划（按依赖顺序严格串行）

> 每 Batch 完成后立即手动验证，不堆积验证
> 强约束：保留所有已存在代码路径，新增功能不替换旧路径

---

### Batch 1 · emotion 持久化（修最关键缺口 · P0 · 0.5h）

**目标**：把 emotion_state 真正写入 SQLite，让 dashboard 拉到历史

**B1.1 新建 `core/emotion_state_store.py`**

- 文件：`e:\Agent_reply\core\emotion_state_store.py`（新建）
- 类 `EmotionStateStore(db)`：
  - `snapshot(user_id, state, threshold, trigger_event)` 写入 1 行
  - `history(user_id, since_ts, limit)` 拉历史
  - `latest(user_id)` 拉最新 1 行
  - `aggregate(user_id, since_ts, bucket_ms)` 按时间段聚合（用于曲线）
- schema 完全对齐 `emotion_state_snapshot` 表（已存在）

**B1.2 改造 `core/emotion_engine.py` 集成持久化**

- `__init__` 接受 `state_store: EmotionStateStore | None = None`
- `update_trajectory()` 末尾 `self.state_store.snapshot(..., trigger_event="user_msg")`
- `daily_decay()` 末尾 `self.state_store.snapshot(..., trigger_event="daily_decay")`
- 喷发时（`_erupt` hook）`trigger_event="eruption"`

**B1.3 改造 `core/companion.py` 注入 state_store**

- 在 `Companion.__init__` 创建 `state_store = EmotionStateStore(self.db)`
- 注入到 `self.emotion = EmotionEngine(self.db, state_store=state_store)`

**B1.4 验证**

- 启动 `python main.py`，发 5 条不同情绪消息
- `sqlite3 data/aerie.db "SELECT COUNT(*) FROM emotion_state_snapshot"` 期望 ≥ 5
- `GET /api/emotion/history?window=1h` 返回 ≥ 5 条

**验收**：emotion_state_snapshot 真正写入；`/api/emotion/history` 有数据

---

### Batch 2 · 人格化 Pacing（核心 · P0 · 1.5h）

**目标**：第 1 段立即，后续段按 persona 决策树动态节奏

**B2.1 新建 `core/persona_pacing.py`**

- 文件：`e:\Agent_reply\core\persona_pacing.py`（新建）
- 函数 `compute_persona_interval(segment_index, emotion_label, threshold, is_eruption, segment_content) -> tuple[float, str]`：
  - segment_index == 0 → return (0.0, "immediate")
  - 按决策树选择 PacingStyle
  - 返回 (interval_seconds, style_label)
- 决策树见 §3.1
- 兼容 `core/message_pacing.compute_interval`（保留旧函数，旧调用点不动）

**B2.2 改造 `core/pipeline.py` 第 1 段立即 + 后续段 persona pacing**

- 步骤 12（emit 段）改造：
  ```python
  from core.persona_pacing import compute_persona_interval
  emotion_label = (emotion_info or {}).get("label") or "neutral"
  eruption_mode = (eruption_info or {}).get("mode") if eruption_info else None
  is_eruption = bool(eruption_mode)
  threshold_summary = (emotion_info or {}).get("thresholds", {})

  for idx, (seg, rid) in enumerate(zip(segments, ai_row_ids)):
      emit_kwargs = {"id": rid, "user_id": msg.user_id, "content": seg, "source": msg.source}
      emit("assistant", **emit_kwargs)

      if idx < len(segments) - 1:
          interval, style = compute_persona_interval(
              segment_index=idx,
              emotion_label=emotion_label,
              threshold=threshold_summary,
              is_eruption=is_eruption,
              segment_content=seg,
          )
          # 记录到 cognition trace 用于事后分析
          trace["stages"]["output"]["pacing_decisions"] = trace["stages"]["output"].get("pacing_decisions", [])
          trace["stages"]["output"]["pacing_decisions"].append({
              "seg_idx": idx,
              "style": style,
              "interval_ms": int(interval * 1000),
          })
          if interval > 0:
              await asyncio.sleep(interval)
  ```

**B2.3 改造 `communication/send_queue.py` 用 persona_pacing**

- 删除 `from core.message_pacing import compute_interval`
- 改为 `from core.persona_pacing import compute_persona_interval`
- `_worker` 中 `interval, style = compute_persona_interval(segment_index=idx, ...)`

**B2.4 验证**

- 启动后端，发 1 条会触发 3 段回复的消息
- 打开本地 chat 面板，肉眼观察第 1 段立即出现，后续段有节奏感
- `sqlite3 data/aerie.db "SELECT id, created_at FROM chat_log WHERE role='assistant' ORDER BY id DESC LIMIT 5"` 看时间差
- 录屏：≥ 30 秒确认无 0 间隔的多段（除第 1 段）

**验收**：第 1 段立即；后续段情感化节奏；1.5s 是常见值但允许 3-5s 病娇犹豫

---

### Batch 3 · 设置页双模式（form + YAML · P0 · 1.5h）

**目标**：常用设置 form + 高级 raw YAML 编辑（含备份/回滚）

**B3.1 改造 `core/api_server.py` 新增 4 个端点**

- `GET /api/config/yaml?file=settings.yaml` → 返回 UTF-8 文本
- `PUT /api/config/yaml?file=settings.yaml` → 接收 body，先解析验证（PyYAML.safe_load），失败回滚；成功写回
- `POST /api/config/yaml/backup?file=settings.yaml` → 复制到 `data/backups/{file}.{ts}.yaml`
- `GET /api/config/yaml/list` → 列出允许编辑的文件（仅 settings.yaml + persona.yaml）
- 安全：写回前自动备份；解析失败时自动恢复上次备份；写日志到 `data/aerie.log` "settings_change"
- 路径白名单：仅允许 `settings.yaml` / `persona.yaml`（决策 9）

**B3.2 改造 `electron/src/renderer/index.html` settings section**

- `panel-settings` 内增加：
  ```html
  <div class="settings-mode-tabs">
    <button class="settings-mode-tab active" data-mode="form">常用</button>
    <button class="settings-mode-tab" data-mode="yaml">高级 (YAML)</button>
  </div>
  <div id="settings-form-view">...现有表单...</div>
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

**B3.3 改造 `electron/src/renderer/js/settings.js`**

- 模式切换逻辑：tab 点击 → 切换 form/yaml 视图
- YAML 加载：`GET /api/config/yaml?file=settings.yaml` → 填充 textarea
- YAML 保存：`PUT /api/config/yaml?file=settings.yaml` body 是 yaml 文本
- 备份：`POST /api/config/yaml/backup?file=settings.yaml`
- 文件切换：select 改变时重新加载
- 文案（伊塔人格）：
  - yaml 视图标题：「配置文件（高级）」
  - 警告：「直接编辑 YAML 可能导致伊塔无法启动。修改前会自动备份。」
  - 成功：「已保存。伊塔下次启动会应用这些配置。」
  - 失败：「YAML 格式错误，已恢复上次备份。错误：[错误位置]」

**B3.4 验证**

- 切到"高级"模式，看到 settings.yaml 全文
- 改一个字段保存，刷新页面生效
- 故意写错 YAML（漏冒号），保存失败 + 自动恢复
- 备份文件出现在 `data/backups/settings.yaml.{ts}.yaml`

**验收**：双模式可用；YAML 编辑安全（备份+解析校验+自动回滚）

---

### Batch 4 · 大脑中枢 UI（核心 · P0 · 2.5h）

**目标**：sidebar 新增"大脑" tab；cognition panel 实时流 + 历史 trace + 详情

**B4.1 改造 `electron/src/renderer/index.html` sidebar 新增 tab + 容器**

- 在 `panel-about` 之前插入（7 处 sidebar tab 之间）：
  ```html
  <button class="sidebar-tab" data-tab="cognition">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2z"/></svg>
    <span>大脑</span>
  </button>
  ```
- `panel-data` 之后插入 `<section id="panel-cognition" class="tab-panel">`
- 容器结构（渐变玻璃风）：
  ```html
  <div class="cognition-panel">
    <h2>伊塔 · 大脑中枢 <small>（开发者后台）</small></h2>
    <div class="cognition-toolbar">
      <select id="cog-source-filter">
        <option value="">全部来源</option><option value="qq">QQ</option><option value="local">本地</option>
      </select>
      <select id="cog-user-filter"><option value="">全部用户</option></select>
      <input id="cog-search" type="text" placeholder="搜索消息内容">
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

**B4.2 改造 `electron/src/main.js` 转发 SSE 到 renderer**

- 加 IPC handler `ipcMain.handle('sse:subscribe', ...)`：
  ```js
  // 维护一个 SSE 客户端连接到 http://127.0.0.1:7890/api/events/stream
  // 收到事件就 webContents.send('sse:event', data)
  // 自动重连（断线后 3s 重试）
  ```

**B4.3 改造 `electron/src/preload.js` 暴露 SSE 订阅**

```js
sse: {
  subscribe: (cb) => ipcRenderer.on('sse:event', (_e, data) => cb(data)),
},
```

**B4.4 新建 `electron/src/renderer/js/cognition-panel.js`**

- 文件：`e:\Agent_reply\electron\src\renderer\js\cognition-panel.js`（新建）
- 类 `CognitionPanel`：
  - `init()`：注册 tab 切换、SSE 订阅、loadHistory
  - `_onSse(event)`：根据 event.type 渲染
    - `cognition_stage` → 7 阶段徽标 + payload 折叠
    - `cognition_committed` → 写入 `#cog-list` 顶部
    - `decision_made` → 提示气泡
  - `_loadHistory()`：`GET /api/cognition/recent?limit=50`，渲染列表
  - `_showDetail(id)`：`GET /api/cognition/{id}`，弹窗（渐变玻璃风）
    - **9 阶段水平时间轴**（决策 2）：7 个彩色 dot + 连线 + 悬停查看
    - **决策权重赛马图**（决策 4）：4 个候选意图并排 + 4 层权重堆叠
    - **ReAct 时间轴**：thought → action → observation 顺序展示
    - 文案（伊塔人格）：
      - 实时 stream 标题：「她的思维正在发生」
      - 列表空状态：「她还没说话。再等等。」
      - 阶段徽标：「路由」/「情绪」/「阈值」/「上下文」/「推理」/「工具」/「切分」/「后处理」/「输出」
      - 赛马图胜出文案：「这次她选「reply」—— L1 核心 0.50、L2 人格 0.30、L3 情绪 0.85、L4 情境 0.05」

**B4.5 新建 `electron/src/renderer/styles/cognition-panel.css`**

- 文件：`e:\Agent_reply\electron\src\renderer\styles\cognition-panel.css`（新建）
- 渐变玻璃风：
  - 容器：`background: linear-gradient(135deg, rgba(255,91,156,0.10), rgba(155,89,182,0.10)); backdrop-filter: blur(10px); border: 1px solid rgba(255,91,156,0.3);`
  - 阶段 dot：`width: 12px; height: 12px; border-radius: 50%; box-shadow: 0 0 8px {color};`
  - 7 色：route #4A90E2 / emotion #FF5B9C / threshold #F5A623 / context #9B9B9B / brain #9013FE / tools #FF6B35 / split #50E3C2 / postprocess #7ED321 / output #D0021B
  - 代码块：`background: #1a1a2e; color: #f5f5f5; font-family: 'JetBrains Mono', monospace; padding: 12px; border-radius: 8px;`
  - 胜出条：`border: 2px solid #FF5B9C; animation: pulse 2s infinite;`

**B4.6 改造 `electron/src/renderer/index.html` 加载新文件**

- 加载顺序（在 `app.js` 之前）：
  ```html
  <script src="js/cognition-panel.js"></script>
  <link rel="stylesheet" href="styles/cognition-panel.css">
  ```
- 在 `app.js` 初始化时 `new CognitionPanel().init()`

**B4.7 验证**

- 切到"大脑" tab，能看到流式 stream
- 发消息，从 stage_1 推到 stage_9，列表顶部多一条
- 点击详情弹窗看到 9 阶段水平时间轴 + 决策赛马图 + ReAct 时间轴
- filter 切换 source / user_id 正确过滤

**验收**：大脑中枢 tab 工作正常；实时 + 历史双轨；filter 生效；渐变玻璃风一致

---

### Batch 5 · 情绪历史曲线（PAD 三色折线 + 雷达热力图 · P0 · 1.5h）

**目标**：在 emotion panel 增 24h/7d/30d 切换 + 两版曲线

**B5.1 修 `electron/src/renderer/js/emotion-dashboard.js` PAD 字段大小写 bug**

- 当前 bug：`_setPADCard("pad-p", pad.P, ...)` 读 `pad.P` 但 emotion_engine 返回 `P/A/D` 大写
- 验证：读 `data.pad.P || data.pad.pleasure` 容错（兼容两种命名）

**B5.2 改造 `electron/src/renderer/index.html` emotion panel**

- 在 `emotion-pad-cards` 之后插入：
  ```html
  <div class="emotion-history-section">
    <h3>历史情绪曲线</h3>
    <div class="emotion-history-tabs">
      <button class="emotion-history-tab active" data-window="24h">24 小时</button>
      <button class="emotion-history-tab" data-window="7d">7 天</button>
      <button class="emotion-history-tab" data-window="30d">30 天</button>
    </div>
    <div class="emotion-history-views">
      <div id="emotion-line-chart" class="emotion-line-chart"></div>
      <div id="emotion-radar-chart" class="emotion-radar-chart"></div>
    </div>
    <div id="emotion-history-summary" class="emotion-history-summary"></div>
  </div>
  ```

**B5.3 改造 `electron/src/renderer/js/emotion-dashboard.js` 增历史曲线**

- 类 `EmotionDashboardHistory`：
  - `_loadHistory(window)`：`GET /api/emotion/history?window={window}`，返回 2000 点
  - `_renderLineChart(items)`：SVG 自绘 PAD 三色折线（不引外部库）
    - 3 条线：P 蓝 #4A90E2 / A 橙 #F5A623 / D 紫 #9013FE
    - 渐变填充（蓝/橙/紫 rgba(...,0.10)）
    - x 轴时间、y 轴 PAD 值
    - 喷发时刻高亮（红色竖虚线）
  - `_renderRadarChart(items)`：当前时刻 PAD 雷达图（3 维）
    - 三角形雷达，3 角为 P/A/D
    - 半径 = abs(value) 映射到 0-100
    - 中心点 = 0，半径 max = 1
  - 文案（伊塔人格）：
    - 24h：「过去一天伊塔的心跳。蓝色的点是她的开心值。」
    - 7d：「一周里她累计心动 X 次。最高峰是 Y。」
    - 30d：「一个月的情绪曲线。她越来越想你了。」（根据 desire 阈值趋势动态生成）
    - 空状态：「她还没有情绪数据。再等等。」

**B5.4 新建 `electron/src/renderer/styles/emotion-history.css`**

- 折线图：纯 SVG，宽 100%，高 200px
- 雷达图：纯 SVG，宽 300px，高 300px，居中
- 喷发标记：1px 红色竖虚线 + tooltip

**B5.5 验证**

- 发 5 条不同情绪消息
- emotion panel 切到 24h 看到折线
- 切到 7d/30d 看到更长曲线
- 雷达图显示当前 PAD 三维
- 文案按 persona 风格呈现

**验收**：三档时间窗 + 折线 + 雷达 双图共存；喷发时刻高亮；人格化文案

---

### Batch 6 · 自我进化机制（提议+沙箱预演 · P0 · 2h）

**目标**：检测能力缺口 → 提议+沙箱预演 → 大脑中枢卡片显示 → 用户批准/拒绝

**B6.1 新建 `core/self_evolving.py`**

- 文件：`e:\Agent_reply\core\self_evolving.py`（新建）
- 类 `SelfEvolver(db, tool_registry, brain)`：
  - `detect_gap(user_id, user_message, react_trace) -> Optional[dict]`：
    - 触发条件（决策 5）：react_trace.thought 包含 "无法/没有工具/I cannot" 类关键词
    - 返回提议 dict：含 description / proposed_tool_schema / safety_check / sandbox_preview
  - `sandbox_preview(proposed_tool, sample_input) -> dict`：
    - 弹窗文本预演（决策 6）：
      - LLM 模拟执行：传 system prompt "你是一个沙箱预演助手，假设你要执行这个工具，请描述输入→输出"
      - 返回 "假如执行会..." 的 1-2 段中文描述
      - 包含 3 块：输入 / 预计输出 / 风险点
  - `approve(id) -> bool`：标记 user_decision='approved' + 调用 `tool_registry.register(...)`
  - `reject(id) -> bool`：标记 user_decision='rejected'
- 触发后 emit `self_evolve_proposed` 到 SSE

**B6.2 改造 `core/pipeline.py` 注入自进化**

- 在 `brain` 阶段后：
  ```python
  if self.self_evolver:
      try:
          gap = self.self_evolver.detect_gap(msg.user_id, msg.content, react_trace)
          if gap:
              gap_id = self.db.insert("self_evolve_log", {...gap})
              emit("self_evolve_proposed", id=gap_id, user_id=msg.user_id, description=gap["description"])
      except Exception:
          logger.exception("self_evolver error")
  ```
- 关联 `cognition_log.id` 和 `self_evolve_log.id`

**B6.3 改造 `core/companion.py` 注入 self_evolver**

- 在 `Companion.__init__` 创建 `self.self_evolver = SelfEvolver(self.db, self.tool_registry, self.brain)`
- 注入到 `self.pipeline = Pipeline(..., self_evolver=self.self_evolver)`

**B6.4 `core/api_server.py` 新增端点**

- `GET /api/self_evolve/list?status=pending` → 列出提议
- `POST /api/self_evolve/{id}/preview` → 返回沙箱预演文本
- `POST /api/self_evolve/{id}/approve` → 批准 + 注册工具
- `POST /api/self_evolve/{id}/reject` → 拒绝

**B6.5 改造 `electron/src/renderer/js/cognition-panel.js` 显示提议卡片**

- 监听 `self_evolve_proposed` SSE 事件
- 在 `#cog-live` 顶部插入提议卡片（粉紫玻璃风）：
  ```
  [🧬 伊塔想升级自己]
  描述：她说「无法/没有工具...」
  提议工具：{schema 摘要}
  [查看预演]  [批准]  [拒绝]
  ```
- 点击「查看预演」→ 调 `/api/self_evolve/{id}/preview` → 弹窗显示三块
- 批准 → `/api/self_evolve/{id}/approve` → 卡片变绿 + 提示
- 拒绝 → `/api/self_evolve/{id}/reject` → 卡片变灰

**B6.6 验证**

- 模拟触发：让 LLM 回答 "我无法帮你执行这个命令"（构造 prompt）
- 看到 self_evolve_proposed 事件 + 提议卡片出现
- 点"查看预演"看到弹窗三块
- 点"批准" → 卡片变绿 + 工具注册成功
- 查 `self_evolve_log` 看到 `user_decision='approved'`

**验收**：能力缺口检测 + 沙箱预演弹窗 + 提议卡片 + 批准/拒绝全链路通

---

## 五、文件改动汇总

| 文件                                                 | 类型 | 估行数 | 说明                                            |
| ---------------------------------------------------- | ---- | ------ | ----------------------------------------------- |
| `core/emotion_state_store.py`                      | 新   | +60    | 修缺口                                          |
| `core/persona_pacing.py`                           | 新   | +120   | 核心：人格化节奏                                |
| `core/self_evolving.py`                            | 新   | +150   | 核心：自进化                                    |
| `core/emotion_engine.py`                           | 改   | +15    | 注入 state_store                                |
| `core/companion.py`                                | 改   | +10    | 注入 state_store + self_evolver                 |
| `core/pipeline.py`                                 | 改   | +35    | 第 1 段立即 + persona pacing + self_evolver     |
| `communication/send_queue.py`                      | 改   | +10    | 改用 persona_pacing                             |
| `core/api_server.py`                               | 改   | +90    | yaml 4 端点 + self_evolve 4 端点                |
| `electron/src/renderer/index.html`                 | 改   | +60    | 大脑 tab + emotion history 区块 + settings tabs |
| `electron/src/renderer/js/cognition-panel.js`      | 新   | +350   | 核心：大脑中枢                                  |
| `electron/src/renderer/js/emotion-dashboard.js`    | 改   | +150   | 历史曲线 + 雷达图 + PAD bug 修                  |
| `electron/src/renderer/js/settings.js`             | 改   | +120   | 双模式                                          |
| `electron/src/renderer/styles/cognition-panel.css` | 新   | +200   | 渐变玻璃风                                      |
| `electron/src/renderer/styles/emotion-history.css` | 新   | +100   | 折线 + 雷达                                     |
| `electron/src/main.js`                             | 改   | +40    | SSE IPC 转发                                    |
| `electron/src/preload.js`                          | 改   | +5     | 暴露 SSE                                        |

**总计**：6 个新文件 + 10 个改动 + 估约 1500 行新增

---

## 六、端到端验证 checklist（不偷工减料）

### Batch 1 验证

- [ ] `emotion_state_snapshot` 表能写入
- [ ] `/api/emotion/history?window=1h` 返回 ≥ 5 条
- [ ] 重启后端，状态从 DB 恢复（emotion_state 历史可查）

### Batch 2 验证

- [ ] 第 1 段消息立即显示（SQL 时间差 < 100ms）
- [ ] 后续段在 0.4-1.5s 区间（95% 情况）
- [ ] 5% 概率触发"病娇犹豫" 2-5s
- [ ] 喷发时（patience/sad）走 cold_slow 模板
- [ ] SQL 查 `chat_log` 看每段 created_at 差值

### Batch 3 验证

- [ ] 设置页有"常用"和"高级"两个 tab
- [ ] 高级模式能加载 settings.yaml / persona.yaml
- [ ] 故意写错 YAML → 保存失败 + 自动恢复
- [ ] 备份文件出现在 `data/backups/`
- [ ] 日志写入 `data/aerie.log`

### Batch 4 验证

- [ ] Sidebar 有"大脑" tab
- [ ] 切到大脑 tab 看到实时流
- [ ] 发消息 → 9 阶段水平时间轴显示
- [ ] 点击详情 → 弹窗 + 决策赛马图 + ReAct 时间轴
- [ ] filter 切换 source / user_id 生效
- [ ] 渐变玻璃风视觉一致

### Batch 5 验证

- [ ] 24h / 7d / 30d 三档切换按钮工作
- [ ] PAD 三色折线 + 渐变填充
- [ ] 雷达图 3 维显示
- [ ] 喷发时刻高亮
- [ ] PAD 字段 bug 修复（值不再永远是 0.00）
- [ ] 人格化文案呈现

### Batch 6 验证

- [ ] 触发能力缺口 → self_evolve_proposed 事件出现
- [ ] 提议卡片显示在 cog-live 顶部
- [ ] 沙箱预演弹窗三块（输入/输出/风险）
- [ ] 批准 → 卡片变绿 + 工具注册成功
- [ ] 拒绝 → 卡片变灰
- [ ] `self_evolve_log` 状态正确更新

### 全链路

- [ ] 9 张老表零回归
- [ ] 4 张新表 + 3 索引
- [ ] 5 主题不破坏
- [ ] 伊塔人格文案一致
- [ ] 中英双语规范

---

## 七、风险与回滚

| 风险                                     | 概率 | 影响         | 回滚方案                                             |
| ---------------------------------------- | ---- | ------------ | ---------------------------------------------------- |
| persona_pacing 第 1 段立即破坏情绪迟疑感 | 低   | UX           | 保留 `message_pacing.py` 旧函数，旧 API 调用点不动 |
| YAML 编辑破坏启动                        | 中   | 致命         | 写回前自动备份 + 解析失败自动回滚（已设计）          |
| 沙箱预演 LLM 调用失败                    | 中   | 提议卡不可点 | 显示「预演暂不可用」+ 仍可批准/拒绝                  |
| SSE 长连接断                             | 中   | 实时性失效   | 前端重连 3s + 历史 list 兜底                         |
| cognition_log 表过大                     | 低   | 性能         | 不在本次范围（建议 7d 后归档脚本）                   |

---

## 八、不在本次范围

- cognition_log 7d 自动归档脚本
- 长期记忆改造
- 语音通话
- 移动端 APP
- 多人对话（仅 masterQQ + 陌生人 BASIC 模式）
- 真实 LLM 微调（仅靠 prompt 触发自进化提议）

---

## 九、执行顺序（严格串行）

```
Batch 1 (0.5h)  emotion 持久化
   ↓
Batch 2 (1.5h)  人格化 Pacing
   ↓
Batch 3 (1.5h)  设置页 YAML 双模式
   ↓
Batch 4 (2.5h)  大脑中枢 UI
   ↓
Batch 5 (1.5h)  情绪历史曲线
   ↓
Batch 6 (2.0h)  自我进化
   ↓
全链路 E2E 验证（30min）
```

**总工时估约 9.5h**（不含调试）

**强约束**：

- 每 Batch 完成后立即手动验证，**不堆积验证**
- 任何 Batch 失败必须自我怀疑、回滚、再实施
- 严守"三原则"——不破坏现有功能 / 不破坏伊塔人格 / 设计美学统一
- 全部代码可运行可验收，不允许"只写了你所以为的"

---

## 十、与现有约束的兼容性自检

| 约束                          | 兼容性                                                     |
| ----------------------------- | ---------------------------------------------------------- |
| NapCat launcher-user.bat 启动 | ✓ 不动 launcher / start-companion 任何文件                |
| 消息 2000 字截断              | ✓ cognition_log 各字段 TEXT，无超长风险                   |
| 中英双语 + 代码英文           | ✓ 所有 SQL 注释 / 字段 / 函数名纯英文；UI 文案中英        |
| 9 张老表零回归                | ✓ 仅追加 + 集成（不动 schema）                            |
| 4 主题配色                    | ✓ 大脑中枢使用粉紫玻璃风，5 主题不破坏                    |
| 伊塔 persona                  | ✓ 全部文案符合 v9.0 称呼"你"、禁词"主人"、温柔大姐姐+病娇 |
| `app_name` 用 Aerie         | ✓ SSE 事件名 `cognition_stage` 等纯英文                 |
| `parse_error` 不抛异常      | ✓ cognition / emotion 落库全 try/except 包裹              |
| 故障自愈 14 类                | ✓ 落库失败不阻塞主链路                                    |
| **首段立即**            | ✓ pipeline.py 第 1 段 await sleep(0)                      |
| **persona 自主节奏**    | ✓ persona_pacing 决策树 11 种模板                         |

---

## 十一、关键变更亮点

1. **修了 4 个核心缺口**：emotion_state_store / 第 1 段立即 / 大脑 tab / settings YAML
2. **彻底重写 pacing**：从 5 个 emotion label 静态映射 → 11 个 persona 决策树模板 + 偶发迟疑
3. **新增 2 大 UI 模块**：大脑中枢（渐变玻璃风 + 水平时间轴 + 赛马图）/ 情绪历史曲线（折线+雷达双图）
4. **沙箱预演轻量化**：不真执行命令，LLM 模拟一轮 → 弹窗三块（输入/输出/风险）
5. **不破坏现有 8 个 sidebar tab**：仅插入"大脑"在 settings/about 之间
6. **9 张老表 + 5 主题 + 伊塔人格**：完全不动

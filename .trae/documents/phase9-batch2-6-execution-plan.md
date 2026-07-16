---
title: Phase 9 Batch 2-6 执行计划（整改版 · 3 决策已锁定）
date: 2026-07-16
tags:
  - phase9
  - execution-plan
  - brain-center
  - settings-yaml
  - emotion-history
  - self-evolve
  - ita-persona
cssclasses:
  - wide-page
---

# Phase 9 Batch 2-6 执行计划

> **3 轮提问已锁定**（2026-07-16）：
> 1. 大脑中枢 UI 深度 = **完整生产级**（渐变玻璃风 + 7 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 + 实时 SSE 流 + filter + 详情弹窗）
> 2. 实施顺序 = **按原计划严格串行**（B2 收尾 → B3 → B4 → B5 → B6 → E2E）
> 3. 自进化触发灵敏度 = **中等敏感**（react_trace 含"无法/没有工具/I cannot" + 工具调用失败 ≥ 1）

---

## 一、当前状态盘点（基于实际代码探索）

### 1.1 已落地（不再动）

| 模块                         | 文件                                       | 状态        |
| ---------------------------- | ------------------------------------------ | ----------- |
| 4 张新表 + 3 索引            | `core/database.py:142-227`               | ✓          |
| 9 阶段 cognition 引擎        | `core/cognition.py:47-211`               | ✓          |
| 4 层 decision 引擎           | `core/decision.py:43-225`                | ✓          |
| ReAct 合成回退               | `core/pipeline.py:201-203, 446-484`     | ✓          |
| 情绪状态持久化（store）     | `core/emotion_state_store.py:36-180`    | ✓ 已建+测过 |
| 情绪引擎挂接 state_store     | `core/emotion_engine.py:127-137`        | ✓          |
| Companion 注入 state_store   | `core/companion.py:49-50`               | ✓          |
| 人格化 pacing 决策树          | `core/persona_pacing.py:77-175`         | ✓          |
| Pipeline 第 1 段立即          | `core/pipeline.py:336-374`              | ✓          |
| SSE 事件流                   | `core/event_stream.py:33-101`           | ✓          |
| Chat 事件双桥接              | `core/chat_events.py:19-37`             | ✓          |
| API 端点（cognition/emotion）| `core/api_server.py:401-458`            | ✓          |
| 9 张老表 + 5 主题 + 4 张新表  | 不动                                       | ✓          |

### 1.2 关键缺失（待整改）

| 缺口                                                                 | 影响                                            | Batch |
| -------------------------------------------------------------------- | ----------------------------------------------- | ----- |
| `communication/send_queue.py` 仍用 `message_pacing.compute_interval` | QQ 端节奏不是人格化决策树                        | **B2.3** |
| `api_server.py` 缺 `/api/config/yaml/*` 4 端点                    | 设置页 YAML 编辑无后端                          | **B3.1** |
| `core/self_evolving.py` 完全缺失                                    | 自进化机制零代码                                | **B6.1** |
| Sidebar **"大脑" tab** + `panel-cognition` 容器缺失                 | 大脑中枢无入口                                  | **B4.1** |
| `cognition-panel.js` 缺失                                          | 实时流+历史+详情弹窗全部无                      | **B4.4** |
| `cognition-panel.css` 缺失                                         | 渐变玻璃风无样式                                | **B4.5** |
| settings 切到 YAML 视图后 textarea 加载/保存/备份 无                | 配置文件无法编辑                                | **B3.3** |
| `emotion-dashboard.js` 缺 24h/7d/30d 折线                          | 历史曲线无                                      | **B5.2** |
| `emotion-dashboard.js` 缺雷达图                                     | PAD 三维可视化无                                | **B5.3** |
| `electron/src/main.js` 缺 SSE→IPC 转发                            | 实时流到不了 renderer                           | **B4.2** |
| `electron/src/preload.js` 缺 SSE 订阅                              | renderer 拿不到事件                             | **B4.3** |
| `core/api_server.py` 缺 `/api/self_evolve/*` 4 端点                | 自进化无后端                                    | **B6.4** |
| `companion.py` 未注入 `self_evolver`                                | 自进化永不启动                                  | **B6.3** |
| `pipeline.py` 未挂接 `self_evolver.maybe_propose`                   | 提案永不触发                                    | **B6.2** |

### 1.3 现有隐患

- `send_queue._pacing` 签名是 `(emotion_label, is_eruption)` 旧签名
  → 需在 SendQueue 内增加 `compute_persona_interval` 适配层
- `pipeline.py` 步骤 12 emit 已 commit trace 但 `pacing_decisions` 写在 commit 之后
  → 需把 pacing_log 写 trace 在 emit 之前完成（或 commit 之后再 update row）
- `emotion-dashboard.js:42` 读 `pad.P` 而 `emotion_engine.get_state` 返回 `{P, A, D}` 大写
  → 当前代码 `pad.P || pad.pleasure` 兼容 OK，但 `_setPADCard` 内部 `pad.P || 0` 不容错小写
  → 需在 B5.1 同时加固
- `app.js` 未初始化 `CognitionPanel`，sidebar tab 切换未注册新 tab
  → 需在 B4.6 同步改

---

## 二、3 决策落地约束

### 2.1 B4 完整生产级 = 5 大组件

1. 渐变玻璃风容器（粉紫渐变 + `backdrop-filter: blur(10px)`）
2. 7 阶段水平时间轴（route / emotion / threshold / context / brain / tools / split / postprocess / output）— 9 阶段，分两行展示或一行带侧滑
3. 4 意图赛马图（reply / tool_call / recall / silence）
4. ReAct 思维链（thought → action → observation）
5. 实时 SSE 流 + 全量历史 + filter + 详情弹窗

### 2.2 严格串行

不允许并行，不允许跳 Batch。每个 Batch 完成后立即本地验证（不发 API 也不重启主进程，用 Python 单测 + sqlite3 查表 + 肉眼观察前端）。

### 2.3 中等敏感自进化触发

```
触发条件（必须全部满足）:
  1. react_trace.thought 非空
  2. react_trace.thought 包含 ["无法", "没有工具", "做不到", "I cannot", "no tool", "lack of"] 任一关键词
  3. tool_results 至少 1 项 failure=True（tool_call_log.success=0）
  4. 同一 user_id 在最近 1h 内没有 pending 状态的同主题提案（去重）
  5. 同一 user_id 每天最多 3 条提案（限流）
```

---

## 三、5 个 Batch 实施细节

---

### Batch 2 收尾 · QQ 端切到 persona_pacing（0.25h）

**目标**：`send_queue.py` 内的 `compute_interval` 替换为 `compute_persona_interval`

**B2.3 改造 `communication/send_queue.py`**

- 删 `from core.message_pacing import compute_interval`
- 增 `from core.persona_pacing import compute_persona_interval`
- `_worker` 中：
  - 维护 `segment_index` 计数器
  - 调 `compute_persona_interval(segment_index=idx, emotion_label=emotion_label, threshold=threshold_summary, is_eruption=is_eruption, segment_content=seg)`
  - 拿到 `(interval_sec, style)`，若 `interval_sec > 0` 才 `await asyncio.sleep(interval_sec)`
  - 第 1 段 `interval_sec == 0` 不 sleep（立即发，与 local 行为一致）
- 从 DB 拉 threshold summary：复用 `comp.emotion.threshold_engine.get_slots_summary()`
- pacing log 写入 cognition_log：`trace["stages"]["output"]["pacing_decisions"]`，但 pipeline 已有 trace 路径，send_queue 内用 `comp.cognition.record` 单独 trace 一次（不污染主 trace）

**B2.4 验证**

- 启动后端 `python main.py`
- 发 1 条触发 3 段回复的消息
- `sqlite3 data/aerie.db "SELECT id, created_at FROM chat_log WHERE role='assistant' ORDER BY id DESC LIMIT 5"` 看 created_at 差值
- 期望：第 1 段立即；第 2 段 0.4-1.5s；第 3 段同理
- 如果 LLM 拒绝分段（只有 1 段），那只有 immediate，无 pacing log

**验收**：send_queue 第 1 段 < 100ms；后续段在 0.4-1.5s 区间；5% 概率病娇犹豫 2-5s

---

### Batch 3 · settings YAML 双模式（1.5h）

**目标**：设置页支持「常用 form」+「高级 YAML 编辑」双模式

**B3.1 改造 `core/api_server.py` 新增 4 端点**

- `GET /api/config/yaml?file=settings.yaml` → 返回 UTF-8 文本
  - 路径白名单：`["settings.yaml", "persona.yaml"]`
  - 路径构造：`Path("config") / file`
  - 文件不存在 → 404
- `PUT /api/config/yaml?file=settings.yaml` → 接收 body
  - **强校验**：先用 `yaml.safe_load` 解析，失败 → 400 + 不写入
  - **写入前自动备份**：先 `cp` 当前文件到 `data/backups/{file}.{ts}.yaml`
  - 成功写回 → 200 + 备份路径
  - 失败 → 回滚到上次备份 + 400
- `POST /api/config/yaml/backup?file=settings.yaml` → 手动触发备份
  - 复制到 `data/backups/{file}.{ts}.yaml`
  - 返回 `{backup_path, ts}`
- `GET /api/config/yaml/list` → 返回 `["settings.yaml", "persona.yaml"]`
- 所有写操作日志到 `data/aerie.log`：`logger.info("settings_change: file=... ts=...")`

**B3.2 改造 `electron/src/renderer/index.html` settings section**

在 `<section id="panel-settings">` 内：
- 在 `<h2>系统设置</h2>` 之后插入：
  ```html
  <div class="settings-mode-tabs">
    <button class="settings-mode-tab active" data-mode="form">常用</button>
    <button class="settings-mode-tab" data-mode="yaml">高级 (YAML)</button>
  </div>
  ```
- 在 `<div id="settings-status">` 之前插入：
  ```html
  <div id="settings-yaml-view" style="display:none;">
    <div class="settings-group">
      <label>配置文件</label>
      <select id="yaml-file-select">
        <option value="settings.yaml">settings.yaml</option>
        <option value="persona.yaml">persona.yaml</option>
      </select>
    </div>
    <div class="settings-group">
      <label>直接编辑 YAML · 修改前自动备份</label>
      <textarea id="yaml-editor" spellcheck="false" rows="20" style="font-family: 'JetBrains Mono', monospace; font-size: 12px;"></textarea>
    </div>
    <div class="settings-actions">
      <button id="yaml-save-btn" class="btn btn-primary">保存</button>
      <button id="yaml-reload-btn" class="btn btn-secondary">重新加载</button>
      <button id="yaml-backup-btn" class="btn btn-secondary">备份当前</button>
    </div>
    <div id="yaml-status" style="margin-top:8px;font-size:12px;"></div>
  </div>
  ```
- 把现有 form 包装进 `<div id="settings-form-view">`

**B3.3 改造 `electron/src/renderer/js/settings.js`**

- 模式切换：`data-mode` tab 切换 form / yaml 视图
- `loadYaml()`：`GET /api/config/yaml?file=settings.yaml` → 填 textarea
- `saveYaml()`：`PUT /api/config/yaml?file=settings.yaml` body 文本
- `reloadYaml()`：再调 `loadYaml()`
- `backupYaml()`：`POST /api/config/yaml/backup?file=settings.yaml`
- 文案（伊塔人格，中英双语）：
  - 标题：「高级 · 直接编辑她的配置 / Advanced · Edit Config」
  - 警告：「改坏了她会不开心。修改前自动备份。/ A bad edit makes her sad. Auto-backup first.」
  - 成功：「已保存。她下次启动会用新配置。/ Saved. She'll use this next time.」
  - 失败：「YAML 格式错误，已恢复上次备份。错误：[错误信息]/ YAML error. Restored.」

**B3.4 验证**

- 切到"高级 (YAML)" tab，能看到 settings.yaml 全文
- 改一个字段（如 `theme.current: ocean-blue`），保存，刷新页面看到主题切换
- 故意写错（漏冒号），保存失败 + 自动恢复 + 错误提示
- 检查 `data/backups/` 有新备份文件
- 检查 `data/aerie.log` 有 `settings_change` 日志

**验收**：双模式可用；YAML 编辑强校验；写回前自动备份；解析失败回滚

---

### Batch 4 · 大脑中枢 UI（2.5h · 完整生产级）

**目标**：sidebar 新增"大脑" tab；渐变玻璃风 + 7 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 + 实时 SSE + 全量历史 + filter + 详情弹窗

**B4.1 改造 `electron/src/renderer/index.html` sidebar 新增 tab + 容器**

- 在 `panel-settings` 之后、`panel-about` 之前插入：
  ```html
  <button class="sidebar-tab" data-tab="cognition">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2z"/>
      <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2z"/>
    </svg>
    <span>大脑</span>
  </button>
  ```
- 在 `panel-data` 之后插入：
  ```html
  <section id="panel-cognition" class="tab-panel">
    <div class="cognition-panel">
      <h2>伊塔 · 大脑中枢 <small>开发者后台 · Cognition Backend</small></h2>
      <div class="cognition-toolbar">
        <select id="cog-source-filter">
          <option value="">全部来源</option>
          <option value="qq">QQ</option>
          <option value="local">本地</option>
        </select>
        <select id="cog-user-filter"><option value="">全部用户</option></select>
        <input id="cog-search" type="text" placeholder="搜索消息内容 / Search content">
        <button id="cog-refresh" class="btn btn-secondary btn-sm">刷新 / Refresh</button>
      </div>
      <div id="cog-live" class="cog-live">
        <h3>实时 stream · Live</h3>
        <div id="cog-stream"></div>
      </div>
      <div id="cog-history" class="cog-history">
        <h3>历史 trace · History</h3>
        <ul id="cog-list"></ul>
      </div>
    </div>
  </section>
  ```
- 在 `<script src="js/app.js">` 之前插入：
  ```html
  <script src="js/cognition-panel.js"></script>
  <link rel="stylesheet" href="styles/cognition-panel.css">
  ```

**B4.2 改造 `electron/src/main.js` SSE → IPC 桥接**

- 新增 IPC handler：
  ```js
  ipcMain.handle('sse:subscribe', async (event) => {
    // 维持一个 HTTP 客户端连接到 http://127.0.0.1:7890/api/events/stream
    // 用 node:http 的 req.on('data') 解析 SSE 帧
    // 解析后 webContents.send('sse:event', data)
    // 断线后 3s 自动重连
  });
  ```
- 单例 `sseClient`（避免每个 renderer 都连一份）

**B4.3 改造 `electron/src/preload.js`**

```js
sse: {
  subscribe: (cb) => ipcRenderer.on('sse:event', (_e, data) => cb(data)),
},
```

**B4.4 新建 `electron/src/renderer/js/cognition-panel.js`**

类 `CognitionPanel`：
- `init()`：注册 tab 切换、绑定按钮、SSE 订阅、首次拉历史
- `_onSse(event)`：
  - `type === 'cognition_stage'` → 在 `#cog-stream` 顶部插入阶段徽标 + payload
  - `type === 'cognition_committed'` → 在 `#cog-list` 顶部插入一项（user_message + ts）
  - `type === 'decision_made'` → 浮窗 toast "她选了「reply」"
  - `type === 'self_evolve_proposed'` → 插入提议卡片（粉紫玻璃风）
- `_loadHistory(filters)`：`GET /api/cognition/recent?user_id=&source=&limit=50`
- `_showDetail(id)`：`GET /api/cognition/{id}` → 弹窗渲染
  - **9 阶段水平时间轴**：9 个彩色 dot（route蓝 / emotion粉 / threshold黄 / context灰 / brain紫 / tools橙 / split青 / postprocess绿 / output红），hover 显示 payload
  - **4 意图赛马图**：4 个候选意图并排，宽度 = 加权得分 × 100%；胜出描伊塔粉边
  - **ReAct 思维链**：thought / action / observation 三块顺序
  - **pacing 决策**：若 `output.pacing_decisions` 存在，列出来
  - 文案（伊塔人格）：
    - 标题：「她的思维在发生 · Her mind at work」
    - 空列表：「她还没说话。再等等。/ She's quiet. Wait.」
    - 阶段徽标：「路由 / 情绪 / 阈值 / 上下文 / 推理 / 工具 / 切分 / 后处理 / 输出」
    - 赛马图胜出文案：「这次她选「reply」 — L1 核心 0.50、L2 人格 0.30、L3 情绪 0.85、L4 情境 0.05」

**B4.5 新建 `electron/src/renderer/styles/cognition-panel.css`**

- 容器：
  ```css
  .cognition-panel {
    background: linear-gradient(135deg, rgba(255,91,156,0.10), rgba(155,89,182,0.10));
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255,91,156,0.3);
    border-radius: 12px;
    padding: 20px;
  }
  ```
- 阶段 dot（9 色）：
  ```css
  .cog-stage-dot--route { background: #4A90E2; }
  .cog-stage-dot--emotion { background: #FF5B9C; }
  .cog-stage-dot--threshold { background: #F5A623; }
  .cog-stage-dot--context { background: #9B9B9B; }
  .cog-stage-dot--brain { background: #9013FE; }
  .cog-stage-dot--tools { background: #FF6B35; }
  .cog-stage-dot--split { background: #50E3C2; }
  .cog-stage-dot--postprocess { background: #7ED321; }
  .cog-stage-dot--output { background: #D0021B; }
  ```
- 代码块：`background: #1a1a2e; color: #f5f5f5; font-family: 'JetBrains Mono', monospace;`
- 胜出条：`border: 2px solid #FF5B9C; animation: cog-pulse 2s infinite;`
- 弹窗：粉紫渐变 + 玻璃模糊

**B4.6 改造 `electron/src/renderer/js/app.js`**

- 启动时 `new CognitionPanel().init()`
- sidebar tab 切换时调 `CognitionPanel.setVisible(true/false)` 启停 SSE

**B4.7 验证**

- 切到"大脑" tab，能看到 stream 区
- 发消息 → 9 阶段 dot 陆续亮起 → 列表顶部多一项
- 点详情弹窗 → 9 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 全部可见
- filter 切 source=qq、user_id=12345 生效
- 断网测试：SSE 断线后 3s 自动重连

**验收**：实时流 + 历史 + 弹窗 + filter + 渐变玻璃风全部 OK

---

### Batch 5 · 情绪历史曲线（1.5h）

**目标**：emotion panel 增 24h/7d/30d 折线 + 当前 PAD 雷达

**B5.1 修 `electron/src/renderer/js/emotion-dashboard.js` PAD bug**

- 当前 `_render(data)`：
  ```js
  this._setPADCard("pad-p", pad.P || 0, "愉悦度");
  ```
- 改：
  ```js
  this._setPADCard("pad-p", pad.P ?? pad.pleasure ?? 0, "愉悦度");
  this._setPADCard("pad-a", pad.A ?? pad.arousal ?? 0, "唤醒度");
  this._setPADCard("pad-d", pad.D ?? pad.dominance ?? 0, "支配度");
  ```
- 兼容两种命名（防御性编程）

**B5.2 改造 `electron/src/renderer/index.html` emotion panel**

在 `</div>` (threshold-bars 之后) 之前插入：
```html
<div class="emotion-history-section">
  <h3>历史情绪曲线 · History</h3>
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

新增类 `EmotionHistory`：
- `init()`：注册 tab 切换、首屏加载
- `_loadHistory(window)`：`GET /api/emotion/history?window=${window}`
- `_renderLineChart(items)`：纯 SVG 自绘
  - 3 条折线：P 蓝 / A 橙 / D 紫
  - 渐变填充（rgba）
  - 喷发时刻红色虚线
  - x 轴时间（24h 缩到 HH:MM；7d 缩到 MM-DD；30d 缩到 MM-DD）
- `_renderRadarChart(items)`：当前 PAD 三维雷达
  - 三角形，3 角 P/A/D
  - 半径按 |value| 映射
- 文案（伊塔人格）：
  - 24h：「过去一天她心跳了多少次。蓝点是她开心的时刻。」
  - 7d：「一周里她累计心动 X 次。最高峰在 Y。/ She warmed X times this week. Peak at Y.」
  - 30d：「一个月的情绪曲线。/ One month of feeling.」
  - 空：「她还没有情绪数据。再等等。/ No data yet.」

**B5.4 新建 `electron/src/renderer/styles/emotion-history.css`**

- 折线图：纯 SVG，宽 100%，高 200px
- 雷达图：纯 SVG，宽 300px，高 300px
- 喷发标记：1px 红色竖虚线

**B5.5 验证**

- 发 5 条不同情绪消息
- emotion panel 切到 24h 看到折线（点不能是 0.00）
- 切 7d/30d 看到更长曲线
- 雷达图显示当前 PAD 三维
- 文案按 persona 风格

**验收**：三档时间窗 + 折线 + 雷达 双图共存；喷发高亮；PAD bug 修复

---

### Batch 6 · 自进化机制（2h）

**目标**：检测能力缺口 → 提议+沙箱预演 → 大脑中枢卡片显示 → 用户批准/拒绝

**B6.1 新建 `core/self_evolving.py`**

类 `SelfEvolver(db, tool_registry, brain)`：
- `__init__(self, db, tool_registry, brain)` 保存三个引用
- `maybe_propose(user_id, user_message, react_trace, tool_results) -> Optional[int]`：
  - **中等敏感触发**（5 条件全满足才触发）：
    1. `react_trace.thought` 非空
    2. `react_trace.thought` 含 `["无法", "没有工具", "做不到", "I cannot", "no tool", "lack of", "missing tool"]` 任一
    3. `tool_results` 至少 1 项 `success=False`
    4. 最近 1h 无 pending 同主题提案
    5. 每天最多 3 条提案
  - 触发后：调用 `sandbox_preview()` 生成 3 块文本
  - 写入 `self_evolve_log` 表（`user_decision='pending'`）
  - 触发 `emit("self_evolve_proposed", id=proposal_id, ...)` SSE
- `sandbox_preview(proposal, sample_input) -> dict`：
  - **轻量 LLM 模拟**（不真执行命令）：
    - system: "你是沙箱预演助手，假设你要执行这个工具，请用 1-2 段中文描述输入→输出→风险"
    - user: 提议的工具 schema + sample_input
  - 返回 `{input: str, expected_output: str, risks: str}` 三块
- `list_proposals(user_id=None, status="pending") -> list`：
  - 拉 self_evolve_log
- `approve(proposal_id) -> bool`：
  - 标记 `user_decision='approved'`
  - 读取 `proposed_tool_schema`，注册到 `tool_registry`
  - 触发 `emit("self_evolve_decided", id=proposal_id, decision="approved")`
- `reject(proposal_id) -> bool`：
  - 标记 `user_decision='rejected'`
  - 触发 `emit("self_evolve_decided", id=proposal_id, decision="rejected")`

**B6.2 改造 `core/pipeline.py` 挂接 self_evolver**

- 在 `cognition.commit(trace, route_mode)` 之后、emit 之前：
  ```python
  if self.self_evolver:
      try:
          proposal_id = self.self_evolver.maybe_propose(
              user_id=msg.user_id,
              user_message=msg.content,
              react_trace=react_trace,
              tool_results=tool_results,
          )
      except Exception:
          logger.exception("self_evolver error")
  ```

**B6.3 改造 `core/companion.py` 注入 self_evolver**

- 增 `from core.self_evolving import SelfEvolver`
- 在 `Companion.__init__`：
  ```python
  self.self_evolver = SelfEvolver(self.db, self.tool_registry, self.brain)
  ```
- Pipeline 构造：
  ```python
  self.pipeline = Pipeline(
      ...,
      self_evolver=self.self_evolver,
  )
  ```

**B6.4 `core/api_server.py` 新增 4 端点**

- `GET /api/self_evolve/list?status=pending` → 列出提议
- `GET /api/self_evolve/{id}` → 单个详情
- `POST /api/self_evolve/{id}/preview` → 返回沙箱预演三块
- `POST /api/self_evolve/{id}/approve` → 批准 + 注册
- `POST /api/self_evolve/{id}/reject` → 拒绝

**B6.5 改造 `electron/src/renderer/js/cognition-panel.js` 显示提议卡片**

- 监听 `self_evolve_proposed` SSE
- 在 `#cog-live` 顶部插入卡片：
  ```html
  <div class="cog-proposal-card">
    <div class="cog-proposal-header">
      <svg .../><span>伊塔想升级自己 · Self-evolve proposal</span>
    </div>
    <div class="cog-proposal-desc">描述: ...</div>
    <div class="cog-proposal-tool">提议工具: {schema 摘要}</div>
    <div class="cog-proposal-actions">
      <button class="cog-proposal-preview">查看预演 · Preview</button>
      <button class="cog-proposal-approve">批准 · Approve</button>
      <button class="cog-proposal-reject">拒绝 · Reject</button>
    </div>
  </div>
  ```
- 预览弹窗：3 块（输入/预计输出/风险）
- 批准 → 调 `/approve` → 卡片变绿（"已升级"）
- 拒绝 → 调 `/reject` → 卡片变灰（"已拒绝"）

**B6.6 验证**

- 模拟触发：构造一个"无法关闭电脑"的 react_trace + 一个失败的 tool_result
- 看到 self_evolve_proposed 事件 + 提议卡片
- 点"查看预演"看到 3 块
- 点"批准" → 卡片变绿 + `tool_registry` 多了一个工具
- 查 `self_evolve_log`：`SELECT user_decision FROM self_evolve_log WHERE id=?` → 'approved'

**验收**：能力缺口检测 + 沙箱预演弹窗 + 提议卡片 + 批准/拒绝全链路通

---

## 四、文件改动汇总

| 文件                                                 | 类型 | 估行数 | 说明                              |
| ---------------------------------------------------- | ---- | ------ | --------------------------------- |
| `communication/send_queue.py`                      | 改   | +20    | B2：切到 persona_pacing          |
| `core/api_server.py`                               | 改   | +120   | B3：yaml 4 端点 + B6：自进化 5 端点 |
| `core/self_evolving.py`                            | 新   | +180   | B6：能力缺口 + 沙箱预演          |
| `core/companion.py`                                | 改   | +5     | B6：注入 self_evolver             |
| `core/pipeline.py`                                 | 改   | +10    | B6：挂接 maybe_propose            |
| `electron/src/renderer/index.html`                 | 改   | +90    | B3 settings tabs + B4 大脑 tab + B5 history 区块 |
| `electron/src/renderer/js/cognition-panel.js`      | 新   | +400   | B4：大脑中枢 完整生产级 + B6 提议卡片 |
| `electron/src/renderer/js/emotion-dashboard.js`    | 改   | +200   | B5：历史曲线 + 雷达 + PAD bug 修 |
| `electron/src/renderer/js/settings.js`             | 改   | +150   | B3：双模式                        |
| `electron/src/renderer/js/app.js`                  | 改   | +5     | B4：初始化 CognitionPanel        |
| `electron/src/renderer/styles/cognition-panel.css` | 新   | +250   | B4：渐变玻璃风                    |
| `electron/src/renderer/styles/emotion-history.css` | 新   | +120   | B5：折线 + 雷达                  |
| `electron/src/main.js`                             | 改   | +50    | B4：SSE → IPC 转发               |
| `electron/src/preload.js`                          | 改   | +5     | B4：暴露 SSE 订阅                |

**总计**：4 个新文件 + 10 个改动 + 估约 1600 行新增

---

## 五、端到端验证 checklist

### Batch 2 收尾
- [ ] send_queue 第 1 段 < 100ms
- [ ] 后续段在 0.4-1.5s 区间（95%）
- [ ] 5% 病娇犹豫 2-5s
- [ ] `pacing_decisions` 写入 cognition_log

### Batch 3
- [ ] 设置页有"常用"和"高级"两个 tab
- [ ] 高级模式加载 settings.yaml / persona.yaml
- [ ] 故意写错 YAML → 400 + 自动回滚
- [ ] 备份文件出现在 `data/backups/`
- [ ] 日志写入 `data/aerie.log`

### Batch 4
- [ ] Sidebar 有"大脑" tab
- [ ] 切到大脑 tab 看到实时流
- [ ] 发消息 → 9 阶段水平时间轴显示
- [ ] 点详情 → 弹窗 + 4 意图赛马图 + ReAct 思维链
- [ ] filter 切换 source / user_id 生效
- [ ] 渐变玻璃风视觉一致

### Batch 5
- [ ] 24h / 7d / 30d 三档切换按钮工作
- [ ] PAD 三色折线 + 渐变填充
- [ ] 雷达图 3 维显示
- [ ] 喷发时刻红色虚线
- [ ] PAD 字段 bug 修复（值不再是 0.00）
- [ ] 人格化文案呈现

### Batch 6
- [ ] 触发能力缺口 → self_evolve_proposed 事件出现
- [ ] 提议卡片显示在 cog-live 顶部
- [ ] 沙箱预演弹窗 3 块
- [ ] 批准 → 卡片变绿 + 工具注册
- [ ] 拒绝 → 卡片变灰
- [ ] `self_evolve_log.user_decision` 正确

### 全链路
- [ ] 9 张老表零回归
- [ ] 4 张新表 + 3 索引
- [ ] 5 主题不破坏
- [ ] 伊塔人格文案一致（禁词"主人"、称呼"你"、中英双语）
- [ ] 代码层英文 + UI 层中英双语
- [ ] 启动后 `python main.py` 正常
- [ ] Electron `npm start` 正常

---

## 六、风险与回滚

| 风险                                  | 概率 | 影响         | 回滚方案                                                |
| ------------------------------------- | ---- | ------------ | ------------------------------------------------------- |
| send_queue pacing 签名不兼容        | 中   | QQ 卡死      | 保留 `message_pacing.compute_interval` 旧函数做兜底 |
| YAML 写入破坏启动                    | 中   | 致命         | 强校验 + 写回前自动备份 + 解析失败回滚（已设计）       |
| 沙箱预演 LLM 调用失败                | 中   | 提议卡不可点 | 显示"预演暂不可用" + 仍可批准/拒绝                   |
| SSE 长连接断                         | 中   | 实时性失效   | 前端重连 3s + 历史 list 兜底                          |
| cognition_log 表过大                 | 低   | 性能         | 不在本次范围（建议 7d 后归档脚本）                     |
| emotion-dashboard PAD bug 未完全修   | 低   | 显示 0.00    | `?? nullish` 兼容大小写（已设计）                       |

---

## 七、不在本次范围

- cognition_log 7d 自动归档
- 长期记忆改造
- 语音通话
- 移动端 APP
- 多人对话
- 真实 LLM 微调
- persona.yaml 字段语义化校验（仅 settings.yaml 严格解析）

---

## 八、执行顺序（严格串行 · 强约束）

```
B2 收尾 (0.25h)  send_queue 切 persona_pacing
   ↓
B3 (1.5h)        settings YAML 双模式
   ↓
B4 (2.5h)        大脑中枢 UI 完整生产级
   ↓
B5 (1.5h)        情绪历史曲线
   ↓
B6 (2.0h)        自进化机制
   ↓
E2E 验证 (0.5h)  全链路
```

**总工时估约 8.25h**（不含调试）

**强约束**：

- 每 Batch 完成后立即本地验证（不堆积）
- 任何 Batch 失败必须自我怀疑、回滚、再实施
- 严守"三原则"（不破坏现有功能 / 不破坏伊塔人格 / 设计美学统一）
- 全部代码可运行可验收，不允许"只写了你所以为的"
- 代码层纯英文 + UI 层中英双语

---

## 九、与现有约束兼容性自检

| 约束                          | 兼容性                                                     |
| ----------------------------- | ---------------------------------------------------------- |
| NapCat launcher-user.bat 启动 | ✓ 不动 launcher / start-companion                          |
| 消息 2000 字截断              | ✓ cognition_log 各字段 TEXT，无超长风险                   |
| 中英双语 + 代码英文           | ✓ SQL 注释 / 字段 / 函数名纯英文；UI 文案中英              |
| 9 张老表零回归                | ✓ 仅追加 + 集成（不动 schema）                            |
| 5 主题配色                    | ✓ 大脑中枢粉紫玻璃风兼容 5 主题                            |
| 伊塔 persona                  | ✓ 文案 v9.0 称呼"你"、禁词"主人"、温柔大姐姐+病娇         |
| `app_name` 用 Aerie         | ✓ 全部响应/SSE 事件名用英文                                |
| `parse_error` 不抛异常      | ✓ cognition / emotion / self_evolve 落库全 try/except     |
| 故障自愈 14 类                | ✓ 落库失败不阻塞主链路                                    |
| **首段立即**            | ✓ B2 send_queue 第 1 段 = 0                               |
| **persona 自主节奏**    | ✓ B2 用 persona_pacing 决策树                              |
| **配置可编辑**        | ✓ B3 YAML 双模式 + 强校验                                 |
| **情绪可视化**        | ✓ B5 折线 + 雷达                                           |
| **开发者后台**        | ✓ B4 大脑中枢完整生产级                                    |
| **自进化提议+沙箱**   | ✓ B6 中等敏感触发 + 轻量预演                              |

---

## 十、关键变更亮点

1. **修了 4 个核心缺口**：send_queue 切 persona_pacing / YAML 编辑 / 大脑中枢 / 情绪曲线 / 自进化
2. **完整生产级大脑中枢**：渐变玻璃风 + 9 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 + 实时 SSE + filter + 详情弹窗
3. **强校验 YAML 编辑**：解析失败回滚到上次备份，写回前自动备份
4. **轻量沙箱预演**：LLM 模拟执行 → 弹窗 3 块（输入/输出/风险）→ 批准/拒绝
5. **中等敏感自进化触发**：5 条件全满足才提案（react 关键词 + 工具失败 + 1h 去重 + 每日限流 3）
6. **不破坏现有功能**：9 张老表 + 5 主题 + 4 张新表 + 3 索引全部不动

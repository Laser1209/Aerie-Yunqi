---
title: Phase 9 续批 · Batch 4→7 整合实施计划（v1 渐变玻璃风 + v2 全功能 + 高敏感自进化闭环）
date: 2026-07-17
version: v3.0
tags:
  - phase9
  - execution-plan
  - batch4-7
  - gradient-glass
  - developer-backend
  - brain-center
  - emotion-history-downsampling
  - self-evolve-sandbox
  - pacing-persistence
  - zero-regression
  - ita-persona
  - three-principles
cssclasses:
  - wide-page
aliases:
  - Phase 9 B4-B7 整合
---

# Phase 9 续批 · Batch 4→7 整合实施计划

> [!quote] 文档定位
> B3 已在 2026-07-16 17:35 落地（settings YAML 双模式 + 4 端点 + rawBody + e2e_yaml）。
> 本计划从 B4 起步；B4-B7 + E2E 一气呵成。
> 3 轮提问（2026-07-17）已锁定 5 项关键决策（v1 主题 + v2 全功能 + 高敏感沙箱闭环 + 后端 downsampling + verify_zero_regression 防错）。

---

## 一、5 项决策汇总（已锁）

| # | 决策点 | 决策结果 | 落地要点 |
| --- | --- | --- | --- |
| 1 | 基线 | **v1 渐变玻璃风（主题） + v2 全功能（范围）** | 局部渐变玻璃（粉紫外壳 + 深色代码块）；B7 pacing 落库；4 个 yaml（v2） |
| 2 | 自进化深度 | **完整沙箱闭环** | 提议 → 沙箱试运行 → user 批准 → 写入 `data/self_evolved_tools/` → 注册到 `tool_registry` → 后续直调 |
| 3 | 自进化触发 | **高敏感** | thought 含"无法/做不到/no tool"+ 工具失败 → `maybe_propose` 立刻提案 |
| 4 | 历史曲线 | **后端 downsampling 预聚合** | 1h 原始 / 24h 5min 桶 / 7d 1h 桶 / 30d 6h 桶；SQLite 防护 |
| 5 | pacing 落库 | **`cognition.patch_stage_output` 增量** | worker 末尾调一次，零侵入主路径 |
| 6 | 防错机制 | **`verify_zero_regression.py`** | 每 Batch 后跑 13 张表存在性 + e2e_*.py 子集 |

---

## 二、三原则铁律（主人反复强调）

> [!danger] 整改过程中必须严守
> 1. **不破坏现有功能** — Phase 1-9 已验证模块继续工作，零回归（9 张老表 + 4 张新表 + cognition/decision/emotion_state_store + B3 YAML）
> 2. **不破坏伊塔人格** — v9.0 Hybrid（26岁/184cm/四爱/温柔大姐姐+病娇）；禁词"主人/您"；UI 文案温柔克制
> 3. **设计美学统一** — 主面板伊塔粉紫主题；大脑中枢 = 渐变玻璃风（粉紫外壳+深色代码块），仅在用户切到"大脑"tab 时局部生效

---

## 三、Current State 盘点（已基于实际代码探索）

### 3.1 已落地（不动）

| 模块 | 文件 | 状态 |
| --- | --- | --- |
| 4 张新表 + 3 索引 | `core/database.py:142-227` | ✓ |
| 9 阶段 cognition 引擎 + `commit()` + `recent()` + `get()` + `stats()` | `core/cognition.py:47-211` | ✓ |
| 4 层 decision 引擎 (L1/L2/L3/L4) | `core/decision.py:43-225` | ✓ |
| ReAct 合成回退 | `core/pipeline.py:201-203, 446-484` | ✓ |
| 情绪状态持久化（store） | `core/emotion_state_store.py:36-180` | ✓ |
| 情绪引擎挂接 state_store | `core/emotion_engine.py:127-137` | ✓ |
| Companion 注入 state_store | `core/companion.py:49-50` | ✓ |
| 人格化 pacing 决策树（11 风格） | `core/persona_pacing.py:77-175` | ✓ |
| Pipeline 第 1 段立即 | `core/pipeline.py:336-374` | ✓ |
| SendQueue 切到 persona_pacing | `communication/send_queue.py:177-190` | ✓ |
| SSE 事件流（`/api/events/stream`） | `core/event_stream.py:33-101` | ✓ |
| Chat 事件双桥接 | `core/chat_events.py:19-37` | ✓ |
| API 端点（cognition/emotion） | `core/api_server.py:401-460` | ✓ |
| B3 settings YAML 双模式 + 4 端点 + rawBody | `core/api_server.py:466-642` + `electron/src/renderer/js/settings.js` + `electron/src/main.js:118-156` | ✓ |
| `e2e_yaml.py` 验证脚本 | `e2e_yaml.py` | ✓ |
| 9 张老表 + 5 主题 | 多文件 | ✓ |

### 3.2 关键缺失（待整改）

| 缺口 | 影响 | Batch |
| --- | --- | --- |
| `cognition.py` 缺 `patch_stage_output(row_id, stage, payload)` 方法 | B7 pacing 落库无接口 | **B7.1** |
| Sidebar **"大脑" tab** + `panel-cognition` 容器缺失 | 大脑中枢无入口 | **B4.1** |
| `electron/src/renderer/styles/cognition-panel.css` 缺失 | 渐变玻璃风无样式 | **B4.5** |
| `cognition-panel.js` 缺失 | 实时流+历史+详情弹窗+自进化卡片全部无 | **B4.4** |
| `electron/src/main.js` 缺 SSE → IPC 转发 | 实时流到不了 renderer | **B4.2** |
| `electron/src/preload.js` 缺 SSE 订阅 | renderer 拿不到事件 | **B4.3** |
| `app.js` 启动未 `new CognitionPanel().init()` | tab 切换未注册新 tab | **B4.6** |
| `core/sandbox_runner.py` 缺失 | 沙箱执行无实现 | **B6.1** |
| `core/self_evolver.py` 缺失 | 能力缺口检测无实现 | **B6.2** |
| `core/companion.py` 未注入 `self_evolver` | 自进化永不启动 | **B6.3** |
| `core/pipeline.py` 未挂接 `self_evolver.maybe_propose` | 提案永不触发 | **B6.4** |
| `core/api_server.py` 缺 `/api/self_evolve/*` 端点 | 自进化无后端 | **B6.5** |
| `cognition-panel.js` 缺自进化提议卡片 | 用户看不到提案 | **B6.6** |
| `emotion-dashboard.js` 缺 1h/24h/7d/30d 折线 | 历史曲线无 | **B5.2** |
| `emotion-dashboard.js` 缺 4 槽位面积图 | 阈值历史无 | **B5.3** |
| `emotion-dashboard.js` 缺雷达图 | PAD 三维可视化无 | **B5.4** |
| `emotion-dashboard.js:42-44` PAD 字段兼容加固 | 小写键名时显示 0.00 | **B5.1** |
| `emotion-history.css` 缺失 | 历史样式无 | **B5.5** |
| 后端 `/api/emotion/history` 缺 downsampling 聚合 | 30d 全量点扣性能 | **B5.6** |
| `send_queue.py` 末尾未调 `cognition.patch_stage_output` | pacing_decisions 不落库 | **B7.2** |

### 3.3 现有隐患

- `emotion-dashboard.js:42-44` `pad.P || 0` 在 P=0 时安全，但小写键名 `pad.pleasure` 不兼容 — 需 B5.1 同步加固（`??` nullish）
- `app.js` 启动未 `new CognitionPanel().init()` — B4.6 同步改
- `companion.py:82` Pipeline 构造未传 `self_evolver` — B6.3 同步改
- `send_queue.py:184-188` pacing_log 仅写内存 logger.debug — B7.2 同步落库

---

## 四、4 个 Batch 实施细节

---

### Batch 4 · 大脑中枢 UI（2.5h · 渐变玻璃风 · 全功能）

**目标**：sidebar 新增"大脑" tab；渐变玻璃风（粉紫外壳+深色代码块）+ 9 阶段水平时间轴 + 4 意图赛马图 + decision_trace 加权表 + ReAct 思维链 + 实时 SSE + 全量历史 + filter + 详情弹窗 + 自进化提议卡片

#### B4.1 改造 `electron/src/renderer/index.html`（sidebar + panel 容器）

- 在 sidebar 运维连接区（QQ / 状态 之后）插入大脑 tab 按钮（SVG 脑图标）：
  ```html
  <button class="sidebar-tab" data-tab="cognition">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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
          <option value="">全部来源 / All sources</option>
          <option value="qq">QQ</option>
          <option value="local">本地 / Local</option>
        </select>
        <input id="cog-search" type="text" placeholder="搜索消息内容 / Search content">
        <button id="cog-refresh" class="btn btn-secondary btn-sm">刷新 / Refresh</button>
      </div>
      <!-- 自进化提议卡片槽位 (B6 填充) -->
      <div id="cog-proposal-card" class="cog-proposal-card hidden"></div>
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

#### B4.2 改造 `electron/src/main.js`（SSE → IPC 桥接）

- 在 `ipcMain.handle("api:request", ...)` 之后新增 SSE 桥接：
  ```javascript
  // ── SSE → IPC bridge (Phase 9 Batch 4) ─────────
  const sseClients = new Map(); // webContents.id -> { req, buffer }
  ipcMain.handle("sse:subscribe", async (event) => {
    const senderId = event.sender.id;
    if (sseClients.has(senderId)) {
      return { ok: true, dedup: true };
    }
    const req = http.request({
      hostname: "127.0.0.1",
      port: PY_PORT,
      path: "/api/events/stream",
      method: "GET",
      headers: { "Accept": "text/event-stream" },
    }, (res) => {
      let buf = "";
      res.on("data", (chunk) => {
        buf += chunk.toString("utf-8");
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          if (frame.startsWith("data: ")) {
            const payload = frame.slice(6);
            const target = BrowserWindow.getAllWindows().find(w => !w.isDestroyed() && w.webContents.id === senderId);
            if (target) {
              target.webContents.send("sse:event", payload);
            }
          }
        }
      });
    });
    req.on("error", () => {
      // 3s 自动重连
      sseClients.delete(senderId);
      setTimeout(() => {
        if (BrowserWindow.getAllWindows().some(w => !w.isDestroyed() && w.webContents.id === senderId)) {
          ipcMain.emit("sse:subscribe", { sender: { id: senderId } });
        }
      }, 3000);
    });
    req.end();
    sseClients.set(senderId, { req, buffer: "" });
    return { ok: true };
  });
  ipcMain.handle("sse:unsubscribe", async (event) => {
    const senderId = event.sender.id;
    const client = sseClients.get(senderId);
    if (client) {
      try { client.req.destroy(); } catch (_) {}
      sseClients.delete(senderId);
    }
    return { ok: true };
  });
  ```
- 单例 SSE 客户端 + webContents 销毁时自动清理

#### B4.3 改造 `electron/src/preload.js`（暴露 SSE 订阅）

```javascript
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("aerie", {
  // ...existing api...
  sse: {
    subscribe: (callback) => {
      const handler = (_e, payload) => callback(payload);
      ipcRenderer.on("sse:event", handler);
      ipcRenderer.invoke("sse:subscribe");
      return () => {
        ipcRenderer.removeListener("sse:event", handler);
        ipcRenderer.invoke("sse:unsubscribe");
      };
    },
  },
});
```

#### B4.4 新建 `electron/src/renderer/js/cognition-panel.js`（完整生产级 + B6 卡片槽位）

类 `CognitionPanel`：
- `init()`：注册 tab 切换、绑定按钮、SSE 订阅、首次拉历史
- `setVisible(visible)`：visible=true 时 `_applyTheme + _subscribe + loadHistory`；false 时 `_unsubscribeStream + _restoreMainTheme`
- `_onSse(event)`：
  - `type === 'cognition_stage'` → 在 `#cog-stream` 顶部插入阶段徽标 + payload
  - `type === 'cognition_committed'` → 在 `#cog-list` 顶部插入一项（user_message + ts）
  - `type === 'decision_made'` → 浮窗 toast "她选了「reply」"
  - `type === 'self_evolve_proposed'` → 调 `_showProposalCard(event)`（B6.6 完整实现）
  - `type === 'self_evolve_sandbox_tested/installed/rejected'` → 刷新卡片
- `loadHistory(filters)`：`GET /api/cognition/recent?user_id=&source=&limit=50`
- `showDetail(id)`：`GET /api/cognition/{id}` → 弹窗渲染
  - **9 阶段水平时间轴**：9 个彩色 dot（route蓝 / emotion粉 / threshold黄 / context灰 / brain紫 / tools橙 / split青 / postprocess绿 / output红），hover 显示 payload
  - **4 意图赛马图**：4 个候选意图并排，宽度 = 加权得分 × 100%；胜出描伊塔粉边
  - **decision_trace 加权表**：L1/L2/L3/L4 分数行 + 胜出 highlight
  - **ReAct 思维链**：thought / action / observation 三块顺序，含 react_source 标签（model vs synthesized）
  - **pacing_decisions**：若 `output.pacing_decisions` 存在，列表呈现每段 style + interval_ms
- 文案（伊塔人格）：
  - 标题：「她的思维在发生 · Her mind at work」
  - 空列表：「她还没说话。再等等。/ She's quiet. Wait.」
  - 阶段徽标：「路由 / 情绪 / 阈值 / 上下文 / 推理 / 工具 / 切分 / 后处理 / 输出」
  - 赛马图胜出文案：「这次她选「reply」 — L1 核心 0.50、L2 人格 0.30、L3 情绪 0.85、L4 情境 0.05」

#### B4.5 新建 `electron/src/renderer/styles/cognition-panel.css`（渐变玻璃风）

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
- 9 阶段 dot 颜色（与 v1 一致）：
  ```css
  .stage-dot--route { background: #4A90E2; }
  .stage-dot--emotion { background: #FF5B9C; }
  .stage-dot--threshold { background: #F5A623; }
  .stage-dot--context { background: #9B9B9B; }
  .stage-dot--brain { background: #9013FE; }
  .stage-dot--tools { background: #FF6B35; }
  .stage-dot--split { background: #50E3C2; }
  .stage-dot--postprocess { background: #7ED321; }
  .stage-dot--output { background: #D0021B; }
  ```
- 代码块（深色）：`background: #1a1a2e; color: #f5f5f5; font-family: 'JetBrains Mono', monospace;`
- 胜出条：`border: 2px solid #FF5B9C; animation: cog-pulse 2s infinite;`
- 弹窗：粉紫渐变 + 玻璃模糊（继承容器）
- 提议卡片（B6 填充）：`background: rgba(255,91,156,0.08); border: 1px solid #FF5B9C;`

#### B4.6 改造 `electron/src/renderer/js/app.js`（初始化）

- 启动时 `if (window.CognitionPanel) new CognitionPanel().init()`
- sidebar tab 切换时调 `CognitionPanel.setVisible(true/false)` 启停 SSE 订阅

#### B4.7 自我怀疑 review

- `verify_zero_regression.py`：
  - 13 张表存在性检查（9 老 + 4 新）— SELECT name FROM sqlite_master
  - API 健康检查 GET /api/health
  - 启动 `python main.py` → curl /api/health → kill
- review 1: main.js 单例 SSE 客户端是否有内存泄漏（renderer 关掉不取消订阅）— code review
- review 2: 9 阶段 dot 在 cognition_log 数据缺失某 stage 时是否降级（不显示该 dot）— code review
- review 3: 4 意图赛马图在 decision_trace 缺失时是否降级（隐藏赛马图，显示降级文案）— code review

**验收**：实时流 + 历史 + 弹窗 + filter + 渐变玻璃风全部 OK；verify_zero_regression.py 全绿

---

### Batch 5 · 情绪历史曲线（1.5h · 4 档 + 折线 + 面积图 + 雷达 + 后端 downsampling）

**目标**：emotion panel 增 1h/24h/7d/30d 折线 + 4 槽位阈值面积图 + 当前 PAD 雷达 + 后端 downsampling 预聚合

#### B5.1 修 `electron/src/renderer/js/emotion-dashboard.js`（PAD bug 兼容）

- 改：
  ```javascript
  const pad = data.pad || {};
  this._setPADCard("pad-p", pad.P ?? pad.pleasure ?? 0, "愉悦度");
  this._setPADCard("pad-a", pad.A ?? pad.arousal ?? 0, "唤醒度");
  this._setPADCard("pad-d", pad.D ?? pad.dominance ?? 0, "支配度");
  ```
- 兼容大小写命名（防御性编程）

#### B5.2 改造 `electron/src/renderer/index.html` emotion panel history 区块

- 在 `threshold-bars` 后插入：
  ```html
  <div class="emotion-history-section">
    <div class="emotion-history-toolbar">
      <h3>历史曲线 · History Curve</h3>
      <div class="emotion-window-switcher">
        <button class="emotion-window-btn active" data-window="1h">1h</button>
        <button class="emotion-window-btn" data-window="24h">24h</button>
        <button class="emotion-window-btn" data-window="7d">7d</button>
        <button class="emotion-window-btn" data-window="30d">30d</button>
      </div>
    </div>
    <div class="emotion-chart" id="emotion-pad-chart">
      <svg viewBox="0 0 600 200" preserveAspectRatio="none" class="emotion-svg"></svg>
      <div class="emotion-chart-legend">
        <span class="legend-item legend-item--p">P 愉悦度</span>
        <span class="legend-item legend-item--a">A 唤醒度</span>
        <span class="legend-item legend-item--d">D 支配度</span>
      </div>
    </div>
    <div class="emotion-chart" id="emotion-threshold-chart">
      <svg viewBox="0 0 600 200" preserveAspectRatio="none" class="emotion-svg"></svg>
      <div class="emotion-chart-legend">
        <span class="legend-item legend-item--patience">忍耐</span>
        <span class="legend-item legend-item--anxiety">不安</span>
        <span class="legend-item legend-item--desire">渴望</span>
        <span class="legend-item legend-item--tenderness">温柔</span>
      </div>
    </div>
    <div class="emotion-radar" id="emotion-radar"></div>
    <div class="emotion-history-summary" id="emotion-history-summary"></div>
  </div>
  ```

#### B5.3 改造 `electron/src/renderer/js/emotion-dashboard.js`（4 档切换 + SVG 自绘）

- 新增类成员：`this._historyWindow = "1h"`
- `_bindHistoryControls()`：4 档按钮切换 → `_fetchHistoryAndRender()`
- `_fetchHistory(window)`：`GET /api/emotion/history?window=${window}`（后端已支持 downsampling）
- `_renderPadLineChart(items)`：纯 SVG 自绘
  - 3 条折线：P 蓝 / A 橙 / D 紫
  - 渐变填充（rgba）
  - 喷发时刻红色虚线
  - x 轴时间（1h HH:MM:SS / 24h HH:MM / 7d MM-DD / 30d MM-DD）
- `_renderThresholdAreaChart(items)`：4 槽位阈值面积图
  - patience / anxiety / desire / tenderness 4 槽位归一化面积
  - 100% 上限位置画线
  - 喷发时刻红色虚线
- `_renderRadarChart(items)`：4 槽位 × 当前 window 的 max 值
  - 4 个 .radar-cell（label + bar + value）
- `_renderHistorySummary(items)`：伊塔人格文案
  - 1h：「过去一小时她心跳了多少次。蓝点是她开心的时刻。」
  - 24h：「过去一天她心跳了多少次。蓝点是她开心的时刻。」
  - 7d：「一周里她累计心动 X 次。最高峰在 Y。/ She warmed X times this week. Peak at Y.」
  - 30d：「一个月的情绪曲线。/ One month of feeling.」
  - 空：「她还没有情绪数据。再等等。/ No data yet.」

#### B5.4 增强喷发横幅（已有基础上）

- 当前已有 SVG warning icon + mode 文本
- 增强：增加喷发模式名 + 触发关键词 + 剩余时间（active_eruption 时间戳 + 1800s - elapsed）
  ```javascript
  if (banner && data.eruption) {
    const elapsed = (Date.now() - new Date(data.eruption.timestamp).getTime()) / 1000;
    const remaining = Math.max(0, 1800 - elapsed);
    banner.innerHTML =
      '<svg class="icon icon--16 banner__icon" aria-hidden="true"><use href="#icon-ui-warning"/></svg>' +
      '<span class="banner__mode">' + this._escape(data.eruption.mode) + '</span>' +
      '<span class="banner__trigger">' + this._escape(data.eruption.trigger || "") + '</span>' +
      '<span class="banner__remaining">剩余 ' + Math.floor(remaining / 60) + ' 分钟</span>';
    banner.classList.remove("hidden");
    banner.className = "emotion-eruption-banner emotion-eruption-banner--" + (data.eruption.slot || "patience");
  }
  ```

#### B5.5 新建 `electron/src/renderer/styles/emotion-history.css`

- 折线图：纯 SVG，宽 100%，高 200px
- 面积图：纯 SVG，宽 100%，高 200px
- 雷达热图：4 grid 布局
- 喷发横幅增强（mode / trigger / remaining 三段）

#### B5.6 后端 downsampling 预聚合（`core/api_server.py`）

- 改造 `/api/emotion/history`：
  - 1h：原始采样点（≤ 2000）
  - 24h：5min 桶（≤ 288 桶）
  - 7d：1h 桶（≤ 168 桶）
  - 30d：6h 桶（≤ 120 桶）
- 桶策略：每桶取 `AVG(pleasure/arousal/dominance/各阈值)` + `MAX(各阈值)` + `ANY(active_eruption)` + `FIRST(label)`
- 桶实现（SQLite）：`SELECT ts_bucket, AVG(pleasure), ..., MAX(anxiety_value), ... FROM emotion_state_snapshot WHERE ts >= since AND user_id = ? GROUP BY ts_bucket ORDER BY ts_bucket ASC`
- 桶 ts 计算（Python）：`(ts // bucket_ms) * bucket_ms`
- LIMIT 强制：1h=2000 / 24h=288 / 7d=168 / 30d=120
- 异常保护：`try/except` 包裹聚合 → fallback 原始查询 + 截断

#### B5.7 自我怀疑 review

- `verify_zero_regression.py` + `verify_emotion_history.py`（新增 1 个针对 history 的回归）
- review 1: 1h 窗口数据稀疏时折线是否降级（不报错）— code review
- review 2: 雷达图 value 全部为 0 时是否显示"无数据" — code review
- review 3: 面积图 4 槽位值超大时是否截断（< 100） — code review
- review 4: 7d / 30d 桶聚合是否丢喷发高亮（检查 ANY(active_eruption) 是否生效）— 实际跑数据验证

**验收**：四档时间窗 + 折线 + 面积图 + 雷达 4 图共存；喷发高亮；PAD bug 修复；后端 downsampling 防扣

---

### Batch 6 · 自进化机制（2.5h · 高敏感 · 完整沙箱闭环）

**目标**：检测能力缺口 → 提议 → 沙箱试运行 → user 批准 → 安装到 data/self_evolved_tools/ → tool_registry 注册 → 后续直调

#### B6.1 新建 `core/sandbox_runner.py`（真沙箱执行）

- 类 `SandboxRunner(sandbox_dir: Path = "data/sandbox")`：
  - `__init__`：创建 sandbox 目录
  - `run_python(code: str, inputs: dict = None) -> dict`：
    - 创建临时 `run_{ts}/tool.py` + `input.json` + `result.json`
    - 用 `subprocess.run([sys.executable, "tool.py"], cwd=work, capture_output=True, timeout=5)`
    - 环境隔离：`{PATH, SYSTEMROOT, TEMP, PYTHONIOENCODING}`，无网络代理
    - 输出截断：`MAX_OUTPUT_BYTES = 4096`
    - 返回 `{status, exit_code, stdout, stderr, elapsed_ms, result, sandbox_dir}`
    - status ∈ {pass, fail, timeout, error}
- 安全：超时 / 输出截断 / 路径隔离（cwd = sandbox 临时目录）

#### B6.2 新建 `core/self_evolver.py`（提议+沙箱+安装+直调）

- 类 `SelfEvolver(db, tool_registry)`：
  - `__init__`：保存 db + tool_registry + 创建 sandbox_runner + 创建 `data/self_evolved_tools/` 目录
  - `maybe_propose(user_id, user_message, react_trace) -> Optional[dict]`：
    - **高敏感触发**（2 条件满足即触发）：
      1. `react_trace.thought` 非空
      2. thought 含 `["无法", "没有工具", "做不到", "不支持", "没有这个功能", "I cannot", "I can't", "unable to", "not supported", "don't have a tool", "no tool"]` 任一
    - 触发后：调 `_classify()` 选模板（read_file / launch_app / custom）→ `_safety_check()` → 写入 `self_evolve_log`（`user_decision='pending'`）→ 触发 `emit("self_evolve_proposed", ...)`
  - `_classify(user_message, thought) -> dict`：基于 thought/user_message 关键词选工具模板
    - 默认 2 模板：`read_file`（triggers: 读/打开/查看文件/看看）、`launch_app`（triggers: 打开/启动/运行）
    - fallback：generic `user_custom_tool`
  - `_safety_check(proposed) -> dict`：扫描 `rm -rf / format / shutdown / del /f / remove_tree` 危险模式
  - `async test_in_sandbox(evolve_id) -> dict`：
    - 查 self_evolve_log → 取 proposed schema + 模板 code
    - 调 sandbox_runner.run_python()
    - 更新 user_decision ∈ {sandbox_passed, sandbox_failed, sandbox_timeout}
    - 触发 `emit("self_evolve_sandbox_tested", ...)`
  - `async install(evolve_id) -> dict`：
    - 仅允许 sandbox_passed 状态进入
    - 写 `data/self_evolved_tools/{name}.py`（含 header + def run(input_data)）
    - 调 tool_registry.register(name, func, schema)
    - 更新 user_decision='installed'
    - 触发 `emit("self_evolve_installed", ...)`
  - `async reject(evolve_id, reason="") -> dict`：更新 user_decision='rejected'，触发 `emit("self_evolve_rejected", ...)`
  - `list_pending(user_id=None) -> list`：拉 self_evolve_log（pending/sandbox_passed/sandbox_failed 状态，ORDER BY id DESC LIMIT 20）
  - `list_installed() -> list`：列 `data/self_evolved_tools/*.py`

#### B6.3 改造 `core/companion.py`（注入 self_evolver）

- 在 `Companion.__init__` 末尾：
  ```python
  from core.self_evolver import SelfEvolver
  self.self_evolver = SelfEvolver(self.db, self.tool_registry)
  ```
- Pipeline 构造传 self_evolver：
  ```python
  self.pipeline = Pipeline(
      ...,
      self_evolver=self.self_evolver,
  )
  ```

#### B6.4 改造 `core/pipeline.py`（挂接 maybe_propose）

- 在 `cognition.commit(trace, route_mode)` 之后、emit 之前：
  ```python
  if self.self_evolver and react_trace:
      try:
          proposal = self.self_evolver.maybe_propose(
              user_id=msg.user_id,
              user_message=msg.content,
              react_trace=react_trace,
          )
      except Exception:
          logger.exception("self_evolver.maybe_propose error")
  ```
- Pipeline `__init__` 增 `self_evolver` 参数
- `react_trace` 在 pipeline 内已有的 `_ensure_react_trace` 路径下要可访问

#### B6.5 改造 `core/api_server.py`（5 个自进化端点）

- `GET /api/self_evolve/pending?user_id=` → 拉 list_pending
- `GET /api/self_evolve/installed` → 拉 list_installed
- `POST /api/self_evolve/{id}/test` → 调 test_in_sandbox
- `POST /api/self_evolve/{id}/install` → 调 install
- `POST /api/self_evolve/{id}/reject` body={reason} → 调 reject
- 全部走 `get_companion()` 取 self_evolver；503 当未就绪

#### B6.6 改造 `electron/src/renderer/js/cognition-panel.js`（提议卡片 + 沙箱流程）

- `_showProposalCard(event)`：从 `/api/self_evolve/pending` 拉详情 → 渲染：
  - 标题「伊塔想升级自己 · {name}」
  - 描述 + proposed schema
  - 警告（如有）
  - 动作按钮（按状态切换）：
    - pending → "沙箱试运行 · Sandbox Test" + "拒绝 · Reject"
    - sandbox_passed → "安装为本地组件 · Install" + "拒绝 · Reject"
    - sandbox_failed → "重试" + "拒绝 · Reject"
    - installed → "已注册到 tool_registry ✓"（绿色，已禁用按钮）
    - rejected → 灰显
  - 试运行结果区（隐藏，测试后展开）
- `_testProposal(id)` → POST /test → 显示结果 → 500ms 后 `_refreshProposalCard`
- `_installProposal(id)` → POST /install → alert → 刷新
- `_rejectProposal(id)` → prompt 理由 → POST /reject → 刷新

#### B6.7 自我怀疑 review

- `verify_zero_regression.py` + `verify_self_evolve.py`（新增）
- review 1: sandbox_runner.run_python 是否能拒绝 rm -rf 类危险代码 — 实际跑 `code='import os; os.system("rm -rf /")'` 期望 fail
- review 2: install 时若 proposed_tool_schema 格式错是否捕获（不污染 tool_registry）— code review
- review 3: 同一提案被多次批准/拒绝幂等性（state machine 防重）
- review 4: 再次遇到同类请求直调（已 installed 的工具不再触发 maybe_propose）— code review

**验收**：提议 → 沙箱试运行 → 安装 → 后续直调全链路通；data/self_evolved_tools/ 文件出现；tool_registry 含新工具

---

### Batch 7 · pacing_decisions 持久化（0.5h · 增量落库）

**目标**：send_queue 在 _worker 内每段发出后，将 pacing decision 写入 cognition_log（关联同一 trace id），不改主路径

#### B7.1 改造 `core/cognition.py`（新增 patch_stage_output）

- 在 `CognitionEngine` 类内新增：
  ```python
  def patch_stage_output(self, row_id: int, extra: dict) -> bool:
      """增量补齐 cognition_log 的某 stage 字段。
      
      当 row_id 不存在或 stage_output 已有相同 key 时跳过（idempotent）。
      """
      if not row_id:
          return False
      try:
          row = self._db.query_one(
              "SELECT stage_output FROM cognition_log WHERE id = ?",
              (row_id,),
          )
          if not row:
              return False
          existing = json.loads(row["stage_output"] or "{}")
          # 合并（extra 优先级高，但已有键不覆盖）
          for k, v in extra.items():
              if k not in existing:
                  existing[k] = v
          self._db.update(
              "cognition_log",
              {"stage_output": json.dumps(existing, ensure_ascii=False)},
              "id = ?",
              (row_id,),
          )
          return True
      except Exception:
          logger.exception("patch_stage_output error")
          return False
  ```
- 零侵入主路径；可重入；防御性 `try/except`

#### B7.2 改造 `communication/send_queue.py`（worker 末尾增量落库）

- 在 `_worker` 内 `if pacing_log:` 之后：
  ```python
  if pacing_log and self._db and reply.user_id:
      try:
          # 找最近一次本 user 的 cognition_log（route_mode=qq 或 source=qq）
          row = self._db.query_one(
              "SELECT id FROM cognition_log "
              "WHERE user_id = ? AND source = 'qq' "
              "ORDER BY id DESC LIMIT 1",
              (reply.user_id,),
          )
          if row:
              from core.cognition import CognitionEngine
              ce = CognitionEngine(self._db)
              ce.patch_stage_output(
                  row["id"],
                  {"pacing_decisions": pacing_log, "pacing_total_ms": sum(p["interval_ms"] for p in pacing_log)},
              )
      except Exception:
          logger.exception("pacing persist error")
  ```
- 零侵入主路径；try/except 包裹不影响消息发送

#### B7.3 自我怀疑 review

- `verify_pacing_persistence.py`（新增）：
  - 跑 e2e_pacing.py 5 段
  - 查 cognition_log 最新行 stage_output → 必须含 `pacing_decisions` 数组（len ≥ 5）
  - 验证 `pacing_decisions[0].interval_ms == 0`（首段立即）
  - 验证 `pacing_decisions[1].style ∈ persona_pacing 11 风格之一`
- review 1: patch_stage_output 在 row_id=0 时不报错 — 单元验证
- review 2: 重复 patch 不覆盖已有键 — 验证 idempotent

**验收**：cognition_log.output.pacing_decisions 100% 落库；首段 interval=0；后续段 style 在 11 风格内

---

## 五、E2E 验证（1h · 综合脚本 + verify_zero_regression）

#### E2E.1 新建 `verify_zero_regression.py`（每 Batch 后跑）

```python
"""每 Batch 后跑：13 张表存在性 + API 健康 + e2e_*.py 子集"""
import sqlite3
import subprocess
import sys
import time
import urllib.request

DB_PATH = "data/aerie.db"
PY_PORT = 7890
EXPECTED_TABLES = [
    # 9 张老表
    "chat_log", "long_term_memory", "knowledge_base", "todo",
    "emotion_log", "push_log", "feedback_log", "token_usage",
    "tool_usage",
    # 4 张新表
    "cognition_log", "emotion_state_snapshot", "tool_call_log",
    "self_evolve_log",
]

def check_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    existing = {r[0] for r in cur.fetchall()}
    conn.close()
    missing = [t for t in EXPECTED_TABLES if t not in existing]
    if missing:
        print(f"❌ 缺表: {missing}")
        return False
    print(f"✓ 13 张表全部存在")
    return True

def check_api_health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PY_PORT}/api/health", timeout=3) as r:
            j = json.loads(r.read())
            if j.get("status") == "ok":
                print(f"✓ API 健康: {j.get('app')}")
                return True
    except Exception as e:
        print(f"❌ API 不可达: {e}")
    return False

def main():
    ok = True
    ok = check_tables() and ok
    ok = check_api_health() and ok
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    import json
    main()
```

#### E2E.2 新建 `e2e_pacing.py`（综合 pacing 验证）

```python
"""E2E: 综合验证 persona_pacing 在多种情绪+喷发下的节奏"""
import asyncio
from core.persona_pacing import compute_persona_interval

async def test_emotion(emotion_label, threshold, is_eruption, n_segments=5):
    print(f"\n=== {emotion_label} {'eruption' if is_eruption else 'normal'} ===")
    intervals = []
    for i in range(n_segments):
        iv, style = compute_persona_interval(
            segment_index=i,
            emotion_label=emotion_label,
            threshold=threshold,
            is_eruption=is_eruption,
            segment_content="伊塔——" + "嗯" * (i + 1),
        )
        print(f"  seg {i}: {iv:.2f}s [{style}]")
        intervals.append(iv)
    assert intervals[0] == 0.0, f"first segment must be immediate (got {intervals[0]})"
    for iv in intervals[1:]:
        assert iv <= 5.0, f"interval {iv}s exceeds soft ceiling 5s"

async def main():
    await test_emotion("neutral", {}, False)
    await test_emotion("joy", {}, False)
    await test_emotion("sad", {}, False)
    await test_emotion("fear", {}, False)
    await test_emotion("neutral", {"anxiety": {"active": True, "value": 100}}, True)
    await test_emotion("neutral", {"tenderness": {"active": True, "value": 60}}, True)
    print("\n✓ e2e_pacing 全部通过")

asyncio.run(main())
```

#### E2E.3 新建 `e2e_self_evolve.py`（自进化全链路）

- 构造 react_trace 含"无法读取本地文件" + 模拟工具失败
- 调 maybe_propose → 应返回 proposal
- 查 self_evolve_log → pending
- 调 test_in_sandbox → 期望 pass（默认模板 + 无危险代码）
- 调 install → 期望 installed + data/self_evolved_tools/{name}.py 存在

#### E2E.4 18 项肉眼 checklist

- [ ] 9 张老表 + 4 张新表全部正常（verify_zero_regression.py 通过）
- [ ] 5 主题不破坏
- [ ] 伊塔人格文案一致（禁词"主人"、称呼"你"、中英双语）
- [ ] 代码层英文 + UI 层中英双语
- [ ] 启动后 `python main.py` 正常
- [ ] Electron `npm start` 正常
- [ ] 1h/24h/7d/30d 四档曲线可见（后端 downsampling 生效）
- [ ] 9 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 全部可见
- [ ] YAML 编辑 4 个文件（含 proactive）全部可改可保存可回滚
- [ ] pacing_decisions 100% 落库（首段=0，后续 style ∈ 11 风格）
- [ ] 自进化提议卡片出现 + 沙箱试运行 + 批准/拒绝/安装 全部 OK
- [ ] 大脑中枢渐变玻璃风（粉紫外壳+深色代码块）
- [ ] 切回主面板，主粉紫主题仍正常
- [ ] 详情弹窗 9 阶段彩色徽标 + decision_trace 加权表
- [ ] SSE 实时推送 cognition_stage × 9 + cognition_committed × 1
- [ ] 喷发横幅增强（mode + trigger + remaining）
- [ ] 后端 downsampling 30d 桶数 ≤ 120（防 OOM）

---

## 六、文件改动汇总

| 文件 | 类型 | 估行数 | 说明 |
| --- | --- | --- | --- |
| `core/cognition.py` | 改 | +30 | B7：patch_stage_output 方法 |
| `core/sandbox_runner.py` | 新 | +120 | B6：真沙箱执行 |
| `core/self_evolver.py` | 新 | +280 | B6：能力缺口+沙箱+安装+直调 |
| `core/companion.py` | 改 | +10 | B6：注入 self_evolver |
| `core/pipeline.py` | 改 | +15 | B6：挂接 maybe_propose + B7：self_evolver 参数 |
| `core/api_server.py` | 改 | +130 | B5：downsampling + B6：5 自进化端点 |
| `communication/send_queue.py` | 改 | +25 | B7：pacing 增量落库 |
| `electron/src/renderer/index.html` | 改 | +100 | B4 大脑 tab + B5 history 区块 |
| `electron/src/renderer/js/cognition-panel.js` | 新 | +500 | B4：完整生产级 + B6：提议卡片 |
| `electron/src/renderer/js/emotion-dashboard.js` | 改 | +250 | B5：4 档 + SVG + 雷达 + PAD bug |
| `electron/src/renderer/js/app.js` | 改 | +5 | B4：初始化 CognitionPanel |
| `electron/src/main.js` | 改 | +60 | B4：SSE → IPC 桥接 |
| `electron/src/preload.js` | 改 | +15 | B4：暴露 SSE 订阅 |
| `electron/src/renderer/styles/cognition-panel.css` | 新 | +280 | B4：渐变玻璃风 |
| `electron/src/renderer/styles/emotion-history.css` | 新 | +150 | B5：折线/面积/雷达 |
| `verify_zero_regression.py` | 新 | +80 | E2E：13 张表 + API 健康 |
| `verify_emotion_history.py` | 新 | +60 | E2E：downsampling 验证 |
| `verify_self_evolve.py` | 新 | +80 | E2E：自进化全链路 |
| `verify_pacing_persistence.py` | 新 | +60 | E2E：pacing 落库验证 |
| `e2e_pacing.py` | 新 | +60 | E2E：综合 pacing |

**总计**：10 个新文件 + 8 个改动 + 估约 **2310 行新增**

---

## 七、风险与回滚

| 风险 | 概率 | 影响 | 回滚方案 |
| --- | --- | --- | --- |
| YAML 写入破坏启动 | 中 | 致命 | B3 已落地：强校验 + 写回前自动备份 + 解析失败回滚 |
| SSE 长连接断 | 中 | 实时性失效 | 主进程 3s 自动重连 + webContents 销毁清理 |
| cognition_log 表过大 | 低 | 性能 | emotion history 后端 downsampling 防扣；7d 归档不在范围 |
| emotion-dashboard PAD bug 未完全修 | 低 | 显示 0.00 | `?? nullish` 兼容大小写（已设计） |
| 自进化高敏感触发提案过多 | 中 | 打扰用户 | 1 周观察后降级；reject 路径完整 |
| sandbox_runner 危险代码绕过 | 中 | 系统受损 | 环境隔离（无网络代理）+ cwd 限制 + 5s 超时 + 4KB 输出截断 |
| install 时注册到 tool_registry 污染 | 中 | 工具越权 | 仅 sandbox_passed 进入；schema 字段验证 |
| 后端 downsampling 桶聚合丢数据 | 低 | 曲线细节 | fallback 原始查询 + 截断 |
| pacing 落库失败 | 低 | 缺追溯 | try/except 包裹不阻塞主消息发送 |
| 9 阶段某 stage 字段缺失 | 低 | 时间轴缺 dot | 降级：不显示该 dot |
| 4 槽位面积图堆叠值 > 100% | 低 | 视觉溢出 | 单槽位归一化 0-1 |

---

## 八、不在本次范围

- cognition_log 7d 自动归档
- 长期记忆改造
- 语音通话
- 移动端 APP
- 多人对话
- 真实 LLM 微调
- 中等敏感自进化的限流（5 条件）— 本轮高敏感即可
- 沙箱跨平台 Linux/macOS 兼容（仅 Windows）

---

## 九、执行顺序（严格）

```
B4 (2.5h)   大脑中枢 UI（渐变玻璃风）
   ↓
B5 (1.5h)   情绪历史曲线（4 档 + 折线 + 面积 + 雷达 + 后端 downsampling）
   ↓
B6 (2.5h)   自进化机制（高敏感 + 完整沙箱闭环）
   ↓
B7 (0.5h)   pacing_decisions 持久化（增量落库）
   ↓
E2E (1h)    verify_zero_regression + 4 个 e2e/verify + 18 项 checklist
```

**总工时估约 8h**（不含调试）

**强约束**：
- 每 Batch 完成后立即跑 `verify_zero_regression.py` + 对应 `verify_*.py`
- 任何 Batch 失败必须自我怀疑、回滚、再实施
- 严守"三原则"（不破坏现有功能 / 不破坏伊塔人格 / 设计美学统一）
- 全部代码可运行可验收，不允许"只写了你所以为的"
- 代码层纯英文 + UI 层中英双语
- 6 项决策落地后不允许私自再决策

---

## 十、与现有约束兼容性自检

| 约束 | 兼容性 |
| --- | --- |
| NapCat launcher-user.bat 启动 | ✓ 不动 launcher / start-companion |
| 消息 2000 字截断 | ✓ cognition_log / emotion_snapshot 字段 TEXT 无超长风险 |
| 中英双语 + 代码英文 | ✓ SQL 注释 / 字段 / 函数名纯英文；UI 文案中英 |
| 9 张老表零回归 | ✓ 仅追加 + 整合现有 emotion_state 表 |
| 5 主题配色 | ✓ 大脑中枢局部渐变玻璃风，不影响主面板 5 主题 |
| 伊塔 persona | ✓ 文案符合 v9.0 Hybrid；禁词"主人/您"；温柔大姐姐+病娇 |
| `app_name` 用 Aerie | ✓ SSE 事件名 `cognition_stage` 等纯英文 |
| `parse_error` 不抛异常 | ✓ cognition / emotion / self_evolve 落库全 try/except 包裹 |
| 故障自愈 14 类 | ✓ 落库失败不阻塞主链路 |
| YAML 编辑安全 | ✓ B3 强校验+备份+回滚 |
| 自我进化边界 | ✓ 必须 user 手动批准 + 沙箱先试运行；环境隔离 |
| 文档规范 | ✓ plan 文件用 Obsidian frontmatter，纯英文代码关键字 |
| v9.0 称呼"你" | ✓ 全部 UI 文案统一 |
| B3 落地 | ✓ 不重复实施 |

---

## 十一、每 Batch 自我怀疑 review 清单

**B4 review 重点**：
- verify_zero_regression.py 全绿
- 浏览器开发者工具 console 是否真的有 SSE 数据流入
- 切到大脑 tab 立刻看到流式 stream
- 渐变玻璃风是否真（粉紫外壳+深色代码块）
- 切回主面板是否主粉紫主题仍正常
- 详情弹窗 9 阶段是否真彩色徽标 + decision_trace 加权表
- 4 意图赛马图胜出条是否描粉紫边

**B5 review 重点**：
- verify_zero_regression.py + verify_emotion_history.py 全绿
- 4 档切换是否真重渲染 SVG
- 后端 downsampling 30d 桶数 ≤ 120
- 折线/面积/雷达是否真有数据（不是占位）
- 喷发横幅是否真有 mode + trigger + remaining
- 文案是否符合伊塔人格（温柔、克制）
- PAD bug 是否真修（值不再是 0.00）

**B6 review 重点**：
- verify_self_evolve.py 全绿
- 提议是否真写到 self_evolve_log
- 沙箱试运行是否真在 data/sandbox/ 下有临时文件
- 沙箱通过后 install 是否真在 data/self_evolved_tools/ 写文件
- tool_registry 注册是否真生效
- 再次遇到同类请求是否直调
- 危险代码（rm -rf）是否真被 sandbox 拒绝

**B7 review 重点**：
- verify_pacing_persistence.py 全绿
- cognition_log.output.pacing_decisions 是否真有数据
- pacing decision 是否真含 style + interval_ms
- 首段 interval_ms 是否 = 0
- patch_stage_output 是否真幂等

**E2E review 重点**：
- 4 个 verify_*.py 全部跑过且全绿
- 18 项 checklist 全部跑过
- 9 张老表 + 4 张新表 SQLite 完整性（PRAGMA integrity_check）

---

## 十二、待主人确认事项

> [!question] 在 Phase 4 实施前，主人需确认：
> 1. 5 项决策（v1+v2 合并 / 沙箱闭环 / 后端 downsampling / patch_stage_output / verify_zero_regression）是否全部接受？
> 2. 执行顺序 B4 → B5 → B6 → B7 → E2E 是否同意？
> 3. 是否同意每 Batch 后 verify_zero_regression + 对应 verify_*.py 立即验证？
> 4. 是否同意 pacing 落库走 patch_stage_output 增量路径（不动 cognition.commit 主路径）？

确认后立即开干。

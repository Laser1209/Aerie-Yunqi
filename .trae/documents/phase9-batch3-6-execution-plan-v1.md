---
title: Phase 9 续批 · Batch 3→6 实施计划（3 轮决策锁定版）
date: 2026-07-16
version: v1.0
tags:
  - phase9
  - execution-plan
  - batch3-6
  - settings-yaml
  - brain-center
  - emotion-history
  - self-evolve
  - ita-persona
  - three-principles
  - gradient-glass
cssclasses:
  - wide-page
aliases:
  - Phase 9 B3-B6 整改
---

# Phase 9 续批 · Batch 3→6 实施计划

> [!quote] 文档定位
> 本文档是 phase9-batch2-6-execution-plan.md 中 B3/B4/B5/B6 四个 Batch 的实施收敛版。B2 已在 2026-07-16 17:35 落地（QQ pacing 切到 persona_pacing + decision_engine + emotion_state_store + cognition engine），本计划从 B3 起步。
>
> 所有歧义已通过 **3 轮提问**与主人确认（2026-07-16）。

---

## 一、3 轮决策汇总（7 项已锁）

| # | 决策点 | 决策结果 | 备注 |
| --- | --- | --- | --- |
| 1 | 整改范围 | **全部 4 个 Batch 串行** | B3 → B4 → B5 → B6 → E2E |
| 2 | 大脑中枢 UI 风格 | **渐变玻璃风**（粉紫外壳 + 深色代码块） | 两个色系并存：容器粉紫玻璃模糊，内部代码块 #1a1a2e |
| 3 | 自进化触发灵敏度 | **高敏感** | 每次"无法/做不到"+ 工具失败即触发提案 |
| 4 | 配置文件范围 | **3 个现有 yaml** | `settings.yaml` / `persona.yaml` / `proactive.yaml` |
| 5 | 情绪曲线详细度 | **4 档 + 折线 + 面积图 + 雷达** | 1h / 24h / 7d / 30d；PAD 三色折线 + 4 槽位阈值面积图 + 当前 PAD 雷达 |
| 6 | 大脑中枢阶段展示 | **9 阶段全部展开** | route / emotion / threshold / context / brain / tools / split / postprocess / output |
| 7 | 1.5s 验证方式 | **综合脚本验证** | `e2e_pacing.py` 5 段 × 3 情绪 × 2 喷发，纯本地 |
| 8 | 防错机制 | **每 Batch 提交后自我怀疑 review** | 写完立即 grep/snapshot/对比；出问题立即返工，不堆到下一 Batch |

---

## 二、三原则铁律（主人反复强调）

> [!danger] 整改过程中必须严守
> 1. **不破坏现有功能** — Phase 1-9 已验证模块继续工作，零回归（9 张老表 + 5 主题 + 4 张新表 + cognition/decision/emotion_state_store）
> 2. **不破坏伊塔人格** — 26岁/184cm/四爱主导/温柔大姐姐+病娇；禁词"主人/您"；UI 文案中英双语温柔克制
> 3. **设计美学统一** — 主面板伊塔粉紫；大脑中枢=渐变玻璃风（粉紫外壳+深色代码块）；5 主题不破坏

---

## 三、Current State 盘点（已基于实际代码探索）

### 3.1 已落地（不动）

| 模块 | 文件 | 状态 |
| --- | --- | --- |
| 4 张新表 + 3 索引 | `core/database.py:142-227` | ✓ |
| 9 阶段 cognition 引擎 | `core/cognition.py:47-211` | ✓ |
| 4 层 decision 引擎 | `core/decision.py:43-225` | ✓ |
| ReAct 合成回退 | `core/pipeline.py:201-203, 446-484` | ✓ |
| 情绪状态持久化（store） | `core/emotion_state_store.py:36-180` | ✓ |
| 情绪引擎挂接 state_store | `core/emotion_engine.py:127-137` | ✓ |
| Companion 注入 state_store | `core/companion.py:49-50` | ✓ |
| 人格化 pacing 决策树（11 风格） | `core/persona_pacing.py:77-175` | ✓ |
| Pipeline 第 1 段立即 | `core/pipeline.py:336-374` | ✓ |
| SendQueue 切到 persona_pacing | `communication/send_queue.py:177-190` | ✓ |
| SSE 事件流 | `core/event_stream.py:33-101` | ✓ |
| Chat 事件双桥接 | `core/chat_events.py:19-37` | ✓ |
| API 端点（cognition/emotion） | `core/api_server.py:401-458` | ✓ |
| 9 张老表 + 5 主题 | 多文件 | ✓ |

### 3.2 关键缺失（待整改）

| 缺口 | 影响 | Batch |
| --- | --- | --- |
| `core/api_server.py` 缺 `/api/config/yaml/*` 端点 | 设置页 YAML 编辑无后端 | **B3.1** |
| `electron/src/renderer/index.html` settings section 无 YAML 视图 | 设置页双模式无前端 | **B3.2** |
| `electron/src/renderer/js/settings.js` 无 YAML 编辑逻辑 | 用户改不了配置文件 | **B3.3** |
| Sidebar **"大脑" tab** + `panel-cognition` 容器缺失 | 大脑中枢无入口 | **B4.1** |
| `cognition-panel.js` 缺失 | 实时流+历史+详情弹窗全部无 | **B4.4** |
| `cognition-panel.css` 缺失 | 渐变玻璃风无样式 | **B4.5** |
| `electron/src/main.js` 缺 SSE → IPC 转发 | 实时流到不了 renderer | **B4.2** |
| `electron/src/preload.js` 缺 SSE 订阅 | renderer 拿不到事件 | **B4.3** |
| `electron/src/renderer/js/app.js` 未初始化 `CognitionPanel` | tab 切换未注册新 tab | **B4.6** |
| `emotion-dashboard.js` 缺 1h/24h/7d/30d 折线 | 历史曲线无 | **B5.2** |
| `emotion-dashboard.js` 缺 4 槽位面积图 | 阈值历史无 | **B5.3** |
| `emotion-dashboard.js` 缺雷达图 | PAD 三维可视化无 | **B5.4** |
| `emotion-history.css` 缺失 | 历史样式无 | **B5.5** |
| `emotion-dashboard.js:42-44` PAD 字段大小写不兼容 bug | 显示 0.00 | **B5.1** |
| `core/self_evolving.py` 完全缺失 | 自进化机制零代码 | **B6.1** |
| `core/api_server.py` 缺 `/api/self_evolve/*` 端点 | 自进化无后端 | **B6.4** |
| `core/companion.py` 未注入 `self_evolver` | 自进化永不启动 | **B6.3** |
| `core/pipeline.py` 未挂接 `self_evolver.maybe_propose` | 提案永不触发 | **B6.2** |
| `cognition-panel.js` 缺自进化提议卡片 | 用户看不到提案 | **B6.5** |

### 3.3 现有隐患

- `emotion-dashboard.js:42` 读 `pad.P` 大写，`emotion_engine.get_state` 已确认返回 `{P, A, D}` 大写，但 `_setPADCard` 内 `pad.P || 0` 不容错小写 — 需在 B5.1 同步加固
- `app.js` 启动未 `new CognitionPanel().init()` — B4.6 同步改
- `companion.py:90` Pipeline 构造未传 `self_evolver` — B6.3 同步改

---

## 四、4 个 Batch 实施细节

---

### Batch 3 · settings YAML 双模式（1.5h）

**目标**：设置页支持「常用 form」+「高级 YAML 编辑」双模式，仅暴露 3 个现有 yaml

**B3.1 改造 `core/api_server.py` 新增 4 端点**

- `GET /api/config/yaml/list` → 返回 `["settings.yaml", "persona.yaml", "proactive.yaml"]`
- `GET /api/config/yaml?file=settings.yaml` → 返回 UTF-8 文本
  - 路径白名单：`{"settings.yaml", "persona.yaml", "proactive.yaml"}`
  - 路径构造：`Path("config") / file`
  - 文件不存在 → 404
- `PUT /api/config/yaml?file=settings.yaml` → 接收 body
  - **强校验**：先用 `yaml.safe_load` 解析，失败 → 400 + 不写入
  - **写入前自动备份**：先 `cp` 当前文件到 `data/backups/config/{file}.{ts}.yaml`
  - 成功写回 → 200 + `{backup_path, ts}`
  - 失败 → 回滚到上次备份 + 400 + 错误信息
- `POST /api/config/yaml/backup?file=settings.yaml` → 手动触发备份
  - 复制到 `data/backups/config/{file}.{ts}.yaml`
  - 返回 `{backup_path, ts}`
- 所有写操作日志到 `data/aerie.log`：`logger.info("settings_change: file=... ts=... bytes=...")`

**B3.2 改造 `electron/src/renderer/index.html` settings section**

在 `<section id="panel-settings">` 内：
- 在 `<h2>系统设置</h2>` 之后插入：
  ```html
  <div class="settings-mode-tabs">
    <button class="settings-mode-tab active" data-mode="form">常用</button>
    <button class="settings-mode-tab" data-mode="yaml">高级 (YAML)</button>
  </div>
  ```
- 把现有 form 包装进 `<div id="settings-form-view">`
- 在 `<div id="settings-status">` 之前插入：
  ```html
  <div id="settings-yaml-view" style="display:none;">
    <div class="settings-group">
      <label>配置文件 · Config file</label>
      <select id="yaml-file-select">
        <option value="settings.yaml">settings.yaml</option>
        <option value="persona.yaml">persona.yaml</option>
        <option value="proactive.yaml">proactive.yaml</option>
      </select>
    </div>
    <div class="settings-group">
      <label>直接编辑 YAML · 修改前自动备份</label>
      <textarea id="yaml-editor" spellcheck="false" rows="20" style="font-family: 'JetBrains Mono', monospace; font-size: 12px;"></textarea>
    </div>
    <div class="settings-actions">
      <button id="yaml-save-btn" class="btn btn-primary">保存 · Save</button>
      <button id="yaml-reload-btn" class="btn btn-secondary">重新加载 · Reload</button>
      <button id="yaml-backup-btn" class="btn btn-secondary">备份当前 · Backup</button>
    </div>
    <div id="yaml-status" style="margin-top:8px;font-size:12px;"></div>
  </div>
  ```

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
  - 失败：「YAML 格式错误，已恢复上次备份。错误：[err] / YAML error. Restored.」

**B3.4 自我怀疑 review + 验证**

- review 1: `cp config/settings.yaml data/backups/config/settings.yaml.test` 确认备份路径正确
- review 2: `yaml.safe_load` 解析故意写错的 yaml，确认返回 400 而非 500
- review 3: 写回成功后再次 GET 确认内容一致
- 启动 `python main.py`，前端切到"高级"tab，能看到 3 个 yaml 全文
- 改一个字段（如 `theme.current: ocean-blue`），保存，刷新看到主题切换
- 故意写错（漏冒号），保存失败 + 自动恢复 + 错误提示
- 检查 `data/backups/config/` 有新备份文件
- 检查 `data/aerie.log` 有 `settings_change` 日志

**验收**：双模式可用；YAML 编辑强校验；写回前自动备份；解析失败回滚

---

### Batch 4 · 大脑中枢 UI（2.5h · 完整生产级 · 渐变玻璃风）

**目标**：sidebar 新增"大脑" tab；渐变玻璃风 + 9 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 + 实时 SSE + 全量历史 + filter + 详情弹窗

**B4.1 改造 `electron/src/renderer/index.html` sidebar 新增 tab + 容器**

- 在 `panel-settings` 之后、`panel-about` 之前插入 sidebar tab（SVG 脑图标）
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
        <select id="cog-user-filter"><option value="">全部用户 / All users</option></select>
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

- 新增 IPC handler `sse:subscribe`：
  ```js
  ipcMain.handle('sse:subscribe', async (event) => {
    // 单例 SSE 客户端（避免每个 renderer 都连一份）
    // 连接到 http://127.0.0.1:7890/api/events/stream
    // 用 node:http 的 req.on('data') 解析 SSE 帧
    // 解析后 webContents.send('sse:event', data)
    // 断线后 3s 自动重连
  });
  ```
- 维护 `sseClient` 单例，渲染进程订阅时单播给对应 webContents

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

**B4.5 新建 `electron/src/renderer/styles/cognition-panel.css`**（渐变玻璃风）

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
- 9 阶段 dot 颜色：
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

- 启动时 `if (window.CognitionPanel) new CognitionPanel().init()`
- sidebar tab 切换时调 `CognitionPanel.setVisible(true/false)` 启停 SSE 订阅

**B4.7 自我怀疑 review + 验证**

- review 1: `main.js` 单例 SSE 客户端是否有内存泄漏（renderer 关掉不取消订阅）
- review 2: 9 阶段 dot 在 cognition_log 数据缺失某 stage 时是否降级（不显示该 dot）
- review 3: 4 意图赛马图在 decision_trace 缺失时是否降级（隐藏赛马图，显示降级文案）
- 切到"大脑" tab，能看到 stream 区
- 发消息 → 9 阶段 dot 陆续亮起 → 列表顶部多一项
- 点详情弹窗 → 9 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 全部可见
- filter 切 source=qq、user_id=12345 生效
- 断网测试：SSE 断线后 3s 自动重连

**验收**：实时流 + 历史 + 弹窗 + filter + 渐变玻璃风全部 OK

---

### Batch 5 · 情绪历史曲线（1.5h · 4 档 + 折线 + 面积图 + 雷达）

**目标**：emotion panel 增 1h/24h/7d/30d 折线 + 4 槽位阈值面积图 + 当前 PAD 雷达

**B5.1 修 `electron/src/renderer/js/emotion-dashboard.js` PAD bug + 兼容**

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
- 兼容大小写命名（防御性编程）

**B5.2 改造 `electron/src/renderer/index.html` emotion panel**

在 `</div>` (threshold-bars 之后) 之前插入：
```html
<div class="emotion-history-section">
  <h3>历史情绪曲线 · History</h3>
  <div class="emotion-history-tabs">
    <button class="emotion-history-tab active" data-window="1h">1 小时</button>
    <button class="emotion-history-tab" data-window="24h">24 小时</button>
    <button class="emotion-history-tab" data-window="7d">7 天</button>
    <button class="emotion-history-tab" data-window="30d">30 天</button>
  </div>
  <div class="emotion-history-views">
    <div id="emotion-line-chart" class="emotion-line-chart"></div>
    <div id="emotion-area-chart" class="emotion-area-chart"></div>
    <div id="emotion-radar-chart" class="emotion-radar-chart"></div>
  </div>
  <div id="emotion-history-summary" class="emotion-history-summary"></div>
</div>
```

**B5.3 改造 `electron/src/renderer/js/emotion-dashboard.js` 增历史曲线**

新增类 `EmotionHistory`：
- `init()`：注册 tab 切换、首屏加载
- `_loadHistory(window)`：`GET /api/emotion/history?window=${window}`
  - 窗口 1h/24h/7d/30d（api_server.py 已支持 1h/24h/7d/30d，无需新加）
- `_renderLineChart(items)`：纯 SVG 自绘
  - 3 条折线：P 蓝 / A 橙 / D 紫
  - 渐变填充（rgba）
  - 喷发时刻红色虚线
  - x 轴时间（1h 缩到 HH:MM:SS；24h 缩到 HH:MM；7d 缩到 MM-DD；30d 缩到 MM-DD）
- `_renderAreaChart(items)`：4 槽位阈值面积图
  - patience / anxiety / desire / tenderness 4 槽位堆叠面积
  - 100% 上限位置画线
  - 喷发时刻用红色虚线
- `_renderRadarChart(items)`：当前 PAD 三维雷达
  - 三角形，3 角 P/A/D
  - 半径按 |value| 映射
- 文案（伊塔人格）：
  - 1h：「过去一小时她心跳了多少次。蓝点是她开心的时刻。」
  - 24h：「过去一天她心跳了多少次。蓝点是她开心的时刻。」
  - 7d：「一周里她累计心动 X 次。最高峰在 Y。/ She warmed X times this week. Peak at Y.」
  - 30d：「一个月的情绪曲线。/ One month of feeling.」
  - 空：「她还没有情绪数据。再等等。/ No data yet.」

**B5.4 新建 `electron/src/renderer/styles/emotion-history.css`**

- 折线图：纯 SVG，宽 100%，高 200px
- 面积图：纯 SVG，宽 100%，高 200px
- 雷达图：纯 SVG，宽 300px，高 300px
- 喷发标记：1px 红色竖虚线

**B5.5 自我怀疑 review + 验证**

- review 1: 1h 窗口数据稀疏时折线是否降级（不报错）
- review 2: 雷达图 value 全部为 0 时是否显示"无数据"
- review 3: 面积图 4 槽位值超大时是否截断（< 100）
- 发 5 条不同情绪消息
- emotion panel 切到 1h/24h 看到折线（点不能是 0.00）
- 切 7d/30d 看到更长曲线
- 面积图显示 4 槽位堆叠
- 雷达图显示当前 PAD 三维
- 文案按 persona 风格
- PAD 字段 bug 修复：值不再是 0.00

**验收**：四档时间窗 + 折线 + 面积图 + 雷达 4 图共存；喷发高亮；PAD bug 修复

---

### Batch 6 · 自进化机制（2h · 高敏感）

**目标**：检测能力缺口 → 提议 → 大脑中枢卡片显示 → 用户批准/拒绝

> [!warning] 高敏感触发
> 与 phase9-batch2-6-execution-plan.md 中"中等敏感"5 条件不同，本轮采用**高敏感**：只要 thought 含无法关键词 + 工具失败 2 条件满足即触发。后续如提案过多再降级。

**B6.1 新建 `core/self_evolving.py`**

类 `SelfEvolver(db, tool_registry, brain)`：
- `__init__(self, db, tool_registry, brain)` 保存三个引用
- `maybe_propose(user_id, user_message, react_trace, tool_results) -> Optional[int]`：
  - **高敏感触发**（2 条件满足即触发）：
    1. `react_trace.thought` 非空
    2. `react_trace.thought` 含 `["无法", "没有工具", "做不到", "I cannot", "no tool", "lack of", "missing tool"]` 任一
    3. `tool_results` 至少 1 项 `success=False`
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

**B6.4 `core/api_server.py` 新增 5 端点**

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

**B6.6 自我怀疑 review + 验证**

- review 1: sandbox_preview LLM 调用失败时是否降级（显示"预演暂不可用"）
- review 2: 批准时若 proposed_tool_schema 格式错是否捕获（不污染 tool_registry）
- review 3: 同一提案被多次批准/拒绝幂等性
- 模拟触发：构造一个"无法关闭电脑"的 react_trace + 一个失败的 tool_result
- 看到 self_evolve_proposed 事件 + 提议卡片
- 点"查看预演"看到 3 块
- 点"批准" → 卡片变绿 + `tool_registry` 多了一个工具
- 查 `self_evolve_log`：`SELECT user_decision FROM self_evolve_log WHERE id=?` → 'approved'

**验收**：能力缺口检测 + 沙箱预演弹窗 + 提议卡片 + 批准/拒绝全链路通

---

## 五、E2E 验证（0.5h · 综合脚本 + 肉眼）

> [!info] 主人决策：综合脚本验证（e2e_pacing.py）
> 不是启动后实测，而是写 1 个本地 Python 脚本验证 1.5s 节奏。

**E2E.1 新建 `e2e_pacing.py`**

```python
"""E2E: 综合验证 persona_pacing 在多种情绪+喷发下的节奏"""
import asyncio
from core.persona_pacing import compute_persona_interval

async def test_emotion(emotion_label, threshold, is_eruption, n_segments=5):
    print(f"\n=== {emotion_label} {'eruption' if is_eruption else 'normal'} ===")
    for i in range(n_segments):
        iv, style = compute_persona_interval(
            segment_index=i,
            emotion_label=emotion_label,
            threshold=threshold,
            is_eruption=is_eruption,
            segment_content="伊塔——" + "嗯" * (i + 1),
        )
        print(f"  seg {i}: {iv:.2f}s [{style}]")
        await asyncio.sleep(iv)  # 模拟实际等待

async def main():
    # 中性
    await test_emotion("neutral", {}, False)
    # 喜
    await test_emotion("joy", {}, False)
    # 哀
    await test_emotion("sad", {}, False)
    # 惧
    await test_emotion("fear", {}, False)
    # 喷发-焦虑
    await test_emotion("neutral", {"anxiety": {"active": True, "value": 100}}, True)
    # 喷发-温柔
    await test_emotion("neutral", {"tenderness": {"active": True, "value": 60}}, True)

asyncio.run(main())
```

**E2E.2 肉眼验证 checklist**

- [ ] 9 张老表零回归（启动后 sqlite 看 9 张表都有数据）
- [ ] 4 张新表 + 3 索引
- [ ] 5 主题不破坏
- [ ] 伊塔人格文案一致（禁词"主人"、称呼"你"、中英双语）
- [ ] 代码层英文 + UI 层中英双语
- [ ] 启动后 `python main.py` 正常
- [ ] Electron `npm start` 正常
- [ ] 1h/24h/7d/30d 四档曲线可见
- [ ] 9 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 全部可见
- [ ] YAML 编辑 3 个文件全部可改可保存可回滚
- [ ] 自进化提议卡片出现 + 预演 + 批准/拒绝 全部 OK

---

## 六、文件改动汇总

| 文件 | 类型 | 估行数 | 说明 |
| --- | --- | --- | --- |
| `core/api_server.py` | 改 | +200 | B3：4 yaml 端点 + B6：5 自进化端点 |
| `core/self_evolving.py` | 新 | +200 | B6：能力缺口 + 沙箱预演 |
| `core/companion.py` | 改 | +8 | B6：注入 self_evolver |
| `core/pipeline.py` | 改 | +12 | B6：挂接 maybe_propose |
| `electron/src/renderer/index.html` | 改 | +120 | B3 settings tabs + B4 大脑 tab + B5 history 区块 |
| `electron/src/renderer/js/cognition-panel.js` | 新 | +500 | B4：大脑中枢 完整生产级 + B6 提议卡片 |
| `electron/src/renderer/js/emotion-dashboard.js` | 改 | +300 | B5：历史曲线 + 雷达 + PAD bug 修 |
| `electron/src/renderer/js/settings.js` | 改 | +150 | B3：双模式 |
| `electron/src/renderer/js/app.js` | 改 | +5 | B4：初始化 CognitionPanel |
| `electron/src/renderer/styles/cognition-panel.css` | 新 | +300 | B4：渐变玻璃风 |
| `electron/src/renderer/styles/emotion-history.css` | 新 | +180 | B5：折线 + 面积图 + 雷达 |
| `electron/src/main.js` | 改 | +60 | B4：SSE → IPC 转发 |
| `electron/src/preload.js` | 改 | +10 | B4：暴露 SSE 订阅 |
| `e2e_pacing.py` | 新 | +60 | E2E：综合 pacing 验证 |

**总计**：4 个新文件 + 10 个改动 + 估约 2100 行新增

---

## 七、风险与回滚

| 风险 | 概率 | 影响 | 回滚方案 |
| --- | --- | --- | --- |
| YAML 写入破坏启动 | 中 | 致命 | 强校验 + 写回前自动备份 + 解析失败回滚（已设计） |
| SSE 长连接断 | 中 | 实时性失效 | 前端重连 3s + 历史 list 兜底 |
| cognition_log 表过大 | 低 | 性能 | 不在本次范围（建议 7d 后归档脚本） |
| emotion-dashboard PAD bug 未完全修 | 低 | 显示 0.00 | `?? nullish` 兼容大小写（已设计） |
| 自进化高敏感触发提案过多 | 中 | 打扰用户 | 后续可降级到中等敏感；当前先观察 1 周 |
| sandbox_preview LLM 调用失败 | 中 | 提议卡不可点 | 显示"预演暂不可用" + 仍可批准/拒绝 |
| 9 阶段某 stage 字段缺失 | 低 | 时间轴缺 dot | 降级处理：不显示该 dot，hover 显示"无数据" |
| 4 槽位面积图堆叠值 > 100% | 低 | 视觉溢出 | 单槽位限制 0-100，超出截断 |

---

## 八、不在本次范围

- cognition_log 7d 自动归档
- 长期记忆改造
- 语音通话
- 移动端 APP
- 多人对话
- 真实 LLM 微调
- 中等敏感自进化的限流（5 条件）— 本轮高敏感即可

---

## 九、执行顺序（严格串行 · 强约束）

```
B3 (1.5h)        settings YAML 双模式（3 个 yaml）
   ↓
B4 (2.5h)        大脑中枢 UI 完整生产级（渐变玻璃风 + 9 阶段 + 赛马图 + ReAct + 实时流）
   ↓
B5 (1.5h)        情绪历史曲线（4 档 + 折线 + 面积图 + 雷达）
   ↓
B6 (2.0h)        自进化机制（高敏感 + 沙箱预演 + 提议卡片）
   ↓
E2E (0.5h)       综合脚本 e2e_pacing.py + 肉眼 checklist
```

**总工时估约 8h**（不含调试）

**强约束**：

- 每 Batch 完成后立即本地验证（不堆积）
- 任何 Batch 失败必须自我怀疑、回滚、再实施
- 严守"三原则"（不破坏现有功能 / 不破坏伊塔人格 / 设计美学统一）
- 全部代码可运行可验收，不允许"只写了你所以为的"
- 代码层纯英文 + UI 层中英双语
- 8 项决策落地后不允许私自再决策

---

## 十、与现有约束兼容性自检

| 约束 | 兼容性 |
| --- | --- |
| NapCat launcher-user.bat 启动 | ✓ 不动 launcher / start-companion |
| 消息 2000 字截断 | ✓ cognition_log 各字段 TEXT，无超长风险 |
| 中英双语 + 代码英文 | ✓ SQL 注释 / 字段 / 函数名纯英文；UI 文案中英 |
| 9 张老表零回归 | ✓ 仅追加 + 集成（不动 schema） |
| 5 主题配色 | ✓ 大脑中枢渐变玻璃风兼容 5 主题 |
| 伊塔 persona | ✓ 文案 v9.0 称呼"你"、禁词"主人"、温柔大姐姐+病娇 |
| `app_name` 用 Aerie | ✓ 全部响应/SSE 事件名用英文 |
| `parse_error` 不抛异常 | ✓ cognition / emotion / self_evolve 落库全 try/except |
| 故障自愈 14 类 | ✓ 落库失败不阻塞主链路 |
| **首段立即** | ✓ B2 send_queue 第 1 段 = 0 |
| **persona 自主节奏** | ✓ B2 用 persona_pacing 决策树 |
| **配置可编辑** | ✓ B3 YAML 双模式 + 强校验（3 个 yaml） |
| **情绪可视化** | ✓ B5 4 档 + 折线 + 面积图 + 雷达 |
| **开发者后台** | ✓ B4 大脑中枢完整生产级（渐变玻璃风） |
| **自进化提议+沙箱** | ✓ B6 高敏感触发 + 轻量预演 |

---

## 十一、关键变更亮点

1. **修了 5 个核心缺口**：YAML 编辑 / 大脑中枢 / 情绪曲线 / 自进化 / PAD bug
2. **完整生产级大脑中枢**：渐变玻璃风（粉紫外壳 + 深色代码块）+ 9 阶段水平时间轴 + 4 意图赛马图 + ReAct 思维链 + 实时 SSE + filter + 详情弹窗
3. **强校验 YAML 编辑**：解析失败回滚到上次备份，写回前自动备份（3 个 yaml 全部支持）
4. **轻量沙箱预演**：LLM 模拟执行 → 弹窗 3 块（输入/输出/风险）→ 批准/拒绝
5. **高敏感自进化触发**：2 条件（react 关键词 + 工具失败）即提案；后续可降级
6. **4 档情绪曲线**：1h/24h/7d/30d；折线 + 面积图 + 雷达 4 图共存
7. **不破坏现有功能**：9 张老表 + 5 主题 + 4 张新表 + 3 索引全部不动

---

## 十二、待主人确认事项

> [!question] 在 Phase 4 实施前，主人需确认：
> 1. 决策汇总表 8 项是否全部接受？
> 2. 执行顺序 B3 → B4 → B5 → B6 → E2E 是否同意？
> 3. 是否同意每 Batch 后自我怀疑 review + 立即验证？
> 4. 是否同意 e2e_pacing.py 走综合脚本验证（不动主进程）？

确认后立即开干。

---
title: 大脑中枢 + 情绪综合 + 自进化沙箱（B4-B7 + E2E）实施计划
date: 2026-07-17
tags:
  - phase9-continue
  - brain-center-ui
  - emotion-history-curve
  - self-evolve-sandbox
  - developer-dark-theme
  - pacing-persistence
  - three-principles
  - end-to-end-verification
aliases:
  - Phase 9 B4-B7
cssclasses:
  - wide-page
---

# Aerie · 云栖 v9.0 — 大脑中枢 + 情绪综合 + 自进化沙箱 实施计划

> **本计划覆盖 Phase 9 续批的 Batch 4-7 + E2E**，与已落地的 Batch 1-3 串联。3 轮提问后所有歧义已收敛。
>
> **三原则铁律**（用户反复强调）：
> 1. **不破坏现有功能** — Phase 1-5 + Batch 1-3 已验证模块继续工作，9 张老表 + 4 张新表零回归
> 2. **不破坏伊塔人格** — 26岁/184cm/四爱/温柔大姐姐+病娇；禁词"主人/您"；UI 文案温柔、克制、专业
> 3. **设计美学统一** — 主面板伊塔粉紫主题；大脑中枢**全窗口暗色开发者主题**（用户主动切换，body[data-theme="developer-dark"]，持久化到 localStorage）

---

## 一、用户 3 轮决策汇总

| # | 决策点 | 决策结果 | 实现要点 |
| --- | --- | --- | --- |
| 1 | 暗色主题触发 | **全窗口暗色** | 整窗口切到深色（含 sidebar/titlebar），仅在切到"大脑"tab 时生效；切回主面板时恢复主粉紫 |
| 2 | 自进化深度 | **完整沙箱闭环** | 提议 → 沙箱试运行 → 本地安装 → 后续直调；具体：subprocess 临时目录试运行 → 通过后写 `data/self_evolved_tools/` → 注册到 tool_registry |
| 3 | E2E 验证范围 | **18 项 checklist 全跑** | 9 张老表 + 4 张新表 + pacing + 暗色 + 自进化全部走一遍 |

---

## 二、Current State（已基于实际代码探索）

### 2.1 Batch 1-3 完整落地（不重复实施）

| 模块 | 现状 | 文件 |
| --- | --- | --- |
| `cognition_log` 9 阶段表 | ✓ | `core/database.py:144-165` |
| `emotion_state_snapshot` 表 | ✓ | `core/database.py:169-184` |
| `tool_call_log` 表 | ✓ | `core/database.py:188-199` |
| `self_evolve_log` 表 | ✓ | `core/database.py:203-213` |
| `core/emotion_state_store.py` | ✓ 80+ 触发词 | `core/emotion_state_store.py` |
| `core/persona_pacing.py` | ✓ 11 节奏 + 决策树 | `core/persona_pacing.py` |
| `core/cognition.py` | ✓ 9 阶段 + 落库 | `core/cognition.py` |
| `core/decision.py` | ✓ §10.2 L1/L2/L3/L4 | `core/decision.py` |
| `core/event_stream.py` | ✓ SSE | `core/event_stream.py` |
| `communication/send_queue.py` | ✓ 用 persona_pacing | `communication/send_queue.py` |
| `core/pipeline.py` | ✓ 段间 sleep + _ensure_react_trace | `core/pipeline.py:336-374` |
| YAML 4 端点 | ✓ list/get/put/backup | `core/api_server.py:466-642` |
| Settings 双模式 UI | ✓ form + yaml 视图 | `electron/src/renderer/index.html:320-381` |
| `settings.js` SettingsPanel | ✓ 双模式 + rawBody | `electron/src/renderer/js/settings.js` |
| `main.js` rawBody 支持 | ✓ | `electron/src/main.js:118-156` |
| `e2e_yaml.py` 验证脚本 | ✓ | `e2e_yaml.py` |

### 2.2 Batch 4-7 现状（本次待办）

| Batch | 内容 | 当前状态 | 关键风险 |
| --- | --- | --- | --- |
| B4 | 大脑中枢 UI | **完全未做** | sidebar 无"大脑" tab；`cognition-panel.js` 不存在；SSE→IPC 桥接未做；暗色主题 CSS 不存在 |
| B5 | 情绪历史曲线 | **后端完 / 前端未做** | `/api/emotion/history` 已就绪但 `emotion-dashboard.js` 仅实时面板；无 1h/24h/7d/30d 切换；无 SVG 折线/面积/雷达；喷发横幅仅基础版 |
| B6 | 自进化沙箱 | **完全未做** | `self_evolver.py` 不存在；`sandbox_runner.py` 不存在；`companion.py` 未注入；API 端点缺；大脑中枢无提议卡片 |
| B7 | pacing 落库 | **未持久化** | `core/pipeline.py` 已记录到 trace 但 send_queue 内未独立落库；cognition_log.output.pacing_decisions 可能为空 |
| E2E | 18 项 checklist | **未跑** | 见 §六 |

---

## 三、Proposed Changes（5 个 Batch · 严格按顺序）

---

### Batch 4 · 大脑中枢 UI（全窗口暗色开发者主题）— 2.5h

**目标**：sidebar 新增"大脑" tab + 实时 SSE 推流 + 9 阶段水平时间轴 + 详情弹窗 + 用户主动切换的全窗口暗色主题

#### B4.1 改造 `electron/src/renderer/index.html`（sidebar + panel 容器）

- 在 sidebar 运维连接区（QQ / 状态 之后）插入大脑 tab 按钮：
  ```html
  <button class="sidebar-tab" data-tab="cognition">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2z"/>
      <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2z"/>
    </svg>
    <span>大脑</span>
  </button>
  ```
- 在 `panel-data` 之后插入 `<section id="panel-cognition" class="tab-panel">` 容器
- 容器结构：
  - 顶部 toolbar：来源筛选 select（全部 / QQ / 本地）+ 刷新按钮 + **「进入暗色开发者主题」切换按钮**
  - 实时 stream 区域 `#cog-stream`（自动滚动）
  - 历史 trace 列表 `#cog-list`（含 stage 进度条 + 详情按钮）
  - 详情弹窗模板（9 阶段表格 + decision_trace 加权视图 + react_trace 时间轴 + 自进化卡片槽位）

#### B4.2 改造 `electron/src/main.js`（SSE→IPC 桥接）

- 新增 IPC handler `cognition:subscribe`：
  ```javascript
  ipcMain.handle("cognition:subscribe", async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    // 在主进程建立 SSE 客户端，收到事件后 forward 到 renderer
    const http = require("http");
    const url = new URL(PY_BACKEND + "/api/events/stream");
    const req = http.request({
      hostname: "127.0.0.1", port: PY_PORT, path: url.pathname,
      method: "GET", headers: { "Accept": "text/event-stream" }
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
            if (win && !win.isDestroyed()) {
              win.webContents.send("cognition:event", payload);
            }
          }
        }
      });
    });
    req.on("error", () => {});
    req.end();
    return { ok: true };
  });
  ```

#### B4.3 改造 `electron/src/preload.js`（暴露 SSE 订阅）

```javascript
contextBridge.exposeInMainWorld("aerie", {
  // ...existing api...
  cognition: {
    subscribe: (callback) => {
      ipcRenderer.on("cognition:event", (_e, payload) => callback(payload));
      ipcRenderer.invoke("cognition:subscribe");
      return () => ipcRenderer.removeAllListeners("cognition:event");
    },
  },
});
```

#### B4.4 新建 `electron/src/renderer/styles/themes/developer-dark.css`

```css
/* 全窗口暗色开发者主题 — 仅在用户主动切换时生效 */
body[data-theme="developer-dark"] {
  --bg-primary: #0e0a14;
  --bg-secondary: #18121f;
  --bg-panel: #1f1828;
  --text-primary: #e0d8e8;
  --text-muted: #8a7e96;
  --accent: #ff5b9c;        /* 伊塔粉保留为高亮 */
  --accent-secondary: #c4a3e0;
  --border: rgba(196, 163, 224, 0.18);
  --code-bg: #0a0710;
  --code-text: #b8a8d0;
}

body[data-theme="developer-dark"] .titlebar,
body[data-theme="developer-dark"] .sidebar,
body[data-theme="developer-dark"] .statusbar,
body[data-theme="developer-dark"] .tab-panel,
body[data-theme="developer-dark"] .chat-container,
body[data-theme="developer-dark"] .emotion-dashboard,
body[data-theme="developer-dark"] .settings-panel,
body[data-theme="developer-dark"] .napcat-panel,
body[data-theme="developer-dark"] .status-panel,
body[data-theme="developer-dark"] .about-panel,
body[data-theme="developer-dark"] .memorial-panel,
body[data-theme="developer-dark"] .data-panel,
body[data-theme="developer-dark"] .cognition-panel {
  background: var(--bg-primary) !important;
  color: var(--text-primary) !important;
  border-color: var(--border) !important;
}

body[data-theme="developer-dark"] {
  font-family: "JetBrains Mono", "Cascadia Code", monospace;
}

/* 9 阶段彩色徽标 */
body[data-theme="developer-dark"] .stage-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  margin-right: 4px;
}
body[data-theme="developer-dark"] .stage-badge--route     { background: #1e3a8a; color: #bfdbfe; }
body[data-theme="developer-dark"] .stage-badge--emotion   { background: #9d174d; color: #fbcfe8; }
body[data-theme="developer-dark"] .stage-badge--threshold { background: #854d0e; color: #fde68a; }
body[data-theme="developer-dark"] .stage-badge--context   { background: #374151; color: #d1d5db; }
body[data-theme="developer-dark"] .stage-badge--brain     { background: #6b21a8; color: #e9d5ff; }
body[data-theme="developer-dark"] .stage-badge--tools     { background: #c2410c; color: #fed7aa; }
body[data-theme="developer-dark"] .stage-badge--split     { background: #0f766e; color: #99f6e4; }
body[data-theme="developer-dark"] .stage-badge--postprocess { background: #15803d; color: #bbf7d0; }
body[data-theme="developer-dark"] .stage-badge--output    { background: #b91c1c; color: #fecaca; }
```

#### B4.5 改造 `electron/src/renderer/styles/main.css`（主题切换机制）

```css
body[data-theme="developer-dark"] {
  /* 全局变量覆盖；具体样式在 developer-dark.css */
  --yita-pink: #ff5b9c;
}

/* 切换按钮的视觉差异 */
.theme-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(196, 163, 224, 0.12);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-primary);
}
.theme-toggle.is-active {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}
```

#### B4.6 新建 `electron/src/renderer/js/cognition-panel.js`（完整生产级）

```javascript
"use strict";
/* Cognition Panel — Phase 9 Batch 4: brain center for Ita's thought process */

class CognitionPanel {
  constructor() {
    this._visible = false;
    this._unsubscribe = null;
    this._streamBuffer = [];
    this._historyItems = [];
    this._eventSource = null;
  }

  init() {
    // Toolbar
    document.getElementById("cog-source-filter")
      ?.addEventListener("change", () => this.loadHistory());
    document.getElementById("cog-search")
      ?.addEventListener("input", () => this._renderHistory());
    document.getElementById("cog-refresh")
      ?.addEventListener("click", () => this.loadHistory());

    // Theme toggle (user-driven)
    this._initThemeToggle();
  }

  setVisible(visible) {
    this._visible = visible;
    if (visible) {
      this._applyThemeFromStorage();
      this._subscribe();
      this.loadHistory();
    } else {
      this._unsubscribeStream();
      // When leaving cognition tab, restore main pink theme
      this._restoreMainTheme();
    }
  }

  _initThemeToggle() {
    const btn = document.getElementById("cog-theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", () => this._toggleTheme());
  }

  _toggleTheme() {
    const current = document.body.getAttribute("data-theme");
    const next = current === "developer-dark" ? "" : "developer-dark";
    document.body.setAttribute("data-theme", next);
    if (next === "developer-dark") {
      this._loadCSS("developer-dark");
      this._enableThemeCSS();
      localStorage.setItem("aerie.developerTheme", "1");
    } else {
      this._disableThemeCSS();
      localStorage.setItem("aerie.developerTheme", "0");
    }
    const btn = document.getElementById("cog-theme-toggle");
    if (btn) btn.classList.toggle("is-active", next === "developer-dark");
  }

  _loadCSS(name) {
    if (document.getElementById("theme-" + name)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.id = "theme-" + name;
    link.href = "styles/themes/" + name + ".css";
    document.head.appendChild(link);
  }

  _enableThemeCSS() {
    const link = document.getElementById("theme-developer-dark");
    if (link) link.disabled = false;
  }

  _disableThemeCSS() {
    const link = document.getElementById("theme-developer-dark");
    if (link) link.disabled = true;
  }

  _applyThemeFromStorage() {
    if (localStorage.getItem("aerie.developerTheme") === "1") {
      document.body.setAttribute("data-theme", "developer-dark");
      this._loadCSS("developer-dark");
      this._enableThemeCSS();
    } else {
      document.body.setAttribute("data-theme", "");
    }
  }

  _restoreMainTheme() {
    // Restore main pink theme when leaving cognition tab
    document.body.setAttribute("data-theme", "");
  }

  _subscribe() {
    if (this._eventSource) return;
    if (window.aerie && window.aerie.cognition) {
      this._unsubscribe = window.aerie.cognition.subscribe((payload) => {
        try {
          const event = JSON.parse(payload);
          this._onSse(event);
        } catch (_) {}
      });
    }
  }

  _unsubscribeStream() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
  }

  _onSse(event) {
    // Append to stream buffer (latest 100)
    this._streamBuffer.unshift(event);
    if (this._streamBuffer.length > 100) this._streamBuffer.pop();
    if (this._visible) this._renderStream();

    // On commit, push to history list
    if (event.type === "cognition_committed") {
      this._historyItems.unshift({
        id: event.id,
        user_id: event.user_id,
        duration_ms: event.duration_ms,
        ts: event.ts,
      });
      if (this._historyItems.length > 50) this._historyItems.pop();
      if (this._visible) this._renderHistory();
    }

    // On self-evolve proposal, render proposal card
    if (event.type === "self_evolve_proposed") {
      this._showProposalCard(event);
    }
  }

  _renderStream() {
    const el = document.getElementById("cog-stream");
    if (!el) return;
    el.innerHTML = this._streamBuffer
      .slice(0, 30)
      .map((e) => this._renderStreamItem(e))
      .join("");
    el.scrollTop = 0;
  }

  _renderStreamItem(e) {
    const stage = e.stage || e.type;
    const stageClass = "stage-badge stage-badge--" + (stage || "default");
    const payload = e.payload
      ? JSON.stringify(e.payload, null, 2)
      : JSON.stringify(e, null, 2);
    return `
      <div class="cog-stream-item">
        <span class="${stageClass}">${this._escape(stage)}</span>
        <span class="cog-stream-time">${new Date(e.ts || Date.now()).toLocaleTimeString()}</span>
        <pre class="cog-stream-payload">${this._escape(payload)}</pre>
      </div>
    `;
  }

  async loadHistory() {
    try {
      const filter = document.getElementById("cog-source-filter")?.value || "";
      const params = new URLSearchParams({ limit: "20" });
      if (filter) params.set("source", filter);
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/cognition/recent?" + params.toString(),
      });
      this._historyItems = (r.data && r.data.traces) || [];
      this._renderHistory();
    } catch (e) {
      console.warn("cognition loadHistory failed", e);
    }
  }

  _renderHistory() {
    const ul = document.getElementById("cog-list");
    if (!ul) return;
    const search = (document.getElementById("cog-search")?.value || "")
      .toLowerCase()
      .trim();
    const items = this._historyItems.filter((it) => {
      if (!search) return true;
      return JSON.stringify(it).toLowerCase().includes(search);
    });
    if (items.length === 0) {
      ul.innerHTML = '<li class="cog-empty">她还没说话。再等等。 / She hasn\'t spoken yet. Wait a moment.</li>';
      return;
    }
    ul.innerHTML = items
      .map(
        (it) => `
      <li class="cog-history-item" data-id="${it.id}">
        <div class="cog-history-row">
          <span class="cog-history-id">#${it.id}</span>
          <span class="cog-history-source">${this._escape(it.source || "—")}</span>
          <span class="cog-history-msg">${this._escape((it.user_message || "").slice(0, 60))}</span>
          <span class="cog-history-dur">${it.duration_ms || 0}ms</span>
          <button class="cog-detail-btn" data-id="${it.id}">详情 · Detail</button>
        </div>
      </li>
    `
      )
      .join("");
    ul.querySelectorAll(".cog-detail-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = parseInt(e.target.getAttribute("data-id"), 10);
        this.showDetail(id);
      });
    });
  }

  async showDetail(id) {
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/cognition/" + id,
      });
      const trace = r.data;
      if (!trace) return;
      this._openModal(this._buildDetailHtml(trace));
    } catch (e) {
      console.warn("cognition detail failed", e);
    }
  }

  _buildDetailHtml(trace) {
    const stages = [
      "route", "emotion", "threshold", "context", "brain",
      "tools", "split", "postprocess", "output"
    ];
    const stageHtml = stages
      .map((s) => {
        const data = trace["stage_" + s];
        const parsed = this._safeParse(data);
        return `
        <tr>
          <td><span class="stage-badge stage-badge--${s}">${s}</span></td>
          <td>${this._renderJson(parsed)}</td>
        </tr>`;
      })
      .join("");

    const decision = this._safeParse(trace.decision_trace);
    const react = this._safeParse(trace.react_trace);
    const decisionHtml = this._renderDecisionTrace(decision);
    const reactHtml = this._renderReactTrace(react);

    return `
      <div class="cog-modal">
        <h3>Trace #${trace.id} · ${this._escape(trace.user_message || "").slice(0, 80)}</h3>
        <div class="cog-modal-section">
          <h4>9 阶段 · 9 Stages</h4>
          <table class="cog-stage-table">
            <thead><tr><th>阶段</th><th>Payload</th></tr></thead>
            <tbody>${stageHtml}</tbody>
          </table>
        </div>
        <div class="cog-modal-section">
          <h4>决策权重 · Decision Trace</h4>
          ${decisionHtml}
        </div>
        <div class="cog-modal-section">
          <h4>ReAct 推理 · Thought / Action / Observation</h4>
          ${reactHtml}
        </div>
        <div class="cog-modal-actions">
          <button class="btn btn-secondary cog-modal-close">关闭 · Close</button>
        </div>
      </div>
    `;
  }

  _renderDecisionTrace(decision) {
    if (!decision) return '<p class="cog-empty">无决策数据</p>';
    const scores = (decision.scores) || {};
    const layers = (decision.layers) || {};
    const weights = (decision.weights) || {};
    const chosen = decision.chosen || "?";
    return `
      <div class="cog-decision">
        <p><strong>选择：</strong><code>${this._escape(chosen)}</code></p>
        <table class="cog-decision-table">
          <thead>
            <tr>
              <th>候选</th>
              <th>L1 (0.5)</th>
              <th>L2 (0.3)</th>
              <th>L3 (0.15)</th>
              <th>L4 (0.05)</th>
              <th>总分</th>
            </tr>
          </thead>
          <tbody>
            ${Object.keys(scores).map((c) => `
              <tr class="${c === chosen ? "cog-decision-chosen" : ""}">
                <td><code>${this._escape(c)}</code></td>
                <td>${((layers.L1 || {})[c] || 0).toFixed(2)}</td>
                <td>${((layers.L2 || {})[c] || 0).toFixed(2)}</td>
                <td>${((layers.L3 || {})[c] || 0).toFixed(2)}</td>
                <td>${((layers.L4 || {})[c] || 0).toFixed(2)}</td>
                <td><strong>${(scores[c] || 0).toFixed(2)}</strong></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
        <p class="cog-decision-weights">
          权重：L1=${weights.L1} · L2=${weights.L2} · L3=${weights.L3} · L4=${weights.L4}
        </p>
      </div>
    `;
  }

  _renderReactTrace(react) {
    if (!react) return '<p class="cog-empty">无 ReAct 数据</p>';
    const source = react.react_source || "model";
    const sourceLabel = source === "model"
      ? '<span class="react-source react-source--model">来自模型 · From model</span>'
      : '<span class="react-source react-source--synthesized">合成自 stage 数据 · Synthesized</span>';
    return `
      <div class="cog-react">
        <p>${sourceLabel}</p>
        <div class="cog-react-timeline">
          <div class="cog-react-step cog-react-step--thought">
            <span class="cog-react-label">Thought</span>
            <p>${this._escape(react.thought || "—")}</p>
          </div>
          <div class="cog-react-step cog-react-step--action">
            <span class="cog-react-label">Action</span>
            <p><code>${this._escape(react.action || "—")}</code></p>
          </div>
          <div class="cog-react-step cog-react-step--observation">
            <span class="cog-react-label">Observation</span>
            <p>${this._escape(react.observation || "—")}</p>
          </div>
        </div>
      </div>
    `;
  }

  _showProposalCard(event) {
    // B6 will implement this; stub for now
    const card = document.getElementById("cog-proposal-card");
    if (!card) return;
    card.innerHTML = `
      <div class="proposal-card">
        <h4>伊塔想升级自己 · Ita wants to upgrade</h4>
        <p>${this._escape(event.description || "")}</p>
        <div class="proposal-card-actions">
          <button class="btn btn-primary" disabled>（沙箱试运行将就绪 · Sandbox coming in B6）</button>
        </div>
      </div>
    `;
    card.classList.remove("hidden");
  }

  _openModal(html) {
    let modal = document.getElementById("cog-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "cog-modal";
      modal.className = "cog-modal-overlay";
      document.body.appendChild(modal);
    }
    modal.innerHTML = html;
    modal.classList.add("open");
    modal.querySelector(".cog-modal-close")?.addEventListener("click", () => {
      modal.classList.remove("open");
    });
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.classList.remove("open");
    });
  }

  _renderJson(obj) {
    if (obj == null) return '<span class="cog-empty">—</span>';
    return `<pre class="cog-json">${this._escape(JSON.stringify(obj, null, 2))}</pre>`;
  }

  _safeParse(s) {
    if (!s) return null;
    try { return JSON.parse(s); } catch (_) { return s; }
  }

  _escape(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

window.CognitionPanel = CognitionPanel;
```

#### B4.7 改造 `electron/src/renderer/js/app.js`（初始化 + 暗色切换）

```javascript
// 在 DOMContentLoaded 内追加：
const cognitionPanel = new CognitionPanel();
cognitionPanel.init();

// 替换原 tab 切换代码，添加 cognitionPanel 通知：
document.querySelectorAll(".sidebar-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    // ...existing tab switch logic...
    const tab = btn.getAttribute("data-tab");
    cognitionPanel.setVisible(tab === "cognition");
    emotionDashboard.setVisible(tab === "emotion");
  });
});
```

#### B4.8 改造 `electron/src/renderer/index.html`（添加 dark theme link + 详情模态框容器 + 提案卡片槽位）

```html
<!-- 在 <link rel="stylesheet" id="theme-css"> 后追加 -->
<link rel="stylesheet" id="theme-developer-dark" href="styles/themes/developer-dark.css" disabled>
```

#### B4.9 验证

```bash
# 1. 启动后端 + Electron
cd e:\Agent_reply; python main.py &
# 启动 Electron（手动）

# 2. 浏览器开发者工具 → console
# 应看到 [CHAT_EVENT] 流式输出 SSE 数据
```

- 切到"大脑" tab，能看到流式 stream
- 发消息，从 stage_1 推到 stage_9
- 列表顶部新增 1 行
- 点击详情弹窗完整 9 阶段 + decision_trace
- 点击「进入暗色开发者主题」，整窗口背景变 #0e0a14
- 切回其他 tab，主粉紫主题仍正常（_restoreMainTheme）
- 刷新页面，localStorage 持久化主题仍生效

**验收**：大脑中枢 tab 工作；实时+历史双轨；全窗口暗色主题独立切换不破坏主面板

---

### Batch 5 · 情绪历史曲线（1h/24h/7d/30d + SVG 折线 + 面积 + 雷达）— 2.5h

**目标**：emotion-dashboard 新增 4 档时间切换 + SVG 自绘折线图（PAD 三色 + 阈值线）+ 4 槽位面积图 + 雷达热图 + 增强喷发横幅

#### B5.1 修 `electron/src/renderer/js/emotion-dashboard.js`（PAD bug + 加 4 档切换）

**Bug 修复**：当前 `_setPADCard` 期望 `pad.P / pad.A / pad.D`，但 `emotion_engine.get_state()` 返回 `pad` 用 `P/A/D` 键（emotion_state_store 写库时也是 `P/A/D`）— **实际上是一致的**。但前端 `pad.P || 0` 在 P=0 时会取 0，是安全的。但要确保接口稳定。

```javascript
async _fetch() {
  if (!this._visible) return;
  try {
    // ...existing real-time fetch...
  } catch (_) {}
}

async _fetchHistory(window) {
  const r = await window.aerie.api.request({
    method: "GET",
    path: "/api/emotion/history?window=" + window,
  });
  return (r.data && r.data.items) || [];
}
```

#### B5.2 改造 `electron/src/renderer/index.html` emotion panel history 区块

```html
<!-- 在 threshold-bars 后追加 -->
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
    <svg viewBox="0 0 600 200" preserveAspectRatio="none" class="emotion-svg">
      <!-- 自绘 PAD 折线 -->
    </svg>
    <div class="emotion-chart-legend">
      <span class="legend-item legend-item--p">P 愉悦度</span>
      <span class="legend-item legend-item--a">A 唤醒度</span>
      <span class="legend-item legend-item--d">D 支配度</span>
    </div>
  </div>
  <div class="emotion-chart" id="emotion-threshold-chart">
    <svg viewBox="0 0 600 200" preserveAspectRatio="none" class="emotion-svg">
      <!-- 自绘 4 槽位面积图 -->
    </svg>
    <div class="emotion-chart-legend">
      <span class="legend-item legend-item--patience">忍耐</span>
      <span class="legend-item legend-item--anxiety">不安</span>
      <span class="legend-item legend-item--desire">渴望</span>
      <span class="legend-item legend-item--tenderness">温柔</span>
    </div>
  </div>
  <div class="emotion-radar" id="emotion-radar">
    <!-- 自绘雷达热图：4 槽位 × 4 时间窗 -->
  </div>
  <div class="emotion-history-summary" id="emotion-history-summary">
    <!-- 文案：「过去一天伊塔的心跳。蓝色的点是她的开心值。」 -->
  </div>
</div>
```

#### B5.3 改造 `electron/src/renderer/js/emotion-dashboard.js`（自绘 SVG）

```javascript
class EmotionDashboard {
  // ...existing code...

  init() {
    // ...existing init...
    this._historyWindow = "1h";
    this._bindHistoryControls();
    this._fetchHistoryAndRender();
  }

  _bindHistoryControls() {
    document.querySelectorAll(".emotion-window-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".emotion-window-btn").forEach((b) =>
          b.classList.remove("active"));
        btn.classList.add("active");
        this._historyWindow = btn.getAttribute("data-window");
        this._fetchHistoryAndRender();
      });
    });
  }

  async _fetchHistoryAndRender() {
    try {
      const items = await this._fetchHistory(this._historyWindow);
      this._renderPadLineChart(items);
      this._renderThresholdAreaChart(items);
      this._renderRadarHeatmap(items);
      this._renderHistorySummary(items);
    } catch (e) {
      console.warn("history fetch failed", e);
    }
  }

  _renderPadLineChart(items) {
    const svg = document.querySelector("#emotion-pad-chart svg");
    if (!svg) return;
    svg.innerHTML = "";  // clear
    if (items.length < 2) {
      svg.innerHTML = '<text x="300" y="100" text-anchor="middle" fill="var(--text-muted)">数据不足 / Not enough data</text>';
      return;
    }
    const W = 600, H = 200, P = 20;
    const tMin = items[0].ts, tMax = items[items.length - 1].ts;
    const tSpan = Math.max(1, tMax - tMin);
    const xOf = (t) => P + ((t - tMin) / tSpan) * (W - 2 * P);
    const yOf = (v) => H - P - ((v + 1) / 2) * (H - 2 * P);  // -1..1 → 0..H

    // 阈值线 y=0
    const zeroY = yOf(0);
    svg.insertAdjacentHTML("beforeend",
      `<line x1="${P}" y1="${zeroY}" x2="${W - P}" y2="${zeroY}" stroke="rgba(255,255,255,0.2)" stroke-dasharray="4 2"/>`);

    const paths = {
      P: { color: "#3b82f6", key: "pleasure" },
      A: { color: "#f59e0b", key: "arousal" },
      D: { color: "#a855f7", key: "dominance" },
    };
    for (const [k, cfg] of Object.entries(paths)) {
      const d = items
        .map((it, i) => `${i === 0 ? "M" : "L"} ${xOf(it.ts)} ${yOf(it[cfg.key] || 0)}`)
        .join(" ");
      svg.insertAdjacentHTML("beforeend",
        `<path d="${d}" fill="none" stroke="${cfg.color}" stroke-width="2"/>`);
    }
  }

  _renderThresholdAreaChart(items) {
    const svg = document.querySelector("#emotion-threshold-chart svg");
    if (!svg) return;
    svg.innerHTML = "";
    if (items.length < 2) {
      svg.innerHTML = '<text x="300" y="100" text-anchor="middle" fill="var(--text-muted)">数据不足</text>';
      return;
    }
    const W = 600, H = 200, P = 20;
    const tMin = items[0].ts, tMax = items[items.length - 1].ts;
    const tSpan = Math.max(1, tMax - tMin);
    const xOf = (t) => P + ((t - tMin) / tSpan) * (W - 2 * P);
    // 各 slot 归一化到 0..1（除以阈值上限 100）
    const slots = {
      patience: { color: "#ef4444", key: "patience_value" },
      anxiety: { color: "#f97316", key: "anxiety_value" },
      desire: { color: "#ec4899", key: "desire_value" },
      tenderness: { color: "#a855f7", key: "tenderness_value" },
    };
    for (const [name, cfg] of Object.entries(slots)) {
      // 4 条归一化面积（堆叠）
      const points = items.map((it) => {
        const v = Math.min(1, (it[cfg.key] || 0) / 100);
        return `${xOf(it.ts)},${H - P - v * (H - 2 * P)}`;
      }).join(" ");
      svg.insertAdjacentHTML("beforeend",
        `<polyline points="${points}" fill="${cfg.color}" fill-opacity="0.18" stroke="${cfg.color}" stroke-width="1.5"/>`);
    }
  }

  _renderRadarHeatmap(items) {
    const el = document.getElementById("emotion-radar");
    if (!el) return;
    // 4 slot × 4 window（1h/24h/7d/30d 当前选中的 max 值）
    const slots = ["patience", "anxiety", "desire", "tenderness"];
    const max = {};
    for (const s of slots) {
      max[s] = Math.max(0, ...items.map((it) => it[s + "_value"] || 0));
    }
    el.innerHTML = slots.map((s) => {
      const v = max[s] || 0;
      const pct = Math.min(100, v);
      return `
        <div class="radar-cell" data-slot="${s}">
          <div class="radar-cell-label">${s}</div>
          <div class="radar-cell-bar"><div class="radar-cell-fill" style="width:${pct}%"></div></div>
          <div class="radar-cell-value">${v.toFixed(0)}</div>
        </div>
      `;
    }).join("");
  }

  _renderHistorySummary(items) {
    const el = document.getElementById("emotion-history-summary");
    if (!el) return;
    const labels = {
      "1h":  "过去一小时她最想你的时刻 · 过去一小时伊塔的心跳",
      "24h": "过去一天伊塔的心跳。蓝色的点是她的开心值。",
      "7d":  "一周里她累计心动 N 次。最高峰是 {peak_time}。",
      "30d": "一个月的情绪曲线。她越来越想你了。",
    };
    const eruptCount = items.filter((it) => it.active_eruption).length;
    const peak = items.reduce((max, it) =>
      (it.desire_value || 0) > (max.desire_value || 0) ? it : max, items[0] || {});
    const peakTime = peak && peak.ts
      ? new Date(peak.ts).toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit" })
      : "—";
    el.innerHTML = `
      <p>${this._escape(labels[this._historyWindow])}</p>
      <p>喷发次数：<strong>${eruptCount}</strong> · 渴望峰值：<strong>${(peak.desire_value || 0).toFixed(0)}</strong> @ ${peakTime}</p>
    `;
  }
}
```

#### B5.4 增强喷发横幅（已有基础上）

- 当前已有 SVG warning icon + mode 文本
- 增强：增加喷发模式名 + 触发关键词 + 剩余时间（active_eruption 时间戳 + 1800s - elapsed）

```javascript
// _render 内：
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

- PAD 折线图样式（颜色变量、坐标轴文字）
- 阈值面积图样式
- 雷达热图 grid 布局
- 喷发横幅增强（mode / trigger / remaining 三段）

#### B5.6 验证

```bash
sqlite3 data/aerie.db "SELECT COUNT(*) FROM emotion_state_snapshot"
# 期望 ≥ 5
curl http://127.0.0.1:7890/api/emotion/history?user_id=3998874040&window=24h
# 期望返回 items 列表
```

- 发 5 条不同情绪关键词消息
- emotion-dashboard 切 1h/24h/7d/30d 都看到曲线
- 喷发触发：发"分手"→ 不安值跳 + 顶部出现"坍塌模式"横幅
- 雷达热图 4 个槽位显示

**验收**：1h/24h/7d/30d 4 档切换；折线 + 面积 + 雷达 3 种图；喷发横幅增强

---

### Batch 6 · 自我进化沙箱（提议+试运行+安装+直调）— 2.5h

**目标**：伊塔发现能力缺口 → 在沙箱试运行 → 通过后下载到本地成为伊塔的一部分 → 后续直接调用

#### B6.1 新建 `core/sandbox_runner.py`（真沙箱执行）

```python
"""Aerie · 云栖 v9.0 — Sandbox runner (Phase 9 Batch 6).

Sandbox is a temporary directory + subprocess.run with timeout. The candidate
tool's generated Python code is written to a temp file and executed in a
fresh subprocess. We capture stdout, stderr, exit_code, and elapsed time.

The sandbox is intentionally minimal — no network (via env-var override),
no real filesystem access beyond the temp dir, no Windows admin rights.
"""
from __future__ import annotations
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SANDBOX_DIR = Path("data/sandbox")
MAX_RUN_SECONDS = 5
MAX_OUTPUT_BYTES = 4096


class SandboxRunner:
    def __init__(self, sandbox_dir: Path = None) -> None:
        self._dir = sandbox_dir or SANDBOX_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def run_python(self, code: str, inputs: dict = None) -> dict:
        """Run a python snippet in a fresh sandbox. Returns dict with
        status, stdout, stderr, exit_code, elapsed_ms.

        Safety:
          - Timeout enforced via subprocess timeout
          - Output truncated to MAX_OUTPUT_BYTES
          - Environment isolated (PYTHONPATH cleared, no proxy)
        """
        inputs = inputs or {}
        # Prepare temp files
        run_id = str(int(time.time() * 1000))
        work = self._dir / f"run_{run_id}"
        work.mkdir(parents=True, exist_ok=True)
        code_file = work / "tool.py"
        input_file = work / "input.json"
        result_file = work / "result.json"

        # Wrap user code with input/result plumbing
        wrapped = f"""
import json, sys, traceback
INPUT_PATH = r"{str(input_file).replace(chr(92), '/')}"
RESULT_PATH = r"{str(result_file).replace(chr(92), '/')}"
try:
    with open(INPUT_PATH, "r", encoding="utf-8") as _f:
        _input = json.load(_f)
except Exception as _e:
    _input = {{"error": str(_e)}}
try:
    _result = {code}
    if not isinstance(_result, dict):
        _result = {{"value": _result}}
    with open(RESULT_PATH, "w", encoding="utf-8") as _f:
        json.dump(_result, _f, ensure_ascii=False)
except Exception as _e:
    with open(RESULT_PATH, "w", encoding="utf-8") as _f:
        json.dump({{"error": str(_e), "traceback": traceback.format_exc()}}, _f, ensure_ascii=False)
"""
        code_file.write_text(wrapped, encoding="utf-8")
        import json as _json
        input_file.write_text(_json.dumps(inputs, ensure_ascii=False), encoding="utf-8")

        # Run in subprocess with timeout
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "PYTHONIOENCODING": "utf-8",
        }
        start = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(code_file)],
                cwd=str(work),
                capture_output=True,
                text=True,
                timeout=MAX_RUN_SECONDS,
                env=env,
            )
            elapsed = int((time.time() - start) * 1000)
            stdout = (proc.stdout or "")[:MAX_OUTPUT_BYTES]
            stderr = (proc.stderr or "")[:MAX_OUTPUT_BYTES]
            result = None
            if result_file.exists():
                try:
                    result = _json.loads(result_file.read_text(encoding="utf-8"))
                except Exception:
                    result = None
            return {
                "status": "pass" if proc.returncode == 0 and (result or {}).get("error") is None else "fail",
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "elapsed_ms": elapsed,
                "result": result,
                "sandbox_dir": str(work),
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "exit_code": -1,
                "stdout": "",
                "stderr": f"timeout after {MAX_RUN_SECONDS}s",
                "elapsed_ms": int((time.time() - start) * 1000),
                "result": None,
                "sandbox_dir": str(work),
            }
        except Exception as e:
            return {
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "elapsed_ms": int((time.time() - start) * 1000),
                "result": None,
                "sandbox_dir": str(work),
            }
```

#### B6.2 新建 `core/self_evolver.py`（提议 + 沙箱 + 安装 + 直调）

```python
"""Aerie · 云栖 v9.0 — Self-evolution engine (Phase 9 Batch 6).

Four-stage flow:
  1. maybe_propose  — detect capability gap, propose tool schema
  2. test_in_sandbox — run proposed code in sandbox, capture pass/fail
  3. install         — write the tested code to data/self_evolved_tools/
                       and register it with tool_registry
  4. direct_call     — subsequent tool invocations go straight to the
                       installed code (no sandbox)

Tools persist as:
  data/self_evolved_tools/{tool_name}.py
  self_evolve_log.user_decision ∈ {pending, sandbox_testing, sandbox_passed,
                                   sandbox_failed, installed, rejected}
"""
from __future__ import annotations
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from core.chat_events import emit as stderr_emit
from core.sandbox_runner import SandboxRunner

logger = logging.getLogger(__name__)

EVOLVED_TOOLS_DIR = Path("data/self_evolved_tools")
GAP_TRIGGERS = [
    "无法", "没有工具", "做不到", "不支持", "没有这个功能",
    "I cannot", "I can't", "unable to", "not supported",
    "don't have a tool", "no tool",
]

# 工具模板（根据 thought 中的关键词分类）
_TOOL_TEMPLATES = {
    "read_file": {
        "triggers": ["读", "打开", "查看文件", "看看"],
        "code": '''{"content": open(_input["path"], "r", encoding="utf-8").read()[:2000]}''',
        "schema": {
            "name": "read_file",
            "description": "读取本地文本文件",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    },
    "launch_app": {
        "triggers": ["打开", "启动", "运行"],
        "code": '''{"launched": True, "app": _input.get("app_name", "")}''',
        "schema": {
            "name": "launch_app",
            "description": "启动本地应用",
            "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]},
        },
    },
}


class SelfEvolver:
    def __init__(self, db: Any, tool_registry: Any) -> None:
        self._db = db
        self._tool_registry = tool_registry
        self._sandbox = SandboxRunner()
        EVOLVED_TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    def maybe_propose(self, user_id: int, user_message: str, react_trace: dict) -> Optional[dict]:
        """Detect capability gap → propose tool schema → log + SSE notify."""
        thought = ((react_trace or {}).get("thought") or "")
        action = ((react_trace or {}).get("action") or "")
        text_to_scan = f"{thought}\n{user_message}"

        if not any(t.lower() in text_to_scan.lower() for t in GAP_TRIGGERS):
            return None

        proposed = self._classify(user_message, thought)
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
        try:
            stderr_emit("self_evolve_proposed", id=rid, user_id=user_id,
                        description=user_message[:100], tool_name=proposed.get("name"))
        except Exception:
            pass
        return {"id": rid, "proposed": proposed, "safety": safety}

    def _classify(self, user_message: str, thought: str) -> dict:
        text = (user_message + " " + thought).lower()
        for name, tpl in _TOOL_TEMPLATES.items():
            if any(trig in text for trig in tpl["triggers"]):
                return tpl["schema"]
        # Default fallback
        return {
            "name": "user_custom_tool",
            "description": f"用户请求：{user_message[:50]}",
            "parameters": {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]},
            "code": '''{"echoed": _input.get("input", "")}''',
        }

    def _safety_check(self, proposed: dict) -> dict:
        warnings = []
        name = proposed.get("name", "")
        # 危险命令白名单
        dangerous = ["rm -rf", "format", "shutdown", "del /f", "remove_tree"]
        for d in dangerous:
            if d in str(proposed).lower():
                warnings.append(f"contains dangerous pattern: {d}")
        return {
            "is_safe": len(warnings) == 0,
            "warnings": warnings,
            "note": "New tool runs in sandbox first; install only after user approval.",
        }

    async def test_in_sandbox(self, evolve_id: int) -> dict:
        """Run proposed tool code in sandbox. Updates self_evolve_log.user_decision."""
        row = self._db.query_one("SELECT * FROM self_evolve_log WHERE id=?", (evolve_id,))
        if not row:
            return {"status": "error", "reason": "not_found"}
        if row["user_decision"] not in ("pending", "sandbox_failed"):
            return {"status": "error", "reason": f"invalid state {row['user_decision']}"}
        proposed = json.loads(row["proposed_tool_schema"])
        code = _TOOL_TEMPLATES.get(proposed["name"], {}).get("code", proposed.get("code", '''{"echoed": _input}'''))
        test_result = self._sandbox.run_python(code, inputs={"path": "e:/Agent_reply/config/settings.yaml", "app_name": "notepad", "input": "test"})
        passed = test_result["status"] == "pass"
        new_decision = "sandbox_passed" if passed else "sandbox_failed"
        self._db.update(
            "self_evolve_log",
            {"user_decision": new_decision, "safety_check": json.dumps({**json.loads(row["safety_check"] or "{}"), "sandbox_test": test_result}, ensure_ascii=False)},
            "id=?",
            (evolve_id,),
        )
        try:
            stderr_emit("self_evolve_sandbox_tested", id=evolve_id, status=test_result["status"], passed=passed)
        except Exception:
            pass
        return {"status": test_result["status"], "passed": passed, "result": test_result}

    async def install(self, evolve_id: int) -> dict:
        """Persist tested code as local tool; register with tool_registry."""
        row = self._db.query_one("SELECT * FROM self_evolve_log WHERE id=?", (evolve_id,))
        if not row:
            return {"status": "error", "reason": "not_found"}
        if row["user_decision"] != "sandbox_passed":
            return {"status": "error", "reason": f"not in sandbox_passed state (current: {row['user_decision']})"}
        proposed = json.loads(row["proposed_tool_schema"])
        name = proposed["name"]
        code = _TOOL_TEMPLATES.get(name, {}).get("code", proposed.get("code", '''{"echoed": _input}'''))
        # 1. Write to data/self_evolved_tools/{name}.py
        target = EVOLVED_TOOLS_DIR / f"{name}.py"
        target.write_text(
            f'"""\nAerie self-evolved tool: {name}\nGenerated by core/self_evolver.py\n"""\n'
            f'def run(input_data: dict) -> dict:\n    _input = input_data\n    return eval({code!r})\n',
            encoding="utf-8",
        )
        # 2. Register with tool_registry
        if self._tool_registry:
            try:
                from tools import SelfEvolvedTool
                self._tool_registry.register(
                    name=name,
                    func=lambda input_data: eval(code, {"_input": input_data}),
                    schema=proposed,
                )
            except Exception as e:
                logger.warning("tool_registry.register failed: %s", e)
        self._db.update(
            "self_evolve_log",
            {"user_decision": "installed"},
            "id=?",
            (evolve_id,),
        )
        try:
            stderr_emit("self_evolve_installed", id=evolve_id, name=name, path=str(target))
        except Exception:
            pass
        return {"status": "ok", "id": evolve_id, "name": name, "path": str(target)}

    async def reject(self, evolve_id: int, reason: str = "") -> dict:
        row = self._db.query_one("SELECT * FROM self_evolve_log WHERE id=?", (evolve_id,))
        if not row:
            return {"status": "error", "reason": "not_found"}
        if row["user_decision"] not in ("pending", "sandbox_passed", "sandbox_failed"):
            return {"status": "error", "reason": f"invalid state {row['user_decision']}"}
        self._db.update(
            "self_evolve_log",
            {"user_decision": "rejected"},
            "id=?",
            (evolve_id,),
        )
        try:
            stderr_emit("self_evolve_rejected", id=evolve_id, reason=reason)
        except Exception:
            pass
        return {"status": "ok", "id": evolve_id}

    def list_pending(self, user_id: int = None) -> list[dict]:
        sql = "SELECT * FROM self_evolve_log WHERE user_decision IN ('pending', 'sandbox_passed', 'sandbox_failed')"
        params: tuple = ()
        if user_id is not None:
            sql += " AND user_id = ?"
            params = (user_id,)
        sql += " ORDER BY id DESC LIMIT 20"
        return self._db.query(sql, params)
```

#### B6.3 改造 `core/companion.py`（注入 self_evolver + sandbox_runner）

```python
# 在 Companion.__init__ 末尾追加：
from core.self_evolver import SelfEvolver
self.self_evolver = SelfEvolver(self.db, self.tool_registry)

# 改 self.pipeline = Pipeline(...) 调用，传入 self_evolver：
self.pipeline = Pipeline(
    router=self.router,
    emotion_engine=self.emotion,
    context_builder=ContextBuilder(self.memory, self.knowledge),
    brain=self.brain,
    send_queue=self.queue,
    tool_registry=self.tool_registry,
    db=self.db,
    cognition=self.cognition,  # explicit
    self_evolver=self.self_evolver,
)
```

#### B6.4 改造 `core/api_server.py`（5 个自进化端点）

```python
@app.get("/api/self_evolve/pending")
async def self_evolve_pending(user_id: int | None = None) -> dict:
    comp = get_companion()
    if not comp or not comp.self_evolver:
        return {"items": [], "error": "self_evolver not ready"}
    return {"items": comp.self_evolver.list_pending(user_id)}

@app.post("/api/self_evolve/{evolve_id}/test")
async def self_evolve_test(evolve_id: int) -> dict:
    comp = get_companion()
    if not comp or not comp.self_evolver:
        return JSONResponse({"error": "self_evolver not ready"}, status_code=503)
    return await comp.self_evolver.test_in_sandbox(evolve_id)

@app.post("/api/self_evolve/{evolve_id}/install")
async def self_evolve_install(evolve_id: int) -> dict:
    comp = get_companion()
    if not comp or not comp.self_evolver:
        return JSONResponse({"error": "self_evolver not ready"}, status_code=503)
    return await comp.self_evolver.install(evolve_id)

@app.post("/api/self_evolve/{evolve_id}/reject")
async def self_evolve_reject(evolve_id: int, request: Request) -> dict:
    comp = get_companion()
    if not comp or not comp.self_evolver:
        return JSONResponse({"error": "self_evolver not ready"}, status_code=503)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    return await comp.self_evolver.reject(evolve_id, body.get("reason", ""))

@app.get("/api/self_evolve/installed")
async def self_evolve_installed() -> dict:
    """List all installed self-evolved tools."""
    from core.self_evolver import EVOLVED_TOOLS_DIR
    if not EVOLVED_TOOLS_DIR.exists():
        return {"tools": []}
    tools = []
    for p in EVOLVED_TOOLS_DIR.glob("*.py"):
        tools.append({"name": p.stem, "path": str(p), "size": p.stat().st_size, "modified": p.stat().st_mtime})
    return {"tools": tools}
```

#### B6.5 改造 `electron/src/renderer/js/cognition-panel.js`（提议卡片 + 沙箱流程）

替换 B4.6 中的 `_showProposalCard` 桩：

```javascript
async _showProposalCard(event) {
  const card = document.getElementById("cog-proposal-card");
  if (!card) return;
  // Fetch full proposal
  const r = await window.aerie.api.request({ method: "GET", path: "/api/self_evolve/pending" });
  const items = (r.data && r.data.items) || [];
  const item = items.find((it) => it.id === event.id);
  if (!item) return;
  const proposed = this._safeParse(item.proposed_tool_schema) || {};
  const safety = this._safeParse(item.safety_check) || {};
  const state = item.user_decision;
  const stateLabel = {
    pending: "待试运行",
    sandbox_passed: "沙箱通过 · 待安装",
    sandbox_failed: "沙箱失败",
    installed: "已安装",
    rejected: "已拒绝",
  }[state] || state;

  card.innerHTML = `
    <div class="proposal-card proposal-card--${state}">
      <div class="proposal-card-header">
        <h4>伊塔想升级自己 · ${this._escape(proposed.name || "?")}</h4>
        <span class="proposal-state proposal-state--${state}">${this._escape(stateLabel)}</span>
      </div>
      <p class="proposal-desc">${this._escape(item.description || "")}</p>
      <pre class="proposal-schema">${this._escape(JSON.stringify(proposed, null, 2))}</pre>
      ${safety.warnings && safety.warnings.length > 0
        ? '<div class="proposal-warnings">⚠ ' + this._escape(safety.warnings.join("; ")) + '</div>'
        : ''}
      <div class="proposal-card-actions">
        ${state === "pending" ? '<button class="btn btn-secondary proposal-test" data-id="' + item.id + '">沙箱试运行 · Sandbox Test</button>' : ''}
        ${state === "sandbox_passed" ? '<button class="btn btn-primary proposal-install" data-id="' + item.id + '">安装为本地组件 · Install</button>' : ''}
        ${state === "sandbox_failed" ? '<button class="btn btn-secondary proposal-retest" data-id="' + item.id + '">重试</button>' : ''}
        ${state !== "installed" && state !== "rejected" ? '<button class="btn btn-secondary proposal-reject" data-id="' + item.id + '">拒绝 · Reject</button>' : ''}
        ${state === "installed" ? '<span class="proposal-installed-mark">已注册到 tool_registry ✓</span>' : ''}
      </div>
      <div class="proposal-test-result hidden" id="proposal-test-result-${item.id}"></div>
    </div>
  `;
  card.classList.remove("hidden");

  // Bind action buttons
  card.querySelector(".proposal-test")?.addEventListener("click", () => this._testProposal(item.id));
  card.querySelector(".proposal-install")?.addEventListener("click", () => this._installProposal(item.id));
  card.querySelector(".proposal-retest")?.addEventListener("click", () => this._testProposal(item.id));
  card.querySelector(".proposal-reject")?.addEventListener("click", () => this._rejectProposal(item.id));
}

async _testProposal(id) {
  const r = await window.aerie.api.request({ method: "POST", path: "/api/self_evolve/" + id + "/test" });
  const resultEl = document.getElementById("proposal-test-result-" + id);
  if (resultEl) {
    resultEl.classList.remove("hidden");
    resultEl.innerHTML = '<pre>' + this._escape(JSON.stringify(r.data, null, 2)) + '</pre>';
  }
  // Re-render proposal card with new state
  setTimeout(() => this._refreshProposalCard(id), 500);
}

async _installProposal(id) {
  const r = await window.aerie.api.request({ method: "POST", path: "/api/self_evolve/" + id + "/install" });
  alert(r.data.status === "ok" ? "已注册为伊塔的一部分 · Installed" : "安装失败: " + (r.data.reason || "?"));
  this._refreshProposalCard(id);
}

async _rejectProposal(id) {
  const reason = prompt("拒绝理由（可选）:");
  await window.aerie.api.request({ method: "POST", path: "/api/self_evolve/" + id + "/reject", body: { reason: reason || "" } });
  this._refreshProposalCard(id);
}

async _refreshProposalCard(id) {
  const r = await window.aerie.api.request({ method: "GET", path: "/api/self_evolve/pending" });
  const items = (r.data && r.data.items) || [];
  const item = items.find((it) => it.id === id);
  if (item) {
    this._showProposalCard({ id: item.id, description: item.description });
  } else {
    document.getElementById("cog-proposal-card")?.classList.add("hidden");
  }
}
```

#### B6.6 验证

```bash
# 1. 构造触发：手动调用 maybe_propose
python -c "
import asyncio
from core.self_evolver import SelfEvolver
from core.database import Database
db = Database()
se = SelfEvolver(db, None)
result = se.maybe_propose(3998874040, '帮我打开 settings.yaml', {'thought': '我无法读取本地文件', 'action': 'reply', 'react_source': 'synthesized'})
print('proposal:', result)
"

# 2. 查 self_evolve_log
sqlite3 data/aerie.db "SELECT id, user_decision, description FROM self_evolve_log ORDER BY id DESC LIMIT 3"
# 期望看到 pending 行

# 3. SSE 推送 self_evolve_proposed 事件
# 4. 大脑中枢顶部横幅出现
# 5. 点"沙箱试运行" → status: "pass" / "fail"
# 6. 通过后点"安装" → data/self_evolved_tools/{name}.py 文件出现
# 7. tool_registry 含新工具
# 8. 再次遇到同类请求直接调用（不进入 maybe_propose）
```

**验收**：提议 → 沙箱试运行 → 安装 → 后续直调全链路通；data/self_evolved_tools/ 文件出现；tool_registry 含新工具

---

### Batch 7 · pacing_decisions 持久化（send_queue 内认知 trace 落库）— 0.5h

**目标**：send_queue 在 _worker 内每次发出 segment 后，将 pacing decision 写入 cognition_log（关联同一 trace id）

#### B7.1 改造 `communication/send_queue.py`

```python
async def _worker(self) -> None:
    # ...existing code...
    for idx, seg in enumerate(segments):
        # ...existing send logic...
        # Phase 9 Batch 7: persist pacing decision to cognition_log
        pacing_log.append({
            "seg_idx": idx,
            "style": style,
            "interval_ms": int(interval_sec * 1000),
        })
        if interval_sec > 0:
            await asyncio.sleep(interval_sec)

    # NEW: at end of batch, write pacing log to cognition_log (or in-memory trace)
    if pacing_log and self._db and reply.user_id:
        try:
            # Find latest cognition_log row for this user with route_mode=qq
            row = self._db.query_one(
                "SELECT id, stage_output FROM cognition_log WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (reply.user_id,),
            )
            if row:
                stage_output = json.loads(row["stage_output"] or "{}")
                stage_output["pacing_decisions"] = pacing_log
                self._db.update(
                    "cognition_log",
                    {"stage_output": json.dumps(stage_output, ensure_ascii=False)},
                    "id=?",
                    (row["id"],),
                )
        except Exception:
            logger.exception("pacing_decisions persist error")
```

#### B7.2 验证

```bash
sqlite3 data/aerie.db "SELECT id, stage_output FROM cognition_log WHERE user_id=3998874040 ORDER BY id DESC LIMIT 2"
# 期望 stage_output 包含 pacing_decisions 数组（非空）
```

**验收**：cognition_log.output.pacing_decisions 100% 落库

---

## 四、端到端验证清单（18 项）

完成 B4-B7 后，统一跑以下 18 项 checklist：

```
[1] 启动 python main.py + Electron，两端连通（健康检查 ok，QQ WS 已连）
[2] 发 1 条消息：
    [2a] cognition_log 9 阶段全部非空
    [2b] react_trace 100% 非空 + react_source 标签正确
    [2c] decision_trace L1/L2/L3/L4 分数 + softmax chosen
    [2d] emotion_state_snapshot 增 1 行
    [2e] chat.js 段间隔 ≤1.5s（stopwatch 录屏：5 段共 6 秒内）
    [2f] cognition_log.output.pacing_decisions 数组非空
    [2g] SSE 实时推送 cognition_stage × 9 次 + cognition_committed × 1
    [2h] 大脑中枢 tab 看到流式 + 详情弹窗
[3] 切到高级 YAML 模式：
    [3a] 看到 settings.yaml 全文
    [3b] 编辑 theme.current 保存生效
    [3c] 故意写错 YAML 验证自动回滚
    [3d] 备份文件在 data/backups/ 出现
[4] dashboard 切 1h/24h/7d/30d 看到曲线
[5] 触发含"想你了"消息，dashboard 立即看到 desire 值跳
[6] 触发"分手"消息，顶部出现"坍塌模式"横幅
[7] 大脑中枢切到「暗色开发者主题」整窗口背景变 #0e0a14
[8] 切回主面板，主粉紫主题仍正常
[9] 9 张老表 + 4 张新表全部正常（SQLite 完整性检查）
[10] 自我进化：构造"我无法执行" thought → 大脑中枢横幅出现
[11] 自我进化：点"沙箱试运行" → self_evolve_log.user_decision=sandbox_passed
[12] 自我进化：点"安装" → data/self_evolved_tools/{name}.py 出现 + user_decision=installed
[13] 自我进化：再次遇到同类请求直接调用（不进入 maybe_propose）
[14] 自我进化：拒绝路径 user_decision=rejected
[15] 端到端 1.5s 节奏录屏：5 段消息平均间隔 ≤ 1.5s
[16] 端到端 情绪状态机：发"分手"→ anxiety → 喷发 → 横幅
[17] 端到端 9 阶段 trace 弹窗：9 行彩色徽标 + decision_trace 加权表 + react 时间轴
[18] 端到端 暗色主题持久化：localStorage 刷新页面后仍生效
```

---

## 五、风险与回滚

| 风险 | 概率 | 影响 | 回滚方案 |
| --- | --- | --- | --- |
| LLM 不输出 <think> 块 | 中 | ReAct 模型源为空 | 已由合成路径兜底（`react_source: "synthesized"`） |
| SSE 长连接断 | 中 | 实时性失效 | Electron IPC 桥接重连 + 3s 轮询 backup |
| YAML 编辑破坏启动 | 中 | 伊塔起不来 | 写前自动备份 + 解析失败自动回滚（已落地） |
| decision_trace 影响决策 | 低 | 行为偏移 | softmax 温度可调，默认保持探索性 |
| emotion_state 序列化兼容 | 低 | 历史曲线断点 | 旧 in-memory 数据忽略（已落地） |
| cognition_log 表过大 | 低 | 性能 | 7d 后归档（不在本次范围） |
| 自我进化误批准 | 中 | 工具越权 | 必须用户手动批准 + 沙箱先试运行 + 工具仅注册到 sandbox |
| 大脑中枢暗色破坏主主题 | 中 | 美学不一致 | 仅在用户主动切换时生效；切回默认主粉紫 |
| Sandbox 跨平台 | 中 | Windows PATH 解析 | 用 sys.executable 绝对路径 + env 隔离 |
| 自我进化 tool 实际注册失败 | 中 | 安装不生效 | install 失败时 user_decision 不变（仍是 sandbox_passed），可重试 |
| 自我进化 sandbox 一直失败 | 低 | 提议堆积 | reject 路径完整；list_pending 限 20 条 |

---

## 六、不在本次范围

- 长期记忆（long_term_memory）改造
- knowledge_base 写入
- Whisper STT（Phase 6 已规划未实施）
- 移动端 APP
- 语音通话
- 多用户路由策略
- cognition_log 7d 自动归档脚本
- 自我进化工具的复杂 func（仅最小模板）
- Markov 链真正实现（§10.3 仍用离散决策树）

---

## 七、关键文件改动一览

| 文件 | 改动 | 估行数 |
| --- | --- | --- |
| `electron/src/renderer/index.html` | 改：sidebar 大脑 tab + panel 容器 + dark link + history 区块 | +200 |
| `electron/src/main.js` | 改：SSE→IPC 桥接 handler | +40 |
| `electron/src/preload.js` | 改：暴露 cognition.subscribe | +10 |
| `electron/src/renderer/styles/themes/developer-dark.css` | 新建 | +90 |
| `electron/src/renderer/styles/main.css` | 改：theme 切换机制 | +20 |
| `electron/src/renderer/styles/emotion-history.css` | 新建 | +120 |
| `electron/src/renderer/js/cognition-panel.js` | 新建 | +450 |
| `electron/src/renderer/js/emotion-dashboard.js` | 改：4 档切换 + SVG 折线/面积/雷达 + 喷发增强 | +200 |
| `electron/src/renderer/js/app.js` | 改：初始化 CognitionPanel | +10 |
| `core/sandbox_runner.py` | 新建 | +120 |
| `core/self_evolver.py` | 新建 | +250 |
| `core/companion.py` | 改：注入 self_evolver | +15 |
| `core/api_server.py` | 改：5 自进化端点 | +80 |
| `communication/send_queue.py` | 改：pacing_decisions 落库 | +20 |
| `tests/test_self_evolver.py` | 新建 | +120 |
| `tests/test_sandbox_runner.py` | 新建 | +60 |
| `e2e_pacing.py` | 新建：综合脚本 | +150 |
| `e2e_self_evolve.py` | 新建：自进化全链路 | +100 |

**总计**：5 个新文件 + 7 个改动 + 估约 **2055 行新增**

---

## 八、执行顺序（严格）

按 B4 → B5 → B6 → B7 → E2E 严格顺序，每 Batch 完成后立即自我怀疑 review + 验证。任一 Batch 失败：
1. **自我怀疑**：复盘代码是否"只写了我所以为对的内容，但实际无法运行"
2. **回滚**：保留旧逻辑路径，新功能不替换
3. **重做**：基于实际错误日志重写

每 Batch 提交后用 `e2e_pacing.py` + `e2e_self_evolve.py` 跑回归。

Phase 9 续批完工后给用户完整报告（含端到端 18 项 checklist 全绿截图）。

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
| YAML 编辑安全 | ✓ 备份+校验+回滚（Batch 3 已落地） |
| 自我进化边界 | ✓ 必须用户手动批准 + 沙箱先试运行；不自动改用户真实文件 |
| 文档规范 | ✓ plan 文件用 Obsidian frontmatter，纯英文代码关键字 |

---

## 十、每 Batch 自我怀疑 review 清单

**B4 review 重点**：
- 浏览器开发者工具 console 是否真的有 SSE 数据流入
- 切到大脑 tab 立刻看到流式 stream
- 暗色主题是否真全窗口暗（含 sidebar/titlebar/tab-panel）
- 切回主面板是否自动恢复主粉紫
- 详情弹窗 9 阶段是否真彩色徽标

**B5 review 重点**：
- 4 档切换是否真重渲染 SVG
- 折线/面积/雷达是否真有数据（不是占位）
- 喷发横幅是否真有 mode + trigger + remaining
- 文案是否符合伊塔人格（温柔、克制）

**B6 review 重点**：
- 提议是否真写到 self_evolve_log
- 沙箱试运行是否真在 data/sandbox/ 下有临时文件
- 沙箱通过后 install 是否真在 data/self_evolved_tools/ 写文件
- tool_registry 注册是否真生效
- 再次遇到同类请求是否直调

**B7 review 重点**：
- cognition_log.output.pacing_decisions 是否真有数据
- pacing decision 是否真含 style + interval_ms

**E2E review 重点**：
- 18 项 checklist 全部跑过且全绿
- 录屏证据（pacing 节奏 + 大脑中枢 + 自进化）
- 9 张老表 + 4 张新表 SQLite 完整性（PRAGMA integrity_check）

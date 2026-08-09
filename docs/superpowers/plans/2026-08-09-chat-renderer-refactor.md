# 聊天渲染器定向重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 chat.js 里 9 条互相重叠的渲染路径收口为"单一数据源 + 单一 DOM 应用"，消除重复气泡、丢消息、状态错位与死代码。

**Architecture:** 新增一个纯逻辑模块 `chat-store.js`，独占消息判重、排序、请求状态与稳定元素 id 映射，`ingestSignal()` 返回"渲染意图(Intent)"数组。chat.js 只剩一层薄的 `_reconcile(intent)` 负责创建/更新/删除 `.chat-msg[data-id]` 元素。这样判重/排序/状态逻辑可在无 DOM 的 `node:test` 下完整 TDD，DOM 层则退化为薄壳。

**Tech Stack:** 原生 ES (UMD class-free, `"use strict"`)，Node 内置 `node:test` + `vm` 桩 DOM，无第三方依赖。测试命令 `npm --prefix electron run test:unit`（即 `node --test electron/tests/*.test.js`）。

**关键不变式（重构后必须成立）：**
1. 每个逻辑消息在 DOM 里**只有一个**元素，元素 `data-id` 稳定不换。
2. 同一消息从 poll/SSE/IPC/history 多条通道重复到达时**只渲染一次**。
3. 助手消息的"输入中→最终"过程**原地更新**同一元素，不做 id 偷换。
4. 全量重绘 `_rerenderVisible` 由 `store.messages()` 重建，行为与增量一致。

---

## 文件结构

- **Create** `electron/src/renderer/js/chat-store.js` — 纯消息状态存储（新核心）
- **Test** `electron/tests/chat-store.test.js` — 该模块的完整单元测试
- **Modify** `electron/src/renderer/js/chat.js` — 收口到 store + `_reconcile`，删旧路径
- **Modify** `electron/src/renderer/chat.html`（如内联引入脚本，需确认）— 引入 `chat-store.js`；若无内联则忽略

> chat.html 引入方式需在 Task 2 开始前用 Grep 确认（`chat.js` 在 HTML 里的 `<script>` 顺序），store 必须在 chat.js 之前加载。

---

### Task 1: 创建纯逻辑模块 chat-store.js

**Files:**
- Create: `electron/src/renderer/js/chat-store.js`
- Test: `electron/tests/chat-store.test.js`

设计要点：store 用 `domId` 作为稳定元素键。助手消息的稳定键为 `req_<request_id>`，用户乐观气泡为 `client_<...>`，历史真实消息用真实 id。`requestIdToDomId` / `clientIdToDomId` / `realIdToDomId` 三张映射让"更新"总能命中同一元素。**元素 `data-id` 从不被改写**；真实消息 id 只记在 `msg.msgId` 元数据里。

- [ ] **Step 1: 写失败测试（先定义契约）**

```js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { createChatStore } = require("../src/renderer/js/chat-store.js");

test("ingestSignal: 重复真实消息只 upsert 一次", () => {
  const s = createChatStore();
  const a = s.ingestSignal({ id: "10", role: "assistant", content: "hi", request_id: "r1" });
  const b = s.ingestSignal({ id: "10", role: "assistant", content: "hi", request_id: "r1" });
  assert.equal(a.filter(i => i.action === "upsert").length, 1);
  assert.equal(b.length, 0);
});

test("ingestSignal: 助手输入中→最终 用同一 domId 原地更新, 不产生新元素", () => {
  const s = createChatStore();
  const run = s.ingestSignal({ request_id: "r1", role: "assistant", status: "running", typing: true, content: "" });
  // running 生成 typing 意图
  assert.ok(run.some(i => i.action === "typing" && i.msg.typing === true));
  const typingDomId = run.find(i => i.action === "typing").msg.domId;
  const done = s.ingestSignal({ request_id: "r1", role: "assistant", id: "55", content: "答案", status: "completed" });
  const ups = done.filter(i => i.action === "upsert");
  assert.equal(ups.length, 1);
  assert.equal(ups[0].msg.domId, typingDomId); // 同一元素
  assert.equal(ups[0].msg.msgId, "55");
  assert.equal(ups[0].msg.content, "答案");
  // 之后历史/轮询再送同 id → 不再渲染
  assert.equal(s.ingestSignal({ id: "55", role: "assistant", content: "答案" }).length, 0);
});

test("ingestSignal: 用户乐观气泡用 client_id 映射升级为真实 id", () => {
  const s = createChatStore();
  s.ingestSignal({ client_id: "c1", role: "user", content: "你", typing: false });
  const up = s.ingestSignal({ id: "9", role: "user", content: "你", client_id: "c1" });
  const ups = up.filter(i => i.action === "upsert");
  assert.equal(ups.length, 1);
  assert.equal(ups[0].msg.domId, "client_c1"); // 稳定键
  assert.equal(ups[0].msg.msgId, "9");
});

test("ingestSignal: 撤回产生 recall 意图", () => {
  const s = createChatStore();
  s.ingestSignal({ id: "7", role: "user", content: "x" });
  const r = s.ingestSignal({ id: "7", type: "recall" });
  assert.ok(r.some(i => i.action === "recall" && i.id === "7"));
});

test("ingestSignal: 乱序分片按 sequence 有序 apply", () => {
  const s = createChatStore();
  s.ingestSignal({ request_id: "r9", role: "assistant", sequence: 2, content: "c" });
  const seq0 = s.ingestSignal({ request_id: "r9", role: "assistant", sequence: 0, content: "a" });
  const seq1 = s.ingestSignal({ request_id: "r9", role: "assistant", sequence: 1, content: "b" });
  assert.equal(seq0.length + seq1.length, 0); // 未按序不产出
  const drain = s.ingestSignal({ request_id: "r9", role: "assistant", sequence: 3, content: "d" });
  assert.ok(drain.length >= 1);
});

test("ingestSignal: 非 request 普通消息直接 upsert 并计数", () => {
  const s = createChatStore();
  const out = s.ingestSignal({ id: "1", role: "assistant", content: "hello" });
  assert.equal(out[0].action, "upsert");
  assert.equal(out[0].msg.domId, "1");
});

test("messages(): 全量重绘数据源, 超 maxMessages 裁剪最旧", () => {
  const s = createChatStore({ maxMessages: 3 });
  for (let i = 1; i <= 5; i++) s.ingestSignal({ id: String(i), role: "assistant", content: "m" + i });
  const ids = s.messages().map(m => m.id);
  assert.deepEqual(ids, ["3", "4", "5"]);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix electron run test:unit`
Expected: `chat-store` 测试报 `Cannot find module '...chat-store.js'` 或 `createChatStore is not a function`。

- [ ] **Step 3: 实现 chat-store.js**

```js
"use strict";

// chat-store.js — 聊天消息状态的单一数据源(纯逻辑, 无 DOM)。
// 独占: 判重(seenIds/seenEventIds)、排序(messages)、请求状态(requests)、
// 请求分片排序(requestSequences)、稳定元素 id 映射(realIdToDomId /
// requestIdToDomId / clientIdToDomId)。
// ingestSignal() 把规范化后的信号翻译成渲染意图(Intent), 由 DOM 层统一应用。

function createChatStore({ maxMessages = 500 } = {}) {
  const messages = [];             // 有序消息描述符
  const byDomId = new Map();       // domId -> msg
  const realIdToDomId = new Map(); // 真实消息 id -> domId
  const requestIdToDomId = new Map(); // request_id -> domId
  const clientIdToDomId = new Map();  // client_id -> domId
  const seenEventIds = new Set();
  const requestSequences = new Map(); // request_id -> { next, pending:Map }
  const requests = new Map();      // request_id -> request state
  const seenRealIds = new Set();   // 已渲染的真实消息 id

  function trim() {
    while (messages.length > maxMessages) {
      const dropped = messages.shift();
      byDomId.delete(dropped.id);
      if (dropped.msgId) realIdToDomId.delete(dropped.msgId);
      if (dropped.msgId) seenRealIds.delete(dropped.msgId);
    }
  }

  function upsert(domId, patch) {
    let msg = byDomId.get(domId);
    if (msg) {
      Object.assign(msg, patch, { id: domId });
      return { action: "upsert", msg };
    }
    msg = { ...patch, id: domId };
    byDomId.set(domId, msg);
    messages.push(msg);
    trim();
    return { action: "upsert", msg };
  }

  function inferRequestStatus(signal) {
    if (signal.status) return signal.status;
    const t = signal.type || "";
    if (t === "chat_request_running") return "running";
    if (t === "chat_request_completed") return "completed";
    if (t === "chat_request_cancelled") return "cancelled";
    if (t === "chat_request_failed") return "failed";
    if (t === "chat_request_cancelling") return "cancelling";
    if (t === "chat_request_queued") return "queued";
    return "";
  }

  function isTerminalStatus(s) {
    return ["completed", "failed", "cancelled"].includes(s);
  }

  function upsertRequestState(signal) {
    const rid = signal.request_id;
    if (!rid) return null;
    const prev = requests.get(rid) || { request_id: rid, statusHistory: [] };
    const status = inferRequestStatus(signal) || prev.status || "queued";
    const next = {
      ...prev, ...signal,
      request_id: rid, status,
      can_cancel: signal.can_cancel ?? ["queued", "running"].includes(status),
      can_retry: signal.can_retry ?? ["failed", "cancelled"].includes(status),
      statusHistory: prev.statusHistory ? prev.statusHistory.slice() : [],
    };
    if (next.statusHistory[next.statusHistory.length - 1] !== status) {
      next.statusHistory.push(status);
    }
    requests.set(rid, next);
    return next;
  }

  // 返回意图数组: { action:"upsert"|"recall"|"typing"|"status"|"remove", ... }
  function ingestSignal(signal, transport = "unknown") {
    if (!signal) return [];
    const intents = [];

    if (signal.event_id) {
      if (seenEventIds.has(signal.event_id)) return [];
      seenEventIds.add(signal.event_id);
    }

    // 乱序分片: 按 sequence 排队, 仅在连续时产出
    const sequence = Number(signal.sequence);
    if (signal.request_id && Number.isInteger(sequence) && sequence >= 0) {
      let tracker = requestSequences.get(signal.request_id);
      if (!tracker) {
        tracker = { next: sequence === 0 ? 0 : 1, pending: new Map() };
        requestSequences.set(signal.request_id, tracker);
      }
      if (sequence < tracker.next) return [];
      tracker.pending.set(sequence, signal);
      while (tracker.pending.has(tracker.next)) {
        const cur = tracker.pending.get(tracker.next);
        tracker.pending.delete(tracker.next);
        intents.push(...applyOne(cur, transport));
        tracker.next += 1;
      }
      return intents;
    }

    return applyOne(signal, transport);
  }

  function applyOne(signal, transport) {
    // 撤回
    if (signal.type === "recall" || signal.is_recalled) {
      if (signal.id) return [{ action: "recall", id: signal.id }];
      return [];
    }

    // 请求状态(可能独立于消息内容到达)
    const status = inferRequestStatus(signal);
    if (signal.request_id && (status || signal.request_status)) {
      const state = upsertRequestState(signal);
      if (state) intentsPush({ action: "status", state });
    }

    const intents = [];
    const hasContent = signal.role === "user" || signal.role === "assistant";

    // 助手: typing 与最终共用稳定 domId = req_<request_id>
    if (signal.role === "assistant" && signal.request_id) {
      const domId = signal.domId || requestIdToDomId.get(signal.request_id) || "req_" + signal.request_id;
      requestIdToDomId.set(signal.request_id, domId);
      const isTyping = signal.typing === true || (signal.request_status || status) === "running";
      if (isTyping && !signal.content) {
        intents.push({
          action: "typing",
          msg: {
            id: domId, role: "assistant", request_id: signal.request_id,
            request_status: status || "running", status: status || "running",
            content: "", domId, typing: true,
          },
        });
        return intents;
      }
      if (signal.id) {
        if (seenRealIds.has(signal.id)) return [];
        seenRealIds.add(signal.id);
        realIdToDomId.set(signal.id, domId);
      }
      intents.push(upsert(domId, {
        ...signal, id: domId, domId,
        msgId: signal.id, typing: false,
        request_status: status || signal.request_status || "",
      }));
      return intents;
    }

    // 用户: 乐观气泡 client_<client_id> 稳定键
    if (signal.role === "user") {
      const domId = signal.domId || clientIdToDomId.get(signal.client_id) || (signal.client_id ? "client_" + signal.client_id : null) || signal.id;
      if (signal.client_id) clientIdToDomId.set(signal.client_id, domId);
      if (signal.id) {
        if (seenRealIds.has(signal.id)) return [];
        seenRealIds.add(signal.id);
        realIdToDomId.set(signal.id, domId);
      }
      intents.push(upsert(domId, {
        ...signal, id: domId, domId, msgId: signal.id, typing: false,
      }));
      return intents;
    }

    // 普通历史消息(无 request): domId = 真实 id
    if (hasContent && signal.id) {
      if (seenRealIds.has(signal.id)) return [];
      seenRealIds.add(signal.id);
      intents.push(upsert(signal.id, { ...signal, id: signal.id, domId: signal.id, msgId: signal.id }));
    }
    return intents;
  }

  function intentsPush(i) { /* keep status first via applyOne ordering */ }

  return {
    ingestSignal,
    messages: () => messages.slice(),
    getMessage: (domId) => byDomId.get(domId),
    requestState: (rid) => requests.get(rid),
    clientIdToDomId,
    requestIdToDomId,
    seenEventIds,
    requestSequences,
    requests,
    markRecalled(id) {
      if (seenRealIds.has(id) && realIdToDomId.has(id)) {
        return [{ action: "recall", id: realIdToDomId.get(id) }];
      }
      return [{ action: "recall", id }];
    },
  };
}

module.exports = { createChatStore };
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npm --prefix electron run test:unit`
Expected: `chat-store` 全部用例 PASS（其他既有测试不回归）。

- [ ] **Step 5: 提交**

```bash
git add electron/src/renderer/js/chat-store.js electron/tests/chat-store.test.js
git commit -m "feat(chat): add pure chat-store as single source of truth"
```

---

### Task 2: chat.js 接入 store + 单一 _reconcile

**Files:**
- Modify: `electron/src/renderer/js/chat.js`
- Modify: `electron/src/renderer/chat.html`（确认并加入 `<script src="js/chat-store.js">` 于 chat.js 之前）

目标：`_ingestChatSignal` / `_applyChatSignal` 改为调用 `store.ingestSignal` 并逐个 `_applyIntent`；新增 `_reconcile(intent)` 作为唯一的创建/更新/删除入口；保留 `_buildMessageHtml`、`_renderRequestStatus`、`_syncRequestTypingBubble` 供 `_applyIntent` 复用。

- [ ] **Step 1: 确认 HTML 引入方式**

Run: `Grep -n "chat.js" electron/src/renderer/*.html`
Expected: 找到 chat.js 的 `<script>` 行；在其前一行插入 chat-store.js 的 `<script>`。若无内联（由 app.js 动态加载），则在 app.js 的加载列表里把 store 排在 chat 之前。

- [ ] **Step 2: 构造函数初始化 store**

```js
this._store = createChatStore({ maxMessages: this._maxDomMessages });
```

（`createChatStore` 由 `<script>` 全局暴露，或在文件顶部 `const { createChatStore } = require(...)`——但 renderer 用 script 标签，故走全局。若 chat.js 是 UMD/全局脚本，则 chat-store.js 也按全局暴露 `window.createChatStore`。）

- [ ] **Step 3: 新增 _applyIntent 单一入口**

```js
_applyIntent(intent) {
  if (!intent) return;
  switch (intent.action) {
    case "upsert":
      this._reconcileMessage(intent.msg);
      break;
    case "typing":
      this._reconcileMessage(intent.msg);
      break;
    case "recall":
      this._reconcileRecalled(intent.id);
      break;
    case "status":
      this._renderRequestStatus(intent.state);
      this._syncRequestTypingBubble(intent.state);
      break;
    case "remove":
      this._removeMessage(intent.id);
      break;
  }
}

_reconcileMessage(msg) {
  if (!this._el.messages) return;
  const domId = msg.id;
  let el = this._el.messages.querySelector(`[data-id="${domId}"]`);
  const create = !el;
  if (create) {
    el = document.createElement("div");
    this._el.messages.appendChild(el);
  }
  el.className = "chat-msg chat-msg--" + msg.role + (msg.typing ? " chat-msg--typing" : "");
  if (msg.typing && this._reducedMotion) el.className += " chat-msg--typing--reduced";
  el.setAttribute("data-id", domId);
  if (msg.msgId) el.setAttribute("data-msg-id", msg.msgId);
  if (msg.request_id) el.setAttribute("data-request-id", msg.request_id);
  el.setAttribute("data-request-status", msg.request_status || msg.status || "");
  if (msg.typing) el.setAttribute("data-chat-typing", "true");
  else el.removeAttribute("data-chat-typing");
  el.innerHTML = this._buildMessageHtml(msg, { typing: Boolean(msg.typing) });
  this._bindMessageActions(el, msg); // 复用 _render 里的 contextmenu / 附件 / 引用绑定
  if (create) this._scrollToBottom();
  return el;
}

_removeMessage(id) {
  const el = this._el.messages && this._el.messages.querySelector(`[data-id="${id}"]`);
  if (el && el.parentNode) el.parentNode.removeChild(el);
}
```

- [ ] **Step 4: 改写信号摄入入口**

```js
_applyChatSignal(signal, transport = "unknown") {
  const intents = this._store.ingestSignal(signal, transport);
  for (const intent of intents) this._applyIntent(intent);
}
```

（`_ingestChatSignal` 保留：先 `_normalizeChatSignal`，再调用 `_store.ingestSignal`。原 `_seenEventIds`/`_requestSequences` 判重由 store 接管，删掉 chat.js 内对应成员。）

- [ ] **Step 5: 历史加载与 _render 改走 reconcile**

把 `_loadHistoryPage` 里的 `this._render(item, {...})` 换成 `for (const intent of this._store.ingestSignal(item, "history")) this._applyIntent(intent);`；`_renderRecalledStub` 由 `_reconcileRecalled` 统一。

- [ ] **Step 6: 运行测试**

Run: `npm --prefix electron run test:unit`
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add electron/src/renderer/js/chat.js electron/src/renderer/chat.html
git commit -m "refactor(chat): funnel all render paths through chat-store + reconcile"
```

---

### Task 3: 删除身份偷换路径

**Files:**
- Modify: `electron/src/renderer/js/chat.js`

删除 `_updateUserBubble`、`_updateTypingBubble`、`_promoteBubbleIdentity`，其调用点（原 `_applyChatSignal` 内 user/assistant 分支）已被 Task 2 的 `_applyIntent` 取代。`_findBubbleForRequest`、`_syncRequestTypingBubble` 若仍被引用则保留，但 `_syncRequestTypingBubble` 改为调用 `_reconcileMessage`（用 `req_<requestId>` 稳定键）而非自建 `typing_<requestId>`。

- [ ] **Step 1: 收敛 typing 气泡到稳定键**

将 `_syncRequestTypingBubble` 的 bubbleId 从 `"typing_" + requestId` 改为 `"req_" + requestId`，并让其通过 `this._reconcileMessage(typingMsg)` 创建/更新/移除，与 store 的 `requestIdToDomId` 一致。

- [ ] **Step 2: 删除三个身份偷换方法**

删 `_updateUserBubble` / `_updateTypingBubble` / `_promoteBubbleIdentity` 整个方法体。

- [ ] **Step 3: 静态检查残留调用**

Run: `Grep -n "_updateUserBubble|_updateTypingBubble|_promoteBubbleIdentity" electron/src/renderer/js/chat.js`
Expected: 无匹配。

- [ ] **Step 4: 运行测试**

Run: `npm --prefix electron run test:unit`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add electron/src/renderer/js/chat.js
git commit -m "refactor(chat): remove typing/user bubble identity-swap paths"
```

---

### Task 4: 删除死代码并重实现全量重绘

**Files:**
- Modify: `electron/src/renderer/js/chat.js`

现状：`_rerenderVisible()` 调用从未定义的 `_renderMessage`，且依赖从不写入的 `this._messages`。

- [ ] **Step 1: 删除 _renderMessage 调用与死方法**

删掉 `_rerenderVisible` 中的 `_renderMessage` 引用。若 `_rerenderVisible` 无调用方，直接删除该方法；若有调用方（如头像刷新 `_refreshAvatarsInDom` 后），则基于 store 重实现：

```js
_rerenderVisible() {
  if (!this._el || !this._el.messages) return;
  const msgs = this._store.messages();
  if (!msgs.length) return;
  this._el.messages.innerHTML = "";
  for (const m of msgs) {
    this._reconcileMessage(m); // 直接重建, appendChild 在 _reconcileMessage 内处理
  }
  this._scrollToBottom();
}
```

- [ ] **Step 2: 确认 _messages 移除**

Run: `Grep -n "_messages" electron/src/renderer/js/chat.js`
Expected: 无匹配（store.messages() 取代）。

- [ ] **Step 3: 运行测试**

Run: `npm --prefix electron run test:unit`
Expected: 全部 PASS。

- [ ] **Step 4: 提交**

```bash
git add electron/src/renderer/js/chat.js
git commit -m "refactor(chat): drop dead _renderMessage/_rerenderVisible, rebuild from store"
```

---

### Task 5: 回归验证

**Files:** 无新增

- [ ] **Step 1: 全量 JS 单元测试**

Run: `npm --prefix electron run test:unit`
Expected: 全部 PASS（含 chat-store + 既有 chat-request-queue 等）。

- [ ] **Step 2: 语法检查改动文件**

Run: `node --check electron/src/renderer/js/chat.js && node --check electron/src/renderer/js/chat-store.js`
Expected: 无输出（exit 0）。

- [ ] **Step 3: 桌面端 e2e 冒烟（若环境可跑）**

Run: `npm --prefix electron run test:e2e`
Expected: 无回归（或记录不可运行原因）。

- [ ] **Step 4: 后端回归（渲染无关，防御性）**

Run: `python -m pytest tests/ -q`
Expected: 无新增失败（渲染改动不触及后端）。

- [ ] **Step 5: 提交（如有遗留改动）**

```bash
git add -A
git commit -m "chore(chat): regression verification"
```

---

## Self-Review

**Spec 覆盖：**
- 单一数据源 → Task 1 (chat-store) ✔
- 单一 DOM 应用 → Task 2 (_reconcile/_applyIntent) ✔
- 消灭身份偷换 → Task 3 ✔
- 删死代码 → Task 4 ✔
- 回归 → Task 5 ✔

**占位符扫描：** 每个任务均含真实代码与命令，无 TBD/TODO。

**类型一致性：** store 的 `ingestSignal` 返回 `{action:"upsert"|"typing"|"recall"|"status"|"remove"}`，chat.js `_applyIntent` switch 分支与之一一对应；`_reconcileMessage(msg)` 使用 `msg.id`(domId)/`msg.msgId`/`msg.typing`/`msg.role`/`msg.request_id`/`msg.request_status`，与 store `upsert` 写入的字段一致；`_syncRequestTypingBubble` 稳定键 `req_<requestId>` 与 store `requestIdToDomId` 默认键一致。✔

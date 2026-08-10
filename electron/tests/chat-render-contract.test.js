"use strict";

// chat-render-contract.test.js — 聊天渲染层重构契约锁定测试。
// 作用：在重写 chat-store.js / chat.js 之前锁定对外契约，重写后跑本文件
// 验证契约未破。覆盖三部分：
//   1) store 公共 API 契约（createChatStore 入口 + 方法 + 暴露的 Map + 双暴露）
//   2) chat.js 被外部模块调用的 13 个公共符号（settings/data-viewer/
//      cognition-panel/chat-uploader/e2e 依赖，签名不可变）
//   3) 事件消费入口（IPC onMessage + SSE subscribe）与 window._chat 挂载

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STORE = path.join(__dirname, "../src/renderer/js/chat-store.js");
const CHAT = path.join(__dirname, "../src/renderer/js/chat.js");
const { createChatStore } = require(STORE);

// ── 1. Store 公共 API 契约 ─────────────────────────────

test("store: createChatStore 入口与核心方法存在", () => {
  const s = createChatStore({ maxMessages: 10 });
  for (const m of ["ingestSignal", "messages", "getMessage", "requestState", "markRecalled"]) {
    assert.equal(typeof s[m], "function", `missing store method: ${m}`);
  }
});

test("store: 暴露的稳定映射/去重容器存在（chat.js 直接读取）", () => {
  const s = createChatStore({ maxMessages: 10 });
  for (const m of ["clientIdToDomId", "requestIdToDomId", "seenEventIds", "requestSequences", "requests"]) {
    assert.ok(s[m], `missing store container: ${m}`);
  }
});

test("store: 双暴露契约（node require + window 全局）", () => {
  assert.equal(typeof createChatStore, "function");
  const src = fs.readFileSync(STORE, "utf8");
  assert.match(src, /window\.createChatStore\s*=\s*createChatStore/);
  assert.match(src, /module\.exports\s*=\s*\{\s*createChatStore\s*\}/);
});

// ── 2. chat.js 13 个公共符号契约（源码级锁定）─────────────

const CHAT_SRC = fs.readFileSync(CHAT, "utf8");

// 被外部模块调用的 window._chat 成员（签名不可变）
const PUBLIC_METHODS = [
  "send",                 // cognition-panel.js
  "setUserAvatar",        // settings.js
  "setUserName",          // settings.js
  "_writeLocalAvatar",    // settings.js
  "_loadPersona",         // settings.js
  "_openAttachment",      // data-viewer.js
  "_retryAttachment",     // data-viewer.js
  "_buildAttachmentCard", // data-viewer.js
  "_request",             // chat-uploader.js
  "_renderAttachmentPreviews", // chat-uploader.js
];
const PUBLIC_PROPERTIES = [
  "_pendingAttachments",  // chat-uploader.js（数组，可读写）
  "_userName",            // settings.js（string）
  "_userDataurl",         // settings.js（string）
];

test("chat.js: 10 个公共方法必须定义（外部模块依赖）", () => {
  for (const m of PUBLIC_METHODS) {
    // 方法定义：类体内 `  async send(` 或 `  send(`（缩进 ≥2）
    const re = new RegExp(`\\n\\s{2,}(?:async\\s+)?${m}\\s*\\(`);
    assert.match(CHAT_SRC, re, `missing public method: ${m}`);
  }
});

test("chat.js: 3 个公共属性必须定义", () => {
  for (const p of PUBLIC_PROPERTIES) {
    // constructor 内以 `this._xxx =` 形式定义
    const re = new RegExp(`\\n\\s{2,}this\\.${p}\\s*=`);
    assert.match(CHAT_SRC, re, `missing public property: ${p}`);
  }
});

// ── 3. 事件消费入口与挂载契约 ────────────────────────────

test("chat.js: IPC 事件消费入口保留（aerie.api.onMessage）", () => {
  assert.match(CHAT_SRC, /aerie\.api\.onMessage/);
});

test("chat.js: SSE 事件消费入口保留（aerie.sse.subscribe）", () => {
  assert.match(CHAT_SRC, /aerie\.sse\.subscribe/);
});

test("chat.js: DOMContentLoaded 后挂载 window._chat", () => {
  assert.match(CHAT_SRC, /window\._chat\s*=/);
});

test("chat.js: 使用 createChatStore 作为消息状态源", () => {
  assert.match(CHAT_SRC, /createChatStore/);
});

test("chat.js: 后端 HTTP 契约 API 路径保留", () => {
  for (const pathStr of [
    "/api/chat/send",
    "/api/chat/history/page",
    "/api/chat/poll",
    "/api/chat/recall/",
    "/api/chat/requests/",
  ]) {
    assert.ok(CHAT_SRC.includes(pathStr), `missing api path: ${pathStr}`);
  }
});

// ── 4. 行为基线（关键契约语义）──────────────────────────

test("baseline: 重复真实消息只 upsert 一次", () => {
  const s = createChatStore();
  const a = s.ingestSignal({ id: "10", role: "assistant", content: "hi", request_id: "r1" });
  const b = s.ingestSignal({ id: "10", role: "assistant", content: "hi", request_id: "r1" });
  assert.equal(a.filter((i) => i.action === "upsert").length, 1);
  assert.equal(b.length, 0);
});

test("baseline: 用户乐观气泡 client_id 映射升级为真实 id", () => {
  const s = createChatStore();
  s.ingestSignal({ client_id: "c1", role: "user", content: "你" });
  const up = s.ingestSignal({ id: "9", role: "user", content: "你", client_id: "c1" });
  const ups = up.filter((i) => i.action === "upsert");
  assert.equal(ups.length, 1);
  assert.equal(ups[0].msg.domId, "client_c1");
  assert.equal(ups[0].msg.msgId, "9");
});

test("baseline: 撤回产生 recall 意图", () => {
  const s = createChatStore();
  s.ingestSignal({ id: "7", role: "user", content: "x" });
  const r = s.ingestSignal({ id: "7", type: "recall" });
  assert.ok(r.some((i) => i.action === "recall" && i.id === "7"));
});

// ── 5. v2 新能力（重写引入，回归门禁）────────────────────

test("v2: 普通历史消息跨通道去重（byKey 消息级去重）", () => {
  const s = createChatStore();
  s.ingestSignal({ id: "77", role: "assistant", content: "a" });
  // 同一 id 从另一通道（poll/历史分页）再次到达 → 不再产生 upsert
  const again = s.ingestSignal({ id: "77", role: "assistant", content: "a" });
  assert.equal(again.filter((i) => i.action === "upsert").length, 0);
});

test("v2: 终态自动清理遗留 typing 气泡（分片从未到达）", () => {
  const s = createChatStore();
  s.ingestSignal({ request_id: "r9", role: "assistant", status: "running", typing: true, content: "" });
  const out = s.ingestSignal({ request_id: "r9", status: "completed" });
  assert.ok(out.some((i) => i.action === "remove"), "expected remove intent for stale typing");
  assert.equal(s.messages().length, 0);
});

test("v2: 真实分片到达后终态不再误删真实消息", () => {
  const s = createChatStore();
  const run = s.ingestSignal({ request_id: "r10", role: "assistant", status: "running", typing: true, content: "" });
  const typingDomId = run.find((i) => i.action === "typing").msg.domId;
  s.ingestSignal({ request_id: "r10", role: "assistant", id: "88", content: "real", status: "running" });
  const out = s.ingestSignal({ request_id: "r10", status: "completed" });
  assert.equal(out.some((i) => i.action === "remove"), false);
  const msg = s.getMessage(typingDomId);
  assert.equal(msg.msgId, "88");
  assert.equal(msg.typing, false);
});

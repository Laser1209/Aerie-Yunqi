"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createChatStore } = require("../src/renderer/js/chat-store.js");

test("ingestSignal: 重复真实消息只 upsert 一次", () => {
  const s = createChatStore();
  const a = s.ingestSignal({ id: "10", role: "assistant", content: "hi", request_id: "r1" });
  const b = s.ingestSignal({ id: "10", role: "assistant", content: "hi", request_id: "r1" });
  assert.equal(a.filter((i) => i.action === "upsert").length, 1);
  assert.equal(b.length, 0);
});

test("ingestSignal: 助手输入中→最终 用同一 domId 原地更新, 不产生新元素", () => {
  const s = createChatStore();
  const run = s.ingestSignal({ request_id: "r1", role: "assistant", status: "running", typing: true, content: "" });
  assert.ok(run.some((i) => i.action === "typing" && i.msg.typing === true));
  const typingDomId = run.find((i) => i.action === "typing").msg.domId;
  const done = s.ingestSignal({ request_id: "r1", role: "assistant", id: "55", content: "答案", status: "completed" });
  const ups = done.filter((i) => i.action === "upsert");
  assert.equal(ups.length, 1);
  assert.equal(ups[0].msg.domId, typingDomId); // 同一元素
  assert.equal(ups[0].msg.msgId, "55");
  assert.equal(ups[0].msg.content, "答案");
  // 之后历史/轮询再送同 id → 不再渲染
  assert.equal(s.ingestSignal({ id: "55", role: "assistant", content: "答案" }).length, 0);
});

test("ingestSignal: 用户乐观气泡用 client_id 映射升级为真实 id", () => {
  const s = createChatStore();
  s.ingestSignal({ client_id: "c1", role: "user", content: "你" });
  const up = s.ingestSignal({ id: "9", role: "user", content: "你", client_id: "c1" });
  const ups = up.filter((i) => i.action === "upsert");
  assert.equal(ups.length, 1);
  assert.equal(ups[0].msg.domId, "client_c1"); // 稳定键
  assert.equal(ups[0].msg.msgId, "9");
});

test("ingestSignal: 撤回产生 recall 意图", () => {
  const s = createChatStore();
  s.ingestSignal({ id: "7", role: "user", content: "x" });
  const r = s.ingestSignal({ id: "7", type: "recall" });
  assert.ok(r.some((i) => i.action === "recall" && i.id === "7"));
});

test("ingestSignal: 乱序分片缓冲, 补齐缺口后按序产出", () => {
  const s = createChatStore();
  s.ingestSignal({ request_id: "r9", role: "assistant", sequence: 2, content: "c" });
  // 缺 0/1, seq2 先缓冲 → 不产出
  const seq1 = s.ingestSignal({ request_id: "r9", role: "assistant", sequence: 1, content: "b" });
  // seq1 补齐缺口 → 按 1,2 顺序一起产出
  const contents = seq1
    .filter((i) => i.action === "upsert")
    .map((i) => i.msg.content)
    .filter(Boolean);
  assert.deepEqual(contents, ["b", "c"]);
});

test("ingestSignal: 非 request 普通消息直接 upsert", () => {
  const s = createChatStore();
  const out = s.ingestSignal({ id: "1", role: "assistant", content: "hello" });
  assert.equal(out[0].action, "upsert");
  assert.equal(out[0].msg.domId, "1");
});

test("ingestSignal: 请求状态信号独立产出 status 意图", () => {
  const s = createChatStore();
  const out = s.ingestSignal({ request_id: "r2", status: "queued" });
  assert.ok(out.some((i) => i.action === "status" && i.state.status === "queued"));
});

test("messages(): 全量重绘数据源, 超 maxMessages 裁剪最旧", () => {
  const s = createChatStore({ maxMessages: 3 });
  for (let i = 1; i <= 5; i++) {
    s.ingestSignal({ id: String(i), role: "assistant", content: "m" + i });
  }
  const ids = s.messages().map((m) => m.id);
  assert.deepEqual(ids, ["3", "4", "5"]);
});

test("附件补齐: 历史消息先无附件后有附件 → 放行一次补图 upsert", () => {
  const s = createChatStore();
  const first = s.ingestSignal({ id: "200", role: "user", content: "[图片:方向盘]" });
  assert.equal(first.filter((i) => i.action === "upsert").length, 1);
  // 同 id 再次到达(轮询/历史补齐)带 attachments → 应放行补图
  const att = [{ category: "image", url: "/uploads/x.png", thumbnailUrl: "/uploads/.image_assets/thumbs/y.png" }];
  const second = s.ingestSignal({ id: "200", role: "user", content: "[图片:方向盘]", attachments: att });
  const ups = second.filter((i) => i.action === "upsert");
  assert.equal(ups.length, 1, "旧无附件、新有附件应放行补图");
  assert.deepEqual(ups[0].msg.attachments, att);
  assert.equal(ups[0].msg.domId, "200");
  // 再次带附件到达 → 已有附件, 不再放行(避免重复渲染)
  assert.equal(s.ingestSignal({ id: "200", role: "user", content: "[图片:方向盘]", attachments: att }).length, 0);
});

test("附件补齐: 已有附件的消息再次到达不重复渲染", () => {
  const s = createChatStore();
  const att = [{ category: "image", url: "/uploads/x.png", thumbnailUrl: "/uploads/.image_assets/thumbs/y.png" }];
  s.ingestSignal({ id: "201", role: "user", content: "[图片:方向盘]", attachments: att });
  const second = s.ingestSignal({ id: "201", role: "user", content: "[图片:方向盘]", attachments: att });
  assert.equal(second.length, 0);
});

test("附件补齐: 用户乐观气泡(client_id) 升级后带附件 → 在 client_ 稳定键上补图", () => {
  const s = createChatStore();
  s.ingestSignal({ client_id: "c9", role: "user", content: "你好" });
  const att = [{ category: "image", url: "/uploads/a.png", thumbnailUrl: "/uploads/.image_assets/thumbs/b.png" }];
  const up = s.ingestSignal({ id: "99", role: "user", content: "你好", client_id: "c9", attachments: att });
  const ups = up.filter((i) => i.action === "upsert");
  assert.equal(ups.length, 1);
  assert.equal(ups[0].msg.domId, "client_c9");
  assert.deepEqual(ups[0].msg.attachments, att);
});

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

test("时间排序: 乱序到达的消息按时间戳正序落位", () => {
  const s = createChatStore();
  // 模拟启动竞态: 先到一条实时新消息, 后到两条更早的历史消息
  s.ingestSignal({ id: "30", role: "assistant", content: "new", ts: "2026-08-17T10:00:30+08:00" });
  s.ingestSignal({ id: "10", role: "assistant", content: "old", ts: "2026-08-17T10:00:10+08:00" });
  s.ingestSignal({ id: "20", role: "assistant", content: "mid", ts: "2026-08-17T10:00:20+08:00" });
  const order = s.messages().map((m) => m.content);
  assert.deepEqual(order, ["old", "mid", "new"]);
});

test("时间排序: 同时刻消息按数字 id 稳定 tiebreak", () => {
  const s = createChatStore();
  const ts = "2026-08-17T10:00:00+08:00";
  s.ingestSignal({ id: "40", role: "user", content: "later", ts });
  s.ingestSignal({ id: "10", role: "user", content: "earlier", ts });
  s.ingestSignal({ id: "20", role: "user", content: "mid", ts });
  const order = s.messages().map((m) => m.id);
  assert.deepEqual(order, ["10", "20", "40"]);
});

test("时间排序: 启动竞态——UUID 历史先落, 轮询全量后到 → 时间正序且去重", () => {
  const s = createChatStore();
  // 历史页(最近 3 条): message_id 为 UUID, 携带 legacy_chat_log_id
  s.ingestSignal({ id: "msg_uuid_3", legacy_chat_log_id: 3, role: "user", content: "c3", ts: "2026-08-17T10:00:03+08:00" });
  s.ingestSignal({ id: "msg_uuid_4", legacy_chat_log_id: 4, role: "assistant", content: "c4", ts: "2026-08-17T10:00:04+08:00" });
  s.ingestSignal({ id: "msg_uuid_5", legacy_chat_log_id: 5, role: "user", content: "c5", ts: "2026-08-17T10:00:05+08:00" });
  // 轮询全量(since_id=0): chat_log 数字 id, 正序到达
  s.ingestSignal({ id: "1", role: "user", content: "c1", ts: "2026-08-17T10:00:01+08:00" });
  s.ingestSignal({ id: "2", role: "assistant", content: "c2", ts: "2026-08-17T10:00:02+08:00" });
  s.ingestSignal({ id: "3", role: "user", content: "c3", ts: "2026-08-17T10:00:03+08:00" }); // 与历史 legacy=3 同一条
  s.ingestSignal({ id: "4", role: "assistant", content: "c4", ts: "2026-08-17T10:00:04+08:00" }); // 与历史 legacy=4 同一条
  s.ingestSignal({ id: "5", role: "user", content: "c5", ts: "2026-08-17T10:00:05+08:00" }); // 与历史 legacy=5 同一条
  const order = s.messages().map((m) => m.content);
  assert.deepEqual(order, ["c1", "c2", "c3", "c4", "c5"], "时间正序且无重复");
});

test("时间排序: 乐观气泡无时间戳按当前时刻靠底, 回显后原地重排", () => {
  const s = createChatStore();
  const now = Date.now();
  s.ingestSignal({ id: "50", role: "assistant", content: "old", ts: new Date(now - 60000).toISOString() });
  // 用户乐观气泡(无 ts) → 应排在最底(最新)
  s.ingestSignal({ client_id: "c_opt", domId: "c_opt", role: "user", content: "hi" });
  let ids = s.messages().map((m) => m.id || m.client_id);
  assert.deepEqual(ids, ["50", "c_opt"]);
  // 回显带真实时间 → 重排到正确位置
  const up = s.ingestSignal({ id: "99", legacy_chat_log_id: 99, client_id: "c_opt", role: "user", content: "hi", ts: new Date(now - 30000).toISOString() });
  const ups = up.filter((i) => i.action === "upsert");
  assert.equal(ups.length, 1);
  assert.equal(ups[0].msg.domId, "c_opt");
  ids = s.messages().map((m) => m.msgId || m.id || m.client_id);
  assert.deepEqual(ids, ["50", "99"], "回显后按真实时间排到最底");
});

test("时间排序: 实时事件(毫秒)与 poll(整秒)同秒混排不倒挂", () => {
  const s = createChatStore();
  const now = Math.floor(Date.now() / 1000) * 1000; // 整秒锚点
  // 用户消息经 SSE 事件到达: 事件信封 ts 带毫秒(该秒内 850ms)
  s.ingestSignal({ id: "3124", role: "user", content: "u", ts: new Date(now + 850).toISOString() });
  // 助手回复经 poll 到达: created_at 只到整秒(同一秒)
  s.ingestSignal({ id: "3125", role: "assistant", content: "a", ts: new Date(now).toISOString() });
  const order = s.messages().map((m) => m.id);
  assert.deepEqual(order, ["3124", "3125"], "同秒内按数字 id 决定先后, 用户在上");
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

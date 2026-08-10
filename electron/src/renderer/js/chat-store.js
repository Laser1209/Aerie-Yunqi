"use strict";

// chat-store.js — 聊天消息状态的单一数据源(纯逻辑, 无 DOM)。
//
// v2 重写(主流架构)：
//   1) 消息级去重归一化 —— byKey(逻辑消息 key) + seenEventIds(事件级) 双层去重。
//      同一逻辑消息无论从哪条通道到达(IPC/SSE/poll/history)都映射到同一 domId，
//      不再靠"通道形态"决定 domId，消灭重复渲染。
//   2) 请求状态内聚 —— requests Map 管理请求生命周期，终态自动清理遗留 typing 气泡。
//   3) 分片缓冲容错 —— 终态信号强制跳过 sequence 缺口，避免缓冲永久卡死。
//   4) 单轨裁剪 —— maxMessages 只在 store 统一裁剪。
//
// 对外契约(重写必须保留)：createChatStore / ingestSignal / messages / getMessage /
// requestState / markRecalled，以及 clientIdToDomId / requestIdToDomId /
// seenEventIds / requestSequences / requests 的暴露。

function createChatStore({ maxMessages = 500 } = {}) {
  const messages = [];             // 有序消息描述符(元素顺序)
  const byDomId = new Map();       // domId -> msg
  const byKey = new Map();         // 逻辑消息 key -> domId（消息级去重）
  const realIdToDomId = new Map(); // 真实消息 id -> domId
  const requestIdToDomId = new Map(); // request_id -> domId
  const clientIdToDomId = new Map();  // client_id -> domId
  const seenEventIds = new Set();
  const seenRealIds = new Set();   // 已渲染的真实消息 id（兼容保留）
  const requestSequences = new Map(); // request_id -> { next, pending:Map }
  const requestSegments = new Set();  // 已产出真实分片的 request_id
  const requests = new Map();      // request_id -> request state

  function trim() {
    while (messages.length > maxMessages) {
      const dropped = messages.shift();
      byDomId.delete(dropped.id);
      if (dropped.msgId) {
        realIdToDomId.delete(dropped.msgId);
        seenRealIds.delete(dropped.msgId);
        byKey.delete("m:" + dropped.msgId);
      }
      if (dropped.clientId) byKey.delete("c:" + dropped.clientId);
    }
  }

  // 逻辑消息 key：同一逻辑消息不管从哪条通道来都归一到同一个 key
  function messageKey(signal) {
    if (signal.msgId) return "m:" + signal.msgId;
    if (signal.id) return "m:" + signal.id;
    if (signal.client_id) return "c:" + signal.client_id;
    return "";
  }

  // 更新已存在元素或创建新元素, 返回 upsert 意图
  function upsert(domId, patch) {
    let msg = byDomId.get(domId);
    if (msg) {
      Object.assign(msg, patch, { id: domId });
      return { action: "upsert", msg: { ...msg } };
    }
    msg = { ...patch, id: domId };
    byDomId.set(domId, msg);
    messages.push(msg);
    trim();
    return { action: "upsert", msg: { ...msg } };
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

  const TERMINAL_STATUS = new Set(["completed", "failed", "cancelled"]);

  function upsertRequestState(signal) {
    const rid = signal.request_id;
    if (!rid) return null;
    const prev = requests.get(rid) || { request_id: rid, statusHistory: [] };
    const status = inferRequestStatus(signal) || prev.status || "queued";
    const next = {
      ...prev,
      ...signal,
      request_id: rid,
      status,
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

  // 终态清理：若该 request 只留下了 typing 气泡(真实分片从未到达)则移除
  function removeTypingFor(requestId) {
    const domId = requestIdToDomId.get(requestId);
    if (!domId) return null;
    const msg = byDomId.get(domId);
    if (!msg || !msg.typing) return null;
    byDomId.delete(domId);
    const idx = messages.findIndex((m) => m.id === domId);
    if (idx >= 0) messages.splice(idx, 1);
    requestIdToDomId.delete(requestId);
    return { action: "remove", id: domId };
  }

  // 单条信号的渲染意图
  function applyOne(signal) {
    const intents = [];

    if (signal.type === "recall" || signal.is_recalled) {
      if (signal.id) intents.push({ action: "recall", id: signal.id });
      return intents;
    }

    const status = inferRequestStatus(signal);
    const isStatusSignal = Boolean(signal.request_id) && Boolean(status || signal.request_status);

    // 请求状态(徽标 / 取消重试按钮), 可独立于消息内容到达
    if (isStatusSignal) {
      const state = upsertRequestState(signal);
      if (state) intents.push({ action: "status", state });
      // 终态: 自动清理该 request 遗留的 typing 气泡(分片从未到达时)
      if (TERMINAL_STATUS.has(status)) {
        const clean = removeTypingFor(signal.request_id);
        if (clean) intents.push(clean);
      }
    }

    // 助手消息: typing 与首个真实分片共用稳定 domId = req_<request_id>
    if (signal.role === "assistant" && signal.request_id) {
      const running =
        signal.typing === true || (signal.request_status || status) === "running";
      if (running && !signal.content) {
        const typingDomId =
          signal.domId ||
          requestIdToDomId.get(signal.request_id) ||
          "req_" + signal.request_id;
        requestIdToDomId.set(signal.request_id, typingDomId);
        const typingMsg = {
          id: typingDomId, role: "assistant", request_id: signal.request_id,
          request_status: status || "running", status: status || "running",
          content: "", domId: typingDomId, typing: true,
        };
        // typing 也进 store：供终态清理、真实分片原地替换（不再绕过 Store）
        upsert(typingDomId, typingMsg);
        intents.push({ action: "typing", msg: { ...typingMsg } });
        return intents;
      }
      // 真实分片：同 id 重复到达去重；但若该 request 的 typing 气泡仍在等待
      // 替换(poll 先渲染了真实 id、IPC 分片后到被 seenRealIds 拦截的场景)，
      // 则清理遗留 typing(已渲染元素保留)，避免 typing 气泡残留与重复渲染。
      if (signal.id && seenRealIds.has(signal.id)) {
        const pendingTypingDomId = requestIdToDomId.get(signal.request_id);
        const pendingTyping = pendingTypingDomId ? byDomId.get(pendingTypingDomId) : null;
        if (pendingTyping && pendingTyping.typing) {
          const clean = removeTypingFor(signal.request_id);
          if (clean) intents.push(clean);
        }
        return intents;
      }
      const isFirst = !requestSegments.has(signal.request_id);
      requestSegments.add(signal.request_id);
      const domId =
        signal.domId ||
        (isFirst
          ? (requestIdToDomId.get(signal.request_id) || "req_" + signal.request_id)
          : "req_" + signal.request_id + "_" + signal.id);
      requestIdToDomId.set(signal.request_id, domId);
      if (signal.id) {
        seenRealIds.add(signal.id);
        realIdToDomId.set(signal.id, domId);
      }
      const key = messageKey(signal);
      if (key) byKey.set(key, domId);
      intents.push(upsert(domId, {
        ...signal, id: domId, domId,
        msgId: signal.id, typing: false,
        request_status: status || signal.request_status || "",
      }));
      return intents;
    }

    // 用户消息: 乐观气泡 client_<client_id> 稳定键
    if (signal.role === "user") {
      const domId =
        signal.domId ||
        (signal.client_id ? clientIdToDomId.get(signal.client_id) || "client_" + signal.client_id : null) ||
        signal.id;
      if (signal.client_id) clientIdToDomId.set(signal.client_id, domId);
      if (signal.id) {
        if (seenRealIds.has(signal.id)) return intents;
        seenRealIds.add(signal.id);
        realIdToDomId.set(signal.id, domId);
        byKey.set("m:" + signal.id, domId);
      }
      if (signal.client_id) byKey.set("c:" + signal.client_id, domId);
      intents.push(upsert(domId, {
        ...signal, id: domId, domId, msgId: signal.id, typing: false,
      }));
      return intents;
    }

    // 普通历史消息(无 request): domId = 真实 id, 消息级去重
    if (signal.id && (signal.role === "user" || signal.role === "assistant")) {
      const key = "m:" + signal.id;
      if (byKey.has(key)) return intents;   // 已渲染过, 不重复
      if (seenRealIds.has(signal.id)) return intents;
      seenRealIds.add(signal.id);
      byKey.set(key, signal.id);
      intents.push(upsert(signal.id, { ...signal, id: signal.id, domId: signal.id, msgId: signal.id }));
    }
    return intents;
  }

  // 分片缺口容错阈值(ms)：pending 中最小 seq 大于 next 且超过该时长，
  // 说明前面的分片已丢失(SSE 溢出/断线/丢弃)，跳过缺口继续消费，避免永久卡死。
  const SEQUENCE_FLUSH_MS = 3000;

  // 入口: 事件去重 + 乱序分片缓冲, 产出渲染意图数组
  function ingestSignal(signal) {
    if (!signal) return [];

    if (signal.event_id) {
      if (seenEventIds.has(signal.event_id)) return [];
      seenEventIds.add(signal.event_id);
    }

    const sequence = Number(signal.sequence);

    if (signal.request_id && Number.isInteger(sequence) && sequence >= 0) {
      let tracker = requestSequences.get(signal.request_id);
      if (!tracker) {
        tracker = { next: sequence === 0 ? 0 : 1, pending: new Map(), lastFlush: 0 };
        requestSequences.set(signal.request_id, tracker);
      }
      // 容错：pending 缺口超时后跳过(分片已丢失, 不能无限等)
      const now = Date.now();
      if (tracker.pending.size > 0 && now - tracker.lastFlush > SEQUENCE_FLUSH_MS) {
        const minSeq = Math.min(...tracker.pending.keys());
        if (minSeq > tracker.next) {
          tracker.next = minSeq;
        }
      }
      if (sequence < tracker.next) return [];
      tracker.pending.set(sequence, signal);
      const out = [];
      while (tracker.pending.has(tracker.next)) {
        const cur = tracker.pending.get(tracker.next);
        tracker.pending.delete(tracker.next);
        out.push(...applyOne(cur));
        tracker.next += 1;
      }
      tracker.lastFlush = now;
      return out;
    }

    return applyOne(signal);
  }

  function markRecalled(id) {
    const domId = realIdToDomId.get(id);
    return [{ action: "recall", id: domId || id }];
  }

  const api = {
    ingestSignal,
    messages: () => messages.slice(),
    getMessage: (domId) => byDomId.get(domId),
    requestState: (rid) => requests.get(rid),
    clientIdToDomId,
    requestIdToDomId,
    seenEventIds,
    requestSequences,
    requests,
    markRecalled,
  };

  return api;
}

// 双暴露: node:test 用 require, 浏览器经典 <script> 用全局
if (typeof module !== "undefined" && module.exports) {
  module.exports = { createChatStore };
}
if (typeof window !== "undefined") {
  window.createChatStore = createChatStore;
}

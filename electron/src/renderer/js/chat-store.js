"use strict";

// chat-store.js — 聊天消息状态的单一数据源(纯逻辑, 无 DOM)。
// 独占: 判重(seenRealIds/seenEventIds)、排序(messages)、请求状态(requests)、
// 请求分片排序(requestSequences)、稳定元素 id 映射(realIdToDomId /
// requestIdToDomId / clientIdToDomId)。
// ingestSignal() 把规范化后的信号翻译成渲染意图(Intent), 由 DOM 层统一应用。

function createChatStore({ maxMessages = 500 } = {}) {
  const messages = [];             // 有序消息描述符(元素顺序)
  const byDomId = new Map();       // domId -> msg
  const realIdToDomId = new Map(); // 真实消息 id -> domId
  const requestIdToDomId = new Map(); // request_id -> domId
  const clientIdToDomId = new Map();  // client_id -> domId
  const seenEventIds = new Set();
  const seenRealIds = new Set();   // 已渲染的真实消息 id
  const requestSequences = new Map(); // request_id -> { next, pending:Map }
  const requestSegments = new Set();  // 已产出真实分片的 request_id(首个分片复用 typing domId)
  const requests = new Map();      // request_id -> request state

  function trim() {
    while (messages.length > maxMessages) {
      const dropped = messages.shift();
      byDomId.delete(dropped.id);
      if (dropped.msgId) {
        realIdToDomId.delete(dropped.msgId);
        seenRealIds.delete(dropped.msgId);
      }
    }
  }

  // 更新已存在元素或创建新元素, 返回 upsert 意图
  function upsert(domId, patch) {
    let msg = byDomId.get(domId);
    if (msg) {
      Object.assign(msg, patch, { id: domId });
      // 返回快照: 同一 drain 循环内连续 upsert 同一 domId 时,
      // 前一个 intent 引用的是会被后一个 Object.assign 改写的活对象。
      // 快照保证每个 intent 携带其生成瞬间的状态, 互不污染。
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
    }

    // 助手消息: typing 与首个真实分片共用稳定 domId = req_<request_id>
    // (输入中→最终原地更新, 见设计契约); 同一请求的后续分片各自独立 domId,
    // 因为后端把每个 assistant segment 存为带独立 id 的独立消息。
    if (signal.role === "assistant" && signal.request_id) {
      const running =
        signal.typing === true || (signal.request_status || status) === "running";
      if (running && !signal.content) {
        const typingDomId =
          signal.domId ||
          requestIdToDomId.get(signal.request_id) ||
          "req_" + signal.request_id;
        requestIdToDomId.set(signal.request_id, typingDomId);
        intents.push({
          action: "typing",
          msg: {
            id: typingDomId, role: "assistant", request_id: signal.request_id,
            request_status: status || "running", status: status || "running",
            content: "", domId: typingDomId, typing: true,
          },
        });
        return intents;
      }
      if (signal.id) {
        if (seenRealIds.has(signal.id)) return intents;
        seenRealIds.add(signal.id);
      }
      const isFirst = !requestSegments.has(signal.request_id);
      requestSegments.add(signal.request_id);
      const domId =
        signal.domId ||
        (isFirst
          ? (requestIdToDomId.get(signal.request_id) || "req_" + signal.request_id)
          : "req_" + signal.request_id + "_" + signal.id);
      requestIdToDomId.set(signal.request_id, domId);
      if (signal.id) realIdToDomId.set(signal.id, domId);
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
      }
      intents.push(upsert(domId, {
        ...signal, id: domId, domId, msgId: signal.id, typing: false,
      }));
      return intents;
    }

    // 普通历史消息(无 request): domId = 真实 id
    if (signal.id && (signal.role === "user" || signal.role === "assistant")) {
      if (seenRealIds.has(signal.id)) return intents;
      seenRealIds.add(signal.id);
      intents.push(upsert(signal.id, { ...signal, id: signal.id, domId: signal.id, msgId: signal.id }));
    }
    return intents;
  }

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
        tracker = { next: sequence === 0 ? 0 : 1, pending: new Map() };
        requestSequences.set(signal.request_id, tracker);
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

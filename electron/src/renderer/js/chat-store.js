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
  const messages = [];             // 有序消息描述符(按时间排序键升序, 即 DOM 元素顺序)
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
  let insertCounter = 0;           // 同时间戳消息的稳定 tiebreaker(按到达序)

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

  // 角色隔离修复：history 用 message_id、poll 用 chat_log.id，两条通道 id 不同
  // 会导致同一逻辑消息渲染两份。legacy_chat_log_id 关联回 chat_log.id，poll 的
  // 数字 id 本身也是 chat_log.id，用它做交叉去重，让两条通道互相命中。
  function legacyDedupKeys(signal) {
    const keys = [];
    if (signal.legacy_chat_log_id != null) keys.push("cl:" + signal.legacy_chat_log_id);
    if (signal.id != null && /^\d+$/.test(String(signal.id))) keys.push("cl:" + signal.id);
    return keys;
  }

  // 附件补齐：同一条真实消息若已渲染但无附件（实时事件漏附件/先无图后有图），
  // 后续带附件的同 id 消息到达时允许放行一次 upsert 补上图片卡片。
  // 仅当"旧无附件、新有附件"时放行，避免无谓重复渲染。
  function backfillAttachmentDomId(signal) {
    if (!signal.id) return null;
    const atts = signal.attachments;
    if (!Array.isArray(atts) || atts.length === 0) return null;
    const domId = realIdToDomId.get(signal.id) || byKey.get("m:" + signal.id);
    if (!domId) return null;
    const existing = byDomId.get(domId);
    if (!existing) return null;
    if (Array.isArray(existing.attachments) && existing.attachments.length > 0) return null;
    return domId;
  }

  // 解析消息时间戳 → ms 数值(统一到整秒); 无法解析返回 null。
  // 为什么要整秒: 实时事件信封 ts 带毫秒, 而 DB created_at 只精确到秒。
  // 若两种源混排比较, 同一秒内 SSE 渲染的消息(带毫秒)会排在 poll 渲染的
  // 消息(整秒)之后, 造成"她的回复排在你消息上面"这类倒挂。
  // 整秒化后同秒消息由 tiebreaker(数字 id=插入序)决定先后, 语义一致。
  function timestampMs(msg) {
    const raw = msg.ts ?? msg.created_at;
    if (raw == null || raw === "") return null;
    let ms;
    if (typeof raw === "number") {
      ms = Number.isFinite(raw) ? raw : null;
    } else {
      const parsed = Date.parse(String(raw));
      ms = Number.isFinite(parsed) ? parsed : null;
    }
    if (ms == null) return null;
    return Math.floor(ms / 1000) * 1000;
  }

  // 计算时间排序键 { t: 时间ms, b: tiebreaker }。
  // 无时间戳时: 打字中/乐观气泡(有 client_id 且尚无真实 msgId)按当前时刻靠底,
  // 其余按最早(排最前)。
  function sortKeyFor(msg) {
    let t = timestampMs(msg);
    if (t == null) {
      const isFresh = msg.typing || (msg.role === "user" && msg.client_id && !msg.msgId);
      t = isFresh ? Math.floor(Date.now() / 1000) * 1000 : 0;
    }
    let b = 0;
    const numId = Number(msg.msgId ?? msg.id);
    if (Number.isFinite(numId) && numId >= 0) b = numId;
    else b = ++insertCounter; // UUID/无 id 用到达序兜底, 保证同刻消息顺序稳定
    return { t, b };
  }

  function compareSort(a, b) {
    const ka = a._sort || { t: 0, b: 0 };
    const kb = b._sort || { t: 0, b: 0 };
    if (ka.t !== kb.t) return ka.t < kb.t ? -1 : 1;
    if (ka.b !== kb.b) return ka.b < kb.b ? -1 : 1;
    return 0;
  }

  // 按排序键二分插入, 保证 messages 始终时间正序
  function insertSorted(msg) {
    let lo = 0;
    let hi = messages.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (compareSort(messages[mid], msg) <= 0) lo = mid + 1;
      else hi = mid;
    }
    messages.splice(lo, 0, msg);
  }

  // 更新已存在元素或创建新元素, 返回 upsert 意图。
  // 新元素按时间排序键有序插入(不再无脑 push), 乱序到达的历史/轮询/实时信号
  // 都能落位在正确的时间位置。
  function upsert(domId, patch) {
    let msg = byDomId.get(domId);
    if (msg) {
      const prevSort = msg._sort;
      const prevT = prevSort ? prevSort.t : null;
      Object.assign(msg, patch, { id: domId });
      const newT = timestampMs(msg);
      // 时间戳变化时(如 typing 占位 → 真实时间)重算排序键并重排。
      // 仅当时间戳由无到有/数值变化时触发, 避免每次 upsert 都做数组重排。
      if ((prevT === null && newT !== null) || (prevT !== null && newT !== null && newT !== prevT)) {
        msg._sort = sortKeyFor(msg);
        if (!prevSort || prevSort.t !== msg._sort.t || prevSort.b !== msg._sort.b) {
          const idx = messages.indexOf(msg);
          if (idx >= 0) {
            messages.splice(idx, 1);
            insertSorted(msg);
          }
        }
      }
      return { action: "upsert", msg: { ...msg } };
    }
    msg = { ...patch, id: domId };
    msg._sort = sortKeyFor(msg);
    byDomId.set(domId, msg);
    insertSorted(msg);
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
        // 附件补齐：同 id 已渲染但旧无附件、新有附件 → 放行补图，不丢卡片
        const backfillDomId = backfillAttachmentDomId(signal);
        if (backfillDomId) {
          intents.push(upsert(backfillDomId, {
            ...signal, id: backfillDomId, domId: backfillDomId,
            msgId: signal.id, typing: false,
          }));
          return intents;
        }
        const legacyKeys = legacyDedupKeys(signal);
        if (seenRealIds.has(signal.id) || legacyKeys.some((k) => byKey.has(k))) {
          return intents;
        }
        seenRealIds.add(signal.id);
        realIdToDomId.set(signal.id, domId);
        byKey.set("m:" + signal.id, domId);
        for (const k of legacyKeys) byKey.set(k, domId);
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
      const legacyKeys = legacyDedupKeys(signal);
      const dup = byKey.has(key) || seenRealIds.has(signal.id)
        || legacyKeys.some((k) => byKey.has(k));
      if (dup) {
        // 附件补齐：同 id 已渲染但旧无附件、新有附件 → 放行补图，不丢卡片
        const backfillDomId = backfillAttachmentDomId(signal);
        if (backfillDomId) {
          intents.push(upsert(backfillDomId, {
            ...signal, id: backfillDomId, domId: backfillDomId, msgId: signal.id,
          }));
        }
        return intents;
      }
      seenRealIds.add(signal.id);
      byKey.set(key, signal.id);
      for (const k of legacyKeys) byKey.set(k, signal.id);
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

  // 角色级隔离：切换 persona 后旧角色的消息不再属于当前会话，
  // 必须整体清空（含去重表/请求态），避免新历史与旧消息混排。
  function clear() {
    messages.length = 0;
    byDomId.clear();
    byKey.clear();
    realIdToDomId.clear();
    requestIdToDomId.clear();
    clientIdToDomId.clear();
    seenEventIds.clear();
    seenRealIds.clear();
    requestSequences.clear();
    requestSegments.clear();
    requests.clear();
    return { action: "clear" };
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
    clear,
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

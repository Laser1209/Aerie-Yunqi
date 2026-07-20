"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

class FakeClassList {
  constructor(owner) {
    this.owner = owner;
    this.values = new Set();
  }

  add(name) {
    this.values.add(name);
    this.owner.className = Array.from(this.values).join(" ");
  }

  remove(name) {
    this.values.delete(name);
    this.owner.className = Array.from(this.values).join(" ");
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.dataset = {};
    this.style = {};
    this.eventListeners = {};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.value = "";
    this._innerHTML = "";
    this._textContent = "";
    this.scrollTop = 0;
    this.scrollHeight = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    this.scrollHeight = this.children.length;
    return child;
  }

  insertBefore(child, before) {
    child.parentNode = this;
    const index = this.children.indexOf(before);
    if (index === -1) {
      this.children.push(child);
    } else {
      this.children.splice(index, 0, child);
    }
    return child;
  }

  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index >= 0) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }

  addEventListener(type, handler) {
    this.eventListeners[type] = handler;
  }

  setAttribute(name, value) {
    const text = String(value);
    this.attributes.set(name, text);
    if (name === "class") this.className = text;
    if (name.startsWith("data-")) {
      const key = name
        .slice(5)
        .replace(/-([a-z])/g, (_match, ch) => ch.toUpperCase());
      this.dataset[key] = text;
    }
  }

  getAttribute(name) {
    return this.attributes.get(name) || null;
  }

  closest() {
    return null;
  }

  scrollIntoView() {}

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const result = [];
    const visit = (node) => {
      if (matchesSelector(node, selector)) result.push(node);
      for (const child of node.children) visit(child);
    };
    for (const child of this.children) visit(child);
    return result;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set textContent(value) {
    this._textContent = String(value);
    this._innerHTML = escapeHtml(this._textContent);
  }

  get textContent() {
    return this._textContent;
  }
}

function matchesSelector(node, selector) {
  if (selector === ".chat-empty") return node.className.includes("chat-empty");
  if (selector === "[data-msg-actions]") {
    return Array.from(node.attributes.keys()).some((name) => name === "data-msg-actions");
  }
  const exact = selector.match(/^\[data-id="(.+)"\]$/);
  if (exact) return node.getAttribute("data-id") === exact[1];
  const prefix = selector.match(/^\[data-id\^="(.+)"\]$/);
  if (prefix) return (node.getAttribute("data-id") || "").startsWith(prefix[1]);
  const msgId = selector.match(/^\[data-msg-id="(.+)"\]$/);
  if (msgId) return node.getAttribute("data-msg-id") === msgId[1];
  if (selector.startsWith(".")) return node.className.split(/\s+/).includes(selector.slice(1));
  return false;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function createDocument() {
  const elements = new Map();
  const body = new FakeElement("body");
  const inputArea = new FakeElement("div");
  inputArea.className = "chat-input-area";
  body.appendChild(inputArea);

  for (const [id, tag] of [
    ["chat-messages", "div"],
    ["chat-input", "textarea"],
    ["chat-send-btn", "button"],
    ["chat-brief-btn", "button"],
  ]) {
    const el = new FakeElement(tag);
    el.setAttribute("id", id);
    elements.set(id, el);
    body.appendChild(el);
  }

  return {
    body,
    elements,
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    getElementById(id) {
      return elements.get(id) || null;
    },
    querySelector(selector) {
      if (selector === ".chat-input-area") return inputArea;
      return body.querySelector(selector);
    },
    querySelectorAll(selector) {
      return body.querySelectorAll(selector);
    },
    addEventListener() {},
  };
}

function createLocalStorage() {
  const store = new Map();
  return {
    getItem(key) {
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      store.set(key, String(value));
    },
    removeItem(key) {
      store.delete(key);
    },
  };
}

function loadChatModule({ request, stubSideEffects = true, matchMediaMatches = false } = {}) {
  const document = createDocument();
  const intervals = [];
  const ipcHandlers = [];
  const sseHandlers = [];
  const calls = [];
  const apiRequest = async (options) => {
    calls.push(options);
    if (request) return request(options);
    if (options.path.startsWith("/api/chat/history")) return { data: { history: [] } };
    if (options.path.startsWith("/api/chat/poll")) return { data: { items: [] } };
    if (options.path.startsWith("/api/persona")) return { data: {} };
    if (options.path.startsWith("/api/qq/avatar")) return { data: {} };
    return { data: {} };
  };
  const sandbox = {
    window: {
      aerie: {
        api: {
          request: apiRequest,
          onMessage(handler) {
            ipcHandlers.push(handler);
          },
        },
        sse: {
          subscribe(handler) {
            sseHandlers.push(handler);
            return () => {};
          },
        },
        electron: {},
      },
      localStorage: createLocalStorage(),
      matchMedia(query) {
        return {
          media: query,
          matches: matchMediaMatches,
          addEventListener() {},
          removeEventListener() {},
          addListener() {},
          removeListener() {},
        };
      },
      addEventListener() {},
      dispatchEvent() {},
      innerWidth: 1280,
      ChatUploader: null,
      ChatVoice: null,
      marked: null,
      DOMPurify: null,
      hljs: null,
    },
    document,
    console,
    alert() {},
    confirm() { return true; },
    navigator: { clipboard: { writeText: async () => {} } },
    setInterval(fn, ms) {
      intervals.push({ fn, ms });
      return intervals.length;
    },
    setTimeout(fn) {
      fn();
      return 1;
    },
    clearInterval() {},
    clearTimeout() {},
    Date,
    Promise,
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "renderer", "js", "chat.js"),
    "utf8",
  );
  vm.runInNewContext(`${source}\nwindow.ChatManager = ChatManager;`, sandbox);

  if (stubSideEffects) {
    const proto = sandbox.window.ChatManager.prototype;
    proto._listenIPC = function noop() {};
    proto._listenOpenTab = function noop() {};
    proto._startPoll = function noop() {};
    proto.loadHistory = async function noop() {};
    proto._loadPersona = async function noop() {};
    proto._loadMasterAvatar = async function noop() {};
    proto._refreshAvatarsInDom = function noop() {};
  }

  return {
    ChatManager: sandbox.window.ChatManager,
    sandbox,
    document,
    calls,
    intervals,
    ipcHandlers,
    sseHandlers,
  };
}

function createManager(options = {}) {
  const loaded = loadChatModule(options);
  const manager = new loaded.ChatManager({ masterQQ: 7001 });
  return { ...loaded, manager };
}

test("three rapid sends issue three POST requests without a global loading lock", async () => {
  const pending = [];
  const { manager, document, calls } = createManager({
    request(options) {
      if (options.path !== "/api/chat/send") return { data: {} };
      const waiter = deferred();
      pending.push(waiter);
      return waiter.promise;
    },
  });

  const input = document.getElementById("chat-input");
  const sends = [];
  try {
    input.value = "one";
    sends.push(manager.send());
    input.value = "two";
    sends.push(manager.send());
    input.value = "three";
    sends.push(manager.send());

    assert.equal(
      calls.filter((call) => call.path === "/api/chat/send").length,
      3,
    );
  } finally {
    pending.forEach((waiter, index) => waiter.resolve({
      status: 202,
      data: {
        request_id: `req_${index + 1}`,
        conversation_id: "conv_1",
        turn_id: `turn_${index + 1}`,
        status: "queued",
      },
    }));
    await Promise.allSettled(sends.filter(Boolean));
  }
});

test("client id is rebound to request id after each 202", async () => {
  const { manager, document } = createManager({
    request(options) {
      if (options.path !== "/api/chat/send") return { data: {} };
      return {
        status: 202,
        data: {
          request_id: "req_rebound",
          conversation_id: "conv_rebound",
          turn_id: "turn_rebound",
          status: "queued",
        },
      };
    },
  });

  document.getElementById("chat-input").value = "queue me";
  await manager.send();

  assert.ok(manager._requests.has("req_rebound"));
  assert.ok(Array.from(manager._clientToRequest.values()).includes("req_rebound"));
  assert.equal(manager._requests.get("req_rebound").status, "queued");
});

test("request map tracks queued running cancelling failed cancelled completed", () => {
  const { manager } = createManager();
  const statuses = ["queued", "running", "cancelling", "failed", "cancelled", "completed"];

  for (const status of statuses) {
    manager._ingestChatSignal({
      event_id: `evt_${status}`,
      request_id: "req_track",
      conversation_id: "conv_track",
      turn_id: "turn_track",
      status,
    }, "test");
  }

  const state = manager._requests.get("req_track");
  assert.equal(state.status, "completed");
  assert.deepEqual(Array.from(state.statusHistory), statuses);
});

test("cancel and retry call request-scoped endpoints", async () => {
  const { manager, calls } = createManager({
    request(options) {
      if (options.path.endsWith("/cancel")) {
        return { data: { request_id: "req_cancel", status: "cancelled" } };
      }
      if (options.path.endsWith("/retry")) {
        return { status: 202, data: { request_id: "req_retry", status: "queued" } };
      }
      return { data: {} };
    },
  });

  manager._upsertRequestState({ request_id: "req_cancel", status: "running" });
  manager._upsertRequestState({ request_id: "req_failed", status: "failed" });

  await manager.cancelRequest("req_cancel");
  await manager.retryRequest("req_failed");

  assert.equal(calls.at(-2).path, "/api/chat/requests/req_cancel/cancel");
  assert.equal(calls.at(-1).path, "/api/chat/requests/req_failed/retry");
  assert.equal(manager._requests.get("req_cancel").status, "cancelled");
  assert.equal(manager._requests.get("req_retry").status, "queued");
});

test("ipc sse and poll share one ingest path", async () => {
  const loaded = loadChatModule({
    stubSideEffects: false,
    request(options) {
      if (options.path.startsWith("/api/chat/poll")) {
        return { data: { items: [{ id: 7, role: "assistant", content: "poll" }] } };
      }
      if (options.path.startsWith("/api/chat/history")) return { data: { history: [] } };
      return { data: {} };
    },
  });
  const transports = [];
  loaded.ChatManager.prototype._ingestChatSignal = function ingest(signal, transport) {
    transports.push({ signal, transport });
  };
  new loaded.ChatManager({ masterQQ: 7001 });

  loaded.ipcHandlers[0]({ id: 1, role: "assistant", content: "ipc" });
  loaded.sseHandlers[0]({ data: JSON.stringify({ id: 2, role: "assistant", content: "sse" }) });
  await loaded.intervals.find((item) => item.ms === 3000).fn();

  assert.deepEqual(
    transports.map((item) => item.transport),
    ["ipc", "sse", "poll"],
  );
});

test("event_id deduplicates across transports", () => {
  const { manager } = createManager();
  const rendered = [];
  manager._render = (msg) => rendered.push(msg);

  manager._ingestChatSignal({
    event_id: "evt_once",
    id: 10,
    role: "assistant",
    content: "first",
  }, "ipc");
  manager._ingestChatSignal({
    event_id: "evt_once",
    id: 11,
    role: "assistant",
    content: "duplicate",
  }, "sse");

  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].content, "first");
});

test("request sequence buffers out-of-order events", () => {
  const { manager } = createManager();

  manager._ingestChatSignal({
    event_id: "evt_seq_2",
    request_id: "req_sequence",
    sequence: 2,
    status: "completed",
  }, "sse");
  assert.equal(manager._requests.has("req_sequence"), false);

  manager._ingestChatSignal({
    event_id: "evt_seq_1",
    request_id: "req_sequence",
    sequence: 1,
    status: "running",
  }, "sse");

  const state = manager._requests.get("req_sequence");
  assert.deepEqual(Array.from(state.statusHistory), ["running", "completed"]);
});

test("terminal request status after message sequences is applied", () => {
  const { manager } = createManager();

  manager._ingestChatSignal({
    event_id: "evt_terminal_0",
    type: "chat_request_running",
    request_id: "req_terminal_after_messages",
    sequence: 0,
    status: "running",
  }, "sse");
  manager._ingestChatSignal({
    event_id: "evt_terminal_1",
    request_id: "req_terminal_after_messages",
    sequence: 1,
    id: 101,
    role: "user",
    content: "queued user",
  }, "sse");
  manager._ingestChatSignal({
    event_id: "evt_terminal_2",
    request_id: "req_terminal_after_messages",
    sequence: 2,
    id: 102,
    role: "assistant",
    content: "queued assistant",
  }, "sse");
  manager._ingestChatSignal({
    event_id: "evt_terminal_3",
    type: "chat_request_completed",
    request_id: "req_terminal_after_messages",
    sequence: 3,
    status: "completed",
  }, "sse");

  const topLevel = Array.from(manager._el.messages.children);
  const roles = topLevel.map((node) => {
    if (node.className.includes("chat-msg--assistant")) return "assistant";
    if (node.className.includes("chat-msg--user")) return "user";
    return "other";
  });

  assert.equal(topLevel.length, 2);
  assert.deepEqual(roles.sort(), ["assistant", "user"]);
  assert.ok(topLevel.every((node) => !node.className.includes("chat-msg--typing")));
  assert.ok(topLevel.some((node) => node.innerHTML.includes("queued user")));
  assert.ok(topLevel.some((node) => node.innerHTML.includes("queued assistant")));
  assert.deepEqual(
    Array.from(manager._requests.get("req_terminal_after_messages").statusHistory),
    ["running", "completed"],
  );
  assert.equal(
    manager._requests.get("req_terminal_after_messages").status,
    "completed",
  );
});

test("legacy numeric message ids remain compatible", () => {
  const { manager } = createManager();
  const rendered = [];
  manager._render = (msg) => rendered.push(msg);

  manager._ingestChatSignal({ id: 42, role: "assistant", content: "once" }, "poll");
  manager._ingestChatSignal({ id: 42, role: "assistant", content: "duplicate" }, "ipc");

  assert.equal(rendered.length, 1);
  assert.equal(manager._sinceId, 42);
});

test("page restore queries non-terminal request statuses", async () => {
  const { manager, sandbox, calls } = createManager({
    request(options) {
      if (options.path.includes("/api/chat/requests/req_restore_1")) {
        return { data: { request_id: "req_restore_1", status: "completed" } };
      }
      if (options.path.includes("/api/chat/requests/req_restore_2")) {
        return { data: { request_id: "req_restore_2", status: "running" } };
      }
      return { data: {} };
    },
  });
  sandbox.window.localStorage.setItem(
    "aerie.chat.pending_requests",
    JSON.stringify(["req_restore_1", "req_restore_2"]),
  );

  await manager.restorePendingRequests();

  assert.deepEqual(
    calls
      .map((call) => call.path)
      .filter((pathName) => pathName.startsWith("/api/chat/requests/")),
    [
      "/api/chat/requests/req_restore_1",
      "/api/chat/requests/req_restore_2",
    ],
  );
  assert.equal(manager._requests.get("req_restore_1").status, "completed");
  assert.equal(manager._requests.get("req_restore_2").status, "running");
});

test("sse disconnect is best effort and status polling recovers truth", async () => {
  const { manager, calls } = createManager({
    request(options) {
      if (options.path === "/api/chat/requests/req_sse") {
        return { data: { request_id: "req_sse", status: "completed" } };
      }
      return { data: {} };
    },
  });
  manager._upsertRequestState({ request_id: "req_sse", status: "running" });

  manager._handleSSEDisconnect(new Error("network down"));
  assert.equal(manager._requests.get("req_sse").status, "running");

  await manager.restorePendingRequests();

  assert.equal(calls.at(-1).path, "/api/chat/requests/req_sse");
  assert.equal(manager._requests.get("req_sse").status, "completed");
});

test("request-scoped user bubbles are rebound in place instead of duplicating", () => {
  const { manager } = createManager();

  manager._render({
    id: "client_user_phase7",
    role: "user",
    content: "我想继续",
  });
  manager._bindClientRequest("client_user_phase7", {
    request_id: "req_user_phase7",
    conversation_id: "conv_user_phase7",
    turn_id: "turn_user_phase7",
    status: "queued",
  });

  manager._ingestChatSignal({
    event_id: "evt_user_phase7",
    request_id: "req_user_phase7",
    sequence: 1,
    id: 901,
    role: "user",
    content: "我想继续",
    source: "local",
  }, "sse");

  const users = manager._el.messages.children.filter((node) =>
    node.className.includes("chat-msg--user")
  );
  assert.equal(users.length, 1);
  assert.equal(users[0].getAttribute("data-id"), "901");
});

test("running request shows typing bubble then preserves assistant bubble order", () => {
  const { manager } = createManager();

  manager._render({
    id: "client_phase7",
    role: "user",
    content: "帮我拆两段",
  });
  manager._bindClientRequest("client_phase7", {
    request_id: "req_phase7",
    conversation_id: "conv_phase7",
    turn_id: "turn_phase7",
    status: "queued",
  });

  manager._ingestChatSignal({
    event_id: "evt_phase7_running",
    type: "chat_request_running",
    request_id: "req_phase7",
    sequence: 0,
    status: "running",
  }, "sse");

  assert.ok(
    manager._el.messages.children.some((node) =>
      node.className.includes("chat-msg--typing"),
    ),
  );

  manager._ingestChatSignal({
    event_id: "evt_phase7_seg_1",
    request_id: "req_phase7",
    sequence: 1,
    id: 1001,
    role: "assistant",
    content: "第一段",
    source: "local",
  }, "sse");

  manager._ingestChatSignal({
    event_id: "evt_phase7_seg_2",
    request_id: "req_phase7",
    sequence: 2,
    id: 1002,
    role: "assistant",
    content: "第二段",
    source: "local",
  }, "sse");

  const topLevel = manager._el.messages.children;
  const assistantNodes = topLevel.filter((node) =>
    node.className.includes("chat-msg--assistant") &&
    !node.className.includes("chat-msg--typing"),
  );
  const typingNodes = topLevel.filter((node) =>
    node.className.includes("chat-msg--typing"),
  );
  assert.equal(assistantNodes.length, 2);
  assert.equal(typingNodes.length, 1);
  assert.ok(assistantNodes[0].innerHTML.includes("第一段"));
  assert.ok(assistantNodes[1].innerHTML.includes("第二段"));
  assert.ok(topLevel[assistantNodes.length + 1].className.includes("chat-msg--typing"));

  manager._ingestChatSignal({
    event_id: "evt_phase7_done",
    type: "chat_request_completed",
    request_id: "req_phase7",
    sequence: 3,
    status: "completed",
  }, "sse");

  assert.equal(
    manager._el.messages.children.filter((node) =>
      node.className.includes("chat-msg--typing"),
    ).length,
    0,
  );
});

test("reduced motion typing bubble renders static label without animated dots", () => {
  const { manager } = createManager({ matchMediaMatches: true });

  manager._upsertRequestState({
    request_id: "req_reduce",
    conversation_id: "conv_reduce",
    turn_id: "turn_reduce",
    status: "running",
  });

  const typingNode = manager._el.messages.children.find((node) =>
    node.className.includes("chat-msg--typing"),
  );
  assert.ok(typingNode);
  assert.ok(typingNode.className.includes("chat-msg--typing--reduced"));
  assert.ok(typingNode.innerHTML.includes("chat-typing-indicator__label"));
  assert.ok(!typingNode.innerHTML.includes("chat-typing-indicator__dot"));
});

test("cancelled request clears typing bubble", () => {
  const { manager } = createManager();

  manager._upsertRequestState({
    request_id: "req_cancel_phase7",
    conversation_id: "conv_cancel_phase7",
    turn_id: "turn_cancel_phase7",
    status: "running",
  });
  assert.equal(
    manager._el.messages.children.filter((node) =>
      node.className.includes("chat-msg--typing"),
    ).length,
    1,
  );

  manager._upsertRequestState({
    request_id: "req_cancel_phase7",
    conversation_id: "conv_cancel_phase7",
    turn_id: "turn_cancel_phase7",
    status: "cancelled",
  });
  assert.equal(
    manager._el.messages.children.filter((node) =>
      node.className.includes("chat-msg--typing"),
    ).length,
    0,
  );
});

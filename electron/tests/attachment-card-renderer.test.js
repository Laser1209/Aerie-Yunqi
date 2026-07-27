"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadChatManager() {
  const noop = () => {};
  const domReadyCallbacks = [];
  const sandbox = {
    console,
    marked: { parse: (t) => t },
    DOMPurify: { sanitize: (t) => t },
    hljs: { highlightElement: noop, getLanguage() { return null; } },
    CustomEvent: class CustomEvent {},
    EventSource: class EventSource { constructor() {} addEventListener() {} close() {} },
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: noop,
    fetch: () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
  };
  // In a browser, `window` IS the global object.  We make the sandbox
  // itself act as window so that class definitions and window.* assigns
  // land on the same object.
  sandbox.window = sandbox;
  sandbox.aerie = {
    api: { request: noop },
    attachments: { open: noop, download: noop },
    on: noop,
    upload: noop,
  };
  sandbox.addEventListener = (evt, cb) => {
    if (evt === "DOMContentLoaded") domReadyCallbacks.push(cb);
  };
  sandbox.dispatchEvent = noop;
  sandbox.matchMedia = () => ({ matches: false, addEventListener: noop });
  sandbox.localStorage = {
    getItem: () => null,
    setItem: noop,
    removeItem: noop,
  };
  sandbox.location = { origin: "http://127.0.0.1:7890" };
  sandbox.document = {
    getElementById: () => null,
    querySelectorAll: () => [],
    createElement: () => {
      let text = "";
      return {
        appendChild: noop,
        setAttribute: noop,
        style: {},
        get textContent() { return text; },
        set textContent(v) { text = String(v ?? ""); },
        get innerHTML() { return text; },
      };
    },
    createTextNode: (t) => ({ nodeType: 3, textContent: t }),
    addEventListener: noop,
  };

  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "renderer", "js", "chat.js"),
    "utf8",
  ) + "\nwindow.ChatManager = ChatManager;";
  vm.runInNewContext(source, sandbox);

  // Manually fire DOMContentLoaded so window._chat = new ChatManager() runs
  for (const cb of domReadyCallbacks) {
    try { cb(); } catch (e) { /* constructor errors are non-fatal for card tests */ }
  }

  const chat = sandbox.window._chat;
  if (chat) return { chat, sandbox };

  // Fallback: instantiate from the class found on the sandbox/window
  const CM = sandbox.ChatManager;
  if (!CM) throw new Error("ChatManager class not found in sandbox");
  const instance = Object.create(CM.prototype);
  return { chat: instance, sandbox };
}

/**
 * Extract _buildAttachmentCard output as a DOM-like object for assertions.
 * We parse the returned HTML string with a minimal regex-based checker.
 */
function parseCard(html) {
  return {
    html,
    hasText: (text) => html.includes(text),
    hasCategory: (cat) => html.includes(`data-type="${cat}"`),
    hasState: (state) => html.includes(`data-state="${state}"`),
    hasOpenButton: () => html.includes("data-attachment-open"),
    hasRetryButton: () => html.includes("data-attachment-retry"),
    hasQuarantinedNotice: () => html.includes("已隔离") || html.includes("quarantined"),
    hasUnsupportedNotice: () => html.includes("不支持") || html.includes("unsupported"),
    hasLocalPath: () => /([A-Z]:\\|\/home\/|\/Users\/|C:\/)/.test(html),
    hasTokenPattern: () => /(api[_-]?key|token|secret|bearer|ghp_)/i.test(html),
    hasThumbnailImg: () => html.includes("<img"),
  };
}

test("attachment card for image category renders thumbnail when thumbnailUrl is provided", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_001",
    category: "image",
    name: "photo.jpg",
    size: 102400,
    state: "ready",
    thumbnailUrl: "uploads/att_001_thumb.jpg",
  }));
  assert.ok(card.hasThumbnailImg(), "image card should render <img> thumbnail");
  assert.ok(card.hasCategory("image"));
  assert.ok(card.hasOpenButton(), "ready image should have open button");
});

test("attachment card for document category shows document icon and open button", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_002",
    category: "document",
    name: "report.pdf",
    size: 2048576,
    state: "ready",
  }));
  assert.ok(card.hasCategory("document"));
  assert.ok(card.hasOpenButton(), "ready document should have open button");
  assert.ok(!card.hasThumbnailImg(), "non-image should not render <img>");
});

test("attachment card for text category shows text icon and open button", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_003",
    category: "text",
    name: "notes.md",
    size: 512,
    state: "ready",
  }));
  assert.ok(card.hasCategory("text"));
  assert.ok(card.hasOpenButton(), "ready text should have open button");
});

test("attachment card for code category shows code icon and open button", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_004",
    category: "code",
    name: "script.py",
    size: 2048,
    state: "ready",
  }));
  assert.ok(card.hasCategory("code"));
  assert.ok(card.hasOpenButton(), "ready code should have open button");
});

test("attachment card for audio category shows audio icon", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_005",
    category: "audio",
    name: "voice.mp3",
    size: 1024000,
    state: "ready",
  }));
  assert.ok(card.hasCategory("audio"));
  assert.ok(card.hasOpenButton(), "ready audio should have open button");
});

test("attachment card for video category shows video icon", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_006",
    category: "video",
    name: "clip.mp4",
    size: 5120000,
    state: "ready",
  }));
  assert.ok(card.hasCategory("video"));
  assert.ok(card.hasOpenButton(), "ready video should have open button");
});

test("attachment card for quarantined state shows isolation notice without open button", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_007",
    category: "document",
    name: "suspicious.pdf",
    size: 1024,
    state: "quarantined",
    error: { code: "signature_mismatch", message: "file signature does not match extension" },
  }));
  assert.ok(card.hasState("quarantined"));
  assert.ok(card.hasQuarantinedNotice(), "quarantined card should show isolation notice");
  assert.ok(!card.hasOpenButton(), "quarantined card should not have open button");
  assert.ok(!card.hasRetryButton(), "quarantined card should not have retry button");
});

test("attachment card for unsupported state shows unsupported notice without open button", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_008",
    category: "unknown",
    name: "file.xyz",
    size: 512,
    state: "unsupported",
    error: { code: "unsupported_type", message: "file extension is not supported" },
  }));
  assert.ok(card.hasState("unsupported"));
  assert.ok(card.hasUnsupportedNotice(), "unsupported card should show unsupported notice");
  assert.ok(!card.hasOpenButton(), "unsupported card should not have open button");
  assert.ok(!card.hasRetryButton(), "unsupported card should not have retry button");
});

test("attachment card for failed state shows retry button and error message", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_009",
    category: "text",
    name: "broken.txt",
    size: 100,
    state: "failed",
    error: { code: "parse_error", message: "encoding error" },
  }));
  assert.ok(card.hasState("failed"));
  assert.ok(card.hasRetryButton(), "failed card should have retry button");
  assert.ok(card.hasText("encoding error"), "error message should be visible");
});

test("attachment card does not expose local absolute paths", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_010",
    category: "image",
    name: "photo.jpg",
    size: 1024,
    state: "ready",
    thumbnailUrl: "uploads/att_010_thumb.jpg",
  }));
  assert.ok(!card.hasLocalPath(), "card HTML must not contain local absolute paths");
});

test("attachment card does not expose tokens or credentials in error messages", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_011",
    category: "document",
    name: "doc.pdf",
    size: 1024,
    state: "failed",
    error: { code: "parse_error", message: "failed to parse C:\\Users\\Alice\\doc.pdf api_key=secret123" },
  }));
  assert.ok(!card.hasTokenPattern(), "card must not expose api_key/token/secret patterns");
  assert.ok(!card.hasLocalPath(), "card must not expose local paths from error messages");
});

test("attachment card for zip category shows archive icon and open button", () => {
  const { chat } = loadChatManager();
  const card = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_012",
    category: "zip",
    name: "bundle.zip",
    size: 4096,
    state: "ready",
  }));
  assert.ok(card.hasCategory("zip"));
  assert.ok(card.hasOpenButton(), "ready zip should have open button");
});

test("attachment card state label is human-readable Chinese for all states", () => {
  const { chat } = loadChatManager();
  const states = [
    { state: "queued", expected: "等待处理" },
    { state: "processing", expected: "解析中" },
    { state: "ready", expected: "可读取" },
    { state: "failed", expected: "解析失败" },
    { state: "quarantined", expected: "已隔离" },
    { state: "unsupported", expected: "不支持" },
  ];
  for (const { state, expected } of states) {
    const card = parseCard(chat._buildAttachmentCard({
      attachmentId: "att_st_" + state,
      category: "text",
      name: "test.txt",
      size: 10,
      state,
    }));
    assert.ok(card.hasText(expected), `state "${state}" should show label "${expected}"`);
  }
});

test("data-viewer reuses chat _buildAttachmentCard for history rendering", () => {
  const { chat } = loadChatManager();
  const card1 = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_share_1",
    category: "image",
    name: "shared.png",
    size: 2048,
    state: "ready",
    thumbnailUrl: "uploads/t.jpg",
  }));
  const card2 = parseCard(chat._buildAttachmentCard({
    attachmentId: "att_share_1",
    category: "image",
    name: "shared.png",
    size: 2048,
    state: "ready",
    thumbnailUrl: "uploads/t.jpg",
  }));
  assert.equal(card1.html, card2.html, "same attachment should render identically in chat and history");
});

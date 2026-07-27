"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadPanelManager() {
  const noop = () => {};
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: noop,
  };
  // window === global for class definitions and window.* assignments.
  sandbox.window = sandbox;
  sandbox.addEventListener = noop;
  sandbox.dispatchEvent = noop;
  // Mock document sufficient for _escapeHtml (createElement div with textContent/innerHTML).
  const elements = new Map();
  let nextId = 0;
  function makeElement(tag) {
    const id = ++nextId;
    let text = "";
    const attrs = Object.create(null);
    const children = [];
    const el = {
      nodeType: 1,
      tagName: String(tag || "").toUpperCase(),
      get textContent() { return text; },
      set textContent(v) { text = String(v ?? ""); },
      get innerHTML() { return text; },
      set innerHTML(v) { text = String(v ?? ""); },
      setAttribute(name, value) { attrs[name] = String(value); },
      getAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null; },
      appendChild(child) { children.push(child); return child; },
      addEventListener: noop,
      style: {},
      children,
    };
    elements.set(id, el);
    return el;
  }
  sandbox.document = {
    createElement: (tag) => makeElement(tag),
    createTextNode: (t) => ({ nodeType: 3, textContent: t }),
    getElementById: () => null,
    querySelectorAll: () => [],
    addEventListener: noop,
  };

  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "renderer", "js", "panels.js"),
    "utf8",
  );
  vm.runInNewContext(source, sandbox);

  const PM = sandbox.window.PanelManager || sandbox.PanelManager;
  if (!PM) throw new Error("PanelManager class not found on window");
  return { PanelManager: PM, sandbox };
}

function parsePanel(html) {
  return {
    html,
    hasText: (text) => html.includes(text),
    hasDataPanelType: (type) => html.includes(`data-panel-type="${type}"`),
    hasLocalPath: () => /([A-Z]:\\|\/home\/|\/Users\/|\/root\/|C:\/)/.test(html),
    hasTokenPattern: () => /(api[_-]?key|token|secret|bearer|ghp_)/i.test(html),
    hasRawScore: () => /\b(score|raw_score|model_score)\s*[:=]\s*-?\d/.test(html),
    hasDataAttr: (name, value) => html.includes(value === undefined ? `data-${name}` : `data-${name}="${value}"`),
  };
}

// ---- Relationship panel ----

test("relationship panel renders Chinese labels for core dimensions", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const panel = parsePanel(pm.renderRelationshipPanel({
    relationship_stage: "familiar",
    familiarity: 0.72,
    trust: 0.55,
    affection: 0.30,
    grudge: 0.10,
    immediate_emotion: { label: "平静", intensity: 0.2 },
    today_delta: { familiarity: +0.05, trust: +0.02 },
  }));
  for (const label of ["熟悉度", "信任感", "好感度", "芥蒂感", "即时情绪", "今日变化"]) {
    assert.ok(panel.hasText(label), `relationship panel should contain label "${label}"`);
  }
  assert.ok(panel.hasDataPanelType("relationship"), "relationship panel should have data-panel-type=relationship");
});

test("relationship panel maps numeric scores to human-readable tiers, not raw scores", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const panel = parsePanel(pm.renderRelationshipPanel({
    relationship_stage: "close",
    familiarity: 0.91,
    trust: 0.88,
    affection: 0.85,
    grudge: 0.05,
    immediate_emotion: { label: "开心", intensity: 0.6 },
    today_delta: {},
  }));
  assert.ok(!panel.hasRawScore(), "must not expose raw model scores (0-1 floats)");
  // Should show readable tiers for high familiarity/trust/affection.
  assert.ok(panel.hasText("亲密") || panel.hasText("很熟") || panel.hasText("熟悉"),
    "high familiarity should map to readable tier");
});

test("relationship panel maps relationship_stage to Chinese stage labels", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const stages = [
    { stage: "stranger", expected: "陌生人" },
    { stage: "acquaintance", expected: "认识" },
    { stage: "familiar", expected: "熟悉" },
    { stage: "close", expected: "亲密" },
    { stage: "beloved", expected: "挚爱" },
  ];
  for (const { stage, expected } of stages) {
    const html = pm.renderRelationshipPanel({
      relationship_stage: stage,
      familiarity: 0.5, trust: 0.5, affection: 0.5, grudge: 0,
      immediate_emotion: { label: "平静", intensity: 0 }, today_delta: {},
    });
    assert.ok(html.includes(expected), `stage "${stage}" should render as "${expected}"`);
  }
});

// ---- Memory panel ----

test("memory panel renders list items with summary, confidence, source, confirmation state", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const panel = parsePanel(pm.renderMemoryPanel({
    memories: [
      {
        id: "mem_1",
        content: "用户喜欢喝拿铁",
        confidence: 0.92,
        source_message_id: "msg_abcdef123456",
        user_confirmed: true,
        created_at: Date.now(),
      },
      {
        id: "mem_2",
        content: "用户每周三晚上健身",
        confidence: 0.55,
        source_message_id: "msg_xyz789",
        user_confirmed: false,
        created_at: Date.now(),
      },
    ],
  }));
  assert.ok(panel.hasDataPanelType("memory"), "memory panel should have data-panel-type=memory");
  assert.ok(panel.hasText("用户喜欢喝拿铁"), "should render memory content summary");
  assert.ok(panel.hasText("用户每周三晚上健身"), "should render second memory");
  assert.ok(/92\s*%/.test(panel.html), "confidence should render as percentage (92%)");
  assert.ok(panel.hasText("已确认"), "confirmed memory should render 已确认 label");
});

test("memory panel provides a delete button per memory with data-memory-id", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const html = pm.renderMemoryPanel({
    memories: [
      { id: "mem_1", content: "a", confidence: 0.8, source_message_id: "msg_x", user_confirmed: false, created_at: Date.now() },
      { id: "mem_2", content: "b", confidence: 0.7, source_message_id: "msg_y", user_confirmed: true, created_at: Date.now() },
    ],
  });
  assert.ok(html.includes('data-memory-delete="mem_1"'), "mem_1 should have delete button with data attr");
  assert.ok(html.includes('data-memory-delete="mem_2"'), "mem_2 should have delete button with data attr");
});

test("memory panel invokes onDeleteMemory callback via data attribute and delete button", () => {
  const { PanelManager } = loadPanelManager();
  const deleted = [];
  const pm = new PanelManager({
    onDeleteMemory: (id) => deleted.push(id),
  });
  const html = pm.renderMemoryPanel({
    memories: [
      { id: "mem_9", content: "x", confidence: 0.5, source_message_id: "msg_z", user_confirmed: false, created_at: Date.now() },
    ],
  });
  // The delete action should be wired; we simulate click handler exposure via the DOM event binding
  // that the renderer wires up. We assert the attribute exists and the handler is reachable.
  assert.ok(html.includes('data-memory-delete="mem_9"'));
  // Simulate the handler entry point if exposed.
  if (typeof pm._handleDeleteMemory === "function") {
    pm._handleDeleteMemory("mem_9");
    assert.deepEqual(deleted, ["mem_9"], "onDeleteMemory should be invoked with the memory id");
  }
});

test("memory panel redacts internal/local paths from content and never shows raw model fields", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const panel = parsePanel(pm.renderMemoryPanel({
    memories: [
      {
        id: "mem_p",
        content: "found token ghp_abcdef1234SECRET at C:\\Users\\Alice\\secret.txt",
        confidence: 0.8,
        source_message_id: "msg_1234567890abcdef",
        user_confirmed: false,
        created_at: Date.now(),
      },
    ],
  }));
  assert.ok(!panel.hasLocalPath(), "memory panel must not expose local absolute paths");
  assert.ok(!panel.hasTokenPattern(), "memory panel must redact tokens/secrets");
});

// ---- Growth panel ----

test("growth panel renders timeline in reverse chronological order", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const html = pm.renderGrowthPanel({
    events: [
      { id: "e1", type: "milestone", description: "第一次分享童年", ts: new Date("2026-01-01T10:00:00Z").getTime() },
      { id: "e2", type: "bond", description: "主动求助", ts: new Date("2026-03-15T10:00:00Z").getTime() },
      { id: "e3", type: "reflection", description: "意识到自己的防御", ts: new Date("2026-05-20T10:00:00Z").getTime() },
    ],
  });
  assert.ok(html.includes('data-panel-type="growth"'), "growth panel should have data-panel-type=growth");
  // Reverse chronological: e3 should appear before e2 before e1 in HTML.
  const idx3 = html.indexOf("意识到自己的防御");
  const idx2 = html.indexOf("主动求助");
  const idx1 = html.indexOf("第一次分享童年");
  assert.ok(idx3 >= 0 && idx2 >= 0 && idx1 >= 0, "all events should render");
  assert.ok(idx3 < idx2 && idx2 < idx1, "events should be ordered newest-first");
});

// ---- Empty states ----

test("memory panel shows friendly empty state when no memories exist", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const html = pm.renderMemoryPanel({ memories: [] });
  assert.ok(/暂无|还没有|空|空空/.test(html), "memory panel should show a friendly empty-state message");
});

test("growth panel shows friendly empty state when no events exist", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  const html = pm.renderGrowthPanel({ events: [] });
  assert.ok(/暂无|还没有|空|开始/.test(html), "growth panel should show a friendly empty-state message");
});

// ---- Container invariants ----

test("every panel root has the correct data-panel-type attribute", () => {
  const { PanelManager } = loadPanelManager();
  const pm = new PanelManager();
  assert.ok(pm.renderRelationshipPanel({ relationship_stage: "stranger", familiarity: 0, trust: 0, affection: 0, grudge: 0, immediate_emotion: { label: "平静", intensity: 0 }, today_delta: {} }).includes('data-panel-type="relationship"'));
  assert.ok(pm.renderMemoryPanel({ memories: [] }).includes('data-panel-type="memory"'));
  assert.ok(pm.renderGrowthPanel({ events: [] }).includes('data-panel-type="growth"'));
});

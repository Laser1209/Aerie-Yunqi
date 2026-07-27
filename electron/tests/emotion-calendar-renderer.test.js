"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const rendererRoot = path.join(__dirname, "..", "src", "renderer", "js");

function loadRenderer(file, extras = {}) {
  const listeners = {};
  const intervals = [];
  const timeouts = [];
  const document = extras.document || {
    getElementById: () => null,
    querySelectorAll: () => [],
    createElement: () => ({ className: "", textContent: "" }),
  };
  const window = {
    addEventListener: (type, handler) => { listeners[type] = handler; },
    ...extras.window,
  };
  const sandbox = {
    window,
    document,
    console,
    confirm: () => false,
    setInterval: (handler, delay) => {
      const token = { handler, delay, active: true };
      intervals.push(token);
      return token;
    },
    clearInterval: (token) => { if (token) token.active = false; },
    setTimeout: (handler, delay) => {
      const token = { handler, delay, active: true };
      timeouts.push(token);
      return token;
    },
    clearTimeout: (token) => { if (token) token.active = false; },
    Date,
  };
  const source = fs.readFileSync(path.join(rendererRoot, file), "utf8");
  vm.runInNewContext(source, sandbox);
  return { sandbox, window, document, listeners, intervals, timeouts };
}

test("emotion dashboard polls only while visible and starts with waiting state", async () => {
  const requests = [];
  const loaded = loadRenderer("emotion-dashboard.js", {
    window: {
      aerie: {
        api: {
          request: async (request) => {
            requests.push(request.path);
            return { status: 503, data: { error: "backend not ready" } };
          },
        },
      },
    },
  });
  const dashboard = new loaded.window.EmotionDashboard();

  dashboard.init();
  assert.equal(loaded.intervals.length, 0);
  assert.equal(requests.length, 0);

  dashboard.setVisible(true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(loaded.intervals.filter((item) => item.active).length, 2);
  assert.ok(requests.includes("/api/emotion/state"));

  dashboard.setVisible(false);
  assert.equal(loaded.intervals.filter((item) => item.active).length, 0);
});

test("emotion history uses a fixed window and overlays the latest live sample", () => {
  const loaded = loadRenderer("emotion-history.js", {
    window: { aerie: { api: { request: async () => ({ status: 200, data: {} }) } } },
  });
  const history = new loaded.window.EmotionHistory();
  history._window = "1h";
  history._data = {
    serverNow: 7_200_000,
    since_ts: 3_600_000,
    items: [{ ts: 4_000_000, pleasure: 0, arousal: 0, dominance: 0 }],
  };
  history._latestState = {
    sampledAt: 7_100_000,
    pad: { P: 0.4, A: 0.2, D: -0.1 },
    thresholds: { desire: { value: 12 } },
    label: "joy",
  };

  const items = history._mergeLivePoint(history._data.items);
  const bounds = history._timeBounds(items);

  assert.equal(items.length, 2);
  assert.equal(items[1].ts, 7_100_000);
  assert.equal(items[1].pleasure, 0.4);
  assert.equal(items[1].desire_value, 12);
  assert.equal(bounds.t0, 3_600_000);
  assert.equal(bounds.t1, 7_200_000);
});

test("calendar retries cold-start failures and reloads on backend-ready", async () => {
  const requests = [];
  let messageHandler = null;
  const loaded = loadRenderer("calendar-panel.js", {
    window: {
      aerie: {
        api: {
          request: async (request) => {
            requests.push(request.path);
            throw new Error("ECONNREFUSED");
          },
          onMessage: (handler) => { messageHandler = handler; },
        },
      },
    },
  });

  const panel = new loaded.window.CalendarPanel();
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(loaded.timeouts.some((item) => item.active && item.delay > 0));

  const before = requests.length;
  messageHandler({ type: "backend_ready" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(requests.length > before);
  panel.destroy();
});

test("visible data panel refreshes immediately on backend-ready", () => {
  const source = fs.readFileSync(path.join(rendererRoot, "data-viewer.js"), "utf8");
  assert.match(source, /onBackendReady\(\(\) =>/);
  assert.match(source, /if \(this\.visible\) this\.refreshActive\(\)/);
});

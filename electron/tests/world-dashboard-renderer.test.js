"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.value = "";
    this.disabled = false;
    this.className = "";
    this.dataset = {};
    this.listeners = {};
    this._textContent = "";
    this._innerHTML = "";
    this.classList = {
      add: (name) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        values.add(name);
        this.className = Array.from(values).join(" ");
      },
      remove: (name) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        values.delete(name);
        this.className = Array.from(values).join(" ");
      },
      contains: (name) => this.className.split(/\s+/).includes(name),
    };
  }

  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }

  async click() {
    if (this.listeners.click) {
      await this.listeners.click({ preventDefault() {} });
    }
  }

  set textContent(value) {
    this._textContent = String(value);
    this._innerHTML = escapeHtml(value);
  }

  get textContent() {
    return this._textContent;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this._textContent = stripTags(value);
  }

  get innerHTML() {
    return this._innerHTML;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function stripTags(value) {
  return String(value).replace(/<[^>]*>/g, "");
}

function createDocument() {
  const ids = [
    "world-dashboard-status",
    "world-dashboard-visible",
    "world-dashboard-plugin",
    "world-dashboard-backend",
    "world-dashboard-chat-publish",
    "world-dashboard-panels",
    "world-dashboard-errors",
    "world-dashboard-updated",
    "world-dashboard-refresh",
    "world-dashboard-show",
    "world-dashboard-hide",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement(id)]));
  return {
    getElementById(id) {
      return elements.get(id) || null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
    elements,
  };
}

function loadWorldDashboardPanel(worldDashboardApi) {
  const document = createDocument();
  const sandbox = {
    window: {
      aerie: { worldDashboard: worldDashboardApi },
      addEventListener() {},
      dispatchEvent() {},
    },
    document,
    console,
    setTimeout(fn) {
      fn();
      return 1;
    },
    clearTimeout() {},
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "renderer", "js", "world-dashboard.js"),
    "utf8",
  );
  vm.runInNewContext(`${source}\nwindow.WorldDashboardPanel = WorldDashboardPanel;`, sandbox);
  return {
    panel: new sandbox.window.WorldDashboardPanel(),
    document,
    sandbox,
  };
}

function readRendererSource(relativePath) {
  return fs.readFileSync(
    path.join(__dirname, "..", "src", "renderer", ...relativePath.split("/")),
    "utf8",
  );
}

test("index wires a real world dashboard tab panel and renderer script", () => {
  const index = readRendererSource("index.html");

  assert.match(index, /class="sidebar-tab"[^>]+data-tab="world-dashboard"/);
  assert.match(index, /id="panel-world-dashboard"[^>]+class="tab-panel"/);
  assert.match(index, /src="js\/world-dashboard\.js"/);
  assert.match(index, /href="styles\/world-dashboard\.css"/);

  const rendererSources = [
    index,
    fs.existsSync(path.join(__dirname, "..", "src", "renderer", "js", "world-dashboard.js"))
      ? readRendererSource("js/world-dashboard.js")
      : "",
  ].join("\n");
  assert.doesNotMatch(rendererSources, /world-dashboard:raw/);
});

test("world dashboard renderer uses narrow preload API and redacted display", async () => {
  const calls = [];
  const { panel, document } = loadWorldDashboardPanel({
    async getStatus() {
      calls.push(["getStatus"]);
      return {
        status: "ready",
        visible: true,
        plugin: {
          pluginId: "aerie.world",
          state: "running",
          crashCount: 0,
          configKeys: ["apiKey"],
          hiddenValue: "redacted-token-should-not-render",
        },
        backend: { status: "healthy", secretValue: "redacted-token-should-not-render" },
        panels: ["world_summary", "image_candidates", "creative_workshop"],
        errors: [],
        chatPublishAvailable: true,
        updatedAt: 1760000000000,
      };
    },
    async show() {
      calls.push(["show"]);
      return this.getStatus();
    },
    async hide() {
      calls.push(["hide"]);
      return { status: "hidden", visible: false, plugin: {}, backend: {}, panels: [] };
    },
  });

  await panel.init();
  await panel.refresh();

  assert.equal(document.getElementById("world-dashboard-status").textContent, "ready");
  assert.equal(document.getElementById("world-dashboard-plugin").textContent, "aerie.world · running · crashes 0");
  assert.equal(document.getElementById("world-dashboard-chat-publish").textContent, "available");
  assert.deepEqual(calls.map((call) => call[0]), ["getStatus"]);

  const rendered = Array.from(document.elements.values())
    .map((element) => `${element.textContent}\n${element.innerHTML}`)
    .join("\n");
  assert.doesNotMatch(rendered, /redacted-token/);
});

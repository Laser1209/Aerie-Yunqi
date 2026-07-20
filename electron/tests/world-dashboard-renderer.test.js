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
    "world-dashboard-summary",
    "world-dashboard-relationship",
    "world-dashboard-timeline",
    "world-dashboard-candidates",
    "world-dashboard-refresh",
    "world-dashboard-show",
    "world-dashboard-hide",
    "world-candidate-id",
    "world-candidate-action",
    "world-candidate-reason",
    "world-candidate-idempotency",
    "world-candidate-result",
    "world-candidate-approve",
    "world-creative-kind",
    "world-creative-title",
    "world-creative-payload",
    "world-creative-result",
    "world-creative-preview",
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
  assert.match(index, /id="world-dashboard-summary"/);
  assert.match(index, /id="world-dashboard-relationship"/);
  assert.match(index, /id="world-dashboard-timeline"/);
  assert.match(index, /id="world-dashboard-candidates"/);
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
    async getSnapshot() {
      calls.push(["getSnapshot"]);
      return {
        status: "ready",
        worldSummary: {
          status: "running",
          phase: "evening",
          location: "studio",
          activity: "drawing",
          rawPrompt: "redacted-token-should-not-render",
        },
        relationshipState: {
          persona_id: "default",
          warmth: 0.73,
          summary: "stable",
          secret: "redacted-token-should-not-render",
        },
        selfModel: {
          mood: "focused",
          energy: 0.62,
          rawThought: "redacted-token-should-not-render",
        },
        actionTimeline: [
          {
            eventId: "evt-1",
            topic: "observations",
            eventType: "world.observation.recorded",
            sequence: 1,
            payload: { secret: "redacted-token-should-not-render" },
          },
        ],
        imageCandidates: [
          {
            candidateId: "cand-1",
            promptKey: "evening_home",
            scene: "idle_care",
            rawPrompt: "redacted-token-should-not-render",
          },
        ],
      };
    },
    async hide() {
      calls.push(["hide"]);
      return { status: "hidden", visible: false, plugin: {}, backend: {}, panels: [] };
    },
    async approveCandidate(payload) {
      calls.push(["approveCandidate", payload]);
      return { status: "submitted", candidateId: payload.candidateId, ack: true };
    },
    async previewCreative(payload) {
      calls.push(["previewCreative", payload]);
      return {
        status: "preview",
        draft: {
          kind: payload.kind,
          title: payload.title,
          payloadKeys: Object.keys(payload.payload || {}).sort(),
          payloadSha256: "digest-only",
        },
      };
    },
  });

  await panel.init();
  await panel.refresh();

  assert.equal(document.getElementById("world-dashboard-status").textContent, "ready");
  assert.equal(document.getElementById("world-dashboard-plugin").textContent, "aerie.world · running · crashes 0");
  assert.equal(document.getElementById("world-dashboard-chat-publish").textContent, "available");
  assert.equal(document.getElementById("world-dashboard-summary").textContent, "running · evening · studio · drawing");
  assert.equal(document.getElementById("world-dashboard-relationship").textContent, "default · warmth 0.73 · stable");
  assert.equal(document.getElementById("world-dashboard-timeline").textContent, "1 · observations · world.observation.recorded");
  assert.equal(document.getElementById("world-dashboard-candidates").textContent, "cand-1 · evening_home · idle_care");

  document.getElementById("world-candidate-id").value = "cand-1";
  document.getElementById("world-candidate-action").value = "approve";
  document.getElementById("world-candidate-reason").value = "manual_ok";
  document.getElementById("world-candidate-idempotency").value = "idem-1";
  await document.getElementById("world-candidate-approve").click();

  assert.equal(
    JSON.stringify(calls.find((call) => call[0] === "approveCandidate")[1]),
    JSON.stringify({
      candidateId: "cand-1",
      action: "approve",
      reasonCode: "manual_ok",
      idempotencyKey: "idem-1",
    }),
  );
  assert.equal(document.getElementById("world-candidate-result").textContent, "submitted · cand-1 · ack");

  document.getElementById("world-creative-kind").value = "world_note";
  document.getElementById("world-creative-title").value = "晨间世界摘要";
  document.getElementById("world-creative-payload").value = '{"scene":"morning","secret":"redacted-token-should-not-render"}';
  await document.getElementById("world-creative-preview").click();

  const previewPayload = calls.find((call) => call[0] === "previewCreative")[1];
  assert.equal(
    JSON.stringify(previewPayload),
    JSON.stringify({
      kind: "world_note",
      title: "晨间世界摘要",
      payload: { scene: "morning", secret: "redacted-token-should-not-render" },
    }),
  );
  assert.equal(
    document.getElementById("world-creative-result").textContent,
    "preview · world_note · 晨间世界摘要 · digest-only · keys: scene, secret",
  );

  const rendered = Array.from(document.elements.values())
    .map((element) => `${element.textContent}\n${element.innerHTML}`)
    .join("\n");
  assert.doesNotMatch(rendered, /redacted-token/);
});

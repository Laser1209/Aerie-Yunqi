"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const rendererRoot = path.join(__dirname, "..", "src", "renderer");
const html = fs.readFileSync(path.join(rendererRoot, "index.html"), "utf8");
const preloadSource = fs.readFileSync(path.join(__dirname, "..", "src", "preload.js"), "utf8");
const mainSource = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

function loadPanelModule() {
  const sandbox = {
    window: {},
    document: { getElementById: () => null, querySelectorAll: () => [] },
    setInterval: () => 0,
    clearInterval: () => {},
    CustomEvent: class CustomEvent {},
  };
  sandbox.window.addEventListener = () => {};
  sandbox.window.dispatchEvent = () => {};
  const source = fs.readFileSync(
    path.join(rendererRoot, "js", "external-connections-panel.js"),
    "utf8",
  );
  vm.runInNewContext(source, sandbox);
  return sandbox.window.ExternalConnectionsPanel;
}

test("system status exposes one external connections region with QQ and WeChat children", () => {
  assert.match(html, /外部连接 · External Connections/);
  assert.doesNotMatch(html, />QQ 运维</);
  assert.match(html, /id="external-connections-toggle"[^>]*aria-expanded="true"[^>]*aria-controls="external-connections-body"/);
  assert.match(html, /id="external-channel-qq-toggle"[^>]*aria-controls="external-channel-qq-body"/);
  assert.match(html, /id="external-channel-ilink-toggle"[^>]*aria-controls="external-channel-ilink-body"/);
  assert.match(html, /微信 Claw/);
  assert.match(html, /name="proactive-primary-channel" value="desktop"/);
  assert.match(html, /name="proactive-primary-channel" value="qq"/);
  assert.match(html, /name="proactive-primary-channel" value="ilink"/);
});

test("external connection aggregation prioritizes errors and counts connected channels", () => {
  const Panel = loadPanelModule();
  assert.deepEqual(
    { ...Panel.aggregateStatuses({ phase: "connected" }, { phase: "idle" }) },
    { connected: 1, total: 2, errors: 0, text: "1/2 已连接", phase: "partial" },
  );
  assert.deepEqual(
    { ...Panel.aggregateStatuses({ phase: "connected" }, { phase: "error" }) },
    { connected: 1, total: 2, errors: 1, text: "1 个异常", phase: "error" },
  );
});

test("external connection panel keeps polling mock-safe when iLink bridge is unavailable", async () => {
  const Panel = loadPanelModule();
  const panel = new Panel({ bridge: {} });
  const status = await panel.readILinkStatus();
  assert.equal(status.phase, "disabled");
  assert.equal(status.mockSafe, true);
});

test("iLink bridge exposes only controlled status and lifecycle operations", () => {
  for (const method of ["getStatus", "start", "stop"]) {
    assert.match(preloadSource, new RegExp(`${method}: \\(\\) => ipcRenderer\\.invoke\\("ilinkGateway:${method}"\\)`));
  }
  assert.match(mainSource, /ipcMain\.handle\("ilinkGateway:getStatus"/);
  assert.match(mainSource, /path: "\/api\/ilink\/status"/);
  assert.match(mainSource, /ipcMain\.handle\("ilinkGateway:start"/);
  assert.match(mainSource, /path: "\/api\/ilink\/start"/);
  assert.match(mainSource, /ipcMain\.handle\("ilinkGateway:stop"/);
  assert.match(mainSource, /path: "\/api\/ilink\/stop"/);
});

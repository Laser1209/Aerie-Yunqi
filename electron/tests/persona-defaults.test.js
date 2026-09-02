"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rendererRoot = path.join(__dirname, "..", "src", "renderer");
const html = fs.readFileSync(path.join(rendererRoot, "dynamic-island.html"), "utf8");
const js = fs.readFileSync(path.join(rendererRoot, "js", "dynamic-island.js"), "utf8");

test("dynamic island uses neutral defaults and active persona data", () => {
  assert.match(html, /Aerie Companion 就绪/);
  assert.match(html, /id="di-companion-name">Aerie Companion</);
  assert.match(html, /Aerie Companion 灵动岛面板/);
  assert.doesNotMatch(html, /云栖在你身边|云栖 · 浮屿|云栖灵动岛|云栖头像/);
  assert.match(js, /path: "\/api\/persona"/);
  assert.match(js, /case "persona:changed"/);
  assert.match(js, /escapeHtml\(uiState\.companion\.name/);
  assert.doesNotMatch(js, /简报由云栖/);
});

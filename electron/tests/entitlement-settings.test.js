"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rendererRoot = path.join(__dirname, "..", "src", "renderer");
const html = fs.readFileSync(path.join(rendererRoot, "index.html"), "utf8");
const settings = fs.readFileSync(path.join(rendererRoot, "js", "settings.js"), "utf8");

test("settings exposes software and hosted API billing boundaries", () => {
  assert.match(html, /id="settings-entitlement-card"/);
  assert.match(html, /方案与用量/);
  assert.match(html, /软件订阅与第三方 API 费用分开/);
  assert.match(settings, /path: "\/api\/billing\/entitlement"/);
  assert.match(settings, /monthly_software_cents/);
  assert.match(settings, /cloud_calls_month/);
  assert.match(settings, /cloud_tokens_month/);
});

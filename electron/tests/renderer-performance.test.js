"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rendererJs = (name) => fs.readFileSync(
  path.join(__dirname, "..", "src", "renderer", "js", name),
  "utf8",
);
const rendererCss = (name) => fs.readFileSync(
  path.join(__dirname, "..", "src", "renderer", "styles", name),
  "utf8",
);

test("hidden panels initialize on first activation", () => {
  const source = rendererJs("app.js");
  assert.match(source, /const initPanel = \(tab\) =>/);
  assert.match(source, /if \(tab === "cognition"[\s\S]*?window\.cognitionPanel\.init\(\)/);
  assert.match(source, /panel\.classList\.add\("active"\);\s*initPanel\(tab\);/);
});

test("global controllers start after the first paint", () => {
  const source = rendererJs("app.js");
  assert.match(source, /const scheduleAfterFirstPaint = \(fn\) =>/);
  assert.match(source, /scheduleAfterFirstPaint\(\(\) => \{[\s\S]*?ApprovalModal[\s\S]*?OfficeModeController/);
});

test("dynamic island has no continuous idle particle or CSS animation loop", () => {
  const source = rendererJs("dynamic-island.js");
  const css = rendererCss("dynamic-island.css");
  assert.doesNotMatch(source, /startBreathParticles|setInterval\s*\(/);
  assert.doesNotMatch(css, /animation:\s*(?:di-bob|di-pulse|di-breath)\b/);
  assert.match(source, /spawnBurstParticles/);
  assert.match(source, /requestAnimationFrame\(animateParticles\)/);
});

test("offscreen chat history skips layout and paint", () => {
  const css = rendererCss("main.css");
  assert.match(css, /\.chat-msg\s*\{[\s\S]*?content-visibility:\s*auto/);
  assert.match(css, /contain-intrinsic-size:\s*auto\s+76px/);
});

test("opaque BrowserWindow has an opaque theme-aware renderer base", () => {
  const css = rendererCss("main.css");
  assert.match(css, /body\s*\{[^}]*background:\s*var\(--color-bg\)/);
  assert.match(css, /\.app\s*\{[^}]*background:\s*var\(--color-bg\)/);
  assert.doesNotMatch(css, /body\s*\{[^}]*background:\s*transparent/);
});

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const css = fs.readFileSync(
  path.join(__dirname, "..", "src", "renderer", "styles", "brief-drawer.css"),
  "utf8",
);
const mainCss = fs.readFileSync(
  path.join(__dirname, "..", "src", "renderer", "styles", "main.css"),
  "utf8",
);
const drawerJs = fs.readFileSync(
  path.join(__dirname, "..", "src", "renderer", "js", "brief-drawer.js"),
  "utf8",
);

function rule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`));
  assert.ok(match, `missing CSS rule: ${selector}`);
  return match[1];
}

test("daily brief uses one backdrop blur without nested compositor layers", () => {
  const backdropRule = rule(".brief-drawer-backdrop");
  assert.match(backdropRule, /backdrop-filter:\s*blur\(3px\)/);
  assert.match(backdropRule, /right:\s*min\(420px,\s*92vw\)/);
  assert.doesNotMatch(css.replace(backdropRule, ""), /(?:-webkit-)?backdrop-filter\s*:/);
  assert.doesNotMatch(rule(".brief-drawer"), /filter\s*:/);
  assert.match(rule(".brief-drawer"), /isolation:\s*isolate/);
});

test("main app surfaces do not keep full-window backdrop filters", () => {
  assert.doesNotMatch(mainCss, /(?:-webkit-)?backdrop-filter\s*:/);
});

test("daily brief has no infinite animation that repaints the blur", () => {
  assert.doesNotMatch(css, /animation:[^;]*\binfinite\b/);
});

test("daily brief card hover does not move composited content", () => {
  for (const selector of [
    ".brief-drawer__row:hover",
    ".brief-drawer__todo-card:hover",
    ".brief-drawer__trend-item:hover",
    ".brief-drawer__news-item:hover",
  ]) {
    assert.doesNotMatch(rule(selector), /transform\s*:/, selector);
  }
});

test("expanded daily brief includes theme-aware activity heatmap with custom tooltip", () => {
  assert.match(drawerJs, /_renderActivityHeatmapSection\(data\)/);
  assert.match(drawerJs, /_bindActivityHeatmap\(section,\s*days\)/);
  assert.match(drawerJs, /_renderActivityDayDetail\(day,\s*detailEl\)/);
  assert.match(drawerJs, /\/api\/calendar\/timeline/);
  assert.match(drawerJs, /aerie:persona-updated/);
  assert.match(css, /\.brief-drawer__activity-cell\s*\{/);
  assert.match(css, /\.brief-drawer__activity-tooltip\s*\{/);
  assert.doesNotMatch(css, /\.brief-drawer__activity-tooltip::after/);
});

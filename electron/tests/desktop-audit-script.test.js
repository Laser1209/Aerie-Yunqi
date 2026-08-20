"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const audit = require("./e2e/desktop-audit.js");

function control(selector, text = "") {
  return {
    locator: { selector },
    id: selector.startsWith("#") ? selector.slice(1) : "",
    accessibleName: text,
    text,
    title: text,
  };
}

test("dangerous, restart, and QQ controls are classified for explicit safe skipping", () => {
  const close = audit.classifyDedicatedControl(control("#btn-close", "关闭"));
  const restart = audit.classifyDedicatedControl(control("#settings-restart-app-btn", "重启应用"));
  const qq = audit.classifyDedicatedControl(control("#qq-gateway-start-btn", "启动 QQ 引擎"));

  assert.equal(close.category, "window-close");
  assert.equal(restart.category, "application-restart");
  assert.equal(qq.category, "qq-connectivity");
  assert.equal(audit.isAllowedSafeSkip(control("#btn-close"), close), true);
});

test("evidence redaction removes credentials and user-home segments", () => {
  const redacted = audit.redactText(
    "C:\\Users\\Alice\\secret.txt API_KEY=top-secret Bearer abcdefghijklmnop ghp_abcdefghijklmnop",
  );
  assert.doesNotMatch(redacted, /Alice|top-secret|abcdefghijklmnop/);
  assert.match(redacted, /<redacted>/);

  const object = audit.redactValue({ token: "secret-token", nested: { message: "ok" } });
  assert.equal(object.token, "<redacted>");
  assert.equal(object.nested.message, "ok");
});

test("overlap detection reports sibling control collisions but ignores parent-child controls", () => {
  const base = {
    interactive: true,
    visible: true,
    inViewport: true,
    parentDomIndex: -1,
    rect: { left: 0, top: 0, right: 100, bottom: 40, width: 100, height: 40 },
    locator: { selector: "#first" },
  };
  const surface = {
    elements: [
      { ...base, domIndex: 1 },
      {
        ...base,
        domIndex: 2,
        rect: { left: 50, top: 0, right: 150, bottom: 40, width: 100, height: 40 },
        locator: { selector: "#second" },
      },
      {
        ...base,
        domIndex: 3,
        parentDomIndex: 1,
        locator: { selector: "#child" },
      },
    ],
    textRuns: [],
  };

  const overlaps = audit.detectOverlaps(surface);
  assert.equal(overlaps.controlOverlaps.length, 2);
  assert.ok(overlaps.controlOverlaps.some((item) => item.first === "#first" && item.second === "#second"));
  assert.ok(!overlaps.controlOverlaps.some((item) => item.first === "#first" && item.second === "#child"));
});

test("surface assertions fail on missing expected evidence and invalid UI text", () => {
  const failures = audit.surfaceFailures({
    document: { bodyTextLength: 10 },
    summary: {
      invalidStrings: 1,
      invalidCharacters: 1,
      unnamedVisibleControls: 0,
      nonUniqueLocators: 0,
      clippedVisibleElements: 0,
      occludedVisibleElements: 0,
    },
  }, { controlOverlaps: [], textOverlaps: [] }, {
    expectedSelector: ".required",
    expectedSelectorCount: 0,
  });

  assert.ok(failures.includes("invalid_strings:1"));
  assert.ok(failures.includes("expected_selector_missing:.required"));
});

test("audit entry covers every required state and writes phase-level artifacts", () => {
  assert.deepEqual(
    new Set(audit.REQUIRED_STATES),
    new Set(["loading", "empty", "success", "error", "stale", "disabled", "filled"]),
  );
  const source = fs.readFileSync(path.join(__dirname, "e2e", "desktop-audit.js"), "utf8");
  for (const artifact of [
    "result.json", "elements.json", "characters.json", "strings.json", "overlaps.json",
    "network.json", "console.json", "screenshot.png",
  ]) {
    assert.match(source, new RegExp(artifact.replace(".", "\\.")));
  }
  assert.match(source, /safeSkippedAreNotCountedAsPassed:\s*true/);
  assert.doesNotMatch(source, /dedicated-flow[^\n]+passed:\s*true/);
});

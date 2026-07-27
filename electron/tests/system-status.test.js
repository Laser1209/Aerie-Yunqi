"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  backendHealthMatches,
  canonicalPathForComparison,
} = require("../src/backend-health");

const mainSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "main.js"),
  "utf8",
);
const islandSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "renderer", "js", "dynamic-island.js"),
  "utf8",
);

test("dynamic island system status never fabricates network traffic", () => {
  assert.doesNotMatch(mainSource, /_systemStatus\.net\s*=\s*Math\.random/);
  assert.match(mainSource, /network_receive_kbps/);
  assert.match(mainSource, /network_send_kbps/);
  assert.match(islandSource, /Number\.isFinite\(s\.net\)/);
});

test("backend health supports isolated port and instance identity", () => {
  assert.match(mainSource, /AERIE_BACKEND_PORT/);
  assert.match(mainSource, /AERIE_BACKEND_INSTANCE_ID/);
  assert.equal(typeof canonicalPathForComparison, "function");
  assert.match(mainSource, /readLegacyBackendDatabasePath/);
});

test("legacy backend fallback requires the Aerie product and expected database", () => {
  const expectedDbPath = path.join(__dirname, "fixtures", "aerie.db");
  const payload = { status: "degraded", app: "Aerie · 云栖" };

  assert.equal(backendHealthMatches({
    payload,
    expectedDbPath,
    expectedInstanceId: "new-instance",
    legacyDbPath: expectedDbPath,
  }), true);
  assert.equal(backendHealthMatches({
    payload: { ...payload, app: "another service" },
    expectedDbPath,
    expectedInstanceId: "new-instance",
    legacyDbPath: expectedDbPath,
  }), false);
  assert.equal(backendHealthMatches({
    payload,
    expectedDbPath,
    expectedInstanceId: "new-instance",
    legacyDbPath: path.join(__dirname, "other.db"),
  }), false);
});

test("a newly loaded renderer receives the current backend-ready state", () => {
  assert.match(mainSource, /function sendBackendState\(/);
  assert.match(
    mainSource,
    /did-finish-load[\s\S]*sendBackendState\(mainWindow, _backendReady\)/,
  );
});

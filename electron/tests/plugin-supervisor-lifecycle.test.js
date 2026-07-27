"use strict";

const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { createPluginSupervisor } = require("../src/plugin-supervisor");

async function waitFor(predicate, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("condition_timeout");
}

function portIsClosed(endpoint) {
  const parsed = new URL(endpoint);
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: parsed.hostname, port: Number(parsed.port) });
    const finish = (closed) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(closed);
    };
    socket.setTimeout(500, () => finish(true));
    socket.once("connect", () => finish(false));
    socket.once("error", () => finish(true));
  });
}

test("supervisor owns real sidecar lifecycle without exposing connection secrets", { timeout: 20000 }, async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "aerie-world-supervisor-"));
  const supervisor = createPluginSupervisor({
    startupTimeoutMs: 10000,
    heartbeatIntervalMs: 250,
    stopTimeoutMs: 3000,
  });
  supervisor.register("aerie.world", {
    command: process.env.PYTHON || "python",
    cwd: path.resolve(__dirname, "..", ".."),
    dataDir,
  });
  try {
    const enabled = await supervisor.enable("aerie.world", { expectedRevision: 0, idempotencyKey: "enable-1" });
    assert.equal(enabled.accepted, true);
    const started = await supervisor.start("aerie.world", { expectedRevision: 1, idempotencyKey: "start-1" });
    assert.equal(started.accepted, true);
    assert.equal(started.actual, "running");
    assert.equal(started.adapter, "remote");
    assert.ok(supervisor.connection("aerie.world").endpoint.startsWith("http://127.0.0.1:"));

    const publicJson = JSON.stringify(supervisor.status("aerie.world"));
    assert.doesNotMatch(publicJson, /AERIE_WORLD_TOKEN|Bearer|127\.0\.0\.1:\d+/);

    const paused = await supervisor.pause("aerie.world", { expectedRevision: 2, idempotencyKey: "pause-1" });
    assert.equal(paused.actual, "paused");
    const duplicate = await supervisor.pause("aerie.world", { expectedRevision: 2, idempotencyKey: "pause-1" });
    assert.deepEqual(duplicate, paused);
    const conflict = await supervisor.resume("aerie.world", { expectedRevision: 1, idempotencyKey: "bad-revision" });
    assert.equal(conflict.errorCode, "revision_conflict");
    const resumed = await supervisor.resume("aerie.world", { expectedRevision: 3, idempotencyKey: "resume-1" });
    assert.equal(resumed.actual, "running");
    const stopped = await supervisor.stop("aerie.world", { expectedRevision: 4, idempotencyKey: "stop-1" });
    assert.equal(stopped.actual, "stopped");
    assert.equal(supervisor.connection("aerie.world"), null);
  } finally {
    await supervisor.dispose();
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("real sidecar crash recovery fuses and can be explicitly restarted without stale ports", { timeout: 30000 }, async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "aerie-world-crash-"));
  const children = [];
  const supervisor = createPluginSupervisor({
    maxCrashes: 2,
    baseRestartDelayMs: 50,
    maxRestartDelayMs: 100,
    startupTimeoutMs: 10000,
    heartbeatIntervalMs: 200,
    stopTimeoutMs: 3000,
    spawn(command, args, options) {
      const child = spawn(command, args, options);
      children.push(child);
      return child;
    },
  });
  supervisor.register("aerie.world", {
    command: process.env.PYTHON || "python",
    cwd: path.resolve(__dirname, "..", ".."),
    dataDir,
  });
  const endpoints = [];
  try {
    await supervisor.enable("aerie.world", { expectedRevision: 0 });
    const started = await supervisor.start("aerie.world", { expectedRevision: 1 });
    assert.equal(started.actual, "running");
    endpoints.push(supervisor.connection("aerie.world").endpoint);

    const first = children.at(-1);
    first.kill();
    await waitFor(() => children.length >= 2 && supervisor.status("aerie.world").actual === "running");
    endpoints.push(supervisor.connection("aerie.world").endpoint);
    assert.equal(supervisor.status("aerie.world").crashCount, 1);

    const second = children.at(-1);
    second.kill();
    await waitFor(() => supervisor.status("aerie.world").state === "fused");
    const fused = supervisor.status("aerie.world");
    assert.equal(fused.errorCode, "plugin_fused");
    assert.equal(fused.actual, "degraded");
    assert.equal(supervisor.connection("aerie.world"), null);

    const restarted = await supervisor.restart("aerie.world", {
      expectedRevision: fused.revision,
      resetFuse: true,
    });
    assert.equal(restarted.accepted, true);
    assert.equal(restarted.actual, "running");
    assert.equal(restarted.plugin.crashCount, 0);
    endpoints.push(supervisor.connection("aerie.world").endpoint);
  } finally {
    await supervisor.dispose();
    fs.rmSync(dataDir, { recursive: true, force: true });
  }

  await waitFor(async () => (await Promise.all(endpoints.map(portIsClosed))).every(Boolean));
  assert.ok(children.every((child) => child.exitCode !== null || child.killed));
});

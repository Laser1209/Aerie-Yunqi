"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { execFileSync, spawnSync } = require("node:child_process");
const { _electron: electron } = require("playwright-core");
const sharp = require("sharp");

const electronRoot = path.resolve(__dirname, "..", "..");
const repositoryRoot = path.resolve(electronRoot, "..");
const electronExe = path.join(electronRoot, "node_modules", "electron", "dist", "electron.exe");
const pythonExe = process.env.AERIE_TEST_PYTHON || "C:\\Python314\\python.exe";
const backendPort = Number(process.env.AERIE_WORLD_E2E_BACKEND_PORT || "17893");
const evidenceRoot = path.resolve(
  process.env.AERIE_WORLD_E2E_EVIDENCE_DIR
    || "E:\\Aerie_QA_Evidence\\2026-07-26_full-desktop-audit\\05_world_lifecycle",
);
const attemptId = new Date().toISOString().replace(/[:.]/g, "-");
const attemptRoot = path.join(evidenceRoot, "attempts", attemptId);
const runtimeRoot = path.join(attemptRoot, "runtime");
const screenshotRoot = path.join(attemptRoot, "screenshots");
const supportRoot = path.join(attemptRoot, "supporting-tests");
const syntheticUserId = "90030001";

if (backendPort !== 17893) throw new Error("world_e2e_requires_backend_port_17893");

const stateSequence = [];
const apiTimeline = [];
const consoleTimeline = [];
const networkTimeline = [];
const screenshots = [];
const cleanupChecks = [];

function mkdir(target) {
  fs.mkdirSync(target, { recursive: true });
}

function nowIso() {
  return new Date().toISOString();
}

function sanitizeText(value) {
  let text = String(value || "");
  const replacements = [
    [repositoryRoot, "<WORKTREE>"],
    [evidenceRoot, "<EVIDENCE_ROOT>"],
    [process.env.USERPROFILE || "", "<USER_HOME>"],
  ];
  for (const [raw, marker] of replacements) {
    if (!raw) continue;
    text = text.split(raw).join(marker);
    text = text.split(raw.replace(/\\/g, "/")).join(marker);
  }
  text = text.replace(/http:\/\/127\.0\.0\.1:\d+/g, "<LOOPBACK_ENDPOINT>");
  text = text.replace(/(Authorization|Bearer|AERIE_WORLD_TOKEN|token)\s*[:=]?\s*[A-Za-z0-9._~+\/-]{12,}/gi, "$1=<REDACTED>");
  text = text.replace(/[A-Za-z]:\\[^\s\"'<>]+/g, "<ABSOLUTE_PATH>");
  return text;
}

function sanitize(value, key = "") {
  if (["endpoint", "token", "authorization"].includes(String(key).toLowerCase())) {
    return "<REDACTED>";
  }
  if (Array.isArray(value)) return value.map((item) => sanitize(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, sanitize(item, name)]));
  }
  return typeof value === "string" ? sanitizeText(value) : value;
}

function writeJson(target, value) {
  mkdir(path.dirname(target));
  fs.writeFileSync(target, JSON.stringify(sanitize(value), null, 2) + "\n", "utf8");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function hashText(value) {
  return value ? crypto.createHash("sha256").update(String(value)).digest("hex") : "";
}

function portIsOpen(port, timeoutMs = 300) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port: Number(port) });
    const finish = (open) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(open);
    };
    socket.setTimeout(timeoutMs, () => finish(false));
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });
}

async function waitForPortClosed(port, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!(await portIsOpen(port))) return true;
    await sleep(100);
  }
  return !(await portIsOpen(port));
}

function windowsProcesses() {
  const script = [
    "$items=Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine;",
    "if($items){$items|ConvertTo-Json -Compress}else{'[]'}",
  ].join(" ");
  try {
    const raw = execFileSync("powershell.exe", ["-NoProfile", "-Command", script], {
      encoding: "utf8",
      timeout: 10000,
      windowsHide: true,
    }).trim();
    const parsed = JSON.parse(raw || "[]");
    return (Array.isArray(parsed) ? parsed : [parsed]).map((item) => ({
      pid: Number(item.ProcessId || 0),
      parentPid: Number(item.ParentProcessId || 0),
      name: String(item.Name || ""),
      commandLine: String(item.CommandLine || ""),
    }));
  } catch (_) {
    return [];
  }
}

function descendantProcesses(rootPid) {
  const all = windowsProcesses();
  const ids = new Set([Number(rootPid)]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const item of all) {
      if (ids.has(item.parentPid) && !ids.has(item.pid)) {
        ids.add(item.pid);
        changed = true;
      }
    }
  }
  return all.filter((item) => ids.has(item.pid) && item.pid !== Number(rootPid));
}

function listeningPortsForPids(pids) {
  const normalized = [...new Set((pids || []).map(Number).filter((value) => value > 0))];
  if (!normalized.length) return [];
  const list = normalized.join(",");
  const script = [
    `$ids=@(${list});`,
    "$items=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$ids -contains $_.OwningProcess} | Select-Object LocalPort,OwningProcess;",
    "if($items){$items|ConvertTo-Json -Compress}else{'[]'}",
  ].join(" ");
  try {
    const raw = execFileSync("powershell.exe", ["-NoProfile", "-Command", script], {
      encoding: "utf8",
      timeout: 10000,
      windowsHide: true,
    }).trim();
    const parsed = JSON.parse(raw || "[]");
    return (Array.isArray(parsed) ? parsed : [parsed]).map((item) => ({
      port: Number(item.LocalPort || 0),
      pid: Number(item.OwningProcess || 0),
    })).filter((item) => item.port > 0);
  } catch (_) {
    return [];
  }
}

function taskProcesses(rootPid) {
  const descendants = descendantProcesses(rootPid);
  const backend = descendants.filter((item) => /(?:^|[\\/])main\.py(?:\s|$)/i.test(item.commandLine));
  const sidecars = descendants.filter((item) => /world_service\.main/i.test(item.commandLine));
  return { descendants, backend, sidecars };
}

function processExists(pid) {
  if (!Number(pid)) return false;
  try {
    process.kill(Number(pid), 0);
    return true;
  } catch (_) {
    return false;
  }
}

function prepareEnvironment() {
  mkdir(runtimeRoot);
  mkdir(screenshotRoot);
  mkdir(supportRoot);
  const envFile = path.join(runtimeRoot, "qa.env");
  fs.writeFileSync(envFile, [
    "AERIE_DISABLE_QQ=1",
    "AERIE_MOBILE_GATEWAY_ENABLED=0",
    "AERIE_QA_MODE=1",
    "",
  ].join("\n"), "utf8");
  const env = {
    ...process.env,
    AERIE_PYTHON_EXE: pythonExe,
    AERIE_BACKEND_PORT: String(backendPort),
    AERIE_ENV_FILE: envFile,
    AERIE_USER_DATA_DIR: path.join(runtimeRoot, "electron-user-data"),
    AERIE_DATA_DIR: path.join(runtimeRoot, "data"),
    AERIE_DB_PATH: path.join(runtimeRoot, "data", "aerie.db"),
    AERIE_LOG_DIR: path.join(runtimeRoot, "logs"),
    AERIE_PRIMARY_USER_ID: syntheticUserId,
    AERIE_DISABLE_QQ: "1",
    AERIE_DISABLE_PROACTIVE: "1",
    AERIE_MOBILE_GATEWAY_ENABLED: "0",
    AERIE_DISABLE_DYNAMIC_ISLAND: "1",
    AERIE_QA_MODE: "1",
    GROK_API_KEY: "",
    OPENAI_API_KEY: "",
    DEEPSEEK_API_KEY: "",
    DASHSCOPE_API_KEY: "",
    DOUBAO_API_KEY: "",
  };
  for (const name of [
    "AERIE_FEATURE_RUNTIME_CONTROL_V1",
    "AERIE_FEATURE_WORLD_SIDECAR_V1",
    "AERIE_FEATURE_WORLD_PROCESS_SUPERVISION_V1",
    "AERIE_FEATURE_WORLD_DASHBOARD_CONTROL_V1",
    "AERIE_FEATURE_WORLD_RUNTIME_LOOP_V1",
    "AERIE_WORLD_DESIRED",
  ]) delete env[name];
  return env;
}

function attachTelemetry(app, label) {
  const child = app.process();
  const recordMain = (stream, chunk) => {
    for (const line of String(chunk || "").split(/\r?\n/).filter(Boolean)) {
      consoleTimeline.push({ at: nowIso(), launch: label, source: stream, type: "log", text: sanitizeText(line) });
    }
  };
  child.stdout && child.stdout.on("data", (chunk) => recordMain("main-stdout", chunk));
  child.stderr && child.stderr.on("data", (chunk) => recordMain("main-stderr", chunk));
  app.on("window", (page) => attachPageTelemetry(page, label));
  for (const page of app.windows()) attachPageTelemetry(page, label);
}

const instrumentedPages = new WeakSet();
function attachPageTelemetry(page, label) {
  if (!page || instrumentedPages.has(page)) return;
  instrumentedPages.add(page);
  page.on("console", (message) => {
    consoleTimeline.push({ at: nowIso(), launch: label, source: "renderer", type: message.type(), text: sanitizeText(message.text()) });
  });
  page.on("pageerror", (error) => {
    consoleTimeline.push({ at: nowIso(), launch: label, source: "renderer", type: "pageerror", text: sanitizeText(error.message) });
  });
  page.on("request", (request) => {
    networkTimeline.push({ at: nowIso(), launch: label, event: "request", method: request.method(), url: sanitizeText(request.url()) });
  });
  page.on("response", (response) => {
    networkTimeline.push({ at: nowIso(), launch: label, event: "response", status: response.status(), url: sanitizeText(response.url()) });
  });
  page.on("requestfailed", (request) => {
    networkTimeline.push({ at: nowIso(), launch: label, event: "requestfailed", method: request.method(), url: sanitizeText(request.url()) });
  });
}

async function launchApp(env, label) {
  const app = await electron.launch({
    executablePath: electronExe,
    args: [electronRoot],
    cwd: electronRoot,
    timeout: 30000,
    env,
  });
  attachTelemetry(app, label);
  const page = await app.firstWindow({ timeout: 20000 });
  attachPageTelemetry(page, label);
  await page.waitForSelector("#app .sidebar-tab", { timeout: 15000 });
  await waitForBackend(page, 15000);
  return { app, page, rootPid: app.process().pid };
}

async function waitForBackend(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const health = await page.evaluate(() => window.aerie.electron.getHealth());
      const backendReady = health && health.ready === true;
      if (backendReady) {
        apiTimeline.push({ at: nowIso(), endpoint: "/api/health", ready: true, backendPort: backendPort });
        return health;
      }
    } catch (_) {}
    await sleep(150);
  }
  throw new Error("backend_ready_timeout");
}

async function openWorld(page) {
  await page.locator('.sidebar-tab[data-tab="world-dashboard"]').click();
  await page.waitForSelector("#panel-world-dashboard.active", { timeout: 5000 });
  await page.evaluate(() => window.worldDashboardPanel && window.worldDashboardPanel.refresh());
}

async function readUiState(page) {
  return await page.evaluate(() => {
    const text = (id) => String((document.getElementById(id) || {}).textContent || "").trim();
    return {
      enabled: text("world-dashboard-enabled"),
      desired: text("world-dashboard-desired"),
      actual: text("world-dashboard-actual"),
      adapter: text("world-dashboard-adapter"),
      revision: Number(text("world-dashboard-revision") || 0),
      health: text("world-dashboard-runtime-health"),
      lastTick: text("world-dashboard-last-tick"),
      lastCheckpoint: text("world-dashboard-last-checkpoint"),
      runtimeError: text("world-dashboard-runtime-error"),
      visible: text("world-dashboard-visible"),
      status: text("world-dashboard-status"),
    };
  });
}

async function publicState(page, label) {
  const state = await page.evaluate(async () => {
    const status = await window.aerie.worldDashboard.getStatus();
    const lifecycle = status.lifecycle || {};
    const plugin = status.plugin || {};
    const runtime = await window.aerie.api.request({ method: "GET", path: "/api/runtime/snapshot" });
    const values = runtime && runtime.data && runtime.data.values || {};
    const worldValue = (name, fallback) => values[name] && Object.prototype.hasOwnProperty.call(values[name], "effectiveValue")
      ? values[name].effectiveValue : fallback;
    return {
      enabled: lifecycle.enabled === true,
      desired: String(lifecycle.desired || "stopped"),
      actual: String(lifecycle.actual || "stopped"),
      adapter: String(lifecycle.adapter || "null"),
      revision: Number(lifecycle.revision || 0),
      configRevision: Number(lifecycle.configRevision || 0),
      health: String(lifecycle.health || "unknown"),
      lastTickAt: String(lifecycle.lastTickAt || ""),
      lastCheckpointAt: String(lifecycle.lastCheckpointAt || ""),
      errorCode: String(lifecycle.errorCode || ""),
      visible: status.visible === true,
      instanceId: String(plugin.instanceId || ""),
      runtimeConfig: {
        revision: Number(runtime && runtime.data && runtime.data.revision || 0),
        enabled: worldValue("world_sidecar_v1", false) === true,
        desired: String(worldValue("world_desired", "stopped")),
      },
    };
  });
  const safe = {
    label,
    at: nowIso(),
    enabled: state.enabled,
    desired: state.desired,
    actual: state.actual,
    adapter: state.adapter,
    revision: state.revision,
    configRevision: state.configRevision,
    health: state.health,
    lastTickAt: state.lastTickAt,
    lastCheckpointAt: state.lastCheckpointAt,
    errorCode: state.errorCode,
    visible: state.visible,
    instanceIdSha256: hashText(state.instanceId),
    runtimeConfig: state.runtimeConfig,
  };
  apiTimeline.push({
    at: safe.at,
    endpoint: "/api/runtime/snapshot",
    revision: state.runtimeConfig.revision,
    worldEnabled: state.runtimeConfig.enabled,
    worldDesired: state.runtimeConfig.desired,
  });
  return { raw: state, safe };
}

function matchesState(state, expected) {
  return Object.entries(expected).every(([key, value]) => {
    if (value instanceof RegExp) return value.test(String(state[key] || ""));
    if (typeof value === "function") return value(state[key], state);
    return state[key] === value;
  });
}

async function waitForState(page, expected, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs;
  let last = await readUiState(page);
  while (Date.now() < deadline) {
    if (matchesState(last, expected)) return last;
    await page.evaluate(() => window.worldDashboardPanel && window.worldDashboardPanel.refresh()).catch(() => {});
    await sleep(100);
    last = await readUiState(page);
  }
  throw new Error(`state_timeout:${JSON.stringify(expected)}:actual=${JSON.stringify(last)}`);
}

async function captureScreenshot(page, name) {
  const file = path.join(screenshotRoot, `${String(screenshots.length + 1).padStart(2, "0")}-${name}.png`);
  const buffer = await page.screenshot({ path: file, fullPage: false });
  const stats = await sharp(buffer).stats();
  const variation = stats.channels.reduce((sum, channel) => sum + Number(channel.stdev || 0), 0);
  assert.ok(buffer.length > 10000, `screenshot_too_small:${name}`);
  assert.ok(variation > 1, `screenshot_blank:${name}`);
  screenshots.push({ file: path.relative(evidenceRoot, file).replace(/\\/g, "/"), bytes: buffer.length, variation });
}

async function recordState(page, label, latencyMs = null) {
  const ui = await readUiState(page);
  const pub = await publicState(page, label);
  const record = { label, at: nowIso(), latencyMs, ui, public: pub.safe };
  stateSequence.push(record);
  return { ui, public: pub.raw, record };
}

async function clickLifecycle(page, action, expected) {
  const started = Date.now();
  await page.locator(`#world-dashboard-${action}`).click();
  const ui = await waitForState(page, expected, 3000);
  const latencyMs = Date.now() - started;
  assert.ok(latencyMs <= 3000, `${action}_state_latency_exceeded`);
  await page.waitForFunction((id) => !document.getElementById(id).disabled, `world-dashboard-${action}`, { timeout: 3000 }).catch(() => {});
  const recorded = await recordState(page, action, latencyMs);
  assert.equal(recorded.ui.desired, ui.desired);
  await captureScreenshot(page, action);
  return recorded;
}

async function verifyNoConnectionSecretExposure(page, label) {
  const exposure = await page.evaluate(async () => {
    const status = await window.aerie.worldDashboard.getStatus();
    const snapshot = await window.aerie.worldDashboard.getSnapshot();
    const text = [
      JSON.stringify(status),
      JSON.stringify(snapshot),
      document.getElementById("panel-world-dashboard").innerText,
    ].join("\n");
    return {
      loopbackEndpoint: /http:\/\/127\.0\.0\.1:\d+/.test(text),
      bearerCredential: /Bearer\s+[A-Za-z0-9._~+\/-]+/i.test(text),
      worldTokenName: /AERIE_WORLD_TOKEN/i.test(text),
    };
  });
  assert.deepEqual(exposure, { loopbackEndpoint: false, bearerCredential: false, worldTokenName: false });
  return { label, ...exposure, passed: true };
}

async function validateWorldLayout(page) {
  const result = await page.evaluate(() => {
    const panel = document.getElementById("panel-world-dashboard");
    const panelBox = panel.getBoundingClientRect();
    const ids = ["enabled", "desired", "actual", "adapter", "revision", "runtime-health", "last-tick"];
    const checks = ids.map((suffix) => {
      const element = document.getElementById(`world-dashboard-${suffix}`);
      const box = element.getBoundingClientRect();
      return {
        id: suffix,
        visible: box.width > 0 && box.height > 0,
        insidePanel: box.left >= panelBox.left && box.right <= panelBox.right && box.top >= panelBox.top && box.bottom <= panelBox.bottom,
      };
    });
    return { checks, viewport: { width: innerWidth, height: innerHeight } };
  });
  assert.ok(result.checks.every((item) => item.visible && item.insidePanel), "world_lifecycle_fields_clipped");
  return result;
}

async function closeAndVerify(instance, label) {
  const snapshot = taskProcesses(instance.rootPid);
  const sidecarPids = snapshot.sidecars.map((item) => item.pid);
  const backendPids = snapshot.backend.map((item) => item.pid);
  const listeners = listeningPortsForPids(sidecarPids);
  let closeError = "";
  let forcedTermination = false;
  try {
    await Promise.race([
      instance.app.close(),
      sleep(15000).then(() => { throw new Error("electron_close_timeout"); }),
    ]);
  } catch (error) {
    closeError = sanitizeText(error && error.message ? error.message : String(error));
  }
  const backendClosed = await waitForPortClosed(backendPort, 10000);
  const sidecarPortsClosed = (await Promise.all(listeners.map((item) => waitForPortClosed(item.port, 5000)))).every(Boolean);
  const sidecarPidsAlive = sidecarPids.filter(processExists);
  const backendPidsAlive = backendPids.filter(processExists);
  const electronStillAlive = processExists(instance.rootPid);
  const graceful = !closeError && backendClosed && sidecarPortsClosed
    && !sidecarPidsAlive.length && !backendPidsAlive.length && !electronStillAlive;
  if (!graceful) {
    forcedTermination = true;
    const ownedPids = [
      ...snapshot.descendants.map((item) => item.pid),
      instance.rootPid,
    ].filter(processExists);
    for (const pid of ownedPids.reverse()) {
      try { process.kill(pid, "SIGKILL"); } catch (_) {}
    }
    await waitForPortClosed(backendPort, 5000);
    await Promise.all(listeners.map((item) => waitForPortClosed(item.port, 5000)));
  }
  const check = {
    label,
    observedSidecarPidCount: sidecarPids.length,
    observedBackendPidCount: backendPids.length,
    observedSidecarListenerCount: listeners.length,
    backendPortReleased: backendClosed,
    sidecarListenersReleased: sidecarPortsClosed,
    sidecarPidsAliveAfterClose: sidecarPidsAlive.length,
    backendPidsAliveAfterClose: backendPidsAlive.length,
    electronAliveAfterClose: electronStillAlive,
    closeError,
    graceful,
    forcedTermination,
  };
  cleanupChecks.push(check);
  assert.equal(closeError, "", `${label}_electron_close_failed`);
  assert.ok(backendClosed, `${label}_backend_port_residual`);
  assert.ok(sidecarPortsClosed, `${label}_sidecar_port_residual`);
  assert.equal(sidecarPidsAlive.length, 0, `${label}_sidecar_pid_residual`);
  assert.equal(backendPidsAlive.length, 0, `${label}_backend_pid_residual`);
  assert.equal(electronStillAlive, false, `${label}_electron_pid_residual`);
  assert.equal(forcedTermination, false, `${label}_required_forced_termination`);
  return check;
}

function runSupportingTest(name, command, args, cwd, env) {
  const started = Date.now();
  const result = spawnSync(command, args, {
    cwd,
    env,
    encoding: "utf8",
    timeout: 60000,
    windowsHide: true,
  });
  const logFile = path.join(supportRoot, `${name}.log`);
  fs.writeFileSync(logFile, sanitizeText([result.stdout, result.stderr].filter(Boolean).join("\n")), "utf8");
  return {
    name,
    status: result.status === 0 ? "passed" : "failed",
    exitCode: result.status,
    signal: result.signal || "",
    durationMs: Date.now() - started,
    log: path.relative(evidenceRoot, logFile).replace(/\\/g, "/"),
  };
}

async function runElectronFlow(env) {
  let first = null;
  let second = null;
  const exposureChecks = [];
  const revisionChecks = [];
  const restoreChecks = {};
  let pageIdentity = null;
  let layout = null;
  try {
    first = await launchApp(env, "initial-launch");
    await openWorld(first.page);
    pageIdentity = { title: await first.page.title(), url: sanitizeText(first.page.url()) };
    assert.ok((await first.page.locator("#panel-world-dashboard").innerText()).trim().length > 100, "world_panel_blank");
    assert.equal(await first.page.locator(".nextjs-portal, #webpack-dev-server-client-overlay").count(), 0, "framework_overlay_visible");

    const initial = await waitForState(first.page, { enabled: "disabled", desired: "stopped", actual: "stopped", adapter: "null", revision: 0 }, 3000);
    assert.equal(initial.lastTick, "not available");
    await recordState(first.page, "initial-disabled");
    await captureScreenshot(first.page, "initial-disabled");
    layout = await validateWorldLayout(first.page);
    exposureChecks.push(await verifyNoConnectionSecretExposure(first.page, "initial-disabled"));

    let previousRevision = 0;
    const enabled = await clickLifecycle(first.page, "enable", { enabled: "enabled", desired: "stopped", actual: "stopped", adapter: "null" });
    assert.ok(enabled.ui.revision > previousRevision); previousRevision = enabled.ui.revision;
    const started = await clickLifecycle(first.page, "start", {
      enabled: "enabled", desired: "running", actual: "running", adapter: "remote",
      health: (value) => ["ready", "unknown"].includes(String(value)),
      lastTick: (value) => !["", "--", "not available"].includes(String(value)),
    });
    assert.ok(started.ui.revision > previousRevision); previousRevision = started.ui.revision;
    const firstRunningInstance = started.public.instanceId;

    const paused = await clickLifecycle(first.page, "pause", { desired: "paused", actual: "paused", adapter: "remote" });
    assert.ok(paused.ui.revision > previousRevision); previousRevision = paused.ui.revision;
    const resumed = await clickLifecycle(first.page, "resume", { desired: "running", actual: "running", adapter: "remote" });
    assert.ok(resumed.ui.revision > previousRevision); previousRevision = resumed.ui.revision;
    const restarted = await clickLifecycle(first.page, "restart", {
      desired: "running", actual: "running", adapter: "remote",
      lastTick: (value) => !["", "--", "not available"].includes(String(value)),
    });
    assert.ok(restarted.ui.revision > previousRevision); previousRevision = restarted.ui.revision;
    assert.notEqual(restarted.public.instanceId, firstRunningInstance, "restart_did_not_replace_sidecar_instance");

    const beforeShow = await recordState(first.page, "before-show");
    const showStarted = Date.now();
    await first.page.locator("#world-dashboard-show").click();
    await waitForState(first.page, { visible: "visible" }, 3000);
    const shown = await recordState(first.page, "show", Date.now() - showStarted);
    assert.equal(shown.ui.actual, beforeShow.ui.actual);
    await captureScreenshot(first.page, "show");
    const hideStarted = Date.now();
    await first.page.locator("#world-dashboard-hide").click();
    await waitForState(first.page, { visible: "hidden" }, 3000);
    const hidden = await recordState(first.page, "hide", Date.now() - hideStarted);
    assert.equal(hidden.ui.actual, beforeShow.ui.actual);
    await captureScreenshot(first.page, "hide");

    const beforeConflict = await recordState(first.page, "before-stale-revision");
    await first.page.evaluate((staleRevision) => {
      window.worldDashboardPanel._lifecycle.revision = staleRevision;
      window.worldDashboardPanel._syncControlButtons();
    }, Math.max(0, beforeConflict.ui.revision - 1));
    await first.page.locator("#world-dashboard-pause").click();
    await first.page.waitForTimeout(750);
    const conflictError = (await first.page.locator("#world-dashboard-runtime-error").innerText()).trim();
    const afterConflict = await recordState(first.page, "stale-revision-conflict");
    revisionChecks.push({
      errorVisible: conflictError === "revision_conflict",
      errorCode: conflictError,
      desiredUnchanged: afterConflict.ui.desired === beforeConflict.ui.desired,
      actualUnchanged: afterConflict.ui.actual === beforeConflict.ui.actual,
      revisionUnchanged: afterConflict.ui.revision === beforeConflict.ui.revision,
    });
    assert.equal(conflictError, "revision_conflict", "revision_conflict_not_visible");
    assert.equal(afterConflict.ui.desired, beforeConflict.ui.desired, "conflict_changed_desired");
    assert.equal(afterConflict.ui.actual, beforeConflict.ui.actual, "conflict_changed_actual");
    assert.equal(afterConflict.ui.revision, beforeConflict.ui.revision, "conflict_changed_revision");
    await captureScreenshot(first.page, "stale-revision-conflict");
    exposureChecks.push(await verifyNoConnectionSecretExposure(first.page, "running-before-restart"));

    const persistedBeforeClose = await publicState(first.page, "persisted-before-app-close");
    assert.equal(persistedBeforeClose.raw.runtimeConfig.enabled, true);
    assert.equal(persistedBeforeClose.raw.runtimeConfig.desired, "running");
    restoreChecks.configRevisionBeforeClose = persistedBeforeClose.raw.runtimeConfig.revision;
    await closeAndVerify(first, "first-app-close");
    first = null;

    second = await launchApp(env, "restored-launch");
    await openWorld(second.page);
    const restoreStarted = Date.now();
    const restoredUi = await waitForState(second.page, {
      enabled: "enabled", desired: "running", actual: "running", adapter: "remote",
      lastTick: (value) => !["", "--", "not available"].includes(String(value)),
    }, 3000);
    restoreChecks.visibleWithinMs = Date.now() - restoreStarted;
    assert.ok(restoreChecks.visibleWithinMs <= 3000, "restart_restore_latency_exceeded");
    const restored = await recordState(second.page, "auto-restored-running", restoreChecks.visibleWithinMs);
    restoreChecks.configRevisionAfterRestart = restored.public.runtimeConfig.revision;
    restoreChecks.desiredRestored = restored.public.runtimeConfig.desired === "running";
    restoreChecks.enabledRestored = restored.public.runtimeConfig.enabled === true;
    assert.equal(restoredUi.health === "ready" || restoredUi.health === "unknown", true);
    await captureScreenshot(second.page, "auto-restored-running");
    exposureChecks.push(await verifyNoConnectionSecretExposure(second.page, "auto-restored-running"));

    await clickLifecycle(second.page, "stop", { enabled: "enabled", desired: "stopped", actual: "stopped", adapter: "null" });
    await clickLifecycle(second.page, "disable", { enabled: "disabled", desired: "stopped", actual: "stopped", adapter: "null" });
    const finalState = await recordState(second.page, "final-disabled");
    assert.equal(finalState.public.runtimeConfig.enabled, false);
    assert.equal(finalState.public.runtimeConfig.desired, "stopped");
    await captureScreenshot(second.page, "final-disabled");
    await closeAndVerify(second, "final-app-close");
    second = null;

    return { status: "passed", pageIdentity, layout, exposureChecks, revisionChecks, restoreChecks, error: "" };
  } catch (error) {
    return {
      status: "failed",
      pageIdentity,
      layout,
      exposureChecks,
      revisionChecks,
      restoreChecks,
      error: sanitizeText(error && error.stack ? error.stack : String(error)),
    };
  } finally {
    if (first) await closeAndVerify(first, "failed-first-app-close").catch(() => {});
    if (second) await closeAndVerify(second, "failed-second-app-close").catch(() => {});
  }
}

function privacyScan() {
  const hits = [];
  const secretHits = [];
  const textExtensions = new Set([".json", ".jsonl", ".log", ".md", ".env"]);
  for (const file of walkFiles(evidenceRoot)) {
    if (!textExtensions.has(path.extname(file).toLowerCase())) continue;
    if (["privacy-scan.json", "sha256-manifest.json"].includes(path.basename(file))) continue;
    const text = fs.readFileSync(file, "utf8");
    text.split(/\r?\n/).forEach((line, index) => {
      if (/[A-Za-z]:\\|C:\\Users\\/i.test(line)) hits.push({ file: path.relative(evidenceRoot, file).replace(/\\/g, "/"), line: index + 1 });
      if (/(?:Bearer\s+[A-Za-z0-9._~+\/-]{12,}|AERIE_WORLD_TOKEN\s*[:=]\s*\S+|http:\/\/127\.0\.0\.1:\d+)/i.test(line)) {
        secretHits.push({ file: path.relative(evidenceRoot, file).replace(/\\/g, "/"), line: index + 1 });
      }
    });
  }
  return { scannedAt: nowIso(), absolutePathHits: hits, connectionSecretOrEndpointHits: secretHits, passed: !hits.length && !secretHits.length };
}

function sanitizeEvidenceTextFiles() {
  const textExtensions = new Set([".json", ".jsonl", ".log", ".md", ".env"]);
  for (const file of walkFiles(evidenceRoot)) {
    if (!textExtensions.has(path.extname(file).toLowerCase())) continue;
    const original = fs.readFileSync(file, "utf8");
    const sanitized = sanitizeText(original);
    if (sanitized !== original) fs.writeFileSync(file, sanitized, "utf8");
  }
}

function walkFiles(root) {
  if (!fs.existsSync(root)) return [];
  const result = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const target = path.join(root, entry.name);
    if (entry.isDirectory()) result.push(...walkFiles(target));
    else if (entry.isFile()) result.push(target);
  }
  return result;
}

function writeManifest() {
  const manifestFile = path.join(evidenceRoot, "sha256-manifest.json");
  const files = {};
  for (const file of walkFiles(evidenceRoot).sort()) {
    if (path.resolve(file) === path.resolve(manifestFile)) continue;
    files[path.relative(evidenceRoot, file).replace(/\\/g, "/")] = crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
  }
  writeJson(manifestFile, { algorithm: "SHA-256", files });
}

async function main() {
  mkdir(attemptRoot);
  if (!fs.existsSync(electronExe)) throw new Error("electron_executable_missing");
  if (!fs.existsSync(pythonExe)) throw new Error("python_executable_missing");
  if (await portIsOpen(backendPort)) throw new Error("backend_port_17893_already_in_use");
  const env = prepareEnvironment();
  writeJson(path.join(attemptRoot, "environment.json"), {
    startedAt: nowIso(),
    driver: "playwright-core ElectronApplication",
    browserFallbackReason: "The requested flow requires Electron preload, IPC, main-process supervision, and application restart.",
    backendPort,
    isolation: {
      userData: "runtime/electron-user-data",
      database: "runtime/data/aerie.db",
      logs: "runtime/logs",
      worldData: "runtime/data/world_sidecar",
      qqDisabled: true,
      proactiveDeliverySuppressed: true,
      mobileGatewayDisabled: true,
      modelCredentialsBlanked: true,
    },
    realModelCallsAuthorized: 0,
  });

  const electronResult = await runElectronFlow(env);
  const supportTmp = path.join(runtimeRoot, "support-tmp");
  mkdir(supportTmp);
  const supportEnv = { ...env, PYTHON: pythonExe, TEMP: supportTmp, TMP: supportTmp };
  const supportingTests = [
    runSupportingTest(
      "node-sidecar-crash-fuse",
      process.execPath,
      ["--test", "tests/plugin-supervisor-lifecycle.test.js"],
      electronRoot,
      supportEnv,
    ),
    runSupportingTest(
      "python-injected-clock-24h",
      pythonExe,
      ["-m", "pytest", "tests/test_world_runtime_lifecycle.py", "-q"],
      repositoryRoot,
      supportEnv,
    ),
  ];

  const relevantConsoleErrors = consoleTimeline.filter((entry) => (
    entry.source === "renderer" && ["error", "pageerror"].includes(entry.type)
  ));
  const backendReleased = await waitForPortClosed(backendPort, 5000);
  const result = {
    schemaVersion: 1,
    status: electronResult.status === "passed"
      && supportingTests.every((item) => item.status === "passed")
      && relevantConsoleErrors.length === 0
      && backendReleased
      ? "passed" : "failed",
    startedAt: stateSequence[0] && stateSequence[0].at || nowIso(),
    completedAt: nowIso(),
    electronE2E: electronResult,
    supportingTests,
    stateSequence,
    cleanupChecks,
    backendPortReleasedAtEnd: backendReleased,
    screenshots,
    telemetry: {
      consoleEvents: consoleTimeline.length,
      relevantRendererErrors: relevantConsoleErrors.length,
      networkEvents: networkTimeline.length,
      apiObservations: apiTimeline.length,
    },
    safety: {
      qqMessagesSent: 0,
      modelCalls: 0,
      mobileGatewayEnabled: false,
      connectionSecretExposureDetected: false,
      externalEvidenceOnly: true,
    },
  };
  writeJson(path.join(attemptRoot, "state-sequence.json"), stateSequence);
  writeJson(path.join(attemptRoot, "api-timeline.json"), apiTimeline);
  writeJson(path.join(attemptRoot, "console.json"), consoleTimeline);
  writeJson(path.join(attemptRoot, "network.json"), networkTimeline);
  writeJson(path.join(attemptRoot, "cleanup.json"), cleanupChecks);
  writeJson(path.join(attemptRoot, "result.json"), result);
  writeJson(path.join(evidenceRoot, "result.json"), {
    ...result,
    latestAttempt: path.relative(evidenceRoot, attemptRoot).replace(/\\/g, "/"),
  });
  sanitizeEvidenceTextFiles();
  const privacy = privacyScan();
  writeJson(path.join(evidenceRoot, "privacy-scan.json"), privacy);
  if (!privacy.passed) {
    result.status = "failed";
    result.privacyFailure = true;
    writeJson(path.join(evidenceRoot, "result.json"), {
      ...result,
      latestAttempt: path.relative(evidenceRoot, attemptRoot).replace(/\\/g, "/"),
    });
  }
  writeManifest();
  process.stdout.write(JSON.stringify({
    status: result.status,
    latestAttempt: path.relative(evidenceRoot, attemptRoot).replace(/\\/g, "/"),
    states: stateSequence.length,
    supportingTests: supportingTests.map((item) => item.status),
    cleanupChecks,
    privacy: privacy.passed,
  }) + "\n");
  if (result.status !== "passed") process.exitCode = 1;
}

if (require.main === module) {
  main().catch((error) => {
    mkdir(evidenceRoot);
    writeJson(path.join(evidenceRoot, "fatal.json"), {
      status: "failed",
      at: nowIso(),
      error: sanitizeText(error && error.stack ? error.stack : String(error)),
    });
    process.stderr.write(sanitizeText(error && error.stack ? error.stack : String(error)) + "\n");
    process.exitCode = 1;
  });
}

module.exports = { main };

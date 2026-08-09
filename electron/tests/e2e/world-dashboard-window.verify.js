"use strict";
// CDP-based end-to-end verification for the aerie.world dashboard MVP.
// Launches Electron with a fixed remote-debugging port, drives the main
// window to open the dashboard, and asserts MVP gates.
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");

const PORT = 9333;
const electronRoot = path.resolve(__dirname, "..", "..");
const electronExe = path.join(electronRoot, "node_modules", "electron", "dist", "electron.exe");
const mainJs = path.join(electronRoot, "src", "main.js");
const userData = path.join(os.tmpdir(), "aerie-dash-verify-" + Date.now());

function getJson(pathname) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: "127.0.0.1", port: PORT, path: pathname, timeout: 4000 }, (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    req.end();
  });
}

async function listTargets() {
  try { return await getJson("/json/list"); } catch (_) { return []; }
}

class CDP {
  constructor(wsUrl) { this.ws = new WebSocket(wsUrl); this.id = 0; this.pending = new Map(); }
  async open() {
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      }
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const r = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error("eval exception: " + JSON.stringify(r.exceptionDetails));
    return r.result && r.result.value;
  }
  close() { try { this.ws.close(); } catch (_) {} }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForTarget(urlFragment, timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const targets = await listTargets();
    const t = targets.find((x) => x.type === "page" && x.url && x.url.includes(urlFragment));
    if (t) return t;
    await sleep(1000);
  }
  throw new Error("target not found: " + urlFragment);
}

(async () => {
  const proc = spawn(electronExe, [
    "--remote-debugging-port=" + PORT,
    "--user-data-dir=" + userData,
    mainJs,
  ], { cwd: electronRoot, env: { ...process.env, AERIE_DISABLE_DYNAMIC_ISLAND: "1" }, stdio: "ignore" });

  // 1. 找到主窗口
  const mainTarget = await waitForTarget("index.html", 90000);
  console.log("[verify] main window:", mainTarget.url);
  const mainCdp = new CDP(mainTarget.webSocketDebuggerUrl);
  await mainCdp.open();

  // 2. 触发 show（等同点击"显示插件"）
  const showStatus = await mainCdp.eval("window.aerie.worldDashboard.show().then(r=>r && r.status)");
  console.log("[verify] show -> status:", showStatus);

  // 3. 等待独立仪表盘窗口出现
  const dashTarget = await waitForTarget("world-dashboard-window.html", 60000);
  console.log("[verify] dashboard window:", dashTarget.url);
  const dashCdp = new CDP(dashTarget.webSocketDebuggerUrl);
  await dashCdp.open();
  await sleep(1500); // 等首次渲染

  // Gate M2.1/B2.5/B3.2: window.world 恰好 8 个白名单方法（MVP 5 + 二批 getMemory/control + 三批 getB3）
  const keys = await dashCdp.eval("Object.keys(window.world||{}).sort()");
  console.log("[verify] window.world keys:", JSON.stringify(keys));
  const whitelistOk =
    Array.isArray(keys) && keys.length === 8 &&
    ["getState", "pause", "previewImageDecision", "resume", "subscribe", "getMemory", "control", "getB3"]
      .every((k) => keys.includes(k));

  // Gate M4.1: 真实数据
  const state = await dashCdp.eval("window.world.getState()");
  const ws = (state && state.worldSummary) || {};
  const pad = (state && state.emotion && state.emotion.pad) || {};
  console.log("[verify] worldSummary:", JSON.stringify(ws));
  console.log("[verify] pad P/A/D:", pad.P, pad.A, pad.D);

  const rendered = await dashCdp.eval(`({
    location: document.getElementById('wdw-location').textContent,
    activity: document.getElementById('wdw-activity').textContent,
    status: document.getElementById('wdw-status').textContent,
    padVal: document.getElementById('wdw-pad-P-val').textContent,
    scenePhase: document.getElementById('wdw-world-scene').getAttribute('data-phase'),
  })`);
  console.log("[verify] rendered:", JSON.stringify(rendered));
  const dataOk = ws.status === "running" && ws.location !== "unknown" && Number.isFinite(pad.P) && rendered.location !== "--";

  // Gate B2.5: 第二批面板（天气显示 + 关系渲染 + 记忆档案 + 控制台方法）
  const b25 = await dashCdp.eval(`(async () => {
    const weather = (document.getElementById('wdw-weather')||{}).textContent || '--';
    const relBarCount = document.querySelectorAll('.wdw-rel').length;
    const memGroups = (document.querySelectorAll('.wdw-memory-group-title')||[]).length;
    const memRefresh = document.getElementById('wdw-memory-refresh');
    memRefresh && memRefresh.click();
    await new Promise(r => setTimeout(r, 600));
    const memAfter = (document.querySelectorAll('.wdw-memory-group-title')||[]).length;
    const hasControl = typeof (window.world||{}).control === 'function';
    const hasGetMemory = typeof (window.world||{}).getMemory === 'function';
    return { weather, relBarCount, memGroups, memAfter, hasControl, hasGetMemory };
  })()`);
  console.log("[verify] b25 panels:", JSON.stringify(b25));
  const b25Ok =
    b25.hasControl === true && b25.hasGetMemory === true &&
    b25.weather !== "--" &&
    (b25.relBarCount > 0 || document.querySelectorAll('.wdw-events-empty').length > 0);

  // Gate B3.2: 9 页导航 + 事件过滤 + 内在状态 + 趋势画布 + B3 白名单
  const b3 = await dashCdp.eval(`(async () => {
    const navCount = document.querySelectorAll('.wdw-nav-btn').length;
    const pageCount = document.querySelectorAll('.wdw-page').length;
    const chipCount = document.querySelectorAll('.wdw-chip').length;
    const hasGetB3 = typeof (window.world||{}).getB3 === 'function';
    // 切到内在页，确认内在状态渲染 + 趋势画布存在
    document.querySelector('.wdw-nav-btn[data-page="internal"]').click();
    await new Promise(r => setTimeout(r, 600));
    const internalRows = document.querySelectorAll('#wdw-internal .wdw-metric-row').length;
    const canvases = document.querySelectorAll('.wdw-chart').length;
    const internalVisible = !document.querySelector('.wdw-page[data-page-panel="internal"]').hidden;
    // 切到设置页，确认设置面板存在
    document.querySelector('.wdw-nav-btn[data-page="settings"]').click();
    await new Promise(r => setTimeout(r, 400));
    const settingsRows = document.querySelectorAll('#wdw-settings .wdw-row').length;
    const settingsVisible = !document.querySelector('.wdw-page[data-page-panel="settings"]').hidden;
    return { navCount, pageCount, chipCount, hasGetB3, internalRows, canvases, internalVisible, settingsRows, settingsVisible };
  })()`);
  console.log("[verify] b3 panels:", JSON.stringify(b3));
  const b3Ok =
    b3.navCount === 9 && b3.pageCount === 9 && b3.chipCount >= 6 &&
    b3.hasGetB3 === true && b3.canvases === 3 &&
    b3.internalVisible === true && b3.settingsVisible === true;

  // Gate M3.1: 重复 show 仍单实例
  await mainCdp.eval("window.aerie.worldDashboard.show()");
  await sleep(1500);
  const targets1 = await listTargets();
  const dashCount = targets1.filter((x) => x.url.includes("world-dashboard-window.html")).length;
  console.log("[verify] dashboard window count after 2nd show:", dashCount);
  const singleOk = dashCount === 1;

  // 隐藏 → 关窗
  await mainCdp.eval("window.aerie.worldDashboard.hide()");
  await sleep(1500);
  const targets2 = await listTargets();
  const afterHide = targets2.filter((x) => x.url.includes("world-dashboard-window.html")).length;
  console.log("[verify] dashboard window count after hide:", afterHide);
  const hideOk = afterHide === 0;

  // 再次显示 → 能重开
  await mainCdp.eval("window.aerie.worldDashboard.show()");
  await sleep(2000);
  const targets3 = await listTargets();
  const reopened = targets3.filter((x) => x.url.includes("world-dashboard-window.html")).length;
  console.log("[verify] dashboard window count after re-show:", reopened);
  const reopenOk = reopened === 1;

  const result = { whitelistOk, dataOk, singleOk, hideOk, reopenOk, b25Ok, b3Ok };
  console.log("[verify] RESULT:", JSON.stringify(result));
  const allOk = whitelistOk && dataOk && singleOk && hideOk && reopenOk && b25Ok && b3Ok;

  mainCdp.close(); dashCdp.close();
  try { proc.kill(); } catch (_) {}
  await sleep(1000);
  try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch (_) {}
  console.log("[verify] ALL_PASS=" + allOk);
  process.exit(allOk ? 0 : 1);
})().catch((err) => {
  console.error("[verify] FAILED:", err && err.message || err);
  process.exit(1);
});

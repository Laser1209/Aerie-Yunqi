"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");

const source = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is missing`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} is incomplete`);
}

test("main window uses a visible default and opt-in software rendering", () => {
  const windowStart = source.indexOf("mainWindow = new BrowserWindow");
  const windowEnd = source.indexOf("mainWindow.webContents.session", windowStart);
  const mainWindowOptions = source.slice(windowStart, windowEnd);

  assert.match(source, /AERIE_SOFTWARE_RENDERING\s*===\s*"1"/);
  assert.match(source, /if \(useSoftwareRendering\) app\.disableHardwareAcceleration\(\)/);
  assert.doesNotMatch(source, /in-process-gpu|appendSwitch\("disable-gpu/);
  assert.match(mainWindowOptions, /transparent:\s*false/);
  assert.match(mainWindowOptions, /backgroundColor:\s*"#ffffff"/);
  assert.doesNotMatch(source, /sandbox:\s*false/);
});

test("packaged builds use an icon that is included in app.asar", () => {
  assert.match(source, /path\.join\(__dirname, "\.\.", "builder", "icon\.ico"\)/);
  assert.match(source, /if \(icon\.isEmpty\(\)\)/);
});

test("detached launcher output cannot crash the main process", () => {
  assert.match(source, /\[process\.stdout, process\.stderr\]/);
  assert.match(source, /error\.code === "EPIPE"/);
  assert.match(source, /stream\.write = \(\) => false/);
});

test("dynamic island uses its native hit area without cursor polling", () => {
  assert.match(source, /dynamicIsland\.setIgnoreMouseEvents\(false\)/);
  assert.doesNotMatch(source, /startIslandPenetrationPolling|getCursorScreenPoint|_islandPollInterval/);
});

test("dynamic island has a low-power opt-out", () => {
  assert.match(source, /AERIE_DISABLE_DYNAMIC_ISLAND\s*!==\s*"1"/);
  assert.match(source, /if \(dynamicIslandEnabled\) createDynamicIsland\(\)/);
});

test("dynamic island preserves native topmost state on Windows", () => {
  assert.match(source, /process\.platform === "win32" \? "screen-saver" : "floating"/);

  const calls = [];
  const context = {
    DYNAMIC_ISLAND_TOP_LEVEL: "screen-saver",
    dynamicIsland: {
      isDestroyed: () => false,
      isVisible: () => true,
      setAlwaysOnTop: (...args) => calls.push(["setAlwaysOnTop", ...args]),
      moveTop: () => calls.push(["moveTop"]),
    },
  };
  vm.runInNewContext(`${extractFunction("ensureDynamicIslandOnTop")}\nthis.run = ensureDynamicIslandOnTop;`, context);

  assert.equal(context.run(), true);
  assert.deepEqual(calls, [
    ["setAlwaysOnTop", true, "screen-saver"],
    ["moveTop"],
  ]);
});

test("topmost refresh respects a hidden or destroyed island", () => {
  const context = {
    DYNAMIC_ISLAND_TOP_LEVEL: "screen-saver",
    dynamicIsland: null,
  };
  vm.runInNewContext(`${extractFunction("ensureDynamicIslandOnTop")}\nthis.run = ensureDynamicIslandOnTop;`, context);

  assert.equal(context.run(), false);
  context.dynamicIsland = {
    isDestroyed: () => true,
    isVisible: () => true,
  };
  assert.equal(context.run(), false);
  context.dynamicIsland = {
    isDestroyed: () => false,
    isVisible: () => false,
  };
  assert.equal(context.run(), false);
});

test("main window only hides when a recovery surface is available", () => {
  const context = { tray: null, dynamicIsland: null };
  vm.runInNewContext(`${extractFunction("hasBackgroundRecoverySurface")}\nthis.run = hasBackgroundRecoverySurface;`, context);

  assert.equal(context.run(), false);
  context.tray = { isDestroyed: () => false };
  assert.equal(context.run(), true);
  context.tray = { isDestroyed: () => true };
  context.dynamicIsland = {
    isDestroyed: () => false,
    isVisible: () => true,
  };
  assert.equal(context.run(), true);
  context.dynamicIsland.isVisible = () => false;
  assert.equal(context.run(), false);

  assert.match(source, /mainWindow\.on\("close", \(event\) => \{[\s\S]*?hasBackgroundRecoverySurface\(\)[\s\S]*?event\.preventDefault\(\);[\s\S]*?mainWindow\.hide\(\);/);
  assert.match(source, /ipcMain\.handle\("window:close",[\s\S]*?if \(win\) win\.close\(\)/);
  assert.match(source, /app\.on\("second-instance", \(\) => \{\s*showMainWindow\(\);/);
  assert.match(source, /function showMainWindow\(tab, payload\)[\s\S]*?mainWindow\.show\(\);[\s\S]*?mainWindow\.moveTop\(\);[\s\S]*?mainWindow\.focus\(\);[\s\S]*?ensureDynamicIslandOnTop\(\);/);
});

test("main-window navigation preserves payloads and failed sends until renderer readiness", () => {
  const calls = [];
  const warnings = [];
  const context = {
    console: { warn: (...args) => warnings.push(args) },
    MAIN_TAB_ALIASES: { calendar: "memorial" },
    mainWindowReady: false,
    pendingMainNavigation: null,
    mainWindow: {
      isDestroyed: () => false,
      webContents: { send: (...args) => calls.push(args) },
    },
  };
  vm.runInNewContext(
    `${extractFunction("dispatchMainNavigation")}\n`
      + `${extractFunction("flushPendingMainNavigation")}\n`
      + `${extractFunction("queueMainNavigation")}\n`
      + "this.queue = queueMainNavigation; this.flush = flushPendingMainNavigation;",
    context,
  );

  assert.equal(context.queue("settings"), false);
  assert.deepEqual(calls, []);
  assert.equal(context.pendingMainNavigation.tab, "settings");
  context.mainWindowReady = true;
  assert.equal(context.flush(), true);
  assert.deepEqual(calls.pop(), ["ui:open-tab", "settings"]);
  const briefPayload = { expanded: true };
  assert.equal(context.queue("brief", briefPayload), true);
  assert.deepEqual(calls.pop(), ["brief:show", briefPayload]);
  assert.equal(context.queue("calendar"), true);
  assert.deepEqual(calls.pop(), ["ui:open-tab", "memorial"]);

  context.mainWindow.webContents.send = () => {
    throw new Error("renderer unavailable");
  };
  assert.equal(context.queue("brief", briefPayload), false);
  assert.equal(context.pendingMainNavigation.tab, "brief");
  assert.equal(context.pendingMainNavigation.payload, briefPayload);
  assert.equal(warnings.length, 1);

  context.mainWindow.webContents.send = (...args) => calls.push(args);
  assert.equal(context.flush(), true);
  assert.equal(context.pendingMainNavigation, null);
  assert.deepEqual(calls.pop(), ["brief:show", briefPayload]);

  assert.match(source, /mainWindow\.webContents\.on\("did-finish-load", \(\) => \{[\s\S]*?flushPendingMainNavigation\(\)/);
  assert.match(source, /mainWindow\.webContents\.on\("render-process-gone",[\s\S]*?mainWindowReady = false/);
  assert.match(source, /notification\.on\("click", \(\) => \{\s*showMainWindow\("memorial"\);/);
});

test("showMainWindow reloads a crashed renderer and forwards navigation payloads", () => {
  const calls = [];
  const payload = { expanded: true };
  const context = {
    app: { isReady: () => true },
    mainWindowReady: true,
    mainWindow: {
      isDestroyed: () => false,
      isMinimized: () => true,
      restore: () => calls.push("restore"),
      setSkipTaskbar: (value) => calls.push(["setSkipTaskbar", value]),
      setOpacity: (value) => calls.push(["setOpacity", value]),
      show: () => calls.push("show"),
      moveTop: () => calls.push("moveTop"),
      focus: () => calls.push("focus"),
      webContents: {
        isCrashed: () => true,
        reload: () => calls.push("reload"),
      },
    },
    createMainWindow: () => calls.push("createMainWindow"),
    ensureDynamicIslandOnTop: () => calls.push("ensureDynamicIslandOnTop"),
    queueMainNavigation: (...args) => calls.push(["queueMainNavigation", ...args]),
  };
  vm.runInNewContext(`${extractFunction("showMainWindow")}\nthis.run = showMainWindow;`, context);

  assert.equal(context.run("brief", payload), true);
  assert.equal(context.mainWindowReady, false);
  assert.equal(calls[0], "reload");
  assert.deepEqual(calls.at(-1), ["queueMainNavigation", "brief", payload]);
});

test("tray and boot brief navigation use the readiness-aware main-window path", () => {
  const trayFunction = extractFunction("createTray");
  assert.match(trayFunction, /showMainWindow\("brief"\)/);
  assert.match(trayFunction, /showMainWindow\("brief", \{ expanded: true \}\)/);
  assert.match(trayFunction, /showMainWindow\("settings"\)/);
  assert.doesNotMatch(trayFunction, /webContents\.send\("brief:show"/);
  assert.doesNotMatch(trayFunction, /webContents\.send\("ui:open-tab"/);

  const bootBriefStart = source.indexOf("let _bootBriefShown");
  const bootBriefEnd = source.indexOf('app.on("window-all-closed"', bootBriefStart);
  const bootBrief = source.slice(bootBriefStart, bootBriefEnd);
  assert.match(bootBrief, /setTimeout\(\(\) => \{\s*showMainWindow\("brief"\);/);
  assert.doesNotMatch(bootBrief, /webContents\.send/);
});

test("main window z-order changes reassert the island without focusing it", () => {
  assert.match(source, /mainWindow\.on\("show", \(\) => \{[\s\S]*?ensureDynamicIslandOnTop\(\);/);
  assert.match(source, /mainWindow\.on\("focus", ensureDynamicIslandOnTop\)/);
  assert.match(source, /mainWindow\.on\("restore", ensureDynamicIslandOnTop\)/);
  assert.match(source, /mainWindow\.on\("enter-full-screen", ensureDynamicIslandOnTop\)/);
  assert.match(source, /mainWindow\.on\("leave-full-screen", ensureDynamicIslandOnTop\)/);
  assert.match(source, /mainWindow\.on\("enter-html-full-screen", ensureDynamicIslandOnTop\)/);
  assert.match(source, /mainWindow\.on\("leave-html-full-screen", ensureDynamicIslandOnTop\)/);
  assert.match(source, /mainWindow\.on\("maximize", \(\) => \{[\s\S]*?ensureDynamicIslandOnTop\(\);/);
  assert.match(source, /mainWindow\.on\("unmaximize", \(\) => \{[\s\S]*?ensureDynamicIslandOnTop\(\);/);

  const helper = extractFunction("ensureDynamicIslandOnTop");
  assert.doesNotMatch(helper, /\.show\(|\.showInactive\(|\.focus\(/);
  assert.match(source, /dynamicIsland\.on\("show", \(\) => \{[\s\S]*?ensureDynamicIslandOnTop\(\);[\s\S]*?_startMediaPolling\(\);/);
  assert.match(source, /dynamicIsland\.showInactive\(\)/);
});

test("media polling is bounded, single-flight, and paused while hidden", () => {
  assert.match(source, /const MEDIA_QUERY_TIMEOUT_MS = 5000/);
  assert.match(source, /const MEDIA_POLL_ACTIVE_MS = 5000/);
  assert.match(source, /const MEDIA_POLL_IDLE_MS = 15000/);
  assert.match(source, /if \(!_mediaPollingActive \|\| _mediaPollInFlight\) return/);
  assert.match(source, /timeoutId = setTimeout\(\(\) => \{[\s\S]*?ps\.kill\(\)[\s\S]*?MEDIA_QUERY_TIMEOUT_MS/);
  assert.match(source, /dynamicIsland\.on\("hide", _stopMediaPolling\)/);
  assert.doesNotMatch(source, /_mediaPollInterval/);
  assert.doesNotMatch(extractFunction("_startMediaPolling"), /setInterval/);
  assert.doesNotMatch(extractFunction("_runMediaControlAndRefresh"), /\.finally\(/);
});

test("a stalled media query is killed and resolves to an empty state", async () => {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  let killCount = 0;
  let spawnCall = null;
  child.kill = () => { killCount += 1; };
  const context = {
    process: { platform: "win32" },
    spawn: (...args) => {
      spawnCall = args;
      return child;
    },
    _SMTC_PS1: "",
    MEDIA_QUERY_TIMEOUT_MS: 5,
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(`${extractFunction("_queryMediaState")}\nthis.run = _queryMediaState;`, context);

  const state = await context.run();
  assert.equal(killCount, 1);
  assert.equal(spawnCall[0], "powershell.exe");
  assert.equal(spawnCall[2].windowsHide, true);
  assert.equal(state.playing, false);
  assert.equal(state.title, "");
  assert.equal(state.thumbnail, "");
});

test("concurrent media state reads share one query promise", async () => {
  const resolvers = [];
  let queryCount = 0;
  const context = {
    _mediaControlInFlight: null,
    _mediaQueryPromise: null,
    _queryMediaState: () => {
      queryCount += 1;
      return new Promise((resolve) => resolvers.push(resolve));
    },
  };
  vm.runInNewContext(`${extractFunction("_fetchMediaState")}\nthis.run = _fetchMediaState;`, context);

  const first = context.run();
  const second = context.run();
  assert.equal(first, second);
  assert.equal(queryCount, 1);

  resolvers.shift()({ playing: false });
  await first;
  const third = context.run();
  assert.notEqual(third, first);
  assert.equal(queryCount, 2);
  resolvers.shift()({ playing: true });
  await third;
});

test("a stalled media control process is hidden, killed, and timeout-bounded", async () => {
  const child = new EventEmitter();
  let killCount = 0;
  let spawnCall = null;
  child.kill = () => { killCount += 1; };
  const context = {
    process: { platform: "win32" },
    spawn: (...args) => {
      spawnCall = args;
      return child;
    },
    _buildMediaControlScript: (action) => `control:${action}`,
    MEDIA_CONTROL_TIMEOUT_MS: 5,
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(
    `${extractFunction("_runMediaControlProcess")}\nthis.run = _runMediaControlProcess;`,
    context,
  );

  await context.run("Next");
  assert.equal(killCount, 1);
  assert.equal(spawnCall[0], "powershell.exe");
  assert.equal(spawnCall[1].at(-2), "-Command");
  assert.equal(spawnCall[1].at(-1), "control:Next");
  assert.equal(spawnCall[2].windowsHide, true);
});

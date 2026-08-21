"use strict";
const { app, BrowserWindow, Tray, ipcMain, nativeImage, screen, Menu, dialog, Notification, shell } = require("electron");
// Hardware acceleration is the normal path. The dynamic island uses blur and
// animation heavily, so forcing SwiftShader can consume an entire CPU core.
// Keep a deliberate escape hatch for machines with broken GPU drivers.
const useSoftwareRendering = process.env.AERIE_SOFTWARE_RENDERING === "1";
if (useSoftwareRendering) app.disableHardwareAcceleration();
// Electron's "floating" level is placed behind the Windows taskbar and can
// lose the native TOPMOST flag. The island is intentionally visible above
// normal and fullscreen app windows, so use the level that preserves TOPMOST.
const DYNAMIC_ISLAND_TOP_LEVEL = process.platform === "win32" ? "screen-saver" : "floating";
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");
const crypto = require("crypto");
const { StringDecoder } = require("string_decoder");
const { backendHealthMatches } = require("./backend-health");
const { createCapabilityBroker } = require("./capability-broker");
const { createPluginSupervisor } = require("./plugin-supervisor");
const { createEnvFeatureFlags, createWorldDashboardHost } = require("./world-dashboard-host");
const { ensurePythonRuntime, buildManualTutorial } = require("./runtime-bootstrap");

// Windows toast 归属：不设置 AppUserModelID 时，系统通知的来源名会显示
// "Electron" 而非 "Aerie · 云栖"。需与 package.json build.appId 保持一致
// （electron-builder 安装时按该 appId 注册开始菜单快捷方式）。
try {
  const _pkg = require("./package.json");
  const _appId = _pkg && _pkg.build && _pkg.build.appId;
  if (typeof _appId === "string" && _appId) {
    app.setAppUserModelId(_appId);
  }
} catch (_) {}

// Development launchers and test harnesses may close their output pipe while
// Electron stays alive. Without an error listener, later console writes turn a
// harmless detached terminal into repeated main-process EPIPE dialogs.
for (const stream of [process.stdout, process.stderr]) {
  if (stream && typeof stream.on === "function") {
    stream.on("error", (error) => {
      if (error && error.code === "EPIPE") {
        stream.write = () => false;
      }
    });
  }
}

// ── Config ──────────────────────────────────────────
const PY_PORT = Number.parseInt(process.env.AERIE_BACKEND_PORT || "7890", 10);
const PY_BACKEND = "http://127.0.0.1:" + PY_PORT;
// All ports that the Python backend may bind during startup. Orphaned
// processes from a previous crash on any of these ports must be killed
// before we spawn a fresh child, otherwise bind() fails with EADDRINUSE
// and (for optional sub-services) can SystemExit the whole process.
const PY_BACKEND_PORTS = [PY_PORT, 7891];

let PROJECT_ROOT;
let PYTHON_ROOT;
let PYTHON_EXE;
let PY_MAIN;
let ICON_PATH;

if (app.isPackaged) {
  PROJECT_ROOT = path.dirname(process.execPath);
  PYTHON_ROOT = path.join(process.resourcesPath, "python");
  // 自包含运行时：真实可迁移的 python.exe，非 venv 重定向器，无需运行时下载。
  PYTHON_EXE = path.join(PYTHON_ROOT, "runtime", "python.exe");
  PY_MAIN = path.join(PYTHON_ROOT, "main.py");
  ICON_PATH = path.join(__dirname, "..", "builder", "icon.ico");
} else {
  PROJECT_ROOT = path.resolve(__dirname, "..", "..");
  PYTHON_ROOT = PROJECT_ROOT;
  PYTHON_EXE = process.env.AERIE_PYTHON_EXE
    ? path.resolve(process.env.AERIE_PYTHON_EXE)
    : path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe");
  PY_MAIN = path.join(PROJECT_ROOT, "main.py");
  ICON_PATH = path.join(PROJECT_ROOT, "Aerie · 云栖.png");
}

// 开场动画（splash）资产：开发态位于项目根 video/，打包态位于
// resources/video/（由 electron-builder.yml 的 extraResources 打入）。
function getSplashAssetPath(filename) {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "video", filename);
  }
  return path.join(PROJECT_ROOT, "video", filename);
}

// 把 Windows 绝对路径转成可直接拼接 file:// 的片段：
// 统一正斜杠后 encodeURI，中文 / 空格等特殊字符不会破坏 URL。
function toFileUriPath(absPath) {
  return encodeURI(absPath.replace(/\\/g, "/"));
}

// ── State ──────────────────────────────────────────
// Development launchers can provide an isolated profile when the default
// Electron user-data directory is locked down or owned by another instance.
// This must run before requestSingleInstanceLock() below.
function configureElectronUserDataPath() {
  const configuredPath = process.env.AERIE_USER_DATA_DIR;
  if (!configuredPath) return;

  const userDataPath = path.resolve(configuredPath);
  try {
    fs.mkdirSync(userDataPath, { recursive: true });
    app.setPath("userData", userDataPath);
    console.log("[main] Electron userData:", userDataPath);
  } catch (error) {
    console.error("[main] failed to configure Electron userData:", error.message);
  }
}

configureElectronUserDataPath();
console.log("[main] software rendering:", useSoftwareRendering);

let pythonProc = null;
let mainWindow = null;
let splashWindow = null;
let tray = null;
let dynamicIsland = null;
let worldDashboardWindow = null;
let isQuitting = false;
let mainWindowReady = false;
let _splashDone = false;
let _splashMode = "video"; // "video" | "loading" | "none"
let pendingMainNavigation = null;
// R7.1: legacy brief popup/detail windows removed. The brief now
// lives inside the main window as a right-side drawer (see
// renderer/js/brief-drawer.js + styles/brief-drawer.css).
let _chatEventBuf = "";
const CHAT_EVENT_PREFIX = "[CHAT_EVENT]";
let _backendReady = false;
let _backendState = "booting";
let _lastBroadcastBackendReady = false;
let _pendingHealthInterval = null;
let _bootingDeadlineTs = 0;
let BACKEND_DB_PATH = null;
let BACKEND_DATA_DIR = null;
let BACKEND_LOG_DIR = null;
let EXPECTED_BACKEND_INSTANCE_ID = null;
const MAIN_PROCESS_TOKEN = crypto.randomBytes(32).toString("base64url");
let _worldConnectionSignature = "";
let _worldConnectionMonitor = null;
const _openedAttachmentTempPaths = new Set();
let _worldShutdownStarted = false;
let _worldShutdownComplete = false;
const _stderrDecoder = new StringDecoder("utf8");
const START_MINIMIZED_ARG = "--start-minimized";
const worldCapabilityBroker = createCapabilityBroker();
const worldPluginSupervisor = createPluginSupervisor();
const worldDashboardHost = createWorldDashboardHost({
  featureFlags: createEnvFeatureFlags(process.env),
  apiRequest,
  supervisor: worldPluginSupervisor,
});

function isStartMinimizedArgPresent() {
  return process.argv.includes(START_MINIMIZED_ARG) || process.argv.includes("--hidden");
}

function getWindowsScriptHostPath() {
  const systemRoot = process.env.SystemRoot || "C:\\Windows";
  return path.join(systemRoot, "System32", "wscript.exe");
}

function getDevSilentLauncherPath() {
  return path.join(PROJECT_ROOT, "start-dev-silent.vbs");
}

function getStartupLaunchConfig(startMinimized) {
  if (app.isPackaged) {
    return {
      path: app.getPath("exe"),
      args: startMinimized ? [START_MINIMIZED_ARG] : [],
    };
  }

  const args = [getDevSilentLauncherPath()];
  if (startMinimized) args.push(START_MINIMIZED_ARG);
  return {
    path: getWindowsScriptHostPath(),
    args,
  };
}

function getStartupSettings() {
  const defaultConfig = getStartupLaunchConfig(false);
  const minimizedConfig = getStartupLaunchConfig(true);
  const defaultState = app.getLoginItemSettings(defaultConfig);
  const minimizedState = app.getLoginItemSettings(minimizedConfig);
  const autoStart = defaultState.openAtLogin === true || minimizedState.openAtLogin === true;
  return {
    autoStart,
    openAtLogin: autoStart,
    wasOpenedAtLogin: defaultState.wasOpenedAtLogin === true || minimizedState.wasOpenedAtLogin === true,
    wasOpenedAsHidden: defaultState.wasOpenedAsHidden === true || minimizedState.wasOpenedAsHidden === true,
    startMinimized: minimizedState.openAtLogin === true || isStartMinimizedArgPresent(),
  };
}

function setStartupSettings(options) {
  const autoStart = options && options.autoStart === true;
  const startMinimized = options && options.startMinimized === true;
  const launchConfig = getStartupLaunchConfig(startMinimized);

  app.setLoginItemSettings({
    openAtLogin: autoStart,
    path: launchConfig.path,
    args: launchConfig.args,
  });

  return {
    ok: true,
    autoStart,
    startMinimized,
    path: launchConfig.path,
    args: launchConfig.args,
    state: getStartupSettings(),
  };
}

function configureBackendDataPath() {
  const explicitDataDir = process.env.AERIE_DATA_DIR;
  const explicitDbPath = process.env.AERIE_DB_PATH;
  const explicitLogDir = process.env.LOG_DIR || process.env.AERIE_LOG_DIR;

  BACKEND_DATA_DIR = explicitDataDir
    ? path.resolve(explicitDataDir)
    : app.isPackaged
    ? path.join(app.getPath("userData"), "data")
    : path.join(PROJECT_ROOT, "data");
  BACKEND_DB_PATH = explicitDbPath
    ? path.resolve(explicitDbPath)
    : path.join(BACKEND_DATA_DIR, "aerie.db");
  BACKEND_LOG_DIR = explicitLogDir
    ? path.resolve(explicitLogDir)
    : app.isPackaged
    ? path.join(app.getPath("userData"), "logs")
    : path.join(PROJECT_ROOT, "logs");

  fs.mkdirSync(BACKEND_DATA_DIR, { recursive: true });
  fs.mkdirSync(path.dirname(BACKEND_DB_PATH), { recursive: true });
  fs.mkdirSync(BACKEND_LOG_DIR, { recursive: true });

  if (app.isPackaged && !explicitDbPath && !fs.existsSync(BACKEND_DB_PATH)) {
    const legacyDbPath = path.join(PYTHON_ROOT, "data", "aerie.db");
    if (fs.existsSync(legacyDbPath)) {
      fs.copyFileSync(legacyDbPath, BACKEND_DB_PATH);
      console.log("[main] migrated legacy database to persistent userData");
    }
  }
}

// ── Backend ────────────────────────────────────────
// R7.2: Derive a three-state backend state so the first paint of the
//       status-bar is "启动中…" instead of the misleading "后端离线".
//
//       - "booting"  : we haven't given up yet (still within the boot-deadline
//                     window, or an explicit respawn is in progress).
//       - "ready"    : _backendReady === true.
//       - "offline"  : explicitly dead (exit handler, timeout expired, or
//                     restart handler told us so).
const BOOT_TIMEOUT_MS = 20000;
function _recomputeBackendState(nowTs = Date.now()) {
  if (_backendReady) { _backendState = "ready"; return; }
  if (_bootingDeadlineTs && nowTs < _bootingDeadlineTs) {
    _backendState = "booting";
    return;
  }
  if (pythonProc && typeof pythonProc.pid === "number") {
    try {
      process.kill(pythonProc.pid, 0);
      _backendState = "booting";
      return;
    } catch (_) {}
  }
  _backendState = "offline";
}
function _setBootingDeadline(ms = BOOT_TIMEOUT_MS) {
  _bootingDeadlineTs = Date.now() + ms;
}

// R7.3: Append ALL raw stderr to a dedicated log file so users can at
//       any time open it and see the *actual* Python startup error, instead
//       of relying on the handleStderr function which only forwards
//       [CHAT_EVENT] JSON lines and silently drops everything else.
let _rawStderrLogPath = null;
let _rawStderrFatalPattern = /(Traceback \(most recent call last\)|SystemExit|OSError|NameError|ModuleNotFoundError|ImportError|AttributeError|TypeError|KeyError|ValueError|error while attempting to bind on address|Address already in use|EADDRINUSE|WinError 10048)/i;
let _lastFatalBroadcastTs = 0;
function decodeBufferedUtf8Chunks(chunks) {
  return Buffer.concat(chunks.map((chunk) => Buffer.from(chunk))).toString("utf8");
}

function createUtf8SseProcessor(onFrame, initialBuffer = "") {
  const decoder = new StringDecoder("utf8");
  let buf = initialBuffer || "";
  function write(chunk) {
    buf += decoder.write(Buffer.from(chunk));
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      onFrame(frame);
    }
  }
  function end() {
    buf += decoder.end();
    const remaining = buf;
    buf = "";
    return remaining;
  }
  return { write, end };
}

function _ensureRawStderrLogger() {
  if (_rawStderrLogPath) return;
  if (!BACKEND_LOG_DIR) return;
  try {
    fs.mkdirSync(BACKEND_LOG_DIR, { recursive: true });
    const stamp = new Date();
    const parts = new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Shanghai",
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false,
    }).formatToParts(stamp).reduce((acc, part) => {
      acc[part.type] = part.value;
      return acc;
    }, {});
    const localIso = `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
    const stampStr = localIso.replace(/:/g, "-");
    _rawStderrLogPath = path.join(BACKEND_LOG_DIR, "backend.stderr." + stampStr + ".raw.log");
    const summaryPath = path.join(BACKEND_LOG_DIR, "backend.stderr.LATEST.raw.log");
    try { fs.rmSync(summaryPath, { force: true }); } catch (_) {}
    try { fs.symlinkSync(_rawStderrLogPath, summaryPath, "file"); } catch (_) {
      try { fs.copyFileSync(_rawStderrLogPath, summaryPath); } catch (_2) {}
    }
    fs.appendFileSync(_rawStderrLogPath,
      "\n# ===== backend stderr session start " + localIso + "+08:00 =====\n",
      "utf8");
  } catch (_err) {
    console.warn("[main] failed to open raw stderr log:", _err && _err.message);
    _rawStderrLogPath = null;
  }
}
function _appendRawStderr(chunkStr) {
  _ensureRawStderrLogger();
  if (!_rawStderrLogPath) return;
  try { fs.appendFileSync(_rawStderrLogPath, chunkStr, "utf8"); } catch (_) {}
}
function _broadcastBackendFatalIfNeeded(chunkStr) {
  if (!_rawStderrFatalPattern.test(chunkStr)) return;
  const nowTs = Date.now();
  if (nowTs - _lastFatalBroadcastTs < 2000) return; // throttle at 2s
  _lastFatalBroadcastTs = nowTs;
  const payload = {
    type: "backend_fatal",
    log_path: _rawStderrLogPath || "",
    message: chunkStr.split("\n").slice(0, 3).join("\n").slice(0, 500),
    ts: Date.now(),
  };
  for (const w of BrowserWindow.getAllWindows()) {
    if (!w || w.isDestroyed()) continue;
    try { w.webContents.send("backend:fatal", payload); } catch (_) {}
    try { w.webContents.send("chat:message", payload); } catch (_) {}
  }
}

function startPythonBackend() {
  _setBootingDeadline();
  _recomputeBackendState();
  broadcastHealth();
  // R7.4: Before doing anything, kill ANY existing python.exe process
  // that is LISTENING on PY_PORT, but ONLY if healthCheck() says it's NOT
  // a compatible Aerie backend we can cleanly attach to.  This eliminates
  // the orphan-7890 problem: a leftover child from yesterday's restart kills
  // the next launch forever (WinError 10048).
  (async () => {
    try { await _evictOrphanBackendIfNeeded(); } catch (_) {}
    // 环境自举：检测/自动下载 Python 运行时（缺环境时联网补齐）
    const rt = await ensurePythonRuntime({
      pythonRoot: PYTHON_ROOT,
      pythonExe: PYTHON_EXE,
      log: (m) => console.log("[main]" + m),
    });
    if (!rt.ok) {
      _backendState = "offline";
      _recomputeBackendState();
      broadcastHealth();
      _showRuntimeBootstrapFailure(rt);
      return;
    }
    if (rt.pythonExe && rt.pythonExe !== PYTHON_EXE) {
      PYTHON_EXE = rt.pythonExe;
      console.log("[main] switched to runtime python:", PYTHON_EXE);
    }
    // v2.2 fix: before spawning a fresh Python, probe port 7890. If a
    // healthy backend is already listening (e.g. the user launched
    // `python main.py` manually, or the previous Electron session left
    // one running), attach to it instead of fighting for the port.
    healthCheck().then((alive) => {
      if (alive) {
        console.log("[main] existing backend detected on port " + PY_PORT + " - attaching");
        _backendReady = true;
        _recomputeBackendState();
        broadcastHealth();
        return;
      }
      _spawnNewPython();
    }).catch(() => _spawnNewPython());
  })();
}

// R7.4: If the port is LISTENING but healthCheck() rejects it (wrong DB,
//       wrong instance id, wrong app id — signs of an orphan process),
//       kill it BEFORE spawn so our new child can bind cleanly.
async function _evictOrphanBackendIfNeeded() {
  if (process.platform !== "win32") return;
  // Step 1: Check if the main backend port has a VALID Aerie backend; if so,
  //         it's not an orphan — leave it alone so startPythonBackend can
  //         attach to it (this is the "attach if port alive" path).
  let healthy = false;
  try { healthy = Boolean(await Promise.race([
    healthCheck(),
    new Promise((r) => setTimeout(() => r(false), 800)),
  ])); } catch (_) { healthy = false; }
  if (healthy) return;

  // Step 2: Collect PIDs listening on any port we own (main + optional
  //         sub-services like the mobile gateway on 7891). An orphan from a
  //         previous crash on any of these blocks the corresponding bind().
  const pidSet = new Set();
  for (const port of PY_BACKEND_PORTS) {
    try {
      const { execSync } = require("child_process");
      const output = execSync(
        "netstat -ano | findstr /R /C:\"" + port + "\\s*\"",
        { encoding: "utf8", timeout: 2000, stdio: ["ignore", "pipe", "ignore"] }
      );
      for (const line of String(output || "").split(/\r?\n/)) {
        const m = line.match(/LISTENING\s+(\d+)\s*$/);
        if (!m) continue;
        const p = Number(m[1]);
        if (Number.isFinite(p) && p > 4 && p !== process.pid) pidSet.add(p);
      }
    } catch (_netstatErr) { /* port free — that's fine */ }
  }
  if (!pidSet.size) return;

  // Step 3: Only kill processes whose image name starts with "python".
  //         We never kill non-python processes (they're unrelated services).
  for (const pid of pidSet) {
    try {
      const proc = require("child_process").execSync(
        "wmic process where ProcessId=" + pid + " get Name,ExecutablePath /format:list",
        { encoding: "utf8", timeout: 2000, stdio: ["ignore", "pipe", "ignore"] }
      );
      const nameLine = String(proc || "").match(/Name=([^\r\n]+)/);
      const name = (nameLine && nameLine[1] || "").trim().toLowerCase();
      if (!name || name.indexOf("python") !== 0) {
        console.log("[main] evict-orphan: skip PID=" + pid + " (Name=" + name + ")");
        continue;
      }
      console.log("[main] evict-orphan: KILLING orphan python PID=" + pid);
      try { process.kill(pid, "SIGKILL"); } catch (_killErr) {
        try { require("child_process").execSync("taskkill /F /PID " + pid, { timeout: 2000, stdio: ["ignore", "pipe", "ignore"] }); } catch (_) {}
      }
    } catch (_wmixErr) { /* PID vanished */ }
  }
  // Small wait so the OS fully releases the socket (avoids TIME_WAIT false reject).
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500);
}

function _spawnNewPython() {
  if (pythonProc) return;
  _setBootingDeadline();
  _recomputeBackendState();
  broadcastHealth();
  EXPECTED_BACKEND_INSTANCE_ID = crypto.randomUUID();
  console.log("[main] starting Python backend:", PY_MAIN);

  pythonProc = spawn(PYTHON_EXE, [PY_MAIN], {
    cwd: PYTHON_ROOT,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1",
      // 打包态禁用用户站点包，确保后端只用随包分发的自包含依赖，
      // 不被目标机器上用户全局安装的 Python 包污染（版本冲突/环境漂移）。
      ...(app.isPackaged ? { PYTHONNOUSERSITE: "1" } : {}),
      AERIE_DATA_DIR: BACKEND_DATA_DIR,
      AERIE_DB_PATH: BACKEND_DB_PATH,
      AERIE_BACKEND_PORT: String(PY_PORT),
      AERIE_BACKEND_INSTANCE_ID: EXPECTED_BACKEND_INSTANCE_ID,
      AERIE_MAIN_PROCESS_TOKEN: MAIN_PROCESS_TOKEN,
      LOG_DIR: BACKEND_LOG_DIR,
    },
  });

  pythonProc.stdout.on("data", (d) => { /* ignore */ });
  pythonProc.stderr.on("data", handleStderr);

  pythonProc.on("error", (err) => {
    console.error("[main] python spawn error:", err.message);
  });
  pythonProc.on("exit", (code, sig) => {
    console.log("[main] python exited code=" + code + " sig=" + sig);
    pythonProc = null;
    _backendReady = false;
    _recomputeBackendState();
    broadcastHealth();
    // v2.2: keep watching for a respawn so a "restart backend" click
    // can flip _backendReady back to true without an Electron reload.
    if (!_pendingHealthInterval) {
      _pendingHealthInterval = setInterval(async () => {
        try {
          const ok = await healthCheck();
          if (ok) {
            _backendReady = true;
            _recomputeBackendState();
            broadcastHealth();
            clearInterval(_pendingHealthInterval);
            _pendingHealthInterval = null;
          } else {
            _recomputeBackendState();
          }
        } catch (_) { _recomputeBackendState(); }
      }, 1000);
    }
  });

  // Poll until backend is ready. Also tick the boot-deadline each round so
  // "启动中…" gracefully falls back to "后端离线" if Python is hanging.
  _pendingHealthInterval = setInterval(async () => {
    try {
      const ok = await healthCheck();
      if (ok) {
        _backendReady = true;
        _recomputeBackendState();
        broadcastHealth();
        clearInterval(_pendingHealthInterval);
        _pendingHealthInterval = null;
      } else {
        _recomputeBackendState();
        if (_backendState === "offline") broadcastHealth();
      }
    } catch (_) {
      _recomputeBackendState();
      if (_backendState === "offline") broadcastHealth();
    }
  }, 1000);
}

// ── 运行时自举失败兜底 ─────────────────────────────
// 三个下载源全部失败时：弹窗提示 + 落盘手动安装教程。
let _runtimeBootstrapDialogShown = false;

function _showRuntimeBootstrapFailure(rt) {
  const tutorial = rt && rt.tutorial ? rt.tutorial : buildManualTutorial();
  const tutorialPath = path.join(app.getPath("userData"), "运行环境安装教程.txt");
  try {
    fs.writeFileSync(tutorialPath, tutorial, "utf8");
    console.log("[main] runtime bootstrap tutorial written:", tutorialPath);
  } catch (err) {
    console.error("[main] failed to write tutorial:", err.message);
  }

  if (_runtimeBootstrapDialogShown) return;
  _runtimeBootstrapDialogShown = true;

  const reason = (rt && rt.reason) || "未知错误";
  const detail =
    `Aerie · 云栖 无法自动下载 Python 运行环境。\n\n` +
    `原因：${reason}\n\n` +
    `已生成手动安装教程：\n${tutorialPath}\n\n` +
    `按教程补齐运行环境后，重启应用即可。`;

  let choice = 1;
  try {
    choice = dialog.showMessageBoxSync({
      type: "error",
      title: "运行环境缺失",
      message: "无法启动后端服务（Python 运行环境缺失）",
      detail,
      buttons: ["打开教程", "稍后处理"],
      defaultId: 0,
      cancelId: 1,
    });
  } catch (_) {}

  if (choice === 0) {
    shell.openPath(tutorialPath).catch(() => {});
  }
}

/**
 * R6.6 FIX — Real Electron-parent-level backend restart.
 *
 * This is the ONLY reliable way to restart the backend when the backend
 * itself is OFFLINE (port not listening, HTTP 5xx, pythonProc died).
 *
 * The previous chain (settings button → IPC → HTTP POST /api/system/restart
 * → Python spawns a PowerShell helper → helper kills Python and re-launches
 * main.py) had THREE stacked bugs:
 *   1. If backend is already offline, the HTTP request fails immediately and
 *      the helper script never runs — the exact scenario users complain about.
 *   2. The helper re-launched main.py WITHOUT the 10+ Electron env vars
 *      (AERIE_DATA_DIR / AERIE_BACKEND_INSTANCE_ID / MAIN_PROCESS_TOKEN /
 *       PYTHONIOENCODING / LOG_DIR …), so the new backend had the wrong
 *      profile, wrong DB, and the UI kept showing "backend offline".
 *   3. The new Python was an orphan process NOT parented under Electron, so
 *      `pythonProc.stderr` stream (which carries all [CHAT_EVENT] JSON lines
 *      that feed the renderer / dynamic island / emotion updates) was lost
 *      FOREVER — health returned 200 but *nothing* streamed any more.
 *
 * This helper kills the running child (if any), resets shared state,
 * rolls a fresh EXPECTED_BACKEND_INSTANCE_ID, and calls the SAME
 * `_spawnNewPython()` path used at cold boot → env vars, stderr pipe,
 * instance-id all line up perfectly.
 */
function _forceRestartPythonBackend() {
  // 1) Clear any in-flight health polling so we don't race the old backend.
  if (_pendingHealthInterval) {
    clearInterval(_pendingHealthInterval);
    _pendingHealthInterval = null;
  }

  // 2) If we still hold a valid pythonProc, kill it forcefully.
  if (pythonProc && typeof pythonProc.pid === "number") {
    try {
      // Best-effort graceful first; Node kill() on Windows is always force.
      pythonProc.kill("SIGKILL");
    } catch (_) { /* ignore */ }
    // Give the OS ~300ms to reclaim the port before we respawn.
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 300);
  }
  // Force-reset the handle even if kill() threw, so _spawnNewPython won't bail.
  pythonProc = null;
  _backendReady = false;
  _setBootingDeadline();
  _recomputeBackendState();
  broadcastHealth();

  // 3) Roll a fresh instance id. This is critical: the old id matched the
  //    dead process; if we kept it, health-check's instance-id gate would
  //    reject our new child (even though *we* spawned it).
  EXPECTED_BACKEND_INSTANCE_ID = crypto.randomUUID();
  console.log("[main] restart backend: new EXPECTED_BACKEND_INSTANCE_ID =",
    EXPECTED_BACKEND_INSTANCE_ID.slice(0, 8) + "...");

  // 4) Spawn via the SAME code path as cold boot.
  //    startPythonBackend() probes the port first:
  //      - if an orphan backend already occupied the port (e.g. leftover from
  //        the previous broken ps1 restart path), it ATTACHES cleanly instead
  //        of spawning a duplicate that would fail EADDRINUSE;
  //      - if the port is free, it calls _spawnNewPython() for us with full
  //        env-var parity, stderr-event plumbing, health polling, etc.
  //    This is strictly safer than calling _spawnNewPython() directly.
  startPythonBackend();
}

function handleStderr(chunk) {
  const s = _stderrDecoder.write(Buffer.from(chunk));
  // R7.3: write ALL stderr (not just CHAT_EVENT lines) to a permanent log
  // so users can diagnose startup crash / traceback / missing modules
  // without needing a debugger.
  _appendRawStderr(s);
  // R7.3: fatal pattern detection → broadcast a `backend:fatal` event so
  // the UI can tell the user where the raw log is and what the error was,
  // instead of silently spinning "启动中…" forever.
  _broadcastBackendFatalIfNeeded(s);
  // Parse [CHAT_EVENT] lines
  _chatEventBuf += s;
  let nl;
  while ((nl = _chatEventBuf.indexOf("\n")) >= 0) {
    const line = _chatEventBuf.slice(0, nl);
    _chatEventBuf = _chatEventBuf.slice(nl + 1);
    const ix = line.indexOf(CHAT_EVENT_PREFIX);
    if (ix < 0) continue;
    const jsonPart = line.slice(ix + CHAT_EVENT_PREFIX.length).trim();
    let payload;
    try { payload = JSON.parse(jsonPart); } catch (_) { continue; }
    emitChatEvent(payload);
  }
}

function emitChatEvent(payload) {
  const wins = BrowserWindow.getAllWindows();
  for (const w of wins) {
    if (w && !w.isDestroyed()) {
      w.webContents.send("chat:message", payload);
    }
  }
}

function sendBackendState(win, includeReadyEvent = false) {
  if (!win || win.isDestroyed()) return;
  _recomputeBackendState();
  win.webContents.send("backend:health", { ready: _backendReady, state: _backendState });
  if (!includeReadyEvent || !_backendReady) return;
  const readyEvent = {
    type: "backend_ready",
    backendInstanceId: EXPECTED_BACKEND_INSTANCE_ID || "compatible-existing",
  };
  win.webContents.send("backend:ready", readyEvent);
  win.webContents.send("chat:message", readyEvent);
}

function broadcastHealth() {
  const becameReady = _backendReady && !_lastBroadcastBackendReady;
  for (const win of BrowserWindow.getAllWindows()) {
    sendBackendState(win, becameReady);
  }
  // 开场动画窗口可能晚于首次广播才完成加载，这里显式补发一次，
  // 确保进度条一定能拿到当前后端状态（ready / booting / offline）。
  if (splashWindow && !splashWindow.isDestroyed()) {
    sendBackendState(splashWindow, false);
  }
  _lastBroadcastBackendReady = _backendReady;
  if (_backendReady) {
    _worldConnectionSignature = "";
    reconcileWorldRuntime().catch(() => {});
  }
}

function readLegacyBackendDatabasePath() {
  return new Promise((resolve) => {
    const req = http.get(PY_BACKEND + "/api/stats/system", (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
      res.on("end", () => {
        const data = decodeBufferedUtf8Chunks(chunks);
        try {
          const payload = JSON.parse(data);
          resolve(payload && payload.database_path ? payload.database_path : null);
        } catch (_) {
          resolve(null);
        }
      });
    });
    req.on("error", () => resolve(null));
    req.setTimeout(2000, () => { req.destroy(); resolve(null); });
  });
}

function healthCheck() {
  return new Promise((resolve) => {
    const req = http.get(PY_BACKEND + "/api/health", (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(Buffer.from(c)));
      res.on("end", async () => {
        const d = decodeBufferedUtf8Chunks(chunks);
        try {
          const j = JSON.parse(d);
          const legacyDbPath = j.data_path_id
            ? null
            : await readLegacyBackendDatabasePath();
          resolve(backendHealthMatches({
            payload: j,
            expectedDbPath: BACKEND_DB_PATH,
            expectedInstanceId: EXPECTED_BACKEND_INSTANCE_ID,
            legacyDbPath,
          }));
        } catch (_) {
          resolve(false);
        }
      });
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2000, () => { req.destroy(); resolve(false); });
  });
}

// P4b: 管理平台 token（后端 unlock 后落 BACKEND_DATA_DIR/admin_unlock.token）。
function getAdminToken() {
  try {
    return fs.readFileSync(path.join(BACKEND_DATA_DIR, "admin_unlock.token"), "utf-8").trim();
  } catch (_) {
    return "";
  }
}

function apiRequest(opts) {
  return new Promise((resolve, reject) => {
    const url = new URL(PY_BACKEND + (opts.path || "/"));
    const isRaw = opts.rawBody === true;
    const headers = isRaw
      ? { "Content-Type": "text/plain; charset=utf-8" }
      : { "Content-Type": "application/json" };
    if (opts.internal === true) {
      headers["X-Aerie-Main-Token"] = MAIN_PROCESS_TOKEN;
    }
    if (opts.admin === true) {
      headers["X-Aerie-Admin-Token"] = getAdminToken();
    }
    const options = {
      hostname: "127.0.0.1",
      port: PY_PORT,
      path: url.pathname + url.search,
      method: opts.method || "GET",
      headers,
      timeout: 30000,
    };
    const req = http.request(options, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(Buffer.from(c)));
      res.on("end", () => {
        const d = decodeBufferedUtf8Chunks(chunks);
        let body;
        const ct = (res.headers && res.headers["content-type"] || "").toLowerCase();
        if (ct.indexOf("application/json") >= 0) {
          try { body = JSON.parse(d); } catch (_) { body = d; }
        } else if (isRaw) {
          body = d; // keep as text for raw text/plain responses (e.g. yaml GET)
        } else {
          try { body = JSON.parse(d); } catch (_) { body = d; }
        }
        const result = { status: res.statusCode, data: body };
        if (res.statusCode < 200 || res.statusCode >= 300) {
          const message = body && body.error ? body.error : `HTTP ${res.statusCode}`;
          const err = new Error(message);
          err.status = res.statusCode;
          err.data = body;
          reject(err);
          return;
        }
        resolve(result);
      });
    });
    req.on("error", (err) => reject(err));
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    if (opts.body) {
      if (isRaw) {
        req.write(String(opts.body));
      } else if (typeof opts.body === "string") {
        req.write(opts.body);
      } else {
        req.write(JSON.stringify(opts.body));
      }
    }
    req.end();
  });
}

// ── Windows ────────────────────────────────────────
function ensureDynamicIslandOnTop() {
  if (!dynamicIsland || dynamicIsland.isDestroyed() || !dynamicIsland.isVisible()) return false;
  dynamicIsland.setAlwaysOnTop(true, DYNAMIC_ISLAND_TOP_LEVEL);
  dynamicIsland.moveTop();
  return true;
}

const MAIN_TAB_ALIASES = Object.freeze({ calendar: "memorial" });

function dispatchMainNavigation(tab, payload) {
  if (!tab || !mainWindow || mainWindow.isDestroyed() || !mainWindowReady) return false;
  try {
    if (tab === "brief") {
      if (payload === undefined) {
        mainWindow.webContents.send("brief:show");
      } else {
        mainWindow.webContents.send("brief:show", payload);
      }
    } else {
      mainWindow.webContents.send("ui:open-tab", MAIN_TAB_ALIASES[tab] || tab);
    }
  } catch (error) {
    console.warn("[main] navigation dispatch failed:", error);
    return false;
  }
  return true;
}

function flushPendingMainNavigation() {
  if (!pendingMainNavigation) return false;
  const navigation = pendingMainNavigation;
  if (!dispatchMainNavigation(navigation.tab, navigation.payload)) return false;
  if (pendingMainNavigation === navigation) pendingMainNavigation = null;
  return true;
}

function queueMainNavigation(tab, payload) {
  if (!tab) return false;
  pendingMainNavigation = { tab, payload };
  return flushPendingMainNavigation();
}

function hasBackgroundRecoverySurface() {
  const hasTray = Boolean(tray && !tray.isDestroyed());
  const hasVisibleIsland = Boolean(
    dynamicIsland && !dynamicIsland.isDestroyed() && dynamicIsland.isVisible(),
  );
  return hasTray || hasVisibleIsland;
}

// ── Splash（开场动画）────────────────────────────────
// 全屏、无边框、置顶、不进任务栏，且不可交互：视频与 LOGO 阶段
// 都由渲染层设置 pointer-events:none / 禁右键 / 无控制条。
function determineSplashMode() {
  const state = _loadLaunchState();
  const version = app.getVersion();
  const bootSession = _getBootSessionId();
  // 本版本第一次开启 → 播放视频
  if (state.video_played_version !== version) {
    return "video";
  }
  // 新开机会话（系统重启后）→ 只播放加载动画
  if (state.loading_boot_session !== bootSession) {
    return "loading";
  }
  // 同一开机会话内的应用重启 → 不开屏
  return "none";
}

function createSplashWindow(mode = "video") {
  if (splashWindow && !splashWindow.isDestroyed()) return splashWindow;
  _splashMode = mode;

  // 开场动画窗口尺寸与主窗口一致：不强制全屏、不置顶，避免干扰其它操作
  const { width: workW, height: workH } = screen.getPrimaryDisplay().workAreaSize;
  splashWindow = new BrowserWindow({
    frame: false,
    width: Math.min(1280, workW),
    height: Math.min(800, workH),
    skipTaskbar: true,
    resizable: false,
    minimizable: false,
    maximizable: false,
    closable: false,
    show: false,
    backgroundColor: "#000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 主进程侧兜底：禁止右键菜单，保证开场动画不可交互
  splashWindow.webContents.on("context-menu", (event) => event.preventDefault());

  splashWindow.loadFile(path.join(__dirname, "renderer", "splash.html"));

  splashWindow.once("ready-to-show", () => {
    if (!splashWindow || splashWindow.isDestroyed()) return;
    splashWindow.show();
    splashWindow.moveTop();
  });

  splashWindow.on("closed", () => {
    splashWindow = null;
  });

  return splashWindow;
}

// 关闭开场动画并显示主窗口。幂等：多次触发只执行一次，避免重复弹窗。
function finishSplash() {
  if (_splashDone) return;
  _splashDone = true;
  // 持久化开屏状态：标记本版本视频已播 + 本次开机会话已播加载动画
  _saveLaunchState({
    video_played_version: app.getVersion(),
    loading_boot_session: _getBootSessionId(),
  });
  if (splashWindow && !splashWindow.isDestroyed()) {
    // 窗口以 closable:false 创建，必须先解除关闭限制，否则 close() 失效，
    // 开场动画窗口会永远盖在主窗口上（与 dynamicIsland 关闭前 setClosable(true) 同理）。
    splashWindow.setClosable(true);
    splashWindow.close();
  }
  if (isStartMinimizedArgPresent()) {
    // 最小化启动：开场动画播完后主窗口保持隐藏
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.hide();
    }
    return;
  }
  showMainWindow();
}

function createMainWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  console.log("[main] creating main window:", { width, height, argv: process.argv });
  mainWindowReady = false;

  mainWindow = new BrowserWindow({
    width: Math.min(1280, width),
    height: Math.min(800, height),
    minWidth: 900,
    minHeight: 600,
    frame: false,
    transparent: false,
    backgroundColor: "#ffffff",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: ICON_PATH,
  });

  mainWindow.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === "audio" || permission === "media" || permission === "microphone") {
      callback(true);
    } else {
      callback(false);
    }
  });

  mainWindow.webContents.session.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
    if (permission === "audio" || permission === "media" || permission === "microphone") {
      return true;
    }
    return false;
  });

  mainWindow.webContents.on("console-message", (_event, level, message, line, source) => {
    if (level >= 2 || process.env.AERIE_DEBUG_LOGS === "1") {
      console.log(`[RENDERER] ${message} (${source}:${line})`);
    }
  });

  let readyToShow = false;
  const readyToShowTimer = setTimeout(() => {
    if (readyToShow || !mainWindow || mainWindow.isDestroyed()) return;
    console.error("[main] main window ready-to-show timeout; forcing visibility");
    // 开场动画未结束前不抢着显示主窗口，避免 splash 被提前顶掉
    if (_splashDone) showMainWindow();
  }, 8000);

  mainWindow.webContents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
    console.error("[main] renderer did-fail-load:", { code, description, url, isMainFrame });
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    mainWindowReady = false;
    console.error("[main] renderer process gone:", details);
  });
  mainWindow.webContents.on("unresponsive", () => {
    console.error("[main] renderer became unresponsive");
  });
  mainWindow.webContents.on("responsive", () => {
    console.log("[main] renderer responsive again");
  });
  mainWindow.webContents.on("did-start-loading", () => {
    mainWindowReady = false;
  });
  mainWindow.webContents.on("did-finish-load", () => {
    mainWindowReady = true;
    // A fast or pre-existing backend can become ready before the Renderer has
    // registered listeners. Always replay the current state to this window.
    sendBackendState(mainWindow, _backendReady);
    flushPendingMainNavigation();
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.once("ready-to-show", () => {
    readyToShow = true;
    clearTimeout(readyToShowTimer);
    console.log("[main] main window ready-to-show");
    // 开场动画未结束时主窗口保持隐藏，等 splash:complete 再显示
    if (!_splashDone) {
      mainWindow.hide();
      return;
    }
    if (isStartMinimizedArgPresent()) {
      mainWindow.hide();
    } else {
      mainWindow.center();
      showMainWindow();
    }
    console.log("[main] main window visibility:", {
      visible: mainWindow.isVisible(),
      bounds: mainWindow.getBounds(),
      nativeHandle: mainWindow.getNativeWindowHandle().toString("hex"),
    });
  });
  mainWindow.on("show", () => {
    console.log("[main] main window shown");
    ensureDynamicIslandOnTop();
  });
  mainWindow.on("focus", ensureDynamicIslandOnTop);
  mainWindow.on("restore", ensureDynamicIslandOnTop);
  mainWindow.on("enter-full-screen", ensureDynamicIslandOnTop);
  mainWindow.on("leave-full-screen", ensureDynamicIslandOnTop);
  mainWindow.on("enter-html-full-screen", ensureDynamicIslandOnTop);
  mainWindow.on("leave-html-full-screen", ensureDynamicIslandOnTop);
  mainWindow.on("hide", () => console.log("[main] main window hidden"));
  mainWindow.on("close", (event) => {
    if (isQuitting) return;
    if (hasBackgroundRecoverySurface()) {
      event.preventDefault();
      mainWindow.hide();
      return;
    }
    isQuitting = true;
    setImmediate(() => app.quit());
  });
  mainWindow.on("closed", () => {
    console.log("[main] main window closed");
    mainWindowReady = false;
    mainWindow = null;
  });

  // Broadcast maximize state changes to renderer so the button glyph can update
  mainWindow.on("maximize", () => {
    broadcastMaximizeState(true);
    ensureDynamicIslandOnTop();
  });
  mainWindow.on("unmaximize", () => {
    broadcastMaximizeState(false);
    ensureDynamicIslandOnTop();
  });
}

function showMainWindow(tab, payload) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    if (!app.isReady()) return false;
    createMainWindow();
  }

  if (mainWindow.webContents.isCrashed()) {
    mainWindowReady = false;
    mainWindow.webContents.reload();
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.setSkipTaskbar(false);
  mainWindow.setOpacity(1);
  mainWindow.show();
  mainWindow.moveTop();
  mainWindow.focus();
  ensureDynamicIslandOnTop();
  if (tab) queueMainNavigation(tab, payload);
  return true;
}

// ── Dynamic Island ────────────────────────────────
// R8.1: Dynamic-island master enable state. Defaults ON for users who
//       don't have the prefs file yet. The state is persisted to
//       {BACKEND_DATA_DIR}/island_prefs.json so (a) restarting the app
//       preserves user choice and (b) the choice is not tied to the
//       Python backend — if the backend is offline we still respect it.
//
//       We do NOT use the Python settings.yaml round-trip for this one
//       because: (1) it creates a circular dependency on backend being up,
//       which matches the exact failure pattern the user just reported,
//       and (2) the island window is 100% Electron-side code.
let _islandEnabled = true;
let _islandPrefsPath = null;

function _resolveIslandPrefsPath() {
  if (_islandPrefsPath) return _islandPrefsPath;
  const base = BACKEND_DATA_DIR
    ? path.resolve(BACKEND_DATA_DIR)
    : (app.getPath ? path.resolve(app.getPath("userData")) : process.cwd());
  try { fs.mkdirSync(base, { recursive: true }); } catch (_) {}
  _islandPrefsPath = path.join(base, "island_prefs.json");
  return _islandPrefsPath;
}
function _loadIslandPrefs() {
  if (process.env.AERIE_DISABLE_DYNAMIC_ISLAND === "1") {
    _islandEnabled = false;
    return;
  }
  const p = _resolveIslandPrefsPath();
  try {
    if (fs.existsSync(p)) {
      const raw = fs.readFileSync(p, "utf8");
      const obj = JSON.parse(raw || "{}");
      if (obj && typeof obj.enabled === "boolean") _islandEnabled = obj.enabled;
      // 恢复上次应用的灵动岛配置（主题/触发方式/组件勾选），否则重启后
      // 设置面板的勾选框会回到初始默认值。
      if (obj && obj.config && typeof obj.config === "object") {
        _islandConfig = Object.assign({}, _islandConfig, obj.config);
      }
    }
  } catch (_e) {
    // Corrupt JSON or ACL problem — fall back to the default (enabled).
    console.warn("[main] failed to read island_prefs.json, defaulting to enabled:", _e && _e.message);
    _islandEnabled = true;
  }
}
function _saveIslandPrefs() {
  const p = _resolveIslandPrefsPath();
  try {
    fs.writeFileSync(
      p,
      JSON.stringify({ enabled: _islandEnabled, config: _islandConfig || {}, updatedAt: Date.now() }, null, 2),
      { encoding: "utf8" }
    );
    return true;
  } catch (_e) {
    console.warn("[main] failed to save island_prefs.json:", _e && _e.message);
    return false;
  }
}

// ── Launch state (开场动画 / 加载动画的播放状态持久化) ──
// 记录「本版本视频是否已播」+「加载动画最近一次播放的开机会话」，用于
// 判断开屏模式：video（本版本首启）→ loading（新开机）→ none（同开机会话内重启）。
let _launchStatePath = null;
function _resolveLaunchStatePath() {
  if (_launchStatePath) return _launchStatePath;
  const base = BACKEND_DATA_DIR
    ? path.resolve(BACKEND_DATA_DIR)
    : (app.getPath ? path.resolve(app.getPath("userData")) : process.cwd());
  try { fs.mkdirSync(base, { recursive: true }); } catch (_) {}
  _launchStatePath = path.join(base, "launch_state.json");
  return _launchStatePath;
}
function _loadLaunchState() {
  const p = _resolveLaunchStatePath();
  try {
    if (fs.existsSync(p)) {
      const obj = JSON.parse(fs.readFileSync(p, "utf8") || "{}");
      return {
        video_played_version: obj.video_played_version || "",
        loading_boot_session: obj.loading_boot_session || 0,
      };
    }
  } catch (_e) {
    console.warn("[main] failed to read launch_state.json:", _e && _e.message);
  }
  return { video_played_version: "", loading_boot_session: 0 };
}
function _saveLaunchState(state) {
  const p = _resolveLaunchStatePath();
  try {
    fs.writeFileSync(p, JSON.stringify(state, null, 2), { encoding: "utf8" });
    return true;
  } catch (_e) {
    console.warn("[main] failed to save launch_state.json:", _e && _e.message);
    return false;
  }
}
// 用系统运行时长推算本次开机会话标识（分钟粒度），系统重启后该值会变化。
function _getBootSessionId() {
  try {
    return Math.floor((Date.now() - os.uptime() * 1000) / 60000);
  } catch (_) {
    return 0;
  }
}

// ── System notifications master switch ───────────────
// 消息提醒总开关：控制所有系统通知（新消息 / 日程 / 主动消息）。状态持久化
// 到 {BACKEND_DATA_DIR}/notif_prefs.json，与灵动岛主开关同一套模式 ——
// 纯 Electron 侧管理，不依赖 Python 后端在线。关闭后 system:notify 直接
// 短路，窗口是否聚焦也不再弹系统通知。
let _notificationsEnabled = true;
let _notifPrefsPath = null;

function _resolveNotifPrefsPath() {
  if (_notifPrefsPath) return _notifPrefsPath;
  const base = BACKEND_DATA_DIR
    ? path.resolve(BACKEND_DATA_DIR)
    : (app.getPath ? path.resolve(app.getPath("userData")) : process.cwd());
  try { fs.mkdirSync(base, { recursive: true }); } catch (_) {}
  _notifPrefsPath = path.join(base, "notif_prefs.json");
  return _notifPrefsPath;
}
function _loadNotifPrefs() {
  if (process.env.AERIE_DISABLE_NOTIFICATIONS === "1") {
    _notificationsEnabled = false;
    return;
  }
  const p = _resolveNotifPrefsPath();
  try {
    if (fs.existsSync(p)) {
      const raw = fs.readFileSync(p, "utf8");
      const obj = JSON.parse(raw || "{}");
      if (obj && typeof obj.enabled === "boolean") _notificationsEnabled = obj.enabled;
    }
  } catch (_e) {
    console.warn("[main] failed to read notif_prefs.json, defaulting to enabled:", _e && _e.message);
    _notificationsEnabled = true;
  }
}
function _saveNotifPrefs() {
  const p = _resolveNotifPrefsPath();
  try {
    fs.writeFileSync(
      p,
      JSON.stringify({ enabled: _notificationsEnabled, updatedAt: Date.now() }, null, 2),
      { encoding: "utf8" }
    );
    return true;
  } catch (_e) {
    console.warn("[main] failed to save notif_prefs.json:", _e && _e.message);
    return false;
  }
}
function _broadcastNotifEnabled() {
  const payload = {
    enabled: _notificationsEnabled,
    prefsPath: _notifPrefsPath || "",
    updatedAt: Date.now(),
  };
  const wins = BrowserWindow.getAllWindows();
  for (const w of wins) {
    if (!w || w.isDestroyed()) continue;
    try { w.webContents.send("notif:enabled-change", payload); } catch (_) {}
  }
}
function _isIslandWindowAlive() {
  return Boolean(dynamicIsland && !dynamicIsland.isDestroyed());
}
function _broadcastIslandEnabled() {
  const payload = {
    enabled: _islandEnabled,
    visible: _isIslandWindowAlive() && dynamicIsland.isVisible(),
    windowExists: _isIslandWindowAlive(),
    prefsPath: _islandPrefsPath || "",
    updatedAt: Date.now(),
  };
  const wins = BrowserWindow.getAllWindows();
  for (const w of wins) {
    if (!w || w.isDestroyed()) continue;
    try { w.webContents.send("island:enabled-change", payload); } catch (_) {}
  }
}
function _applyIslandEnabledToWindow() {
  if (_islandEnabled) {
    if (!_isIslandWindowAlive()) {
      // The env guard was the *only* gate before R8.1; we keep it as a safety
      // escape hatch for headless / CI / broken-GPU-machine users.
      if (process.env.AERIE_DISABLE_DYNAMIC_ISLAND === "1") {
        console.log("[main] _applyIslandEnabledToWindow: skipping create (env AERIE_DISABLE_DYNAMIC_ISLAND=1)");
        return;
      }
      createDynamicIsland();
    } else if (!dynamicIsland.isVisible()) {
      dynamicIsland.showInactive();
    }
  } else {
    if (_isIslandWindowAlive()) {
      stopSystemStatusPolling();
      _stopMediaPolling();
      _cleanupOldThumbnail();
      try { dynamicIsland.setClosable(true); } catch (_) {}
      try { dynamicIsland.hide(); } catch (_) {}
      try { dynamicIsland.close(); } catch (_) {}
      // Windows destroy is async; give it a tick before broadcasting so
      // callers checking "is there a window" don't see a stale handle.
      setTimeout(() => {
        if (dynamicIsland && !dynamicIsland.isDestroyed()) {
          try { dynamicIsland.destroy(); } catch (_) {}
        }
        dynamicIsland = null;
        _broadcastIslandEnabled();
      }, 0);
    }
  }
}

function createDynamicIsland() {
  if (dynamicIsland) return;

  const display = screen.getPrimaryDisplay();
  const { workArea } = display;
  // 窗口固定为「最大尺寸」：宽 = 最大内容宽度(宽屏 720) + 两侧 10px 边距；
  // 高 = 胶囊 44 + 面板最大展开高 640 + 上下 10px 边距。
  // hover 拉长 / 点击展开 / 宽屏 的宽度动画全部在窗口内居中完成，窗口不再
  // resize —— 从根本上消除「CSS 动画先于 setBounds 反应」的瞬时裁切与闪烁。
  // 桌面遮挡由「动态鼠标穿透」解决：renderer 按鼠标位置实时切换
  // setIgnoreMouseEvents（鼠标在交互区则接收，否则穿透；按住 ALT 强制穿透）。
  const ISLAND_EDGE = 10;
  const width = 720 + ISLAND_EDGE * 2; // 740
  const height = 44 + 640 + ISLAND_EDGE * 2; // 704
  const x = Math.round(workArea.x + (workArea.width - width) / 2);
  const y = workArea.y + 12;

  dynamicIsland = new BrowserWindow({
    width,
    height,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    minimizable: false,
    maximizable: false,
    closable: false,
    focusable: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  dynamicIsland.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  ensureDynamicIslandOnTop();
  // 初始穿透：窗口尺寸固定最大，靠 renderer 按鼠标位置动态切换穿透，
  // 鼠标不在灵动岛交互区时窗口不拦截桌面点击（forward 转发 mousemove 供判断）。
  _islandIgnoreState = true;
  dynamicIsland.setIgnoreMouseEvents(true, { forward: true });

  dynamicIsland.loadFile(path.join(__dirname, "renderer", "dynamic-island.html"));

  dynamicIsland.webContents.on("did-finish-load", () => {
    ensureDynamicIslandOnTop();
    startSystemStatusPolling();
    _startMediaPolling();
  });

  dynamicIsland.on("show", () => {
    ensureDynamicIslandOnTop();
    _startMediaPolling();
  });
  dynamicIsland.on("hide", _stopMediaPolling);

  dynamicIsland.on("closed", () => {
    stopSystemStatusPolling();
    _stopMediaPolling();
    _cleanupOldThumbnail();
    dynamicIsland = null;
  });
}

// ── World Dashboard 独立窗口 ──────────────────
// R7.x: "显示插件/隐藏插件"真正弹窗/关窗。窗口为单实例，关闭按钮等同 hide 语义。
function openWorldDashboardWindow() {
  if (worldDashboardWindow && !worldDashboardWindow.isDestroyed()) {
    worldDashboardWindow.show();
    worldDashboardWindow.focus();
    return worldDashboardWindow;
  }
  worldDashboardWindow = new BrowserWindow({
    width: 520,
    height: 720,
    minWidth: 400,
    minHeight: 520,
    title: "AERIE.WORLD · 世界仪表盘",
    backgroundColor: "#ffffff",
    frame: false,
    icon: ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, "world-dashboard-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  worldDashboardWindow.loadFile(path.join(__dirname, "renderer", "world-dashboard-window.html"));
  worldDashboardWindow.on("closed", () => {
    // 关窗（含 X 按钮）同步宿主 hide 语义，保持状态一致。
    worldDashboardWindow = null;
    try { worldDashboardHost.hide(); } catch (_) {}
  });
  return worldDashboardWindow;
}

// ── P4b 管理平台独立窗口（懒创建：首次入口点击才实例化） ──
let adminWindow = null;

function openAdminWindow() {
  if (adminWindow && !adminWindow.isDestroyed()) {
    adminWindow.show();
    adminWindow.focus();
    return adminWindow;
  }
  adminWindow = new BrowserWindow({
    width: 920,
    height: 720,
    minWidth: 760,
    minHeight: 560,
    title: "AERIE.ADMIN · 管理平台",
    backgroundColor: "#ffffff",
    frame: false,
    icon: ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, "admin-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  adminWindow.loadFile(path.join(__dirname, "renderer", "admin-window.html"));
  adminWindow.on("closed", () => { adminWindow = null; });
  return adminWindow;
}

// ── Dynamic Island Mouse Input ──────────────
let _islandIgnoreState = false;
let _islandExpanded = false;

function setIslandExpanded(expanded) {
  _islandExpanded = Boolean(expanded);
  setIslandIgnoreMouse(false);
  if (_mediaPollingActive) _scheduleMediaPoll(0);
}

function setIslandIgnoreMouse(ignore) {
  if (!dynamicIsland || dynamicIsland.isDestroyed()) return;
  if (_islandIgnoreState === ignore) return;
  _islandIgnoreState = ignore;
  dynamicIsland.setIgnoreMouseEvents(ignore, { forward: true });
}

function broadcastMaximizeState(isMax) {
  const wins = BrowserWindow.getAllWindows();
  for (const w of wins) {
    if (w && !w.isDestroyed()) {
      w.webContents.send("window:maximized", isMax);
    }
  }
}

// ── Tray ───────────────────────────────────────────
function createTray() {
  if (!fs.existsSync(ICON_PATH)) {
    console.warn("[main] tray icon not found:", ICON_PATH);
    return;
  }
  const icon = nativeImage.createFromPath(ICON_PATH).resize({ width: 16, height: 16 });
  if (icon.isEmpty()) {
    console.warn("[main] tray icon is empty:", ICON_PATH);
    return;
  }
  tray = new Tray(icon);
  tray.setToolTip("Aerie · 云栖");
  // Block-2 T1: right-click context menu
  const menu = Menu.buildFromTemplate([
    {
      label: "显示 / 隐藏窗口",
      click: () => {
        if (!mainWindow) return;
        if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
          mainWindow.hide();
        } else {
          showMainWindow();
        }
      },
    },
    {
      label: "显示 / 隐藏灵动岛",
      click: () => {
        if (!dynamicIsland) return;
        if (dynamicIsland.isVisible()) {
          dynamicIsland.hide();
        } else {
          dynamicIsland.showInactive();
        }
      },
    },
    { type: "separator" },
    {
      // R7.1: trigger the in-app right-side drawer (no separate window)
      label: "打开今日简报 / Open Brief",
      click: () => {
        showMainWindow("brief");
      },
    },
    {
      label: "展开完整日报 / Full Brief",
      click: () => {
        showMainWindow("brief", { expanded: true });
      },
    },
    {
      label: "设置",
      click: () => {
        showMainWindow("settings");
      },
    },
    { type: "separator" },
    {
      label: "重启后端 / Restart Backend",
      click: () => {
        restartBackend();
      },
    },
    {
      label: "重启应用 / Restart App",
      click: () => {
        restartApp();
      },
    },
    { type: "separator" },
    {
      label: "关于",
      click: () => {
        dialog.showMessageBox({
          type: "info",
          title: "Aerie · 云栖",
          message: "Aerie · 云栖",
          detail:
            "Aerie · 云栖 v" + app.getVersion() + "\n" +
            "A girl who walks with you through every step.\n" +
            "© 2026",
          buttons: ["好 / OK"],
          defaultId: 0,
        });
      },
    },
    { type: "separator" },
    {
      label: "退出",
      click: () => {
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(menu);
  tray.on("click", () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    }
  });
}

// R7.1: brief windows (popup + detail) are gone. The brief now lives
// inside the main window as a self-painted right-side drawer — no
// BrowserWindow, no IPC, no second process. The two tray menu items
// above just send a ``ui:open-brief`` IPC to the main window.

// ── IPC Handlers ───────────────────────────────────
ipcMain.handle("api:request", async (_event, opts) => {
  try {
    const rendererOptions = opts && typeof opts === "object" ? { ...opts } : {};
    delete rendererOptions.internal;
    return await apiRequest(rendererOptions);
  } catch (err) {
    return { status: 0, data: { error: err.message } };
  }
});

ipcMain.handle("world-dashboard:get-status", async () => {
  return await worldDashboardHost.getStatus();
});

ipcMain.handle("world-dashboard:get-snapshot", async () => {
  return await worldDashboardHost.getSnapshot();
});

// 独立仪表盘窗口专用：直接拉取后端快照 + 情绪状态（供 world.getState() 使用）。
// 不经过 host 的 isEnabled 门控：世界以 inprocess/sidecar 任一模式运行时，
// 后端快照即返回真实数据，仪表盘应如实展示。
ipcMain.handle("world-dashboard:get-state", async () => {
  let snapshot = {};
  let emotion = {};
  try {
    const r = await apiRequest({ method: "GET", path: "/api/world/dashboard/snapshot" });
    snapshot = (r && r.data && typeof r.data === "object") ? r.data : {};
  } catch (_) {}
  try {
    const r = await apiRequest({ method: "GET", path: "/api/emotion/state" });
    emotion = (r && r.data && typeof r.data === "object") ? r.data : {};
  } catch (_) {}
  return { ...snapshot, emotion };
});

// 只读记忆档案（P6）：白名单专用方法，仅返回公开元数据。
ipcMain.handle("world-dashboard:get-memory", async () => {
  try {
    const r = await apiRequest({ method: "GET", path: "/api/memory/list" });
    return (r && r.data && typeof r.data === "object") ? r.data : { layers: {}, total: 0 };
  } catch (_) {
    return { layers: {}, total: 0 };
  }
});

// 第三批（B3.2）只读聚合：内在状态 + 趋势 + 决策观察 + 插件设置。
// 一次 IPC 并行拉取，供 9 页中的 内在状态/决策/设置 复用。绝不暴露写路径。
ipcMain.handle("world-dashboard:get-b3", async () => {
  const out = { internal: {}, trends: [], cognition: [], permissions: {} };
  try {
    const r = await apiRequest({ method: "GET", path: "/api/internal/state" });
    out.internal = (r && r.data && typeof r.data === "object") ? r.data : {};
  } catch (_) {}
  try {
    const r = await apiRequest({ method: "GET", path: "/api/internal/history?limit=60" });
    const d = (r && r.data && typeof r.data === "object") ? r.data : {};
    out.trends = Array.isArray(d.items) ? d.items : [];
  } catch (_) {}
  try {
    const r = await apiRequest({ method: "GET", path: "/api/cognition/recent?limit=30" });
    const d = (r && r.data && typeof r.data === "object") ? r.data : {};
    out.cognition = Array.isArray(d.traces) ? d.traces : [];
    // P4: 候选决策日志（伪主观性证据），随 get-b3 一并透传。
    out.decisionLog = Array.isArray(d.decision_log) ? d.decision_log : [];
  } catch (_) {}
  try {
    const r = await apiRequest({ method: "GET", path: "/api/permissions/config" });
    out.permissions = (r && r.data && typeof r.data === "object") ? r.data : {};
  } catch (_) {}
  return out;
});

// 数据统计看板（P4）：只读聚合端点，供"统计"页图表使用。
ipcMain.handle("world-dashboard:get-stats", async (_event, windowParam) => {
  const win = typeof windowParam === "string" ? windowParam : "7d";
  try {
    const r = await apiRequest({ method: "GET", path: "/api/stats/dashboard?window=" + encodeURIComponent(win) });
    return (r && r.data && typeof r.data === "object") ? r.data : {};
  } catch (_) {
    return {};
  }
});

ipcMain.handle("world-dashboard:show", async () => {
  openWorldDashboardWindow();
  return await worldDashboardHost.show();
});

ipcMain.handle("world-dashboard:hide", async () => {
  if (worldDashboardWindow && !worldDashboardWindow.isDestroyed()) {
    worldDashboardWindow.close();
  }
  return await worldDashboardHost.hide();
});

// ── P4b 管理平台 IPC（懒加载；路径/method 双重白名单） ──
ipcMain.handle("admin:api", async (_event, input) => {
  const req = input && typeof input === "object" ? input : {};
  const method = String(req.method || "GET").toUpperCase();
  const path = String(req.path || "");
  if (!path.startsWith("/api/admin/")) return { ok: false, error: "bad_path" };
  if (!["GET", "POST", "PUT", "DELETE"].includes(method)) {
    return { ok: false, error: "bad_method" };
  }
  try {
    const r = await apiRequest({ method, path, body: req.body, admin: true });
    return { ok: true, status: r.status, data: r.data };
  } catch (err) {
    return {
      ok: false,
      status: (err && err.status) || 0,
      error: String((err && err.message) || err),
      data: err && err.data,
    };
  }
});

ipcMain.handle("admin:show", async () => {
  openAdminWindow();
  return { ok: true };
});

ipcMain.handle("attachments:open", async (_event, attachmentId) => {
  try {
    return await openDesktopAttachment(attachmentId);
  } catch (error) {
    return { ok: false, error: String((error && error.message) || error) };
  }
});

ipcMain.handle("attachments:download", async (_event, attachmentId) => {
  try {
    return await saveDesktopAttachment(attachmentId);
  } catch (error) {
    return { ok: false, error: String((error && error.message) || error) };
  }
});

ipcMain.handle("world-dashboard:control", async (_event, input) => {
  const payload = input && typeof input === "object" ? input : {};
  const result = await worldDashboardHost.control(
    payload.action,
    payload.payload && typeof payload.payload === "object" ? payload.payload : {},
  );
  await bindWorldConnectionToBackend(true);
  return result;
});

ipcMain.handle("world-dashboard:approve-candidate", async (_event, payload) => {
  return await worldDashboardHost.approveCandidate(payload || {});
});

ipcMain.handle("world-dashboard:preview-creative", async (_event, payload) => {
  return await worldDashboardHost.previewCreative(payload || {});
});

ipcMain.handle("world-dashboard:set-location", async (_event, payload) => {
  const city = payload && typeof payload === "object" ? String(payload.city || "") : "";
  const result = await worldDashboardHost.setWorldLocation(city);
  await bindWorldConnectionToBackend(true);
  return result;
});

// Dynamic Island IPC
ipcMain.on("ui:open-main", () => {
  showMainWindow();
});

ipcMain.on("ui:open-quick-chat", () => {
  showMainWindow("chat");
});

ipcMain.on("ui:quit-app", () => {
  app.quit();
});

// Dynamic Island control IPC
let _islandIgnoreDebounce = null;

ipcMain.handle("island:set-size", async (_event, { width, height }) => {
  if (!dynamicIsland || dynamicIsland.isDestroyed()) return { ok: false };
  try {
    const [x, y] = dynamicIsland.getPosition();
    const currentSize = dynamicIsland.getSize();
    const newX = Math.round(x + (currentSize[0] - width) / 2);
    dynamicIsland.setBounds({ x: newX, y, width, height }, true);
    return { ok: true };
  } catch (err) {
    console.error("[DynamicIsland] setBounds error:", err.message);
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("island:set-ignore-mouse", async (_event, { ignore }) => {
  if (!dynamicIsland || dynamicIsland.isDestroyed()) return { ok: false };
  try {
    if (_islandIgnoreDebounce) clearTimeout(_islandIgnoreDebounce);
    _islandIgnoreDebounce = setTimeout(() => {
      setIslandIgnoreMouse(!!ignore);
    }, 60);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("island:state-change", async (_event, { expanded }) => {
  setIslandExpanded(!!expanded);
  return { ok: true };
});

ipcMain.handle("island:open-main", async (_event, { tab }) => {
  try {
    return { ok: showMainWindow(tab) };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("island:notify", async (_event, data) => {
  if (!dynamicIsland || dynamicIsland.isDestroyed()) return { ok: false };
  try {
    dynamicIsland.webContents.send("island:notify", data || {});
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("system:notify", async (_event, data) => {
  try {
    // 消息提醒总开关：关闭时直接短路，任何来源（新消息/日程/主动消息）都不弹。
    if (!_notificationsEnabled) {
      return { ok: false, reason: "notifications_disabled" };
    }
    // 主窗口在最上层且有焦点时不弹系统通知——用户正看着窗口，不该打扰。
    // （聊天窗口/主动消息的通知只在窗口不在最上层时弹出。）
    if (mainWindow && !mainWindow.isDestroyed() && mainWindow.isFocused()) {
      return { ok: false, reason: "main_window_focused" };
    }
    if (!Notification.isSupported()) return { ok: false, error: "notification_not_supported" };
    const notification = new Notification({
      title: String(data?.title || "Aerie · 云栖"),
      body: String(data?.body || data?.desc || ""),
      icon: fs.existsSync(ICON_PATH) ? ICON_PATH : undefined,
      silent: Boolean(data?.silent),
    });
    notification.on("click", () => {
      showMainWindow("memorial");
    });
    notification.show();
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// Island config (from main window → island window)
let _islandConfig = {
  theme: "dark",
  interaction: "click",
  expandType: "panel",
  capsuleComponents: ["companion", "status", "notifications"],
  expandedComponents: ["quickActions", "notifList"],
};

ipcMain.handle("island:set-config", async (_event, cfg) => {
  _islandConfig = Object.assign(_islandConfig, cfg || {});
  _saveIslandPrefs();
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.webContents.send("island:config-change", _islandConfig);
  }
  return { ok: true, config: _islandConfig };
});

ipcMain.handle("island:get-config", async () => {
  return { ok: true, config: _islandConfig };
});

// 灵动岛头像：返回带时间戳的绝对 URL（防缓存），未设置时后端返回 404 → renderer onerror 回退 logo
ipcMain.handle("island:get-avatar-url", async () => {
  return { ok: true, url: `${PY_BACKEND}/api/persona/avatar?t=${Date.now()}` };
});

// 设置页头像上传成功后调用：刷新绝对 URL 并广播到灵动岛窗口
ipcMain.handle("island:refresh-avatar", async () => {
  const avatarUrl = `${PY_BACKEND}/api/persona/avatar?t=${Date.now()}`;
  _islandConfig = Object.assign({}, _islandConfig, { avatarUrl });
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    try { dynamicIsland.webContents.send("island:config-change", _islandConfig); } catch (_) {}
  }
  return { ok: true, url: avatarUrl };
});

// 灵动岛宽屏右栏数据供给：只读转发到后端（简报/日历），白名单 GET，不带任何凭据外的参数
ipcMain.handle("island:api", async (_event, opts) => {
  try {
    const path = String((opts && opts.path) || "");
    if (!path.startsWith("/api/") || /[?&=]/.test(path)) {
      return { ok: false, error: "invalid_path" };
    }
    const response = await apiRequest({ path, method: (opts && opts.method) || "GET" });
    return { ok: true, data: response && response.data };
  } catch (err) {
    return { ok: false, error: err && err.message || String(err) };
  }
});

// R8.1: master enable/disable IPC.  These are deliberately *not* guarded by
//       backend readiness because the island is 100% Electron — the same
//       circularity (backend off → can't change backend-off status) was the
//       root of the previous bug reports.
ipcMain.handle("island:get-enabled", async () => {
  return {
    ok: true,
    enabled: _islandEnabled,
    visible: _isIslandWindowAlive() && dynamicIsland.isVisible(),
    windowExists: _isIslandWindowAlive(),
    prefsPath: _islandPrefsPath || "",
    saved: Boolean(_islandPrefsPath && fs.existsSync(_islandPrefsPath)),
  };
});
ipcMain.handle("island:set-enabled", async (_event, payload) => {
  const wanted = Boolean(payload && payload.enabled);
  if (_islandEnabled === wanted &&
      (wanted ? _isIslandWindowAlive() : !_isIslandWindowAlive())) {
    // State already matches — nothing to do, just confirm to caller.
    _broadcastIslandEnabled();
    return {
      ok: true,
      changed: false,
      enabled: _islandEnabled,
      visible: _isIslandWindowAlive() && dynamicIsland.isVisible(),
      windowExists: _isIslandWindowAlive(),
      prefsPath: _islandPrefsPath || "",
    };
  }

  // 1) Persist FIRST. If we can't write the prefs file (read-only folder),
  //    fail the whole change instead of silently flipping the UI without
  //    saving — that was another previously-reported bug pattern.
  _islandEnabled = wanted;
  const saved = _saveIslandPrefs();

  // 2) Create / destroy the actual BrowserWindow.
  try {
    _applyIslandEnabledToWindow();
  } catch (e) {
    console.error("[main] _applyIslandEnabledToWindow failed:", e && e.message);
    // Rollback the in-memory state (but keep persisted file: the user really
    // wanted this toggle, next app restart will retry with a clean window).
    const payload2 = {
      ok: false,
      error: e && e.message || "apply_failed",
      saved,
      enabled: _islandEnabled,
      prefsPath: _islandPrefsPath || "",
    };
    _broadcastIslandEnabled();
    return payload2;
  }

  // 3) Broadcast to all renderer processes (main window, settings tab, any
  //    secondary windows). Also push the enabled flag into _islandConfig so
  //    the island window itself doesn't have to learn about it separately.
  _islandConfig = Object.assign({}, _islandConfig, { enabled: _islandEnabled });
  if (_isIslandWindowAlive()) {
    try { dynamicIsland.webContents.send("island:config-change", _islandConfig); } catch (_) {}
  }
  _broadcastIslandEnabled();
  return {
    ok: true,
    changed: true,
    enabled: _islandEnabled,
    saved,
    prefsPath: _islandPrefsPath || "",
    visible: _isIslandWindowAlive() && dynamicIsland.isVisible(),
    windowExists: _isIslandWindowAlive(),
  };
});

// 消息提醒总开关 IPC。与灵动岛主开关同理，不依赖后端就绪。
ipcMain.handle("notif:get-enabled", async () => {
  return {
    ok: true,
    enabled: _notificationsEnabled,
    prefsPath: _notifPrefsPath || "",
    saved: Boolean(_notifPrefsPath && fs.existsSync(_notifPrefsPath)),
  };
});
ipcMain.handle("notif:set-enabled", async (_event, payload) => {
  const wanted = Boolean(payload && payload.enabled);
  if (_notificationsEnabled === wanted) {
    _broadcastNotifEnabled();
    return {
      ok: true,
      changed: false,
      enabled: _notificationsEnabled,
      prefsPath: _notifPrefsPath || "",
    };
  }
  // 先持久化，写不进去就整个失败，避免 UI 翻转了但没保存。
  _notificationsEnabled = wanted;
  const saved = _saveNotifPrefs();
  _broadcastNotifEnabled();
  return {
    ok: true,
    changed: true,
    enabled: _notificationsEnabled,
    saved,
    prefsPath: _notifPrefsPath || "",
  };
});

// System status (CPU / memory / network)
const os = require("os");
let _lastCpuTimes = null;

function _getCpuUsage() {
  const cpus = os.cpus();
  let idle = 0, total = 0;
  for (const cpu of cpus) {
    for (const type in cpu.times) {
      total += cpu.times[type];
    }
    idle += cpu.times.idle;
  }
  const now = { idle, total };
  let usage = 0;
  if (_lastCpuTimes) {
    const idleDiff = now.idle - _lastCpuTimes.idle;
    const totalDiff = now.total - _lastCpuTimes.total;
    usage = totalDiff > 0 ? (1 - idleDiff / totalDiff) * 100 : 0;
  }
  _lastCpuTimes = now;
  return Math.max(0, Math.min(100, usage));
}

function _getMemUsage() {
  const total = os.totalmem();
  const free = os.freemem();
  return ((total - free) / total) * 100;
}

let _systemStatusInterval = null;
let _systemStatus = {
  cpu: 0,
  mem: 0,
  net: null,
  netReceive: null,
  netSend: null,
  networkAvailable: false,
  sampledAt: "",
};

async function sampleSystemStatus() {
  _systemStatus.cpu = _getCpuUsage();
  _systemStatus.mem = _getMemUsage();
  try {
    const response = await apiRequest({ path: "/api/stats/system" });
    const data = response && response.data && typeof response.data === "object"
      ? response.data
      : {};
    const receive = Number(data.network_receive_kbps);
    const send = Number(data.network_send_kbps);
    if (Number.isFinite(receive) && Number.isFinite(send)) {
      _systemStatus.netReceive = receive;
      _systemStatus.netSend = send;
      _systemStatus.net = receive + send;
      _systemStatus.networkAvailable = true;
    } else {
      _systemStatus.netReceive = null;
      _systemStatus.netSend = null;
      _systemStatus.net = null;
      _systemStatus.networkAvailable = false;
    }
    _systemStatus.sampledAt = String(data.sampled_at || "");
  } catch (_) {
    _systemStatus.netReceive = null;
    _systemStatus.netSend = null;
    _systemStatus.net = null;
    _systemStatus.networkAvailable = false;
    _systemStatus.sampledAt = "";
  }
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.webContents.send("island:system-status", _systemStatus);
  }
}

function configureWorldSupervisor() {
  const sidecarDataDir = path.join(BACKEND_DATA_DIR, "world_sidecar");
  fs.mkdirSync(sidecarDataDir, { recursive: true });
  worldPluginSupervisor.register("aerie.world", {
    command: PYTHON_EXE,
    cwd: PYTHON_ROOT,
    dataDir: sidecarDataDir,
  });
}

async function fetchDesktopAttachment(attachmentId) {
  const id = String(attachmentId || "");
  if (!/^att_[a-f0-9]{32}$/i.test(id)) throw new Error("invalid_attachment_id");
  const status = await apiRequest({
    method: "GET",
    path: "/api/attachments/" + encodeURIComponent(id),
  });
  const record = status && status.data && status.data.attachment;
  if (!record || record.state !== "ready") throw new Error("attachment_not_ready");
  const originalName = path.basename(String(record.name || "attachment.bin"));
  const safeName = originalName.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").slice(0, 180)
    || "attachment.bin";
  const bytes = await new Promise((resolve, reject) => {
    const req = http.get(
      PY_BACKEND + "/api/attachments/" + encodeURIComponent(id) + "/download",
      (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          reject(new Error("attachment_download_failed"));
          return;
        }
        const chunks = [];
        let size = 0;
        res.on("data", (chunk) => {
          size += chunk.length;
          if (size > 21 * 1024 * 1024) {
            req.destroy(new Error("attachment_too_large"));
            return;
          }
          chunks.push(chunk);
        });
        res.on("end", () => resolve(Buffer.concat(chunks)));
      },
    );
    req.on("error", reject);
    req.setTimeout(30000, () => req.destroy(new Error("attachment_download_timeout")));
  });
  return { id, name: safeName, bytes };
}

async function fetchGatewayQrCode() {
  const bytes = await new Promise((resolve, reject) => {
    const req = http.get(PY_BACKEND + "/api/qq/gateway/qrcode", (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error("qq_gateway_qrcode_unavailable"));
        return;
      }
      const chunks = [];
      let size = 0;
      res.on("data", (chunk) => {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) {
          req.destroy(new Error("qq_gateway_qrcode_too_large"));
          return;
        }
        chunks.push(chunk);
      });
      res.on("end", () => resolve(Buffer.concat(chunks)));
    });
    req.on("error", reject);
    req.setTimeout(5000, () => req.destroy(new Error("qq_gateway_qrcode_timeout")));
  });
  if (!bytes.length) throw new Error("qq_gateway_qrcode_empty");
  return `data:image/png;base64,${bytes.toString("base64")}`;
}

async function openDesktopAttachment(attachmentId) {
  const attachment = await fetchDesktopAttachment(attachmentId);
  const targetDir = path.join(app.getPath("temp"), "Aerie", "attachments-open");
  fs.mkdirSync(targetDir, { recursive: true });
  const target = path.join(targetDir, attachment.id + "-" + attachment.name);
  fs.writeFileSync(target, attachment.bytes, { flag: "w" });
  _openedAttachmentTempPaths.add(target);
  const error = await shell.openPath(target);
  return error ? { ok: false, error: "open_failed" } : { ok: true };
}

async function saveDesktopAttachment(attachmentId) {
  const attachment = await fetchDesktopAttachment(attachmentId);
  const selected = await dialog.showSaveDialog(mainWindow || undefined, {
    defaultPath: attachment.name,
  });
  if (selected.canceled || !selected.filePath) return { ok: false, canceled: true };
  fs.writeFileSync(selected.filePath, attachment.bytes, { flag: "w" });
  return { ok: true };
}

function runtimeConfigValue(snapshot, key, fallback) {
  const values = snapshot && snapshot.values && typeof snapshot.values === "object"
    ? snapshot.values
    : {};
  const entry = values[key];
  return entry && typeof entry === "object" && "effectiveValue" in entry
    ? entry.effectiveValue
    : fallback;
}

async function bindWorldConnectionToBackend(force = false) {
  if (!_backendReady) return false;
  const connection = worldPluginSupervisor.connection("aerie.world");
  const signature = connection
    ? crypto.createHash("sha256").update([
        connection.endpoint,
        connection.token,
        connection.instanceId,
        connection.expiresAt,
      ].join("\u001f")).digest("hex")
    : "none";
  if (!force && signature === _worldConnectionSignature) return true;
  try {
    const response = await apiRequest({
      method: "POST",
      path: "/api/world/runtime/bind",
      internal: true,
      body: { connection },
    });
    if (!response || !response.data || response.data.accepted !== true) return false;
    _worldConnectionSignature = signature;
    return true;
  } catch (_) {
    return false;
  }
}

async function reconcileWorldRuntime() {
  if (!_backendReady) return;
  let snapshot;
  try {
    const response = await apiRequest({ method: "GET", path: "/api/runtime/snapshot" });
    snapshot = response && response.data && typeof response.data === "object"
      ? response.data
      : {};
  } catch (_) {
    return;
  }
  const effective = worldDashboardHost.applyRuntimeSnapshot(snapshot);
  let plugin = worldPluginSupervisor.status("aerie.world");
  if (!effective.enabled) {
    if (plugin.enabled) {
      await worldPluginSupervisor.disable("aerie.world", {
        expectedRevision: plugin.revision,
      });
    }
    await bindWorldConnectionToBackend(true);
    return;
  }
  if (!plugin.enabled) {
    await worldPluginSupervisor.enable("aerie.world", {
      expectedRevision: plugin.revision,
    });
    plugin = worldPluginSupervisor.status("aerie.world");
  }
  const desired = String(runtimeConfigValue(snapshot, "world_desired", "stopped"));
  if (desired === "running" && plugin.actual !== "running") {
    const command = plugin.actual === "paused" ? "resume" : "start";
    await worldPluginSupervisor.control("aerie.world", command, {
      expectedRevision: plugin.revision,
    });
  } else if (desired === "paused" && plugin.actual !== "paused") {
    if (plugin.actual !== "running") {
      await worldPluginSupervisor.start("aerie.world", {
        expectedRevision: plugin.revision,
      });
      plugin = worldPluginSupervisor.status("aerie.world");
    }
    await worldPluginSupervisor.pause("aerie.world", {
      expectedRevision: plugin.revision,
    });
  } else if (desired === "stopped" && plugin.actual !== "stopped") {
    await worldPluginSupervisor.stop("aerie.world", {
      expectedRevision: plugin.revision,
    });
  }
  await bindWorldConnectionToBackend(true);
}

function startWorldConnectionMonitor() {
  if (_worldConnectionMonitor) return;
  _worldConnectionMonitor = setInterval(() => {
    bindWorldConnectionToBackend(false).catch(() => {});
  }, 2000);
}

function startSystemStatusPolling() {
  if (_systemStatusInterval) return;
  _getCpuUsage();
  void sampleSystemStatus();
  _systemStatusInterval = setInterval(() => {
    void sampleSystemStatus();
  }, 2000);
}

function stopSystemStatusPolling() {
  if (_systemStatusInterval) {
    clearInterval(_systemStatusInterval);
    _systemStatusInterval = null;
  }
}

ipcMain.handle("island:get-system-status", async () => {
  return { ok: true, data: _systemStatus };
});

// Media control (Windows SMTC integration)
let _mediaState = {
  playing: false,
  title: "",
  artist: "",
  progress: 0,
  duration: 0,
  thumbnail: "",
};
const MEDIA_QUERY_TIMEOUT_MS = 5000;
const MEDIA_CONTROL_TIMEOUT_MS = 3000;
const MEDIA_CONTROL_REFRESH_DELAY_MS = 150;
const MEDIA_POLL_ACTIVE_MS = 5000;
const MEDIA_POLL_IDLE_MS = 15000;
let _mediaPollTimer = null;
let _mediaPollingActive = false;
let _mediaPollInFlight = false;
let _mediaQueryPromise = null;
let _mediaControlChain = Promise.resolve();
let _mediaControlInFlight = null;
let _lastThumbnailPath = null;

const _SMTC_PS1 = `
try {
    $ErrorActionPreference = 'Stop'
    # v13.9: Force UTF-8 output so Chinese titles/artists don't become garbled
    # when Node.js reads stdout. Without this, PowerShell 5.1 on Windows
    # defaults to the system ANSI code page (GBK on Chinese Windows) and
    # UTF-8 bytes get reinterpreted as question marks / replacement chars.
    $OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    chcp 65001 | Out-Null
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSession, Windows.Media.Control, ContentType = WindowsRuntime]
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionPlaybackStatus, Windows.Media.Control, ContentType = WindowsRuntime]
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType = WindowsRuntime]
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    function Await-WinRtAsync($asyncOp, $resultType) {
        $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() |
            Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 } |
            Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation\`1' } |
            Select-Object -First 1
        $asTask = $asTaskGeneric.MakeGenericMethod($resultType)
        $task = $asTask.Invoke($null, @($asyncOp))
        $task.Wait() | Out-Null
        return $task.Result
    }
    $managerOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()
    $manager = Await-WinRtAsync $managerOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    $session = $manager.GetCurrentSession()
    if ($session -ne $null) {
        $mediaOp = $session.TryGetMediaPropertiesAsync()
        $mediaProps = Await-WinRtAsync $mediaOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        $timelineProps = $session.GetTimelineProperties()
        $playbackInfo = $session.GetPlaybackInfo()
        $playing = $playbackInfo.PlaybackStatus -eq [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionPlaybackStatus]::Playing

        $thumbnailPath = ""
        try {
            if ($mediaProps.Thumbnail -ne $null) {
                $streamOp = $mediaProps.Thumbnail.OpenReadAsync()
                $stream = Await-WinRtAsync $streamOp ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
                if ($stream -ne $null) {
                    $asStreamMethod = $null
                    $asm = [System.AppDomain]::CurrentDomain.GetAssemblies() |
                        Where-Object { $_.GetName().Name -eq 'System.Runtime.WindowsRuntime' } |
                        Select-Object -First 1
                    if ($asm -ne $null) {
                        $extType = $asm.GetType('System.IO.WindowsRuntimeStreamExtensions')
                        if ($extType -ne $null) {
                            $methods = $extType.GetMethods() | Where-Object { $_.Name -eq 'AsStream' -and $_.IsStatic }
                            foreach ($m in $methods) {
                                $params = $m.GetParameters()
                                if ($params.Count -eq 1 -and $params[0].ParameterType.Name -eq 'IRandomAccessStream') {
                                    $asStreamMethod = $m
                                    break
                                }
                            }
                        }
                    }
                    if ($asStreamMethod -ne $null) {
                        $dotNetStream = $asStreamMethod.Invoke($null, @($stream))
                        if ($dotNetStream -ne $null) {
                            $ms = New-Object System.IO.MemoryStream
                            $dotNetStream.CopyTo($ms)
                            $buffer = $ms.ToArray()
                            $ms.Close()
                            $dotNetStream.Close()
                            if ($buffer -and $buffer.Length -gt 0) {
                                $ext = ".jpg"
                                if ($buffer.Length -ge 4) {
                                    if ($buffer[0] -eq 0x89 -and $buffer[1] -eq 0x50 -and $buffer[2] -eq 0x4E -and $buffer[3] -eq 0x47) { $ext = ".png" }
                                    elseif ($buffer[0] -eq 0xFF -and $buffer[1] -eq 0xD8) { $ext = ".jpg" }
                                    elseif ($buffer[0] -eq 0x47 -and $buffer[1] -eq 0x49 -and $buffer[2] -eq 0x46) { $ext = ".gif" }
                                }
                                $tempPath = Join-Path $env:TEMP "aerie_media_thumb_$([Guid]::NewGuid())$ext"
                                [System.IO.File]::WriteAllBytes($tempPath, $buffer)
                                $thumbnailPath = $tempPath
                            }
                        }
                    }
                }
            }
        } catch {
            $thumbnailPath = ""
        }

        [PSCustomObject]@{
            playing = $playing
            title = $mediaProps.Title
            artist = $mediaProps.Artist
            position = [int][Math]::Round($timelineProps.Position.TotalSeconds)
            duration = [int][Math]::Round($timelineProps.EndTime.TotalSeconds)
            thumbnail = $thumbnailPath
        } | ConvertTo-Json -Compress
    } else {
        '{"playing":false,"title":"","artist":"","position":0,"duration":0,"thumbnail":""}'
    }
} catch {
    '{"playing":false,"title":"","artist":"","position":0,"duration":0,"thumbnail":""}'
}
`;

function _queryMediaState() {
  return new Promise((resolve) => {
    const emptyState = {
      playing: false,
      title: "",
      artist: "",
      progress: 0,
      duration: 0,
      thumbnail: "",
    };
    if (process.platform !== "win32") {
      resolve(emptyState);
      return;
    }
    let settled = false;
    let timeoutId = null;
    const finish = (state = emptyState) => {
      if (settled) return;
      settled = true;
      if (timeoutId) clearTimeout(timeoutId);
      resolve(state);
    };
    let ps;
    try {
      ps = spawn("powershell.exe", [
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", _SMTC_PS1,
      ], { windowsHide: true });
    } catch (_) {
      finish();
      return;
    }
    let stdout = "";
    ps.stdout.on("data", (d) => (stdout += d.toString()));
    ps.stderr.on("data", () => {});
    timeoutId = setTimeout(() => {
      try { ps.kill(); } catch (_) {}
      finish();
    }, MEDIA_QUERY_TIMEOUT_MS);
    ps.on("close", () => {
      try {
        const data = JSON.parse(stdout.trim());
        finish({
          playing: !!data.playing,
          title: data.title || "",
          artist: data.artist || "",
          progress: data.position || 0,
          duration: data.duration || 0,
          thumbnail: data.thumbnail || "",
        });
      } catch {
        finish();
      }
    });
    ps.on("error", () => finish());
  });
}

function _fetchMediaState() {
  if (_mediaControlInFlight) return _mediaControlInFlight;
  if (!_mediaQueryPromise) {
    _mediaQueryPromise = _queryMediaState().finally(() => {
      _mediaQueryPromise = null;
    });
  }
  return _mediaQueryPromise;
}

function _runMediaControlProcess(action, positionSeconds = 0) {
  return new Promise((resolve) => {
    if (process.platform !== "win32") {
      resolve();
      return;
    }
    let settled = false;
    let timeoutId = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (timeoutId) clearTimeout(timeoutId);
      resolve();
    };
    let ps;
    try {
      ps = spawn("powershell.exe", [
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", _buildMediaControlScript(action, positionSeconds),
      ], { windowsHide: true });
    } catch (_) {
      finish();
      return;
    }
    timeoutId = setTimeout(() => {
      try { ps.kill(); } catch (_) {}
      finish();
    }, MEDIA_CONTROL_TIMEOUT_MS);
    ps.on("close", finish);
    ps.on("error", finish);
  });
}

function _runMediaControlAndRefresh(action, positionSeconds = 0) {
  const operation = _mediaControlChain.then(async () => {
    if (_mediaQueryPromise) await _mediaQueryPromise;
    await _runMediaControlProcess(action, positionSeconds);
    await new Promise((resolve) => setTimeout(resolve, MEDIA_CONTROL_REFRESH_DELAY_MS));
    return _queryMediaState();
  });
  _mediaControlChain = operation.catch(() => _mediaState);
  _mediaControlInFlight = operation;
  const clearInFlight = () => {
    if (_mediaControlInFlight === operation) _mediaControlInFlight = null;
  };
  void operation.then(clearInFlight, clearInFlight);
  return operation;
}

function _cleanupOldThumbnail() {
  if (_lastThumbnailPath) {
    try {
      fs.unlinkSync(_lastThumbnailPath);
    } catch (_) {}
    _lastThumbnailPath = null;
  }
}

function _applyMediaState(state) {
  const changed =
    state.playing !== _mediaState.playing ||
    state.title !== _mediaState.title ||
    state.artist !== _mediaState.artist ||
    state.thumbnail !== _mediaState.thumbnail ||
    state.progress !== _mediaState.progress ||
    state.duration !== _mediaState.duration;
  if (state.thumbnail !== _mediaState.thumbnail) {
    _cleanupOldThumbnail();
    if (state.thumbnail) _lastThumbnailPath = state.thumbnail;
  }
  _mediaState = state;
  if (changed && dynamicIsland && !dynamicIsland.isDestroyed() && dynamicIsland.isVisible()) {
    dynamicIsland.webContents.send("island:media-update", _mediaState);
  }
}

function _scheduleMediaPoll(delayMs) {
  if (!_mediaPollingActive) return;
  if (_mediaPollTimer) clearTimeout(_mediaPollTimer);
  _mediaPollTimer = setTimeout(() => {
    _mediaPollTimer = null;
    void _pollMediaOnce();
  }, delayMs);
}

async function _pollMediaOnce() {
  if (!_mediaPollingActive || _mediaPollInFlight) return;
  if (!dynamicIsland || dynamicIsland.isDestroyed() || !dynamicIsland.isVisible()) {
    _stopMediaPolling();
    return;
  }
  _mediaPollInFlight = true;
  try {
    const state = await _fetchMediaState();
    _applyMediaState(state);
  } finally {
    _mediaPollInFlight = false;
    if (_mediaPollingActive) {
      const delay = _islandExpanded || _mediaState.playing
        ? MEDIA_POLL_ACTIVE_MS
        : MEDIA_POLL_IDLE_MS;
      _scheduleMediaPoll(delay);
    }
  }
}

function _startMediaPolling() {
  if (_mediaPollingActive) return;
  if (!dynamicIsland || dynamicIsland.isDestroyed() || !dynamicIsland.isVisible()) return;
  _mediaPollingActive = true;
  _scheduleMediaPoll(MEDIA_POLL_ACTIVE_MS);
}

function _stopMediaPolling() {
  _mediaPollingActive = false;
  if (_mediaPollTimer) {
    clearTimeout(_mediaPollTimer);
    _mediaPollTimer = null;
  }
}

ipcMain.handle("island:media-get-state", async () => {
  const state = await _fetchMediaState();
  _applyMediaState(state);
  return { ok: true, data: _mediaState };
});

ipcMain.handle("island:media-play-pause", async () => {
  const state = await _runMediaControlAndRefresh("PlayPause");
  _applyMediaState(state);
  return { ok: true, data: _mediaState };
});

ipcMain.handle("island:media-next", async () => {
  const state = await _runMediaControlAndRefresh("Next");
  _applyMediaState(state);
  return { ok: true, data: _mediaState };
});

ipcMain.handle("island:media-prev", async () => {
  const state = await _runMediaControlAndRefresh("Previous");
  _applyMediaState(state);
  return { ok: true, data: _mediaState };
});

ipcMain.handle("island:media-seek", async (_event, positionSeconds) => {
  const sec = Number(positionSeconds);
  if (!Number.isFinite(sec) || sec < 0) {
    return { ok: false, data: _mediaState };
  }
  const state = await _runMediaControlAndRefresh("Seek", sec);
  _applyMediaState(state);
  return { ok: true, data: _mediaState };
});

function _buildMediaControlScript(action, positionSeconds = 0) {
  return `
try {
    $ErrorActionPreference = 'Stop'
    # v13.9: Force UTF-8 output (see _SMTC_PS1 for rationale)
    $OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    chcp 65001 | Out-Null
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSession, Windows.Media.Control, ContentType = WindowsRuntime]
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    function Await-WinRtAsync($asyncOp, $resultType) {
        $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() |
            Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 } |
            Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation\`1' } |
            Select-Object -First 1
        $asTask = $asTaskGeneric.MakeGenericMethod($resultType)
        $task = $asTask.Invoke($null, @($asyncOp))
        $task.Wait() | Out-Null
        return $task.Result
    }
    function Await-WinRtAction($asyncOp) {
        $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
            Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 } |
            Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } |
            Select-Object -First 1
        $task = $asTask.Invoke($null, @($asyncOp))
        $task.Wait() | Out-Null
    }
    $managerOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()
    $manager = Await-WinRtAsync $managerOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    $session = $manager.GetCurrentSession()
    if ($session -ne $null) {
        switch ('${action}') {
            'PlayPause' {
                $playback = $session.GetPlaybackInfo()
                if ($playback.PlaybackStatus -eq 'Playing') {
                    Await-WinRtAction $session.TryPauseAsync()
                } else {
                    Await-WinRtAction $session.TryPlayAsync()
                }
            }
            'Next' { Await-WinRtAction $session.TrySkipNextAsync() }
            'Previous' { Await-WinRtAction $session.TrySkipPreviousAsync() }
            'Seek' {
                $posTicks = [int64]([double]'${positionSeconds}' * 10000000)
                Await-WinRtAsync ($session.TryChangePlaybackPositionAsync($posTicks)) ([System.Boolean])
            }
        }
    }
    'ok'
} catch {
    'error'
}
`;
}

// R7.0: multipart upload IPC. The renderer cannot use file:// fetch
// (CORS). This handler receives the raw bytes (as a plain Array) plus
// metadata, builds a real multipart/form-data body, and forwards to
// the Python backend over loopback HTTP. The backend's
// /api/persona/avatar endpoint sees a normal FastAPI UploadFile.
ipcMain.handle("api:upload", async (_event, opts) => {
  try {
    if (!opts || !opts.path) {
      return { status: 0, data: { error: "missing path" } };
    }
    const filename = opts.filename || "upload.bin";
    const contentType = opts.contentType || "application/octet-stream";
    const bytes = Array.isArray(opts.bytes) ? Buffer.from(opts.bytes) : Buffer.alloc(0);
    if (!bytes || bytes.length === 0) {
      return { status: 0, data: { error: "empty bytes" } };
    }
    const boundary = "----AerieBoundary" + Date.now().toString(16);
    const crlf = "\r\n";
    const head = Buffer.from(
      "--" + boundary + crlf
      + 'Content-Disposition: form-data; name="file"; filename="' + filename + '"' + crlf
      + "Content-Type: " + contentType + crlf + crlf,
      "utf-8"
    );
    const tail = Buffer.from(crlf + "--" + boundary + "--" + crlf, "utf-8");
    const body = Buffer.concat([head, bytes, tail]);

    const url = new URL(PY_BACKEND + opts.path);
    return await new Promise((resolve, reject) => {
      const req = http.request({
        hostname: "127.0.0.1",
        port: PY_PORT,
        path: url.pathname + url.search,
        method: opts.method || "POST",
        headers: {
          "Content-Type": "multipart/form-data; boundary=" + boundary,
          "Content-Length": body.length,
        },
        timeout: 30000,
      }, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(Buffer.from(c)));
        res.on("end", () => {
          const d = decodeBufferedUtf8Chunks(chunks);
          const ct = (res.headers && res.headers["content-type"] || "").toLowerCase();
          let parsed;
          if (ct.indexOf("application/json") >= 0) {
            try { parsed = JSON.parse(d); } catch (_) { parsed = d; }
          } else {
            try { parsed = JSON.parse(d); } catch (_) { parsed = d; }
          }
          resolve({ status: res.statusCode, data: parsed });
        });
      });
      req.on("error", (err) => reject(err));
      req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
      req.write(body);
      req.end();
    });
  } catch (err) {
    return { status: 0, data: { error: err && err.message || String(err) } };
  }
});

// ── Phase 9 Batch 4: SSE → IPC bridge (brain center) ──
const sseClients = new Map(); // webContents.id -> { req, closing }
const sseCursors = new Map(); // webContents.id -> last SSE id

function buildSseHeaders(lastEventId) {
  const headers = { "Accept": "text/event-stream" };
  if (lastEventId) {
    headers["Last-Event-ID"] = String(lastEventId);
  }
  return headers;
}

function parseSseFrame(frame) {
  if (!frame || !String(frame).trim()) return null;
  const lines = String(frame).split(/\r?\n/);
  const dataLines = [];
  let id = "";

  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("id:")) {
      id = line.slice(3).replace(/^ /, "");
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }

  if (!dataLines.length) return null;
  const data = dataLines.join("\n");
  if (!id) {
    try {
      const parsed = JSON.parse(data);
      if (parsed && parsed.event_id) id = String(parsed.event_id);
    } catch (_) {}
  }
  return { id, data };
}

function findWindowByWebContentsId(senderId) {
  return BrowserWindow.getAllWindows().find(
    (w) => !w.isDestroyed() && w.webContents.id === senderId
  );
}

function scheduleSseReconnect(senderId) {
  setTimeout(() => {
    if (findWindowByWebContentsId(senderId)) {
      connectSseForWebContents(senderId);
    }
  }, 3000);
}

function forwardSseFrame(senderId, frame) {
  const parsed = parseSseFrame(frame);
  if (!parsed) return;
  if (parsed.id) sseCursors.set(senderId, parsed.id);

  const target = findWindowByWebContentsId(senderId);
  if (target) {
    try { target.webContents.send("sse:event", parsed.data); } catch (_) {}
  }
}

ipcMain.handle("sse:subscribe", async (event) => {
  const senderId = event.sender.id;
  if (sseClients.has(senderId)) {
    return { ok: true, dedup: true };
  }
  connectSseForWebContents(senderId);
  return { ok: true };
});

function connectSseForWebContents(senderId) {
  // Internal helper used for initial subscription and auto-reconnect.
  if (sseClients.has(senderId)) return;
  const req = http.request(
    {
      hostname: "127.0.0.1",
      port: PY_PORT,
      path: "/api/events/stream",
      method: "GET",
      headers: buildSseHeaders(sseCursors.get(senderId)),
    },
    (res) => {
      const sseProcessor = createUtf8SseProcessor((frame) => forwardSseFrame(senderId, frame));
      res.on("data", (chunk) => {
        sseProcessor.write(chunk);
      });
      res.on("end", () => {
        const buf = sseProcessor.end();
        if (buf.trim()) forwardSseFrame(senderId, buf);
        handleSseDisconnect(senderId, client);
      });
    }
  );
  req.on("error", () => {
    handleSseDisconnect(senderId, client);
  });
  const client = { req, closing: false };
  req.end();
  sseClients.set(senderId, client);
}

function handleSseDisconnect(senderId, client) {
  if (!client || client.closing) return;
  if (sseClients.get(senderId) !== client) return;
  sseClients.delete(senderId);
  scheduleSseReconnect(senderId);
}

ipcMain.handle("sse:unsubscribe", async (event) => {
  const senderId = event.sender.id;
  const client = sseClients.get(senderId);
  if (client) {
    client.closing = true;
    try { client.req.destroy(); } catch (_) {}
    sseClients.delete(senderId);
  }
  return { ok: true };
});

// Cleanup SSE clients when webContents is destroyed
app.on("web-contents-destroyed", (_event, contents) => {
  const client = sseClients.get(contents.id);
  if (client) {
    client.closing = true;
    try { client.req.destroy(); } catch (_) {}
    sseClients.delete(contents.id);
  }
  sseCursors.delete(contents.id);
});

// ── Window controls ───────────────────────────────
function getSenderWindow(event) {
  return BrowserWindow.fromWebContents(event.sender);
}

ipcMain.handle("window:minimize", (event) => {
  const win = getSenderWindow(event);
  if (win) win.minimize();
  return true;
});

ipcMain.handle("window:toggle-maximize", (event) => {
  const win = getSenderWindow(event);
  if (!win) return false;
  if (win.isMaximized()) {
    win.unmaximize();
  } else {
    win.maximize();
  }
  return win.isMaximized();
});

ipcMain.handle("window:is-maximized", (event) => {
  const win = getSenderWindow(event);
  return win ? win.isMaximized() : false;
});

ipcMain.handle("window:close", (event) => {
  const win = getSenderWindow(event);
  // The main-window close listener decides between background hide and a
  // normal quit based on whether a recovery surface is actually available.
  if (win) win.close();
  return true;
});

// 办公模式：选择文件夹对话框
ipcMain.handle("dialog:openDirectory", async (event, opts = {}) => {
  const { dialog } = require("electron");
  const win = getSenderWindow(event);
  const result = await dialog.showOpenDialog(win || BrowserWindow.getFocusedWindow(), {
    title: opts.title || "选择文件夹",
    defaultPath: opts.defaultPath || "",
    properties: ["openDirectory", "createDirectory"],
  });
  if (result.canceled || !result.filePaths?.length) return null;
  return result.filePaths[0];
});

// 办公模式：在资源管理器中打开路径
ipcMain.handle("shell:openPath", async (_event, path) => {
  const { shell } = require("electron");
  if (!path) return { success: false, error: "path is required" };
  try {
    await shell.openPath(path);
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
});

// 用系统默认浏览器打开外链（避免 Electron 内嵌新窗口打不开外部页面）
ipcMain.handle("shell:openExternal", async (_event, url) => {
  const { shell } = require("electron");
  if (!url || !/^https?:\/\//i.test(url)) return { success: false, error: "invalid url" };
  try {
    await shell.openExternal(url);
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
});

// R7.0: Forward /api/health as-is so the renderer can read stale_code
// without a second round-trip. The renderer's poll already calls
// /api/health, so this IPC is mainly used by the very first paint
// before the renderer's poll loop kicks in.
// R7.2: get-health MUST return instantly (<1ms) so renderer first-paint
// shows a correct status instead of spinning on "后端离线" for 2s while
// the old implementation awaited apiRequest() on a not-yet-running backend.
// Stale metadata (stale_code / process_started_at) is fetched best-effort
// in the background and broadcast via the normal onHealth channel later.
// 开场动画：返回视频 / LOGO 的绝对路径（已 encodeURI，渲染层拼 file://）
ipcMain.handle("splash:get-config", () => {
  return {
    videoPath: toFileUriPath(getSplashAssetPath("start-video.mp4")),
    logoPath: toFileUriPath(getSplashAssetPath("Aerie.png")),
    playVideo: _splashMode === "video",
  };
});

// 开场动画：视频播完且后端就绪后，渲染层通知主进程关闭 splash 并显示主窗口
ipcMain.on("splash:complete", () => {
  finishSplash();
});

ipcMain.handle("get-health", async () => {
  _recomputeBackendState();
  const snap = {
    ready: _backendReady,
    state: _backendState,
    port: PY_PORT,
    stale: false,
    modified: [],
    started_at: "",
  };
  // Kick off an async refresh WITHOUT awaiting. Populates stale_code
  // if backend is alive; does nothing when offline (no harm).
  setImmediate(async () => {
    try {
      const r = await apiRequest({ path: "/api/health", timeoutMs: 1500 });
      if (r && r.data) {
        const sc = (r.data && r.data.stale_code) || {};
        snap.stale = !!sc.stale;
        snap.modified = sc.modified || [];
        snap.started_at = sc.started_at || r.data.process_started_at || "";
      }
    } catch (_) {}
  });
  return snap;
});

ipcMain.handle("qqGateway:getStatus", async () => {
  try {
    const r = await apiRequest({ path: "/api/qq/gateway/status" });
    const status = r.data && typeof r.data === "object" ? { ...r.data } : {};
    delete status.qrcode_path;
    return status;
  } catch (_) {
    return { phase: "error", error: "backend unreachable", error_code: "backend_unreachable" };
  }
});

ipcMain.handle("qqGateway:getQrCode", async () => {
  try {
    return { ok: true, dataUrl: await fetchGatewayQrCode() };
  } catch (error) {
    return {
      ok: false,
      dataUrl: "",
      errorCode: String(error && error.message || "qq_gateway_qrcode_unavailable"),
    };
  }
});

ipcMain.handle("qqGateway:start", async () => {
  try {
    const r = await apiRequest({ method: "POST", path: "/api/qq/gateway/start" });
    return r.data;
  } catch (_) {
    return { ok: false, message: "backend unreachable" };
  }
});

ipcMain.handle("qqGateway:stop", async () => {
  try {
    const r = await apiRequest({ method: "POST", path: "/api/qq/gateway/stop" });
    return r.data;
  } catch (_) {
    return { ok: false, message: "backend unreachable" };
  }
});

ipcMain.handle("settings:get", async () => {
  try {
    const r = await apiRequest({ path: "/api/settings" });
    return r.data;
  } catch (_) {
    return { error: "backend unreachable" };
  }
});

ipcMain.handle("settings:set", async (_event, data) => {
  try {
    const r = await apiRequest({ method: "PUT", path: "/api/settings", body: data });
    return r.data;
  } catch (_) {
    return { error: "backend unreachable" };
  }
});

ipcMain.handle("settings:reset", async () => {
  try {
    const r = await apiRequest({ method: "POST", path: "/api/settings/reset" });
    return r.data;
  } catch (_) {
    return { error: "backend unreachable" };
  }
});

ipcMain.handle("startup:get", async () => {
  try {
    return { ok: true, ...getStartupSettings() };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
});

ipcMain.handle("startup:set", async (_event, options) => {
  try {
    return setStartupSettings(options || {});
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
});

// R6.6: backend self-restart.
//
// FIXED: The primary restart path is now Electron-parent-level
// `_forceRestartPythonBackend()` (see definition above).  We no longer depend
// on the Python-side /api/system/restart HTTP endpoint because that endpoint
// is unreachable in the exact scenario users complain about: the backend is
// OFFLINE and the user clicks "重启后端".
//
// We still fire a best-effort POST to /api/system/restart BEFORE the hard
// kill, so:
//   - If the backend is still alive, it can flush caches / write a clean
//     "i am restarting" line to logs / trigger its helper (harmless backup);
//   - If the backend is already dead, the HTTP failure is caught & ignored,
//     and the Electron hard restart proceeds anyway.
function restartBackend() {
  // (A) Best-effort polite notification to a still-alive backend.
  //      Fire & forget — no await, no throw on failure.
  try {
    apiRequest({ method: "POST", path: "/api/system/restart", timeoutMs: 700 })
      .catch(() => {});
  } catch (_) {}

  // (B) Broadcast to renderers immediately (don't wait for step A).
  const wins = BrowserWindow.getAllWindows();
  for (const w of wins) {
    if (w && !w.isDestroyed()) {
      try { w.webContents.send("system:restarting", { target: "backend" }); } catch (_) {}
    }
  }

  // (C) The real restart. Runs regardless of step A succeeding.
  //     This is the line that fixes the "backend offline, restart button
  //     does nothing" user complaint.
  try { _forceRestartPythonBackend(); } catch (err) {
    console.error("[main] _forceRestartPythonBackend threw:", err && err.message);
  }
}

function restartApp() {
  const { app } = require("electron");
  restartBackend();
  setTimeout(() => {
    app.relaunch();
    app.exit(0);
  }, 1500);
}

ipcMain.handle("system:restart-backend", async () => {
  // FIXED: call restartBackend() synchronously from the IPC handler so the
  // return value reflects whether we actually scheduled the Electron-level
  // restart.  We no longer require apiRequest() to succeed.
  try {
    restartBackend();
    return { status: "scheduled", mode: "electron_parent_restart" };
  } catch (e) {
    return { error: String((e && e.message) || e) };
  }
});

ipcMain.handle("system:restart-app", async () => {
  restartApp();
  return { status: "scheduled" };
});

ipcMain.handle("system:reload-config", async () => {
  try {
    const r = await apiRequest({ method: "POST", path: "/api/system/reload-config" });
    return r.data || { status: "ok" };
  } catch (e) {
    return { error: String((e && e.message) || e) };
  }
});

// R7.1: brief IPC handlers (brief:open-detail, brief:hide,
// brief:detail-close, brief:export, brief:chat) removed. The
// legacy brief popup / detail BrowserWindows no longer exist;
// the brief drawer is driven from the renderer via ``ui:open-brief``
// webContents.send and the bus.emit("brief:open") channel.

// ── Lifecycle ──────────────────────────────────────
const gotSingleInstanceLock = app.requestSingleInstanceLock();

if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showMainWindow();
  });
}

if (gotSingleInstanceLock) {
  app.whenReady().then(() => {
    configureBackendDataPath();
    configureWorldSupervisor();
    startWorldConnectionMonitor();
    // 根据启动状态决定开屏模式：
    //   video（本版本首启）→ loading（新开机）→ none（同开机会话内重启）
    _splashMode = determineSplashMode();
    if (_splashMode === "none") {
      _splashDone = true; // 不开屏，主窗口直接显示
    } else {
      createSplashWindow(_splashMode);
    }
    startPythonBackend();
    // R8.1: read persistent island/notif prefs *before* creating windows,
    // so the settings panel loads the saved island config (theme / interaction
    // / component checkboxes) on first paint instead of the defaults.
    try { _loadIslandPrefs(); } catch (_e) { _islandEnabled = true; }
    try { _loadNotifPrefs(); } catch (_e) { _notificationsEnabled = true; }
    createMainWindow();
    if (_islandEnabled && process.env.AERIE_DISABLE_DYNAMIC_ISLAND !== "1") {
      createDynamicIsland();
    } else {
      console.log("[main] skipping dynamic island create: enabled=" + _islandEnabled + " env=" + (process.env.AERIE_DISABLE_DYNAMIC_ISLAND || "0"));
    }
    // Delay tray creation to avoid flash
    setTimeout(createTray, 2000);
    // R8.1: after the main window finishes loading, push the initial
    //       island-enabled state once so the settings slider isn't blindly
    //       defaulting to "checked" and lying to the user.
    const syncOnce = () => {
      try { _broadcastIslandEnabled(); } catch (_) {}
    };
    if (mainWindow && typeof mainWindow.once === "function") {
      mainWindow.once("ready-to-show", syncOnce);
      mainWindow.once("did-finish-load", syncOnce);
    } else {
      setTimeout(syncOnce, 1500);
    }
    // R7.1: after backend is ready, wait 8s and tell the main window
    // to open the brief drawer once. Replaces the old
    // ``showBriefPopup()`` which opened a separate BrowserWindow.
    let _bootBriefShown = false;
    const _bootBriefTimer = setInterval(async () => {
      if (_bootBriefShown) {
        clearInterval(_bootBriefTimer);
        return;
      }
      if (_backendReady) {
        _bootBriefShown = true;
        clearInterval(_bootBriefTimer);
        setTimeout(() => {
          showMainWindow("brief");
        }, 8000);
      }
    }, 1000);
  });
}

app.on("window-all-closed", () => {
  // Keep app running if tray is available (background mode with Dynamic Island)
  // If tray failed to create, quit after all windows close
  if (!tray) {
    app.quit();
  }
});

app.on("before-quit", (event) => {
  isQuitting = true;
  if (!_worldShutdownComplete) {
    event.preventDefault();
    if (!_worldShutdownStarted) {
      _worldShutdownStarted = true;
      if (_worldConnectionMonitor) {
        clearInterval(_worldConnectionMonitor);
        _worldConnectionMonitor = null;
      }
      worldPluginSupervisor.dispose().catch(() => {}).finally(() => {
        _worldShutdownComplete = true;
        app.quit();
      });
    }
    return;
  }
  _cleanupOldThumbnail();
  for (const temporaryPath of _openedAttachmentTempPaths) {
    try { fs.unlinkSync(temporaryPath); } catch (_) {}
  }
  _openedAttachmentTempPaths.clear();
  if (pythonProc) {
    pythonProc.kill();
    pythonProc = null;
  }
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.destroy();
    splashWindow = null;
  }
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.setClosable(true);
    dynamicIsland.close();
    dynamicIsland = null;
  }
  if (worldDashboardWindow && !worldDashboardWindow.isDestroyed()) {
    worldDashboardWindow.destroy();
    worldDashboardWindow = null;
  }
  if (tray) tray.destroy();
});

app.on("activate", () => {
  showMainWindow();
});

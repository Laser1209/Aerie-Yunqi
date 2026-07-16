"use strict";
const { app, BrowserWindow, Tray, ipcMain, nativeImage, screen } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

// ── Config ──────────────────────────────────────────
const PY_PORT = 7890;
const PY_BACKEND = "http://127.0.0.1:" + PY_PORT;

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const PYTHON_EXE = path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe");
const PY_MAIN = path.join(PROJECT_ROOT, "main.py");

// ── State ──────────────────────────────────────────
let pythonProc = null;
let mainWindow = null;
let tray = null;
let _chatEventBuf = "";
const CHAT_EVENT_PREFIX = "[CHAT_EVENT]";
let _backendReady = false;
let _pendingHealthInterval = null;

// ── Backend ────────────────────────────────────────
function startPythonBackend() {
  if (pythonProc) return;
  console.log("[main] starting Python backend:", PY_MAIN);

  pythonProc = spawn(PYTHON_EXE, [PY_MAIN], {
    cwd: PROJECT_ROOT,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
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
    broadcastHealth();
  });

  // Poll until backend is ready
  _pendingHealthInterval = setInterval(async () => {
    try {
      const ok = await healthCheck();
      if (ok) {
        _backendReady = true;
        broadcastHealth();
        clearInterval(_pendingHealthInterval);
        _pendingHealthInterval = null;
      }
    } catch (_) {}
  }, 1000);
}

function handleStderr(chunk) {
  const s = chunk.toString("utf-8");
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

function broadcastHealth() {
  const wins = BrowserWindow.getAllWindows();
  for (const w of wins) {
    if (w && !w.isDestroyed()) {
      w.webContents.send("backend:health", { ready: _backendReady });
    }
  }
}

function healthCheck() {
  return new Promise((resolve) => {
    const req = http.get(PY_BACKEND + "/api/health", (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => {
        try {
          const j = JSON.parse(d);
          resolve(j.status === "ok");
        } catch (_) {
          resolve(false);
        }
      });
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2000, () => { req.destroy(); resolve(false); });
  });
}

function apiRequest(opts) {
  return new Promise((resolve, reject) => {
    const url = new URL(PY_BACKEND + (opts.path || "/"));
    const options = {
      hostname: "127.0.0.1",
      port: PY_PORT,
      path: url.pathname + url.search,
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" },
      timeout: 30000,
    };
    const req = http.request(options, (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => {
        let body;
        try { body = JSON.parse(d); } catch (_) { body = d; }
        resolve({ status: res.statusCode, data: body });
      });
    });
    req.on("error", (err) => reject(err));
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    if (opts.body) req.write(JSON.stringify(opts.body));
    req.end();
  });
}

// ── Windows ────────────────────────────────────────
function createMainWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width: Math.min(1280, width),
    height: Math.min(800, height),
    minWidth: 900,
    minHeight: 600,
    frame: false,
    transparent: true,
    titleBarStyle: "hidden",
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: path.join(PROJECT_ROOT, "Aerie · 云栖.png"),
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.on("closed", () => { mainWindow = null; });
}

// ── Tray ───────────────────────────────────────────
function createTray() {
  const iconPath = path.join(PROJECT_ROOT, "Aerie · 云栖.png");
  if (!fs.existsSync(iconPath)) {
    console.warn("[main] tray icon not found:", iconPath);
    return;
  }
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip("Aerie · 云栖");
  tray.on("click", () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    }
  });
}

// ── IPC Handlers ───────────────────────────────────
ipcMain.handle("api:request", async (_event, opts) => {
  try {
    return await apiRequest(opts);
  } catch (err) {
    return { status: 0, data: { error: err.message } };
  }
});

ipcMain.handle("get-health", async () => {
  return { ready: _backendReady, port: PY_PORT };
});

ipcMain.handle("napcat:getStatus", async () => {
  try {
    const r = await apiRequest({ path: "/api/napcat/status" });
    return r.data;
  } catch (_) {
    return { phase: "idle", error: "backend unreachable" };
  }
});

ipcMain.handle("napcat:start", async () => {
  try {
    const r = await apiRequest({ method: "POST", path: "/api/napcat/start" });
    return r.data;
  } catch (_) {
    return { ok: false, message: "backend unreachable" };
  }
});

ipcMain.handle("napcat:stop", async () => {
  try {
    const r = await apiRequest({ method: "POST", path: "/api/napcat/stop" });
    return r.data;
  } catch (_) {
    return { ok: false, message: "backend unreachable" };
  }
});

// ── Lifecycle ──────────────────────────────────────
app.whenReady().then(() => {
  startPythonBackend();
  createMainWindow();
  // Delay tray creation to avoid flash
  setTimeout(createTray, 2000);
});

app.on("window-all-closed", () => {
  // Don't quit on all windows closed (keep tray)
});

app.on("before-quit", () => {
  if (pythonProc) {
    pythonProc.kill();
    pythonProc = null;
  }
  if (tray) tray.destroy();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
});

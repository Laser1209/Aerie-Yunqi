"use strict";
const { app, BrowserWindow, Tray, ipcMain, nativeImage, screen, Menu, dialog } = require("electron");
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
let dynamicIsland = null;
// R7.1: legacy brief popup/detail windows removed. The brief now
// lives inside the main window as a right-side drawer (see
// renderer/js/brief-drawer.js + styles/brief-drawer.css).
let _chatEventBuf = "";
const CHAT_EVENT_PREFIX = "[CHAT_EVENT]";
let _backendReady = false;
let _pendingHealthInterval = null;

// ── Backend ────────────────────────────────────────
function startPythonBackend() {
  // v2.2 fix: before spawning a fresh Python, probe port 7890. If a
  // healthy backend is already listening (e.g. the user launched
  // `python main.py` manually, or the previous Electron session left
  // one running), attach to it instead of fighting for the port.
  healthCheck().then((alive) => {
    if (alive) {
      console.log("[main] existing backend detected on port " + PY_PORT + " — attaching");
      _backendReady = true;
      broadcastHealth();
      return;
    }
    _spawnNewPython();
  }).catch(() => _spawnNewPython());
}

function _spawnNewPython() {
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
    // v2.2: keep watching for a respawn so a "restart backend" click
    // can flip _backendReady back to true without an Electron reload.
    if (!_pendingHealthInterval) {
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
    const isRaw = opts.rawBody === true;
    const headers = isRaw
      ? { "Content-Type": "text/plain; charset=utf-8" }
      : { "Content-Type": "application/json" };
    const options = {
      hostname: "127.0.0.1",
      port: PY_PORT,
      path: url.pathname + url.search,
      method: opts.method || "GET",
      headers,
      timeout: 30000,
    };
    const req = http.request(options, (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => {
        let body;
        const ct = (res.headers && res.headers["content-type"] || "").toLowerCase();
        if (ct.indexOf("application/json") >= 0) {
          try { body = JSON.parse(d); } catch (_) { body = d; }
        } else if (isRaw) {
          body = d; // keep as text for raw text/plain responses (e.g. yaml GET)
        } else {
          try { body = JSON.parse(d); } catch (_) { body = d; }
        }
        resolve({ status: res.statusCode, data: body });
      });
    });
    req.on("error", (err) => reject(err));
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    if (opts.body) {
      req.write(isRaw ? String(opts.body) : JSON.stringify(opts.body));
    }
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

  // Broadcast maximize state changes to renderer so the button glyph can update
  mainWindow.on("maximize", () => broadcastMaximizeState(true));
  mainWindow.on("unmaximize", () => broadcastMaximizeState(false));
}

// ── Dynamic Island ────────────────────────────────
function createDynamicIsland() {
  if (dynamicIsland) return;

  const display = screen.getPrimaryDisplay();
  const { workArea } = display;
  const width = 200;
  const height = 36;
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

  dynamicIsland.setAlwaysOnTop(true, "floating");
  dynamicIsland.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  dynamicIsland.setIgnoreMouseEvents(true, { forward: true });

  dynamicIsland.loadFile(path.join(__dirname, "renderer", "dynamic-island.html"));

  dynamicIsland.webContents.on("did-finish-load", () => {
    startIslandPenetrationPolling();
    startSystemStatusPolling();
  });

  dynamicIsland.on("closed", () => {
    stopIslandPenetrationPolling();
    stopSystemStatusPolling();
    dynamicIsland = null;
  });
}

// ── Dynamic Island Mouse Penetration System ───
let _islandIgnoreState = true;
let _islandHoverTimer = null;
let _islandPollInterval = null;
let _islandExpanded = false;

function startIslandPenetrationPolling() {
  if (_islandPollInterval) return;

  _islandPollInterval = setInterval(() => {
    if (!dynamicIsland || dynamicIsland.isDestroyed()) return;

    if (_islandExpanded) {
      setIslandIgnoreMouse(false);
      return;
    }

    try {
      const cursorPos = screen.getCursorScreenPoint();
      const winBounds = dynamicIsland.getBounds();
      const scaleFactor = screen.getPrimaryDisplay().scaleFactor || 1;

      const inBounds =
        cursorPos.x >= winBounds.x &&
        cursorPos.x <= winBounds.x + winBounds.width &&
        cursorPos.y >= winBounds.y &&
        cursorPos.y <= winBounds.y + winBounds.height;

      if (inBounds) {
        if (_islandHoverTimer) {
          clearTimeout(_islandHoverTimer);
          _islandHoverTimer = null;
        }
        setIslandIgnoreMouse(false);
      } else {
        if (!_islandHoverTimer && !_islandIgnoreState) {
          _islandHoverTimer = setTimeout(() => {
            setIslandIgnoreMouse(true);
            _islandHoverTimer = null;
          }, 120);
        }
      }
    } catch (_) {}
  }, 30);
}

function stopIslandPenetrationPolling() {
  if (_islandPollInterval) {
    clearInterval(_islandPollInterval);
    _islandPollInterval = null;
  }
  if (_islandHoverTimer) {
    clearTimeout(_islandHoverTimer);
    _islandHoverTimer = null;
  }
}

function setIslandExpanded(expanded) {
  _islandExpanded = !!expanded;
  if (expanded) {
    setIslandIgnoreMouse(false);
  }
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
  const iconPath = path.join(PROJECT_ROOT, "Aerie · 云栖.png");
  if (!fs.existsSync(iconPath)) {
    console.warn("[main] tray icon not found:", iconPath);
    return;
  }
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
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
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
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
          dynamicIsland.show();
        }
      },
    },
    { type: "separator" },
    {
      // R7.1: trigger the in-app right-side drawer (no separate window)
      label: "打开今日简报 / Open Brief",
      click: () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.show();
          mainWindow.focus();
          try { mainWindow.webContents.send("brief:show"); } catch (_) {}
        }
      },
    },
    {
      label: "展开完整日报 / Full Brief",
      click: () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.show();
          mainWindow.focus();
          try { mainWindow.webContents.send("brief:show", { expanded: true }); } catch (_) {}
        }
      },
    },
    {
      label: "设置",
      click: () => {
        if (mainWindow) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
        }
        BrowserWindow.getAllWindows().forEach((w) => {
          if (w && !w.isDestroyed()) {
            try { w.webContents.send("ui:open-tab", "settings"); } catch (_) {}
          }
        });
      },
    },
    {
      label: "关于",
      click: () => {
        dialog.showMessageBox({
          type: "info",
          title: "Aerie · 云栖",
          message: "Aerie · 云栖",
          detail:
            "Aerie · 云栖 v10.1.1\n" +
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
    return await apiRequest(opts);
  } catch (err) {
    return { status: 0, data: { error: err.message } };
  }
});

// Dynamic Island IPC
ipcMain.on("ui:open-main", () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
});

ipcMain.on("ui:open-quick-chat", () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  try {
    mainWindow.webContents.send("ui:open-tab", "chat");
  } catch (_) {}
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
  if (!mainWindow) return { ok: false };
  try {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    if (tab) {
      mainWindow.webContents.send("ui:open-tab", tab);
    }
    return { ok: true };
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
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.webContents.send("island:config-change", _islandConfig);
  }
  return { ok: true, config: _islandConfig };
});

ipcMain.handle("island:get-config", async () => {
  return { ok: true, config: _islandConfig };
});

// System status (CPU / memory / network)
const os = require("os");
let _lastCpuTimes = null;
let _lastNetStats = null;

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
let _systemStatus = { cpu: 0, mem: 0, net: 0 };

function startSystemStatusPolling() {
  if (_systemStatusInterval) return;
  _getCpuUsage();
  _systemStatusInterval = setInterval(() => {
    _systemStatus.cpu = _getCpuUsage();
    _systemStatus.mem = _getMemUsage();
    _systemStatus.net = Math.random() * 200 + 20;
    if (dynamicIsland && !dynamicIsland.isDestroyed()) {
      dynamicIsland.webContents.send("island:system-status", _systemStatus);
    }
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

// Media control (mock for now, can integrate with Windows SMTC later)
let _mediaState = {
  playing: false,
  title: "",
  artist: "",
  progress: 0,
  duration: 0,
};

ipcMain.handle("island:media-get-state", async () => {
  return { ok: true, data: _mediaState };
});

ipcMain.handle("island:media-play-pause", async () => {
  _mediaState.playing = !_mediaState.playing;
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.webContents.send("island:media-update", _mediaState);
  }
  return { ok: true, data: _mediaState };
});

ipcMain.handle("island:media-next", async () => {
  _mediaState.progress = 0;
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.webContents.send("island:media-update", _mediaState);
  }
  return { ok: true, data: _mediaState };
});

ipcMain.handle("island:media-prev", async () => {
  _mediaState.progress = 0;
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.webContents.send("island:media-update", _mediaState);
  }
  return { ok: true, data: _mediaState };
});

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
        let d = "";
        res.on("data", (c) => (d += c));
        res.on("end", () => {
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
const sseClients = new Map(); // webContents.id -> { req }

ipcMain.handle("sse:subscribe", async (event) => {
  const senderId = event.sender.id;
  if (sseClients.has(senderId)) {
    return { ok: true, dedup: true };
  }
  const req = http.request(
    {
      hostname: "127.0.0.1",
      port: PY_PORT,
      path: "/api/events/stream",
      method: "GET",
      headers: { "Accept": "text/event-stream" },
    },
    (res) => {
      let buf = "";
      res.on("data", (chunk) => {
        buf += chunk.toString("utf-8");
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          if (frame.startsWith("data: ")) {
            const payload = frame.slice(6);
            const target = BrowserWindow.getAllWindows().find(
              (w) => !w.isDestroyed() && w.webContents.id === senderId
            );
            if (target) {
              try { target.webContents.send("sse:event", payload); } catch (_) {}
            }
          }
        }
      });
    }
  );
  req.on("error", () => {
    sseClients.delete(senderId);
    setTimeout(() => {
      const stillAlive = BrowserWindow.getAllWindows().some(
        (w) => !w.isDestroyed() && w.webContents.id === senderId
      );
      if (stillAlive) {
        // reconnect by re-invoking ourselves
        const target = BrowserWindow.getAllWindows().find(
          (w) => !w.isDestroyed() && w.webContents.id === senderId
        );
        if (target) {
          // Recreate the connection
          connectSseForWebContents(senderId);
        }
      }
    }, 3000);
  });
  req.end();
  sseClients.set(senderId, { req });
  return { ok: true };
});

function connectSseForWebContents(senderId) {
  // Internal helper: same logic as the ipcMain handler, but for auto-reconnect.
  if (sseClients.has(senderId)) return;
  const req = http.request(
    {
      hostname: "127.0.0.1",
      port: PY_PORT,
      path: "/api/events/stream",
      method: "GET",
      headers: { "Accept": "text/event-stream" },
    },
    (res) => {
      let buf = "";
      res.on("data", (chunk) => {
        buf += chunk.toString("utf-8");
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          if (frame.startsWith("data: ")) {
            const payload = frame.slice(6);
            const target = BrowserWindow.getAllWindows().find(
              (w) => !w.isDestroyed() && w.webContents.id === senderId
            );
            if (target) {
              try { target.webContents.send("sse:event", payload); } catch (_) {}
            }
          }
        }
      });
    }
  );
  req.on("error", () => {
    sseClients.delete(senderId);
    setTimeout(() => {
      const stillAlive = BrowserWindow.getAllWindows().some(
        (w) => !w.isDestroyed() && w.webContents.id === senderId
      );
      if (stillAlive) connectSseForWebContents(senderId);
    }, 3000);
  });
  req.end();
  sseClients.set(senderId, { req });
}

ipcMain.handle("sse:unsubscribe", async (event) => {
  const senderId = event.sender.id;
  const client = sseClients.get(senderId);
  if (client) {
    try { client.req.destroy(); } catch (_) {}
    sseClients.delete(senderId);
  }
  return { ok: true };
});

// Cleanup SSE clients when webContents is destroyed
app.on("web-contents-destroyed", (_event, contents) => {
  const client = sseClients.get(contents.id);
  if (client) {
    try { client.req.destroy(); } catch (_) {}
    sseClients.delete(contents.id);
  }
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
  if (win) win.close();
  return true;
});

// R7.0: Forward /api/health as-is so the renderer can read stale_code
// without a second round-trip. The renderer's poll already calls
// /api/health, so this IPC is mainly used by the very first paint
// before the renderer's poll loop kicks in.
ipcMain.handle("get-health", async () => {
  try {
    const r = await apiRequest({ path: "/api/health" });
    if (r && r.data) {
      const sc = (r.data && r.data.stale_code) || {};
      return {
        ready: _backendReady,
        port: PY_PORT,
        stale: !!sc.stale,
        modified: sc.modified || [],
        started_at: sc.started_at || r.data.process_started_at || "",
      };
    }
  } catch (_) {}
  return { ready: _backendReady, port: PY_PORT, stale: false, modified: [] };
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

// R6.6: backend self-restart. Triggers tools/restart_helper.ps1 via the
// Python /api/system/restart endpoint, which spawns a fresh main.py in
// a detached process. The Electron window stays alive; its SSE / status
// polling will reconnect once the new backend is up.
ipcMain.handle("system:restart-backend", async () => {
  try {
    const r = await apiRequest({ method: "POST", path: "/api/system/restart" });
    return r.data || { status: "scheduled" };
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
app.whenReady().then(() => {
  startPythonBackend();
  createMainWindow();
  createDynamicIsland();
  // Delay tray creation to avoid flash
  setTimeout(createTray, 2000);
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
        try {
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send("brief:show");
          }
        } catch (e) { console.warn("[main] open-brief send failed:", e); }
      }, 8000);
    }
  }, 1000);
});

app.on("window-all-closed", () => {
  // Don't quit on all windows closed (keep tray)
});

app.on("before-quit", () => {
  if (pythonProc) {
    pythonProc.kill();
    pythonProc = null;
  }
  if (dynamicIsland && !dynamicIsland.isDestroyed()) {
    dynamicIsland.setClosable(true);
    dynamicIsland.close();
    dynamicIsland = null;
  }
  if (tray) tray.destroy();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
});

/* Aerie · 云栖 v9.0 — Electron main process
 *
 * Responsibilities:
 *  - Single-instance lock
 *  - Load userData/config.json
 *  - Spawn pythonw.exe main.py (windowsHide, no console)
 *  - Main window + floating ball + tray
 *  - IPC bridge
 *  - Self startup registration
 */

'use strict';

const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

// Disable hardware acceleration to reduce memory + avoid GPU issues on Win11.
app.disableHardwareAcceleration();

// Single-instance lock
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

// Paths
const ROOT = path.resolve(__dirname, '..', '..');
const RENDERER_DIR = path.join(__dirname, 'renderer');
const USER_DATA = () => app.getPath('userData');
const CONFIG_PATH = () => path.join(USER_DATA(), 'config.json');

// Globals
let mainWindow = null;
let floatingBall = null;
let tray = null;
let pythonProc = null;
let config = {};

// ---- Config ----
function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_PATH())) {
      config = JSON.parse(fs.readFileSync(CONFIG_PATH(), 'utf-8'));
    }
  } catch (e) {
    console.error('loadConfig failed:', e);
  }
  config = Object.assign({
    app_name: '云栖',
    self_qq: 123456789,
    napcat_ws_url: 'ws://127.0.0.1:3001',
    http_api_host: '127.0.0.1',
    http_api_port: 7890,
    theme: 'yita-pink',
    auto_start: false,
    start_minimized: true,
    window: { main: { w: 1280, h: 800 }, chat: { w: 380, h: 480 } },
    ball: { size: 64, margin: 30, opacity_idle: 0.3 },
  }, config);
  return config;
}

function saveConfig() {
  try {
    if (!fs.existsSync(USER_DATA())) fs.mkdirSync(USER_DATA(), { recursive: true });
    fs.writeFileSync(CONFIG_PATH(), JSON.stringify(config, null, 2));
  } catch (e) {
    console.error('saveConfig failed:', e);
  }
}

// ---- Python path detection ----
function getPythonPath() {
  const candidates = [
    path.join(ROOT, '.venv', 'Scripts', 'pythonw.exe'),
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    'C:\\Python314\\pythonw.exe',
    'C:\\Python313\\pythonw.exe',
    'C:\\Python312\\pythonw.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python314', 'pythonw.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python313', 'pythonw.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'pythonw.exe'),
  ];
  for (const c of candidates) {
    try {
      if (c && fs.existsSync(c)) return c;
    } catch (e) {}
  }
  return 'pythonw';
}

function ensureLogsDir() {
  const dir = path.join(ROOT, 'logs');
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  return dir;
}

function startPythonBackend() {
  const py = getPythonPath();
  const args = [path.join(ROOT, 'main.py')];
  const logsDir = ensureLogsDir();
  const stderrPath = path.join(logsDir, 'python_stderr.log');
  const stdoutPath = path.join(logsDir, 'python_stdout.log');
  let stderrStream = null;
  try {
    stderrStream = fs.createWriteStream(stderrPath, { flags: 'a' });
    stderrStream.write(`\n===== [${new Date().toISOString()}] spawn: ${py} ${args.join(' ')} =====\n`);
    pythonProc = spawn(py, args, {
      cwd: ROOT,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: false,
      env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1', LOG_DIR: logsDir }),
    });
    if (pythonProc.stdout) {
      pythonProc.stdout.on('data', (d) => fs.appendFileSync(stdoutPath, d));
    }
    if (pythonProc.stderr) {
      pythonProc.stderr.on('data', (d) => {
        const s = d.toString();
        stderrStream.write(s);
        process.stderr.write('[python] ' + s);
      });
    }
    pythonProc.on('exit', (code) => {
      console.log('python exited', code);
      stderrStream && stderrStream.end();
      if (mainWindow) mainWindow.webContents.send('backend:exit', code);
    });
    pythonProc.on('error', (e) => {
      console.error('python spawn error:', e);
      const hint = e && e.code === 'ENOENT' ? '找不到 Python 解释器，请安装 Python 3.12+ 并确保在 PATH 中' : '';
      if (stderrStream) stderrStream.write('ERROR: ' + String(e) + ' ' + hint + '\n');
      if (mainWindow) mainWindow.webContents.send('backend:error', String(e) + ' ' + hint);
    });
    // Health check: poll until backend is ready or timeout (60s)
    let napcatBootstrapTried = false;
    async function bootstrapNapcatIfNeeded() {
      if (napcatBootstrapTried) return;
      napcatBootstrapTried = true;
      const base = `http://${config.http_api_host}:${config.http_api_port}`;
      try {
        const r = await fetch(`${base}/api/napcat/status`, { signal: AbortSignal.timeout(5000) });
        if (!r.ok) return;
        const status = await r.json();
        if (status && status.ws_port_open) {
          console.log('[Aerie] NapCat WS port already open, skipping auto-start');
          return;
        }
        console.log('[Aerie] NapCat not detected, requesting auto-bootstrap');
        const rb = await fetch(`${base}/api/napcat/bootstrap`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prefer_user: true, wait_port: true }),
          signal: AbortSignal.timeout(60000),
        });
        const result = await rb.json().catch(() => ({}));
        console.log('[Aerie] NapCat bootstrap result:', result);
        if (mainWindow) {
          mainWindow.webContents.send('napcat:bootstrap', { ...result, status: result.status || 'unknown' });
        }
      } catch (e) {
        console.warn('[Aerie] NapCat bootstrap failed:', String(e));
        if (mainWindow) {
          mainWindow.webContents.send('napcat:bootstrap', { status: 'error', error: String(e).slice(0, 200) });
        }
      }
    }
    pollBackendHealth(0, 30);
  } catch (e) {
    console.error('startPythonBackend failed:', e);
    if (mainWindow) mainWindow.webContents.send('backend:error', String(e));
  }
}

async function pollBackendHealth(retry, maxRetries) {
  const url = `http://${config.http_api_host}:${config.http_api_port}/api/health`;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(3000) });
    if (r.ok) {
      console.log('[Aerie] Python backend ready');
      if (mainWindow) mainWindow.webContents.send('backend:ready');
      // Fire-and-forget: try to bootstrap NapCat after the backend is reachable.
      setTimeout(() => { bootstrapNapcatIfNeeded(); }, 500);
      return;
    }
  } catch (e) {
    // Not ready yet
  }
  // Progress event every 5s to renderer
  if (retry % 3 === 0 && mainWindow) {
    mainWindow.webContents.send('backend:progress', {
      retry, maxRetries, secondsElapsed: retry * 2,
      hint: retry < 6 ? '正在启动 Python 后端…' : '启动较慢，请检查日志 logs/python_stderr.log',
    });
  }
  if (retry < maxRetries) {
    setTimeout(() => pollBackendHealth(retry + 1, maxRetries), 2000);
  } else {
    console.warn('[Aerie] Python backend timeout');
    if (mainWindow) mainWindow.webContents.send('backend:timeout');
  }
}

// ---- Windows ----
function createMainWindow() {
  const w = (config.window && config.window.main) || { w: 1280, h: 800 };
  mainWindow = new BrowserWindow({
    width: w.w,
    height: w.h,
    minWidth: 960,
    minHeight: 640,
    title: 'Aerie · 云栖',
    backgroundColor: '#1a1a1a',
    show: !config.start_minimized,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  });
  mainWindow.loadFile(path.join(RENDERER_DIR, 'index.html'));
  mainWindow.on('close', (e) => {
    if (!app.isQuiting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });
}

function createFloatingBall() {
  const size = (config.ball && config.ball.size) || 80;
  floatingBall = new BrowserWindow({
    width: size,
    height: size,
    frame: false,
    transparent: true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    fullscreenable: false,
    useContentSize: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      devTools: false,
    },
  });
  floatingBall.setMinimumSize(size, size);
  floatingBall.setMaximumSize(size, size);
  floatingBall.loadFile(path.join(RENDERER_DIR, 'floating-ball.html'));
  const { screen } = require('electron');
  const display = screen.getPrimaryDisplay();
  const margin = (config.ball && config.ball.margin) || 30;
  floatingBall.setPosition(
    display.workArea.width - size - margin,
    display.workArea.height - size - margin
  );
}

function createTray() {
  // Generate a simple 16x16 icon on the fly if no icon.ico exists
  const iconPath = path.join(__dirname, '..', 'builder', 'icon.ico');
  let icon;
  if (fs.existsSync(iconPath)) {
    icon = nativeImage.createFromPath(iconPath);
  } else {
    icon = nativeImage.createEmpty();
  }
  tray = new Tray(icon);
  const menu = Menu.buildFromTemplate([
    { label: '打开 Aerie', click: () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } } },
    { label: '悬浮球', click: () => { if (floatingBall) floatingBall.show(); } },
    { type: 'separator' },
    { label: '开机自启', type: 'checkbox', checked: !!config.auto_start, click: (item) => {
      config.auto_start = item.checked;
      app.setLoginItemSettings({ openAtLogin: item.checked });
      saveConfig();
    } },
    { label: '暂停推送 1 小时', click: async () => {
      try {
        await fetch(`http://${config.http_api_host}:${config.http_api_port}/api/proactive/pause`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ minutes: 60 }),
        });
      } catch (e) { console.error(e); }
    }},
    { type: 'separator' },
    { label: '退出', click: () => { app.isQuiting = true; app.quit(); } },
  ]);
  tray.setToolTip('Aerie · 云栖');
  tray.setContextMenu(menu);
  tray.on('click', () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } });
}

// ---- IPC ----
function setupIPC() {
  ipcMain.handle('config:get', () => config);
  ipcMain.handle('config:set', (_e, patch) => {
    Object.assign(config, patch || {});
    saveConfig();
    return config;
  });
  ipcMain.handle('api:request', async (_e, { method = 'GET', path: p, body }) => {
    const base = `http://${config.http_api_host}:${config.http_api_port}`;
    try {
      const r = await fetch(base + p, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await r.text();
      let data;
      try { data = JSON.parse(text); } catch (_) { data = text; }
      return { status: r.status, data };
    } catch (e) {
      return { status: 0, error: String(e) };
    }
  });
  ipcMain.handle('window:minimize', () => { if (mainWindow) mainWindow.minimize(); });
  ipcMain.handle('window:close', () => { if (mainWindow) mainWindow.close(); });
  ipcMain.handle('ball:expand', () => {
    if (floatingBall) floatingBall.hide();
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
  });
  ipcMain.handle('ball:showMain', (_e, { wideSidebar } = {}) => {
    if (floatingBall) floatingBall.hide();
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
      if (wideSidebar) {
        // Renderer will read body class via global event
        mainWindow.webContents.send('sidebar:wide', true);
      } else {
        mainWindow.webContents.send('sidebar:wide', false);
      }
    }
  });
  ipcMain.handle('ball:move', (_e, { dx, dy }) => {
    if (!floatingBall) return;
    const { screen } = require('electron');
    const display = screen.getPrimaryDisplay();
    const cur = floatingBall.getBounds();
    const maxX = Math.max(0, display.workArea.width - cur.width);
    const maxY = Math.max(0, display.workArea.height - cur.height);
    const newX = Math.min(maxX, Math.max(0, cur.x + dx));
    const newY = Math.min(maxY, Math.max(0, cur.y + dy));
    floatingBall.setPosition(Math.round(newX), Math.round(newY));
  });
  ipcMain.handle('ball:snapToEdge', (_e, axis) => {
    if (!floatingBall) return;
    const { screen } = require('electron');
    const display = screen.getPrimaryDisplay();
    const [x, y] = floatingBall.getPosition();
    const bw = floatingBall.getBounds().width;
    const bh = floatingBall.getBounds().height;
    const margin = (config.ball && config.ball.margin) || 30;
    const centerX = x + bw / 2;
    const centerY = y + bh / 2;
    if (axis === 'x' || axis === 'both') {
      const snapLeft = centerX < display.workArea.width / 2;
      const snapX = snapLeft ? margin : display.workArea.width - bw - margin;
      floatingBall.setPosition(snapX, floatingBall.getBounds().y);
    }
    if (axis === 'y' || axis === 'both') {
      const snapTop = centerY < display.workArea.height / 2;
      const snapY = snapTop ? margin : display.workArea.height - bh - margin;
      floatingBall.setPosition(floatingBall.getBounds().x, snapY);
    }
  });
  ipcMain.handle('ball:getBounds', () => {
    if (!floatingBall) return null;
    const { screen } = require('electron');
    const display = screen.getPrimaryDisplay();
    const b = floatingBall.getBounds();
    return {
      x: b.x, y: b.y, w: b.width, h: b.height,
      screenW: display.workArea.width, screenH: display.workArea.height,
      margin: (config.ball && config.ball.margin) || 30,
      size: b.width,
    };
  });
  ipcMain.handle('app:openExternal', (_e, url) => shell.openExternal(url));
  ipcMain.handle('app:quit', () => { app.isQuiting = true; app.quit(); });

  // ---- NapCat control ----
  const napcatApiCall = async (method, path, body) => {
    const base = `http://${config.http_api_host}:${config.http_api_port}`;
    try {
      const r = await fetch(base + path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(90000),
      });
      const text = await r.text();
      let data;
      try { data = JSON.parse(text); } catch (_) { data = text; }
      return { status: r.status, data };
    } catch (e) {
      return { status: 0, error: String(e) };
    }
  };
  ipcMain.handle('napcat:status', () => napcatApiCall('GET', '/api/napcat/status'));
  ipcMain.handle('napcat:start', (_e, opts) => napcatApiCall('POST', '/api/napcat/start', opts || {}));
  ipcMain.handle('napcat:stop', () => napcatApiCall('POST', '/api/napcat/stop', {}));
  ipcMain.handle('napcat:bootstrap', (_e, opts) => napcatApiCall('POST', '/api/napcat/bootstrap', opts || {}));
}

// ---- App lifecycle ----
app.on('second-instance', () => {
  if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
});

app.whenReady().then(() => {
  loadConfig();
  app.setLoginItemSettings({ openAtLogin: !!config.auto_start });
  startPythonBackend();
  createMainWindow();
  createFloatingBall();
  createTray();
  setupIPC();
});

app.on('window-all-closed', (e) => {
  // Don't quit on window close; keep running in tray.
  e.preventDefault && e.preventDefault();
});

app.on('before-quit', () => {
  app.isQuiting = true;
  if (pythonProc) {
    try { pythonProc.kill(); } catch (_) {}
  }
});

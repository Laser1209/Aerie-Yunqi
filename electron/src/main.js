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
  ];
  for (const c of candidates) {
    try {
      if (fs.existsSync(c)) return c;
    } catch (e) {}
  }
  return 'pythonw';
}

function startPythonBackend() {
  const py = getPythonPath();
  const args = [path.join(ROOT, 'main.py')];
  try {
    pythonProc = spawn(py, args, {
      cwd: ROOT,
      windowsHide: true,
      stdio: 'ignore',
      detached: false,
      env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1', LOG_DIR: path.join(ROOT, 'logs') }),
    });
    pythonProc.on('exit', (code) => console.log('python exited', code));
    pythonProc.on('error', (e) => console.error('python spawn error:', e));
  } catch (e) {
    console.error('startPythonBackend failed:', e);
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
  const size = (config.ball && config.ball.size) || 64;
  floatingBall = new BrowserWindow({
    width: size,
    height: size,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  });
  floatingBall.loadFile(path.join(RENDERER_DIR, 'floating-ball.html'));
  // Place in bottom-right
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
  ipcMain.handle('app:openExternal', (_e, url) => shell.openExternal(url));
  ipcMain.handle('app:quit', () => { app.isQuiting = true; app.quit(); });
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

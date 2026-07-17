"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aerie", {
  api: {
    request: (opts) => ipcRenderer.invoke("api:request", opts),
    // R7.0: multipart upload IPC. Renderer passes raw bytes (as Array)
    // + filename/contentType; the main process builds the multipart body
    // and forwards to the Python backend. This is the only path that
    // works under file:// (no CORS, no file:// fetch limitations).
    upload: (opts) => ipcRenderer.invoke("api:upload", opts),
    onMessage: (cb) => {
      ipcRenderer.on("chat:message", (_event, data) => cb(data));
    },
  },
  // Phase 9 Batch 4: SSE → IPC bridge subscription for brain center
  sse: {
    subscribe: (callback) => {
      const handler = (_event, payload) => {
        try { callback(payload); } catch (_) {}
      };
      ipcRenderer.on("sse:event", handler);
      ipcRenderer.invoke("sse:subscribe");
      return () => {
        ipcRenderer.removeListener("sse:event", handler);
        ipcRenderer.invoke("sse:unsubscribe");
      };
    },
  },
  napcat: {
    getStatus: () => ipcRenderer.invoke("napcat:getStatus"),
    start: () => ipcRenderer.invoke("napcat:start"),
    stop: () => ipcRenderer.invoke("napcat:stop"),
    onEvent: (cb) => {
      ipcRenderer.on("napcat:event", (_event, data) => cb(data));
    },
  },
  electron: {
    onHealth: (cb) => {
      ipcRenderer.on("backend:health", (_event, data) => cb(data));
    },
    getHealth: () => ipcRenderer.invoke("get-health"),
    window: {
      minimize: () => ipcRenderer.invoke("window:minimize"),
      toggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
      isMaximized: () => ipcRenderer.invoke("window:is-maximized"),
      close: () => ipcRenderer.invoke("window:close"),
      onMaximize: (cb) => {
        ipcRenderer.on("window:maximized", (_event, isMax) => cb(isMax));
      },
    },
    // Block-2 T1 bridge: tray "设置" click → settings tab
    onOpenTab: (cb) => {
      ipcRenderer.on("ui:open-tab", (_event, tab) => cb(tab));
    },
    // R6.6 / v2.2: one-click backend restart bridge. The handler
    // lives in main.js (ipcMain.handle("system:restart-backend"))
    // and ultimately calls /api/system/restart on the Python side.
    system: {
      restartBackend: () => ipcRenderer.invoke("system:restart-backend"),
    },
    // Block-4A R1.6 bridge: tray "打开今日简报" or boot 8s later → pop brief iframe
    onBriefShow: (cb) => {
      ipcRenderer.on("brief:show", (_event, data) => cb(data || {}));
    },
    // Block-5A: brief popup/detail window IPC bridge
    brief: {
      openDetail: (data) => ipcRenderer.invoke("brief:open-detail", data || {}),
      hide: () => ipcRenderer.invoke("brief:hide"),
      detailClose: () => ipcRenderer.invoke("brief:detail-close"),
      export: (data) => ipcRenderer.invoke("brief:export", data || {}),
      chat: () => ipcRenderer.invoke("brief:chat"),
    },
    notify: (channel, payload) => {
      // 弹窗/详情页用：旧 IPC 兼容通道
      const map = {
        "brief:open-detail":   () => ipcRenderer.invoke("brief:open-detail", payload || {}),
        "brief:hide":          () => ipcRenderer.invoke("brief:hide"),
        "brief:detail-close":  () => ipcRenderer.invoke("brief:detail-close"),
        "brief:export":        () => ipcRenderer.invoke("brief:export", payload || {}),
        "brief:chat":          () => ipcRenderer.invoke("brief:chat"),
      };
      const fn = map[channel];
      if (fn) { try { fn(); } catch (_) {} }
    },
  },
  settings: {
    get: () => ipcRenderer.invoke("settings:get"),
    set: (data) => ipcRenderer.invoke("settings:set", data),
    reset: () => ipcRenderer.invoke("settings:reset"),
  },
});

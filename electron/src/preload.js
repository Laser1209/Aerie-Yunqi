"use strict";
const { contextBridge, ipcRenderer } = require("electron");

// 后端就绪等待：应用冷启动/重启后端时，渲染进程的请求会先于后端
// 监听 7890 到达，主进程 http.request 立即返回 ECONNREFUSED，各面板
// 会把该错误作为永久横幅展示（即使后端随后恢复也不消失）。这里在
// IPC 层自动重试，等后端就绪后正常返回，从而根治启动窗口期的
// "connect ECONNREFUSED 127.0.0.1:7890" 报错。超时后仍返回原始错误。
const BACKEND_WAIT = Object.freeze({ maxMs: 15000, stepMs: 500 });

function isBackendRefused(result) {
  if (!result || result.status !== 0) return false;
  const message = String((result.data && result.data.error) || "");
  return /ECONNREFUSED|backend not ready/i.test(message);
}

async function withBackendWait(invoke, opts) {
  const deadline = Date.now() + BACKEND_WAIT.maxMs;
  for (;;) {
    const result = await invoke(opts);
    if (!isBackendRefused(result)) return result;
    if (Date.now() >= deadline) return result;
    await new Promise((resolve) => setTimeout(resolve, BACKEND_WAIT.stepMs));
  }
}

contextBridge.exposeInMainWorld("aerie", {
  api: {
    request: (opts) => withBackendWait((o) => ipcRenderer.invoke("api:request", o), opts),
    // R7.0: multipart upload IPC. Renderer passes raw bytes (as Array)
    // + filename/contentType; the main process builds the multipart body
    // and forwards to the Python backend. This is the only path that
    // works under file:// (no CORS, no file:// fetch limitations).
    upload: (opts) => withBackendWait((o) => ipcRenderer.invoke("api:upload", o), opts),
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
    getQrCode: () => ipcRenderer.invoke("napcat:getQrCode"),
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
    onBackendReady: (cb) => {
      ipcRenderer.on("backend:ready", (_event, data) => cb(data || {}));
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
      restartApp: () => ipcRenderer.invoke("system:restart-app"),
      reloadConfig: () => ipcRenderer.invoke("system:reload-config"),
      onRestarting: (cb) => {
        ipcRenderer.on("system:restarting", (_event, data) => cb(data || {}));
      },
    },
    // Block-4A R1.6 bridge: tray "打开今日简报" or boot 8s later → pop brief iframe
    onBriefShow: (cb) => {
      ipcRenderer.on("brief:show", (_event, data) => cb(data || {}));
    },
    // 办公模式：选择文件夹 / 打开路径
    dialog: {
      openDirectory: (opts) => ipcRenderer.invoke("dialog:openDirectory", opts || {}),
    },
    shell: {
      openPath: (path) => ipcRenderer.invoke("shell:openPath", path),
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
  attachments: {
    open: (attachmentId) => ipcRenderer.invoke("attachments:open", attachmentId),
    download: (attachmentId) => ipcRenderer.invoke("attachments:download", attachmentId),
  },
  worldDashboard: {
    getStatus: () => ipcRenderer.invoke("world-dashboard:get-status"),
    getSnapshot: () => ipcRenderer.invoke("world-dashboard:get-snapshot"),
    show: () => ipcRenderer.invoke("world-dashboard:show"),
    hide: () => ipcRenderer.invoke("world-dashboard:hide"),
    control: (action, payload) => ipcRenderer.invoke(
      "world-dashboard:control",
      { action, payload: payload || {} },
    ),
    enable: (payload) => ipcRenderer.invoke("world-dashboard:control", { action: "enable", payload: payload || {} }),
    disable: (payload) => ipcRenderer.invoke("world-dashboard:control", { action: "disable", payload: payload || {} }),
    start: (payload) => ipcRenderer.invoke("world-dashboard:control", { action: "start", payload: payload || {} }),
    stop: (payload) => ipcRenderer.invoke("world-dashboard:control", { action: "stop", payload: payload || {} }),
    pause: (payload) => ipcRenderer.invoke("world-dashboard:control", { action: "pause", payload: payload || {} }),
    resume: (payload) => ipcRenderer.invoke("world-dashboard:control", { action: "resume", payload: payload || {} }),
    restart: (payload) => ipcRenderer.invoke("world-dashboard:control", { action: "restart", payload: payload || {} }),
    approveCandidate: (payload) => ipcRenderer.invoke("world-dashboard:approve-candidate", payload || {}),
    previewCreative: (payload) => ipcRenderer.invoke("world-dashboard:preview-creative", payload || {}),
  },
  startup: {
    get: () => ipcRenderer.invoke("startup:get"),
    set: (options) => ipcRenderer.invoke("startup:set", options || {}),
  },
  islandControl: {
    setConfig: (cfg) => ipcRenderer.invoke("island:set-config", cfg || {}),
    getConfig: () => ipcRenderer.invoke("island:get-config"),
    notify: (data) => ipcRenderer.invoke("island:notify", data || {}),
    // R8.1: master enable switch for dynamic island
    setEnabled: (enable) => ipcRenderer.invoke("island:set-enabled", { enabled: !!enable }),
    getEnabled: () => ipcRenderer.invoke("island:get-enabled"),
    onEnabledChange: (cb) => {
      const handler = (_event, data) => {
        try { cb(data || {}); } catch (_) {}
      };
      ipcRenderer.on("island:enabled-change", handler);
      return () => ipcRenderer.removeListener("island:enabled-change", handler);
    },
  },
  dynamicIsland: {
    setSize: (width, height) => ipcRenderer.invoke("island:set-size", { width, height }),
    setState: (expanded) => ipcRenderer.invoke("island:state-change", { expanded }),
    setIgnoreMouse: (ignore) => ipcRenderer.invoke("island:set-ignore-mouse", { ignore }),
    openMain: (tab) => ipcRenderer.invoke("island:open-main", { tab }),
    notify: (data) => ipcRenderer.invoke("island:notify", data || {}),
    systemNotify: (data) => ipcRenderer.invoke("system:notify", data || {}),
    getSystemStatus: () => ipcRenderer.invoke("island:get-system-status"),
    onSystemStatus: (cb) => {
      ipcRenderer.on("island:system-status", (_event, data) => cb(data || {}));
    },
    mediaGetState: () => ipcRenderer.invoke("island:media-get-state"),
    mediaPlayPause: () => ipcRenderer.invoke("island:media-play-pause"),
    mediaNext: () => ipcRenderer.invoke("island:media-next"),
    mediaPrev: () => ipcRenderer.invoke("island:media-prev"),
    onMediaUpdate: (cb) => {
      ipcRenderer.on("island:media-update", (_event, data) => cb(data || {}));
    },
    onConfigChange: (cb) => {
      ipcRenderer.on("island:config-change", (_event, cfg) => cb(cfg || {}));
    },
    onNotify: (cb) => {
      ipcRenderer.on("island:notify", (_event, data) => cb(data || {}));
    },
    sseSubscribe: (callback) => {
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
});

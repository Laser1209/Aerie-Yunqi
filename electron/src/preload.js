"use strict";
const { contextBridge, ipcRenderer } = require("electron");

// Sandboxed Electron preloads can require Electron/built-in modules only.
// Keep this tiny allowlist local to the preload; the equivalent pure module is
// used by Node tests and the Renderer adapter, while no sandbox relaxation is
// needed in production.
function createCompanionStudioApi(request) {
  const paths = Object.freeze({
    health: "/api/integrations/companion-studio",
    talk: "/api/integrations/companion-studio/talk",
    speak: "/api/integrations/companion-studio/speak",
    asr: "/api/integrations/companion-studio/asr",
  });
  const text = (value, field) => {
    if (typeof value !== "string" || value.trim() === "") {
      throw new TypeError(`${field} must be a non-empty string`);
    }
    return value;
  };
  const normalize = (result) => {
    const body = result && result.data && typeof result.data === "object"
      ? result.data : result;
    if (!body || typeof body !== "object") {
      return { ok: false, status: "unavailable", reason: "invalid_response" };
    }
    return {
      ...body,
      ok: body.ok === true,
      status: typeof body.status === "string" ? body.status : "unavailable",
    };
  };
  const call = (method, path, body) => Promise.resolve(request({
    method,
    path,
    ...(body === undefined ? {} : { body }),
  })).then(normalize);
  return Object.freeze({
    health: () => call("GET", paths.health),
    talk: (value, source = "text") => call("POST", paths.talk, {
      text: text(value, "text"), source: text(source, "source"),
    }),
    speak: (value, echo) => {
      const body = { text: text(value, "text") };
      if (echo !== undefined) {
        if (typeof echo !== "boolean") throw new TypeError("echo must be a boolean");
        body.echo = echo;
      }
      return call("POST", paths.speak, body);
    },
    asr: (audioBase64, audioFormat = "wav") => call("POST", paths.asr, {
      audioBase64: text(audioBase64, "audioBase64"),
      format: text(audioFormat, "audioFormat"),
    }),
  });
}

// Keep every renderer surface on the same backend port, including isolated
// QA instances and packaged launches configured through the environment.
const BACKEND_PORT = Number.parseInt(process.env.AERIE_BACKEND_PORT || "7890", 10);
const API_BASE = `http://127.0.0.1:${Number.isFinite(BACKEND_PORT) ? BACKEND_PORT : 7890}`;
Object.defineProperty(window, "__API_BASE__", {
  configurable: false,
  enumerable: false,
  value: API_BASE,
});

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
    request: (opts) => withBackendWait((opts) => ipcRenderer.invoke("api:request", opts), opts),
    // R7.0: multipart upload IPC. Renderer passes raw bytes (as Array)
    // + filename/contentType; the main process builds the multipart body
    // and forwards to the Python backend. This is the only path that
    // works under file:// (no CORS, no file:// fetch limitations).
    upload: (opts) => withBackendWait((o) => ipcRenderer.invoke("api:upload", o), opts),
    onMessage: (cb) => {
      ipcRenderer.on("chat:message", (_event, data) => cb(data));
    },
  },
  // Companion Studio is a Renderer capability backed by Aerie's API. Keep
  // this allowlisted surface separate from the generic request bridge so the
  // integrated module cannot depend on the standalone 8899 service or invent
  // arbitrary IPC channels.
  companionStudio: createCompanionStudioApi((opts) => withBackendWait(
    (requestOpts) => ipcRenderer.invoke("api:request", requestOpts),
    opts,
  )),
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
    refreshQrCode: () => ipcRenderer.invoke("napcat:refreshQrCode"),
    getQuickAccounts: () => ipcRenderer.invoke("napcat:getQuickAccounts"),
    quickLogin: (uin) => ipcRenderer.invoke("napcat:quickLogin", uin),
    start: () => ipcRenderer.invoke("napcat:start"),
    stop: () => ipcRenderer.invoke("napcat:stop"),
    onEvent: (cb) => {
      ipcRenderer.on("napcat:event", (_event, data) => cb(data));
    },
  },
  ilinkGateway: {
    getStatus: () => ipcRenderer.invoke("ilinkGateway:getStatus"),
    start: () => ipcRenderer.invoke("ilinkGateway:start"),
    stop: () => ipcRenderer.invoke("ilinkGateway:stop"),
    loginStart: () => ipcRenderer.invoke("ilinkGateway:loginStart"),
    loginCancel: () => ipcRenderer.invoke("ilinkGateway:loginCancel"),
    pairingCode: () => ipcRenderer.invoke("ilinkGateway:pairingCode"),
  },
  electron: {
    onHealth: (cb) => {
      ipcRenderer.on("backend:health", (_event, data) => cb(data));
    },
    onBackendReady: (cb) => {
      ipcRenderer.on("backend:ready", (_event, data) => cb(data || {}));
    },
    getHealth: () => ipcRenderer.invoke("get-health"),
    // 开场动画（splash）：读取资产路径配置，并在视频播完 + 后端就绪后通知主进程关闭
    splash: {
      getConfig: () => ipcRenderer.invoke("splash:get-config"),
      complete: () => ipcRenderer.send("splash:complete"),
    },
    window: {
      minimize: () => ipcRenderer.invoke("window:minimize"),
      toggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
      isMaximized: () => ipcRenderer.invoke("window:is-maximized"),
      close: () => ipcRenderer.invoke("window:close"),
      // 日报抽屉展开/收起时，让 Electron 外壳的宽度跟着走（展开撑开、收起收回），
      // 而不是常驻加宽窗口去容纳抽屉。
      setDrawerExpanded: (expanded) =>
        ipcRenderer.invoke("window:drawer-shell", { expanded: !!expanded }),
      onMaximize: (cb) => {
        ipcRenderer.on("window:maximized", (_event, isMax) => cb(isMax));
      },
    },
    // 小伊 · 系统管家：她是**独立窗口**（贴在主窗口左边），主窗口这侧只负责
    // 开/关/查状态，内容全在她自己的窗口里（renderer/xiaoyi.html）。
    xiaoyi: {
      open: () => ipcRenderer.invoke("xiaoyi:open"),
      close: () => ipcRenderer.invoke("xiaoyi:close"),
      toggle: () => ipcRenderer.invoke("xiaoyi:toggle"),
      isOpen: () => ipcRenderer.invoke("xiaoyi:is-open"),
      onStateChange: (cb) => {
        ipcRenderer.on("xiaoyi:state", (_event, data) => cb(data || {}));
      },
    },
    // Block-2 T1 bridge: tray "设置" click → settings tab
    onOpenTab: (cb) => {
      ipcRenderer.on("ui:open-tab", (_event, tab) => cb(tab));
    },
    // R6.6 / v2.2: one-click backend restart bridge. The handler lives in
    // main.js (ipcMain.handle("system:restart-backend")) and restarts via the
    // Electron parent process (restartBackend()), NOT a Python-side
    // /api/system/restart call.
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
      openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),
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
  // 功能包模块中心：目录/安装/取消/移除/本地手动安装；下载进度走事件订阅。
  plugins: {
    catalog: () => ipcRenderer.invoke("plugins:catalog"),
    install: (id) => ipcRenderer.invoke("plugins:install", { id }),
    cancel: (id) => ipcRenderer.invoke("plugins:cancel", { id }),
    remove: (id) => ipcRenderer.invoke("plugins:remove", { id }),
    installLocal: () => ipcRenderer.invoke("plugins:install-local"),
    openDir: () => ipcRenderer.invoke("plugins:open-dir"),
    onProgress: (cb) => {
      const handler = (_event, data) => {
        try { cb(data || {}); } catch (_) {}
      };
      ipcRenderer.on("plugins:progress", handler);
      return () => ipcRenderer.removeListener("plugins:progress", handler);
    },
  },
  attachments: {
    open: (attachmentId) => ipcRenderer.invoke("attachments:open", attachmentId),
    download: (attachmentId) => ipcRenderer.invoke("attachments:download", attachmentId),
  },
  worldDashboard: {
    getStatus: () => ipcRenderer.invoke("world-dashboard:get-status"),
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
  },
  admin: {
    // P4b 管理平台（懒加载窗口，入口连点解锁后打开）
    show: () => ipcRenderer.invoke("admin:show"),
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
  // 消息提醒总开关：控制系统通知（新消息 / 日程 / 主动消息）
  notifControl: {
    setEnabled: (enable) => ipcRenderer.invoke("notif:set-enabled", { enabled: !!enable }),
    getEnabled: () => ipcRenderer.invoke("notif:get-enabled"),
    onEnabledChange: (cb) => {
      const handler = (_event, data) => {
        try { cb(data || {}); } catch (_) {}
      };
      ipcRenderer.on("notif:enabled-change", handler);
      return () => ipcRenderer.removeListener("notif:enabled-change", handler);
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
    getAvatarUrl: () => ipcRenderer.invoke("island:get-avatar-url"),
    api: (opts) => ipcRenderer.invoke("island:api", opts || {}),
    onSystemStatus: (cb) => {
      ipcRenderer.on("island:system-status", (_event, data) => cb(data || {}));
    },
    mediaGetState: () => ipcRenderer.invoke("island:media-get-state"),
    mediaPlayPause: () => ipcRenderer.invoke("island:media-play-pause"),
    mediaNext: () => ipcRenderer.invoke("island:media-next"),
    mediaPrev: () => ipcRenderer.invoke("island:media-prev"),
    mediaSeek: (positionSeconds) => ipcRenderer.invoke("island:media-seek", positionSeconds),
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

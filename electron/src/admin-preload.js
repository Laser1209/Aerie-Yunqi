"use strict";
// aerie.admin 管理平台专用 preload（P4b）。
// 安全红线：只暴露 api 通用方法（路径/method 由 main 侧双重白名单）+ 窗口控制，
// 绝不透传 ipcRenderer / 通用 api.request。token 由 main 进程注入，不暴露给页面。
const { contextBridge, ipcRenderer } = require("electron");

// 白名单：只暴露这些专用方法。
const ALLOWED_METHODS = ["api", "minimize", "close"];

const admin = {
  // 调用 /api/admin/*（main 侧自动附加 X-Aerie-Admin-Token）。
  // 返回 { ok, status, data, error }。
  api: (method, path, body) =>
    ipcRenderer.invoke("admin:api", {
      method: String(method || "GET"),
      path: String(path || ""),
      body: body === undefined ? undefined : body,
    }),
  // 无外壳窗口控制（复用主进程通用 IPC，作用于当前发送窗口）。
  minimize: () => ipcRenderer.invoke("window:minimize"),
  close: () => ipcRenderer.invoke("window:close"),
};

const exposed = {};
for (const key of ALLOWED_METHODS) {
  if (Object.prototype.hasOwnProperty.call(admin, key)) exposed[key] = admin[key];
}

contextBridge.exposeInMainWorld("admin", exposed);

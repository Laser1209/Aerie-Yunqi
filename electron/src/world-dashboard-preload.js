"use strict";
// aerie.world 独立仪表盘专用 preload。
// 安全红线：只暴露 5 个白名单方法，绝不透传 ipcRenderer / 通用 api.request。
const { contextBridge, ipcRenderer } = require("electron");

// 白名单：只暴露这些专用方法，绝不透传 ipcRenderer / 通用 api.request。
// 新增面板能力（记忆/控制台）也走显式枚举，不放开通配。
const ALLOWED_METHODS = [
  "getState",
  "pause",
  "resume",
  "previewImageDecision",
  "subscribe",
  "getMemory",
  "control",
  "getB3",
];

const world = {
  // 返回：{ status, worldSummary, emotion, actionTimeline, updatedAt }
  getState: () => ipcRenderer.invoke("world-dashboard:get-state"),
  pause: () => ipcRenderer.invoke("world-dashboard:control", { action: "pause", payload: {} }),
  resume: () => ipcRenderer.invoke("world-dashboard:control", { action: "resume", payload: {} }),
  previewImageDecision: (candidateId) => ipcRenderer.invoke(
    "world-dashboard:preview-creative",
    { candidateId: String(candidateId || "") },
  ),
  // 只读记忆档案（P6）：按层分组元数据，绝不写/删。
  getMemory: () => ipcRenderer.invoke("world-dashboard:get-memory"),
  // 第三批只读聚合（B3.2）：内在状态/趋势/决策观察/插件设置。仅读。
  getB3: () => ipcRenderer.invoke("world-dashboard:get-b3"),
  // 世界控制台（P8）：动作白名单在 main 侧与 host 侧双重校验。
  control: (action, payload = {}) => ipcRenderer.invoke(
    "world-dashboard:control",
    { action: String(action || ""), payload: payload && typeof payload === "object" ? payload : {} },
  ),
  // 订阅仪表盘状态更新。MVP 采用轮询实现：每 3s 拉取一次 getState 并回调。
  // 返回取消订阅函数。
  subscribe: (callback) => {
    if (typeof callback !== "function") return () => {};
    const POLL_MS = 3000;
    const timer = setInterval(async () => {
      try {
        const state = await ipcRenderer.invoke("world-dashboard:get-state");
        callback(state);
      } catch (_) {}
    }, POLL_MS);
    return () => clearInterval(timer);
  },
};

// 只暴露白名单方法（防御性剔除多余键，防 future drift）。
const exposed = {};
for (const key of ALLOWED_METHODS) {
  if (Object.prototype.hasOwnProperty.call(world, key)) exposed[key] = world[key];
}

contextBridge.exposeInMainWorld("world", exposed);

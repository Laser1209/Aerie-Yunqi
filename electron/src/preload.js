"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aerie", {
  api: {
    request: (opts) => ipcRenderer.invoke("api:request", opts),
    onMessage: (cb) => {
      ipcRenderer.on("chat:message", (_event, data) => cb(data));
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
  },
  settings: {
    get: () => ipcRenderer.invoke("settings:get"),
    set: (data) => ipcRenderer.invoke("settings:set", data),
    reset: () => ipcRenderer.invoke("settings:reset"),
  },
});

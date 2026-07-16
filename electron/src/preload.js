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
  },
  settings: {
    get: () => ipcRenderer.invoke("settings:get"),
    set: (data) => ipcRenderer.invoke("settings:set", data),
    reset: () => ipcRenderer.invoke("settings:reset"),
  },
});

/* Aerie · 云栖 v9.0 — Preload script
 * Exposes a narrow, safe `window.aerie` API to the renderer.
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aerie', {
  config: {
    get: () => ipcRenderer.invoke('config:get'),
    set: (patch) => ipcRenderer.invoke('config:set', patch),
  },
  api: {
    get: (path) => ipcRenderer.invoke('api:request', { method: 'GET', path }),
    post: (path, body) => ipcRenderer.invoke('api:request', { method: 'POST', path, body }),
  },
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    close: () => ipcRenderer.invoke('window:close'),
  },
  ball: {
    expand: () => ipcRenderer.invoke('ball:expand'),
  },
  system: {
    openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
    quit: () => ipcRenderer.invoke('app:quit'),
  },
});

/* Aerie · 云栖 v9.0 — Preload script
 * Exposes a narrow, safe `window.aerie` API to the renderer.
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aerie', {
  on: (channel, callback) => {
    const validChannels = [
      'backend:ready',
      'backend:timeout',
      'backend:error',
      'backend:progress',
      'backend:exit',
      'qq:status',
      'napcat:bootstrap',
    ];
    if (validChannels.includes(channel)) {
      ipcRenderer.on(channel, (_e, ...args) => callback(...args));
    }
  },
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
    showMain: (wideSidebar = false) => ipcRenderer.invoke('ball:showMain', { wideSidebar }),
    move: (dx, dy) => ipcRenderer.invoke('ball:move', { dx, dy }),
    snapToEdge: (axis = 'both') => ipcRenderer.invoke('ball:snapToEdge', axis),
    getBounds: () => ipcRenderer.invoke('ball:getBounds'),
  },
  napcat: {
    status: () => ipcRenderer.invoke('napcat:status'),
    start: (opts) => ipcRenderer.invoke('napcat:start', opts || {}),
    stop: () => ipcRenderer.invoke('napcat:stop'),
    bootstrap: (opts) => ipcRenderer.invoke('napcat:bootstrap', opts || {}),
  },
  system: {
    openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
    quit: () => ipcRenderer.invoke('app:quit'),
  },
});

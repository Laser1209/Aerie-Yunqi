"use strict";
/* 小伊独立窗口的 preload。
 *
 * 只暴露两件事，够用就好：
 *   1. api.request —— 与主窗口同一条 IPC 转发链路。她自己的窗口是 file://，
 *      直接 fetch 会被 CSP 的 default-src 'self' 拦掉，必须借主进程的手。
 *   2. xiaoyi.close —— 顶部 × 是「收起」而不是「销毁」：窗口留着，她记着的
 *      聊天记录和轮询状态都不丢，再点一下就能立刻回来。
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aerie", {
  api: {
    request: (opts) => ipcRenderer.invoke("api:request", opts),
  },
  xiaoyi: {
    close: () => ipcRenderer.invoke("xiaoyi:close"),
  },
});

"use strict";
/*
 * 世界仪表盘独立窗口的生命周期契约。
 *
 * 为什么用「读源码断言」而不是真跑 Electron：
 * 这个 bug 是**主进程窗口引用与异步 close() 之间的竞态**，只有真起 Electron 才跑得出来，
 * 而 e2e 成本高、CI 也不一定有显示环境。这里钉住的是修复的**关键不变量（顺序）**：
 * 顺序写反 bug 就会回来，而这恰恰是最容易被顺手的重构破坏的地方。
 *
 * 2026-09-30 真机故障：点「显示插件」后窗口出现又立刻消失，面板状态回到 hidden。
 * 根因：hide 里 close() 是异步的，期间窗口既没销毁、引用也没断 ——
 * 此时再点「显示插件」会 show() 一个**正在关闭**的窗口，随即又关。
 */

const assert = require("node:assert");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const MAIN = path.join(__dirname, "..", "src", "main.js");
const source = fs.readFileSync(MAIN, "utf8");

/** 取 ipcMain.handle("<name>") 到下一个 handler 之间的正文。 */
function handlerBody(name) {
  const start = source.indexOf(`ipcMain.handle("${name}"`);
  assert.notStrictEqual(start, -1, `找不到 ${name} 的 handler`);
  const next = source.indexOf("ipcMain.handle(", start + 10);
  return source.slice(start, next === -1 ? undefined : next);
}

/** 取 function <name>( ) { ... } 的正文（按花括号配平，够用即可）。 */
function functionBody(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notStrictEqual(start, -1, `找不到函数 ${name}`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`函数 ${name} 花括号不配平`);
}

test("hide 先断开窗口引用再 close（否则会复用一个正在关闭的窗口）", () => {
  const body = handlerBody("world-dashboard:hide");
  const clearAt = body.indexOf("worldDashboardWindow = null");
  const closeAt = body.indexOf(".close()");
  assert.notStrictEqual(clearAt, -1, "hide 必须把引用置 null");
  assert.notStrictEqual(closeAt, -1, "hide 必须关窗");
  assert.ok(
    clearAt < closeAt,
    "必须先置 null 再 close —— close 是异步的，反了就会 show() 一个正在关闭的窗口",
  );
});

test("closed 只在引用仍指向自己时才清空（防止旧窗口抹掉新窗口）", () => {
  assert.match(
    source,
    /if \(worldDashboardWindow === win\) worldDashboardWindow = null;/,
    "closed 里无条件置 null 会让迟到的旧窗口把新窗口的引用抹掉",
  );
});

test("窗口先隐藏、ready-to-show 后再显示（避免先闪白底）", () => {
  const body = functionBody("openWorldDashboardWindow");
  assert.match(body, /show: false,/, "创建时应先隐藏");
  assert.match(body, /once\("ready-to-show"/, "应在 ready-to-show 后再 show");
});

test("open 复用的前提是窗口存在且未销毁", () => {
  const body = functionBody("openWorldDashboardWindow");
  assert.match(
    body,
    /worldDashboardWindow && !worldDashboardWindow\.isDestroyed\(\)/,
    "复用一个已销毁的窗口会抛错",
  );
});

"use strict";
/*
 * 小伊 · 系统管家**独立窗口**的结构契约测试。
 *
 * 为什么用源码断言而不是跑真机：她"好不好看/好不好用"靠人看，但**结构不塌**
 * 可以钉住 —— 窗口页面、id、端点、停靠布局、IPC 通道一旦被后人改动而没同步，
 * 真机才会炸。与 world-dashboard-window 的验收方式保持一致。
 *
 * 重点防的是上一版翻车的那件事：她曾经是主窗口里的一块面板，被 flex 排到了
 * 聊天输入框底下，还占走聊天区。现在她是独立窗口，所以 index.html 里不该再
 * 出现她的任何 DOM。
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..", "src");
const RENDERER = path.join(SRC, "renderer");
const INDEX = fs.readFileSync(path.join(RENDERER, "index.html"), "utf8");
const PAGE = fs.readFileSync(path.join(RENDERER, "xiaoyi.html"), "utf8");
const CSS = fs.readFileSync(path.join(RENDERER, "styles", "xiaoyi-window.css"), "utf8");
const JS = fs.readFileSync(path.join(RENDERER, "js", "xiaoyi.js"), "utf8");
const MAIN = fs.readFileSync(path.join(SRC, "main.js"), "utf8");
const PRELOAD = fs.readFileSync(path.join(SRC, "preload.js"), "utf8");
const XIAOYI_PRELOAD = fs.readFileSync(path.join(SRC, "xiaoyi-preload.js"), "utf8");

function extractFunction(name) {
  const start = MAIN.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is missing`);
  // 从参数表结束处找函数体的 `{`：默认参数（opts = {}）里也有大括号，
  // 直接找第一个 `{` 会截到参数上。
  const bodyStart = MAIN.indexOf(") {", start) + 2;
  assert.notEqual(bodyStart, 1, `${name} has no body`);
  let depth = 0;
  for (let i = bodyStart; i < MAIN.length; i += 1) {
    if (MAIN[i] === "{") depth += 1;
    if (MAIN[i] === "}") depth -= 1;
    if (depth === 0) return MAIN.slice(start, i + 1);
  }
  throw new Error(`${name} is incomplete`);
}

test("她有自己的窗口页面，DOM 齐全", () => {
  for (const id of [
    "xiaoyi-avatar",
    "xiaoyi-board",
    "xiaoyi-chat",
    "xiaoyi-input",
    "xiaoyi-send",
    "xiaoyi-refresh",
    "xiaoyi-close",
  ]) {
    assert.match(PAGE, new RegExp(`id="${id}"`), `缺少 #${id}`);
  }
  assert.match(PAGE, /styles\/xiaoyi-window\.css/);
  assert.match(PAGE, /js\/xiaoyi\.js/);
  assert.match(PAGE, /frame: false|Content-Security-Policy/);
});

test("主窗口里不再有她的 DOM —— 她不该再占聊天区", () => {
  for (const leftover of ["xiaoyi-sidebar", "xiaoyi-toggle", "xiaoyi-collapse", "xiaoyi-board", "xiaoyi-chat"]) {
    assert.equal(INDEX.includes(leftover), false, `index.html 里还留着 ${leftover}`);
  }
  assert.equal(INDEX.includes("styles/xiaoyi-sidebar.css"), false);
  assert.equal(INDEX.includes("js/xiaoyi.js"), false);
  // 旧的页内侧栏样式表必须删掉，别留成孤儿
  assert.equal(fs.existsSync(path.join(RENDERER, "styles", "xiaoyi-sidebar.css")), false);
});

test("主窗口留了叫她的按钮，且状态由主进程回推", () => {
  assert.match(INDEX, /id="xiaoyi-open-btn"/);
  const app = fs.readFileSync(path.join(RENDERER, "js", "app.js"), "utf8");
  assert.match(app, /xiaoyi-open-btn/);
  assert.match(app, /xiaoyiBridge\.onStateChange/);
  assert.match(app, /xiaoyiBridge\.toggle\(\)/);
});

test("窗口样式自带 token，:root 之外没有字面色值", () => {
  const outsideRoot = CSS.replace(/:root\s*\{[\s\S]*?\}/g, "");
  assert.equal(/#[0-9a-fA-F]{3,8}\b/.test(outsideRoot), false, "CSS 里不允许出现 :root 之外的 hex 色值");
  for (const rule of [
    ".xiaoyi-board__row",
    ".xiaoyi-msg--user",
    ".xiaoyi-msg--xiaoyi",
    ".xiaoyi-composer__input",
    ".xiaoyi-composer__send",
  ]) {
    assert.ok(CSS.includes(rule), `缺少样式规则 ${rule}`);
  }
});

test("JS 用的是小伊自己的两个端点", () => {
  assert.match(JS, /\/api\/xiaoyi\/snapshot/);
  assert.match(JS, /\/api\/xiaoyi\/chat/);
  // 不能借用主人格的聊天端点（否则系统问题会漏进伊塔的对话）
  assert.equal(JS.includes("/api/chat/send"), false);
});

test("看板给每项配了小白话，而不是直接显示原始字段", () => {
  for (const phrase of [
    "运行正常，已经连续工作",
    "今天思考了",
    "个功能还没配好",
    "在等你确认",
  ]) {
    assert.ok(JS.includes(phrase), `缺少小白话文案：${phrase}`);
  }
});

test("收起 = 让主进程隐藏窗口，不是 window.close 销毁", () => {
  assert.match(JS, /aerie\.xiaoyi/);
  assert.match(JS, /api\.close\(\)/);
});

test("立绘缺失时用应用图标占位，不引用不存在的素材", () => {
  assert.match(JS, /logo-96\.png/);
  assert.ok(fs.existsSync(path.join(RENDERER, "logo-96.png")), "占位图必须真实存在");
});

test("主进程建窗、停靠、跟随、清理一条龙", () => {
  assert.match(MAIN, /function _createXiaoyiWindow\(\)/);
  assert.match(MAIN, /loadFile\(path\.join\(__dirname, "renderer", "xiaoyi\.html"\)\)/);
  assert.match(MAIN, /preload: path\.join\(__dirname, "xiaoyi-preload\.js"\)/);
  assert.match(MAIN, /ipcMain\.handle\("xiaoyi:open"/);
  assert.match(MAIN, /ipcMain\.handle\("xiaoyi:close"/);
  assert.match(MAIN, /ipcMain\.handle\("xiaoyi:toggle"/);
  assert.match(MAIN, /ipcMain\.handle\("xiaoyi:is-open"/);
  // 主窗口一动她就跟着贴回去
  assert.match(MAIN, /mainWindow\.on\("move", _syncXiaoyiPosition\)/);
  assert.match(MAIN, /mainWindow\.on\("resize", _syncXiaoyiPosition\)/);
  // 主窗口收起来（托盘 / 最小化）她也收，别孤零零留在桌面上
  assert.match(MAIN, /mainWindow\.on\("hide", _hideXiaoyiWindowWithMain\)/);
  assert.match(MAIN, /mainWindow\.on\("minimize", _hideXiaoyiWindowWithMain\)/);
  assert.match(MAIN, /mainWindow\.on\("show", _showXiaoyiWindowWithMain\)/);
  assert.match(MAIN, /mainWindow\.on\("restore", _showXiaoyiWindowWithMain\)/);
  // 停靠窗不该被拖动/缩放：宽度固定、高度跟着主窗口
  assert.match(MAIN, /resizable: false,[\s\S]*?maximizable: false,[\s\S]*?minimizable: false,/);
  // 退出时销毁
  assert.match(MAIN, /xiaoyiWindow\.destroy\(\)/);
});

test("两侧 preload 各只暴露够用的面", () => {
  assert.match(PRELOAD, /xiaoyi: \{[\s\S]*?toggle: \(\) => ipcRenderer\.invoke\("xiaoyi:toggle"\)/);
  assert.match(PRELOAD, /onStateChange:/);
  assert.match(XIAOYI_PRELOAD, /xiaoyi: \{[\s\S]*?close: \(\) => ipcRenderer\.invoke\("xiaoyi:close"\)/);
  // 她自己的窗口靠主进程转发请求：file:// 直接 fetch 会被 CSP 拦掉
  assert.match(XIAOYI_PRELOAD, /request: \(opts\) => ipcRenderer\.invoke\("api:request", opts\)/);
  assert.doesNotMatch(XIAOYI_PRELOAD, /nodeIntegration|require\("fs"\)/);
});

/* ── 停靠布局（纯函数） ───────────────────────────── */

function dock(mainBounds, workArea, opts) {
  const context = { XIAOYI_WINDOW_WIDTH: 340, XIAOYI_WINDOW_GAP: 12, MAIN_WINDOW_MIN_WIDTH: 900 };
  vm.runInNewContext(`${extractFunction("computeXiaoyiDock")}\nthis.run = computeXiaoyiDock;`, context);
  return context.run(mainBounds, workArea, opts);
}

const SCREEN = { x: 0, y: 0, width: 1920, height: 1040 };

test("左边有地方：主窗口原地不动，小伊插在它左边", () => {
  const out = dock({ x: 600, y: 100, width: 1280, height: 800 }, SCREEN);
  assert.equal(out.main.x, 600, "主窗口不该被动");
  assert.equal(out.main.width, 1280, "主窗口宽度不该被改");
  assert.equal(out.xiaoyi.x, 600 - 352);
  assert.equal(out.xiaoyi.x + out.xiaoyi.width, 600 - 12);
  assert.equal(out.shifted, 0);
});

test("左边不够：主窗口整体右移补足，小伊贴住工作区左边缘", () => {
  const out = dock({ x: 100, y: 0, width: 1280, height: 800 }, SCREEN);
  assert.equal(out.xiaoyi.x, 0);
  assert.equal(out.main.x, 352, "主窗口右移了 252");
  assert.equal(out.main.width, 1280, "右移够用就不动宽度");
  assert.equal(out.shifted, 252);
});

test("右移后顶出屏幕右边：压主窗口宽度，但不低于 minWidth", () => {
  const out = dock({ x: 800, y: 0, width: 1280, height: 800 }, SCREEN);
  assert.equal(out.xiaoyi.x, 800 - 352);
  assert.equal(out.main.x, 800);
  assert.equal(out.main.width, 1120, "1920 - 800 = 1120");
  assert.equal(out.main.x + out.main.width, 1920);

  const tight = dock({ x: 1100, y: 0, width: 1280, height: 800 }, SCREEN);
  assert.equal(tight.main.width, 900, "宁可他探出屏幕，也不把主窗口压到 minWidth 以下");
});

test("小伊的高度和 y 跟着主窗口走", () => {
  const out = dock({ x: 600, y: 240, width: 1280, height: 760 }, SCREEN);
  assert.equal(out.xiaoyi.y, 240);
  assert.equal(out.xiaoyi.height, 760);
  assert.equal(out.xiaoyi.width, 340);
});

test("多屏／带偏移的工作区也守得住", () => {
  const workArea = { x: 1920, y: 0, width: 1600, height: 900 };
  const out = dock({ x: 2000, y: 50, width: 1280, height: 700 }, workArea);
  assert.ok(out.xiaoyi.x >= workArea.x, "小伊不能跑到副屏左边之外");
  assert.ok(out.main.x + out.main.width <= workArea.x + workArea.width, "主窗口要留在工作区内");
});

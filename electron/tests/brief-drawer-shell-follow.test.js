"use strict";

/* 回归：日报抽屉展开时，Electron 外壳的宽度要跟着"当场撑开 / 收起时收回"，
 * 而不是让主窗口常驻加宽去容纳它。收回是两段的：先把抽屉（CSS width 0.5s）
 * 收进去，收到一半（250ms）再把外壳跟着收。
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const read = (...parts) => fs.readFileSync(path.join(__dirname, "..", "src", ...parts), "utf8");

const main = read("main.js");
const preload = read("preload.js");
const drawer = read("renderer", "js", "brief-drawer.js");
const drawerCss = read("renderer", "styles", "brief-drawer.css");

test("preload exposes the drawer shell bridge on window.setDrawerExpanded", () => {
  assert.match(
    preload,
    /setDrawerExpanded:\s*\(expanded\)\s*=>\s*ipcRenderer\.invoke\("window:drawer-shell",\s*\{\s*expanded:\s*!!expanded\s*\}\)/,
  );
});

test("main process owns the drawer shell handler with guards and edge anchoring", () => {
  assert.match(main, /ipcMain\.handle\("window:drawer-shell"/);
  // 最大化/全屏时窗口尺寸由系统托管，抽屉不该动它
  assert.match(main, /window:drawer-shell"[\s\S]*?isMaximized\(\)\s*\|\|\s*win\.isFullScreen\(\)/);
  // 右边缘锚定：向左撑开，抽屉贴右看起来才是"原地展开"
  assert.match(main, /const right = base\.x \+ base\.width;/);
  assert.match(main, /const right = bounds\.x \+ bounds\.width;/);
  // 展开前记 baseBounds，收起时原样还原，反复开合不会越撑越宽
  assert.match(main, /if \(!_drawerBaseBounds\) _drawerBaseBounds = bounds;/);
  assert.match(main, /_drawerBaseBounds = null;/);
  assert.match(main, /_drawerBaseBounds = null;[\s\S]*?Math\.max\(MAIN_WINDOW_MIN_WIDTH, base\.width\)/);
});

test("the shell animates its width instead of snapping", () => {
  assert.match(main, /function _animateMainWindowWidth\(win, targetWidth, targetX, durationMs\)/);
  assert.match(main, /_animateWindowBounds\(win, \{ x: targetX, width: targetWidth \}, durationMs\)/);
  // 共用的步进动画：16ms 一帧 + easeOutCubic，每个窗口一个定时器
  assert.match(main, /function _animateWindowBounds\(win, target, durationMs\)/);
  assert.match(main, /const eased = 1 - Math\.pow\(1 - t, 3\);/);
  assert.match(main, /win\.setBounds\(patch\)/);
  assert.match(main, /const timer = setInterval\([\s\S]*?\}, 16\);/);
  assert.match(main, /_boundsAnimTimers\.set\(win, timer\)/);
});

test("the main window keeps an honest default size instead of a permanently widened one", () => {
  const windowStart = main.indexOf("mainWindow = new BrowserWindow");
  const windowEnd = main.indexOf("mainWindow.webContents.session", windowStart);
  const options = main.slice(windowStart, windowEnd);

  assert.match(options, /width:\s*Math\.min\(1280, width\)/);
  assert.match(options, /minWidth:\s*MAIN_WINDOW_MIN_WIDTH/);
  assert.match(main, /const MAIN_WINDOW_MIN_WIDTH = 900;/);
  assert.match(main, /const DRAWER_GROW_PX = 520;/);
  assert.doesNotMatch(options, /Math\.min\(1440, width\)/);
});

test("collapsing is two-stage: drawer first, shell at the half-way mark", () => {
  // 抽屉自身的宽度过渡是 0.5s，半程就是 250ms
  assert.match(drawerCss, /\.brief-drawer \{[\s\S]*?transition:[\s\S]*?width 0\.5s/);
  assert.match(drawer, /_scheduleShellCollapse\(\)\s*\{[\s\S]*?\}, 250\);/);
  // 收起走半程延时，展开当场通知
  assert.match(
    drawer,
    /if \(changed\) \{\s*if \(next\) this\._notifyShell\(true\);\s*else this\._scheduleShellCollapse\(\);\s*\}/,
  );
});

test("closing the drawer resets the expanded state so nothing leaks into the next open", () => {
  const close = drawer.slice(drawer.indexOf("  close() {"), drawer.indexOf("  /* 通知主进程"));
  assert.match(close, /if \(this\._expanded\) this\._setExpanded\(false, false\);/);
  assert.match(close, /this\._drawer\.classList\.remove\("is-open"\);/);
});

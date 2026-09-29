"use strict";
/*
 * 小伊侧栏（E2）源码契约测试。
 *
 * 为什么用源码断言而不是跑真机：侧栏的"能不能用"靠人看，但**结构不塌**可以钉住 ——
 * DOM id / 资源引用 / 端点 / 折叠持久化这些一旦被后人改动而没同步，真机才会炸。
 * 与 world-dashboard-window 的验收方式保持一致。
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const SRC = path.join(__dirname, "..", "src");
const HTML = fs.readFileSync(path.join(SRC, "renderer", "index.html"), "utf8");
const CSS = fs.readFileSync(
  path.join(SRC, "renderer", "styles", "xiaoyi-sidebar.css"),
  "utf8",
);
const JS = fs.readFileSync(path.join(SRC, "renderer", "js", "xiaoyi.js"), "utf8");
const MAIN = fs.readFileSync(path.join(SRC, "main.js"), "utf8");

test("index.html 挂上了小伊侧栏的完整 DOM", () => {
  for (const id of [
    "xiaoyi-sidebar",
    "xiaoyi-toggle",
    "xiaoyi-collapse",
    "xiaoyi-avatar",
    "xiaoyi-board",
    "xiaoyi-chat",
    "xiaoyi-input",
    "xiaoyi-send",
  ]) {
    assert.match(HTML, new RegExp(`id="${id}"`), `缺少 #${id}`);
  }
});

test("样式与脚本都进了 index.html", () => {
  assert.match(HTML, /styles\/xiaoyi-sidebar\.css/);
  assert.match(HTML, /js\/xiaoyi\.js/);
});

test("侧栏与图标导航栏是 .main-layout 的兄弟节点（同一个 flex 行）", () => {
  const layoutIdx = HTML.indexOf('class="main-layout"');
  const sidebarIdx = HTML.indexOf('id="xiaoyi-sidebar"');
  const workspaceIdx = HTML.indexOf('id="workspace-sidebar"');

  assert.ok(layoutIdx > -1 && sidebarIdx > layoutIdx, "侧栏必须在 .main-layout 之内");
  assert.ok(sidebarIdx < workspaceIdx, "侧栏放在工作区侧栏之前，避免盖住它");
});

test("CSS 不含字面色值，且覆盖折叠/看板/气泡/输入区", () => {
  assert.equal(/#[0-9a-fA-F]{3,8}\b/.test(CSS), false, "CSS 里不允许出现 hex 色值");
  assert.match(CSS, /\.xiaoyi-sidebar\[hidden\]/, "折叠要靠 hidden 属性");
  assert.match(CSS, /\.xiaoyi-board__row/);
  assert.match(CSS, /\.xiaoyi-msg--user/);
  assert.match(CSS, /\.xiaoyi-msg--xiaoyi/);
  assert.match(CSS, /\.xiaoyi-composer__input/);
});

test("JS 用的是小伊自己的两个端点", () => {
  assert.match(JS, /\/api\/xiaoyi\/snapshot/);
  assert.match(JS, /\/api\/xiaoyi\/chat/);
  // 不能借用主人格的聊天端点（否则系统问题会漏进伊塔的对话）
  assert.equal(JS.includes("/api/chat/send"), false);
});

test("折叠状态持久化在 localStorage", () => {
  assert.match(JS, /aerie\.xiaoyi\.open/);
  assert.match(JS, /localStorage\.setItem/);
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

test("主窗口为侧栏留出了宽度", () => {
  assert.match(MAIN, /minWidth:\s*1120/);
  assert.match(MAIN, /Math\.min\(1440,\s*width\)/);
});

test("立绘缺失时用应用图标占位，不引用不存在的素材", () => {
  assert.match(JS, /logo-96\.png/);
  const rendererDir = path.join(SRC, "renderer");
  assert.ok(fs.existsSync(path.join(rendererDir, "logo-96.png")), "占位图必须真实存在");
});

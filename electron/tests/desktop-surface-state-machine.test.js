"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");

const { IslandState, IslandStateMachine } = require(
  path.join(__dirname, "..", "src", "desktop_surface"),
);

test("IslandState 枚举定义了四种状态", () => {
  assert.equal(IslandState.COLLAPSED, "collapsed");
  assert.equal(IslandState.PEEK, "peek");
  assert.equal(IslandState.EXPANDED, "expanded");
  assert.equal(IslandState.TOOL_PANEL, "tool-panel");
});

test("初始状态为 collapsed", () => {
  const sm = new IslandStateMachine();
  assert.equal(sm.getState(), IslandState.COLLAPSED);
});

test("可通过构造函数指定初始状态", () => {
  const sm = new IslandStateMachine(IslandState.EXPANDED);
  assert.equal(sm.getState(), IslandState.EXPANDED);
});

test("合法转换: collapsed → peek（鼠标悬停）", () => {
  const sm = new IslandStateMachine();
  assert.equal(sm.transition(IslandState.PEEK), true);
  assert.equal(sm.getState(), IslandState.PEEK);
});

test("合法转换: peek → expanded（点击）", () => {
  const sm = new IslandStateMachine(IslandState.PEEK);
  assert.equal(sm.transition(IslandState.EXPANDED), true);
  assert.equal(sm.getState(), IslandState.EXPANDED);
});

test("合法转换: expanded → tool-panel（选择工具）", () => {
  const sm = new IslandStateMachine(IslandState.EXPANDED);
  assert.equal(sm.transition(IslandState.TOOL_PANEL), true);
  assert.equal(sm.getState(), IslandState.TOOL_PANEL);
});

test("合法转换: expanded → collapsed（失焦）", () => {
  const sm = new IslandStateMachine(IslandState.EXPANDED);
  assert.equal(sm.transition(IslandState.COLLAPSED), true);
  assert.equal(sm.getState(), IslandState.COLLAPSED);
});

test("合法转换: tool-panel → expanded（关闭面板）", () => {
  const sm = new IslandStateMachine(IslandState.TOOL_PANEL);
  assert.equal(sm.transition(IslandState.EXPANDED), true);
  assert.equal(sm.getState(), IslandState.EXPANDED);
});

test("合法转换: peek → collapsed（鼠标离开）", () => {
  const sm = new IslandStateMachine(IslandState.PEEK);
  assert.equal(sm.transition(IslandState.COLLAPSED), true);
  assert.equal(sm.getState(), IslandState.COLLAPSED);
});

test("非法转换: collapsed → tool-panel（跳过中间态）返回 false 且状态不变", () => {
  const sm = new IslandStateMachine();
  assert.equal(sm.transition(IslandState.TOOL_PANEL), false);
  assert.equal(sm.getState(), IslandState.COLLAPSED);
});

test("非法转换: tool-panel → collapsed（必须经过 expanded）返回 false", () => {
  const sm = new IslandStateMachine(IslandState.TOOL_PANEL);
  assert.equal(sm.transition(IslandState.COLLAPSED), false);
  assert.equal(sm.getState(), IslandState.TOOL_PANEL);
});

test("非法转换: expanded → peek（不能回退）返回 false", () => {
  const sm = new IslandStateMachine(IslandState.EXPANDED);
  assert.equal(sm.transition(IslandState.PEEK), false);
  assert.equal(sm.getState(), IslandState.EXPANDED);
});

test("canTransition 仅查询不改变状态", () => {
  const sm = new IslandStateMachine();
  assert.equal(sm.canTransition(IslandState.PEEK), true);
  assert.equal(sm.canTransition(IslandState.TOOL_PANEL), false);
  assert.equal(sm.getState(), IslandState.COLLAPSED);
});

test("转换到当前状态（自转换）返回 false", () => {
  const sm = new IslandStateMachine();
  assert.equal(sm.transition(IslandState.COLLAPSED), false);
  assert.equal(sm.getState(), IslandState.COLLAPSED);
});

test("未知状态转换返回 false", () => {
  const sm = new IslandStateMachine();
  assert.equal(sm.transition("unknown-state"), false);
  assert.equal(sm.getState(), IslandState.COLLAPSED);
});

test("onStateChange 回调接收 (fromState, toState, timestamp) 并记录 trace", () => {
  const trace = [];
  const sm = new IslandStateMachine(IslandState.COLLAPSED, (from, to, ts) => {
    trace.push({ from, to, ts });
  });

  sm.transition(IslandState.PEEK);
  sm.transition(IslandState.EXPANDED);
  sm.transition(IslandState.COLLAPSED);

  assert.equal(trace.length, 3);
  assert.deepEqual(trace[0], {
    from: IslandState.COLLAPSED,
    to: IslandState.PEEK,
    ts: trace[0].ts,
  });
  assert.deepEqual(trace[1], {
    from: IslandState.PEEK,
    to: IslandState.EXPANDED,
    ts: trace[1].ts,
  });
  assert.deepEqual(trace[2], {
    from: IslandState.EXPANDED,
    to: IslandState.COLLAPSED,
    ts: trace[2].ts,
  });
  // timestamp 应为递增的数字
  assert.equal(typeof trace[0].ts, "number");
  assert.ok(trace[1].ts >= trace[0].ts);
  assert.ok(trace[2].ts >= trace[1].ts);
});

test("非法转换不触发 onStateChange 回调", () => {
  const trace = [];
  const sm = new IslandStateMachine(IslandState.COLLAPSED, (from, to, ts) => {
    trace.push({ from, to, ts });
  });

  sm.transition(IslandState.TOOL_PANEL); // 非法
  sm.transition(IslandState.PEEK); // 合法

  assert.equal(trace.length, 1);
  assert.equal(trace[0].to, IslandState.PEEK);
});

test("完整合法路径: collapsed → peek → expanded → tool-panel → expanded → collapsed", () => {
  const trace = [];
  const sm = new IslandStateMachine(IslandState.COLLAPSED, (from, to) => {
    trace.push(`${from}->${to}`);
  });

  assert.equal(sm.transition(IslandState.PEEK), true);
  assert.equal(sm.transition(IslandState.EXPANDED), true);
  assert.equal(sm.transition(IslandState.TOOL_PANEL), true);
  assert.equal(sm.transition(IslandState.EXPANDED), true);
  assert.equal(sm.transition(IslandState.COLLAPSED), true);

  assert.deepEqual(trace, [
    "collapsed->peek",
    "peek->expanded",
    "expanded->tool-panel",
    "tool-panel->expanded",
    "expanded->collapsed",
  ]);
});

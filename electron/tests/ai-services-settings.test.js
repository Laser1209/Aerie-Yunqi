"use strict";

// 设置页「AI 服务配置」前后端契约：保存即测、自定义厂商单条增改删、功能点路由。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rendererRoot = path.join(__dirname, "..", "src", "renderer");
const html = fs.readFileSync(path.join(rendererRoot, "index.html"), "utf8");
const settings = fs.readFileSync(path.join(rendererRoot, "js", "settings.js"), "utf8");

test("custom providers use single-record PUT and DELETE (no env-bulk POST)", () => {
  assert.match(settings, /method: "PUT", path: "\/api\/env\/custom-providers"/);
  assert.match(settings, /method: "DELETE", path: "\/api\/env\/custom-providers\/" \+ id/);
  // 旧的全量数组覆盖式保存已删除
  assert.doesNotMatch(settings, /_saveCustomProviders/);
  assert.doesNotMatch(settings, /extra_kv/);
});

test("custom provider save is test-before-commit with force fallback", () => {
  assert.match(settings, /async saveCustomProvider\(force\)/);
  assert.match(settings, /先小流量验证，通过才写入/);
  assert.match(settings, /r\.status === 422[\s\S]*saveCustomProvider\(true\)/);
  // 自定义厂商可编辑、可勾选 tools
  assert.match(settings, /_editCustomProvider/);
  assert.match(settings, /custom-provider-supports-tools/);
});

test("model roles panel binds provider dropdown + model + live check dots", () => {
  assert.match(settings, /path: "\/api\/env\/bindable-providers"/);
  assert.match(settings, /data-role-provider/);
  assert.match(settings, /data-role-model/);
  assert.match(settings, /小流量测试/);
  assert.match(settings, /async saveModelRoles\(force\)/);
  assert.match(settings, /saveModelRoles\(true\)/);
});

test("standalone provider-check endpoint is wired for test-only probes", () => {
  assert.match(settings, /测试并保存/);
});

test("built-in provider save surfaces check result to status line", () => {
  assert.match(settings, /连通正常/);
  assert.match(settings, /连通性测试失败/);
});

test("index.html exposes role routing panel with test-and-save CTA", () => {
  assert.match(html, /id="custom-api-toggle-btn"[^>]*>功能点路由/);
  assert.match(html, /id="custom-api-save-btn"[^>]*>测试并保存/);
  assert.match(html, /id="custom-provider-save-btn"[^>]*>测试并保存/);
});

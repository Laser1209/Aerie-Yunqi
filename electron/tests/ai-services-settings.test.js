"use strict";

// 设置页「AI 服务配置」前后端契约：一张厂商数据表 + 抽屉式增删改查 + 功能点路由。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rendererRoot = path.join(__dirname, "..", "src", "renderer");
const html = fs.readFileSync(path.join(rendererRoot, "index.html"), "utf8");
const settings = fs.readFileSync(path.join(rendererRoot, "js", "settings.js"), "utf8");

test("providers load from /api/ai/providers table endpoint", () => {
  assert.match(settings, /method: "GET", path: "\/api\/ai\/providers"/);
  assert.match(settings, /available_builtins/);
  assert.match(settings, /special_services/);
});

test("provider create/update uses PUT /api/ai/providers, delete really hits the backend", () => {
  assert.match(settings, /this\._apiCall\("PUT", "\/api\/ai\/providers", body\)/);
  assert.match(settings, /this\._apiCall\("DELETE", "\/api\/ai\/providers\/"/);
  // 旧的假状态 + 旧端点全部移除，删除必须真的调后端
  assert.doesNotMatch(settings, /_addedProviderKeys/);
  assert.doesNotMatch(settings, /_apikeyProviders/);
  assert.doesNotMatch(settings, /_customProviders/);
  assert.doesNotMatch(settings, /\/api\/env\/save/);
  assert.doesNotMatch(settings, /\/api\/env\/providers/);
  assert.doesNotMatch(settings, /\/api\/env\/custom-providers/);
  assert.doesNotMatch(settings, /_saveCustomProviders/);
});

test("provider save is test-before-commit with force fallback and check endpoint", () => {
  assert.match(settings, /async _saveProvider\(force\)/);
  assert.match(settings, /先小流量验证，通过才写入/);
  assert.match(settings, /this\._isForceable\(e\) && !force/);
  assert.match(settings, /this\._saveProvider\(true\)/);
  assert.match(settings, /"\/check"/);
  assert.match(settings, /"\/enabled"/);
});

test("provider table supports sorting, role tags and delete confirmation", () => {
  assert.match(settings, /_renderProviderTable\(\)/);
  assert.match(settings, /data-sort="name"/);
  assert.match(settings, /data-sort="kind"/);
  assert.match(settings, /data-sort="status"/);
  assert.match(settings, /_providerRoleTags/);
  assert.match(settings, /内置厂商，删除会同时清掉 \.env 里的凭据/);
  assert.match(settings, /_isForceable/);
});

test("model roles card binds provider dropdown + model + live check dots", () => {
  assert.match(settings, /path: "\/api\/env\/bindable-providers"/);
  assert.match(settings, /data-role-provider/);
  assert.match(settings, /data-role-model/);
  assert.match(settings, /（多 Key 池）/);
  assert.match(settings, /小流量测试/);
  assert.match(settings, /async saveModelRoles\(force\)/);
  assert.match(settings, /saveModelRoles\(true\)/);
});

test("built-in provider save surfaces check result to status line", () => {
  assert.match(settings, /连通正常/);
  assert.match(settings, /连通性测试失败/);
});

test("standalone provider-check endpoint is wired for test-only probes", () => {
  assert.match(settings, /测试并保存/);
  assert.match(settings, /_testDrawerProvider/);
  assert.match(settings, /_testAllProviders/);
});

test("index.html exposes the provider table + drawer, old cards removed", () => {
  assert.match(html, /id="apikey-add-btn"[^>]*>＋ 添加厂商/);
  assert.match(html, /id="apikey-testall-btn"/);
  assert.match(html, /id="apikey-provider-list"[^>]*class="apikey-table-wrap"/);
  assert.match(html, /id="model-roles-table"/);
  assert.match(html, /id="model-roles-save-btn"[^>]*>测试并保存/);
  assert.match(html, /id="special-services-table"/);
  assert.match(html, /id="apikey-drawer"/);
  assert.match(html, /id="apikey-drawer-api-key"/);
  // 旧的卡片堆 / 二级菜单 / 独立表单区块全部删除
  assert.doesNotMatch(html, /id="apikey-add-menu"/);
  assert.doesNotMatch(html, /id="apikey-menu-tabs"/);
  assert.doesNotMatch(html, /id="apikey-menu-panel"/);
  assert.doesNotMatch(html, /id="apikey-add-badge"/);
  assert.doesNotMatch(html, /id="apikey-count-reminder"/);
  assert.doesNotMatch(html, /id="custom-provider-panel"/);
  assert.doesNotMatch(html, /id="custom-provider-form"/);
  assert.doesNotMatch(html, /id="custom-api-panel"/);
  assert.doesNotMatch(html, /id="custom-api-role-list"/);
  assert.doesNotMatch(html, /id="custom-api-toggle-btn"/);
});

"use strict";
/*
 * 远程 catalog（B6）契约：拉到就增量合并，拉不到**绝不让模块中心变空**。
 *
 * 依赖 node 内置 test runner：node --test tests/plugin-catalog-remote.test.js
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

const pluginManager = require("../src/plugin-manager");

function tmpUserData() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "aerie-catalog-"));
}

function writeCache(userData, packs) {
  fs.writeFileSync(
    path.join(userData, pluginManager.CATALOG_CACHE_FILE),
    JSON.stringify({ packs }),
    "utf8",
  );
}

test("没有配置位置时只读内置 catalog", () => {
  pluginManager.configure(null);
  const packs = pluginManager.loadCatalog();

  assert.equal(packs.length, 4);
  assert.deepEqual(
    packs.map((p) => p.id).sort(),
    ["browser", "knowledge", "voice-asr", "voice-rvc"],
  );
});

test("远程缓存与内置按 id 合并，不丢内置条目", () => {
  const userData = tmpUserData();
  pluginManager.configure({ userData, isPackaged: true, projectRoot: "/tmp" });
  writeCache(userData, [{ id: "pdf-tools", version: "2.0.0", name: { zh: "PDF 工具" } }]);

  const packs = pluginManager.loadCatalog();
  const ids = packs.map((p) => p.id);

  assert.equal(packs.length, 5, "内置 4 个 + 远程新增 1 个");
  assert.ok(ids.includes("pdf-tools"));
  assert.ok(ids.includes("knowledge"), "内置条目必须保留");
});

test("远程覆盖同名条目时用远程版本", () => {
  const userData = tmpUserData();
  pluginManager.configure({ userData, isPackaged: true, projectRoot: "/tmp" });
  writeCache(userData, [{ id: "knowledge", version: "9.9.9", summary: { zh: "新" } }]);

  const packs = pluginManager.loadCatalog();
  const knowledge = packs.find((p) => p.id === "knowledge");

  assert.equal(knowledge.version, "9.9.9");
});

test("缓存损坏时退回内置 catalog，不抛错", () => {
  const userData = tmpUserData();
  pluginManager.configure({ userData, isPackaged: true, projectRoot: "/tmp" });
  fs.writeFileSync(
    path.join(userData, pluginManager.CATALOG_CACHE_FILE),
    "{ this is not json",
    "utf8",
  );

  const packs = pluginManager.loadCatalog();
  assert.equal(packs.length, 4);
});

test("指向错误的 URL：refresh 失败但内置清单完好", async () => {
  const userData = tmpUserData();
  pluginManager.configure({ userData, isPackaged: true, projectRoot: "/tmp" });

  const result = await pluginManager.refreshCatalog("http://127.0.0.1:1/definitely-not-here", {
    timeoutMs: 1500,
  });

  assert.equal(result.ok, false);
  assert.equal(pluginManager.loadCatalog().length, 4, "拉不到也必须列出内置 4 个包");
});

test("空 body / 非 JSON 也当作失败", async () => {
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end("{}");
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;

  const userData = tmpUserData();
  pluginManager.configure({ userData, isPackaged: true, projectRoot: "/tmp" });

  try {
    const result = await pluginManager.refreshCatalog(`http://127.0.0.1:${port}/catalog.json`);
    assert.equal(result.ok, false);
    assert.equal(result.error, "empty_catalog");
  } finally {
    server.close();
  }
});

test("拉到合法 catalog：写缓存并在下次 loadCatalog 生效", async () => {
  const remote = {
    packs: [{ id: "pdf-tools", version: "1.2.3", sizeMb: 12, api_level: 1, urls: ["https://x/y"] }],
  };
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(remote));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;

  const userData = tmpUserData();
  pluginManager.configure({ userData, isPackaged: true, projectRoot: "/tmp" });

  try {
    const result = await pluginManager.refreshCatalog(`http://127.0.0.1:${port}/catalog.json`);
    assert.equal(result.ok, true);
    assert.equal(result.count, 5);

    const ids = pluginManager.loadCatalog().map((p) => p.id);
    assert.ok(ids.includes("pdf-tools"));
    assert.ok(ids.includes("browser"));
  } finally {
    server.close();
  }
});

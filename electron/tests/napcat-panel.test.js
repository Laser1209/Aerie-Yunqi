"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const electronRoot = path.resolve(__dirname, "..");

test("NapCat QR code uses a narrow main-process bridge and no fixed backend port", () => {
  const preload = fs.readFileSync(path.join(electronRoot, "src", "preload.js"), "utf8");
  const main = fs.readFileSync(path.join(electronRoot, "src", "main.js"), "utf8");
  const panel = fs.readFileSync(
    path.join(electronRoot, "src", "renderer", "js", "napcat-panel.js"),
    "utf8",
  );

  assert.match(preload, /getQrCode:\s*\(\)\s*=>\s*ipcRenderer\.invoke\("napcat:getQrCode"\)/);
  assert.match(main, /ipcMain\.handle\("napcat:getQrCode"/);
  assert.match(main, /delete status\.qrcode_path/);
  assert.match(panel, /window\.aerie\.napcat\.getQrCode\(\)/);
  assert.match(panel, /getAttribute\("src"\)/);
  assert.doesNotMatch(panel, /127\.0\.0\.1:7890|qrcode_path/);
});

test("NapCat panel renders stable error states and only stops owned processes", () => {
  const panel = fs.readFileSync(
    path.join(electronRoot, "src", "renderer", "js", "napcat-panel.js"),
    "utf8",
  );
  const css = fs.readFileSync(
    path.join(electronRoot, "src", "renderer", "styles", "main.css"),
    "utf8",
  );

  assert.match(panel, /napcat_start_timeout:\s*"启动超时"/);
  assert.match(panel, /status\.owned\s*!==\s*true/);
  assert.match(panel, /Aerie 不会停止外部启动的 NapCat/);
  assert.match(css, /\.phase-dot--error/);
  assert.match(css, /\.status-qq-badge--error/);
});

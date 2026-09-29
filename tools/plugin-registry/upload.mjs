#!/usr/bin/env node
"use strict";
/*
 * 把 dist/*.aeriepack 上传到 R2，并生成 / 上传 catalog.json。
 *
 * 用法（在 tools/plugin-registry 下）：
 *   PUBLIC_BASE=https://plugins.example.com node upload.mjs ../../dist
 *   PUBLIC_BASE=... node upload.mjs ../../dist --dry-run     # 只生成 catalog，不传
 *
 * 依赖 wrangler CLI（`npx wrangler`）：用它的 `r2 object put` 逐文件上传，
 * 这样不必引入 @aws-sdk/client-s3 之类的额外依赖，也与仓库既有做法一致。
 *
 * 为什么 catalog 由本脚本生成而不是手写：sha256 / 体积必须与**实际产物**一致，
 * 手抄一次就会漂移一次，客户端校验必挂。
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const BUCKET = process.env.R2_BUCKET || "aerie-plugins";
const PUBLIC_BASE = (process.env.PUBLIC_BASE || "").replace(/\/+$/, "");
const PACK_PREFIX = "packs";

// pack.json 在 .aeriepack 的根目录；用 Python 的 zipfile 读，省掉一个 zip 依赖。
const PY_READ_MANIFEST = `
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as zf:
    print(zf.read("pack.json").decode("utf-8"))
`;

function sha256(file) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(file));
  return hash.digest("hex");
}

function readManifest(archive) {
  const out = execFileSync("python", ["-c", PY_READ_MANIFEST, archive], { encoding: "utf8" });
  return JSON.parse(out.trim());
}

function wranglerPut(file, key, dryRun) {
  const args = ["wrangler", "r2", "object", "put", `${BUCKET}/${key}`, "--file", file, "--remote"];
  if (dryRun) {
    console.log(`[dry-run] npx --yes ${args.join(" ")}`);
    return;
  }
  console.log(`uploading -> ${key}`);
  execFileSync("npx", ["--yes", ...args], { stdio: "inherit" });
}

function main() {
  const distDir = path.resolve(process.argv[2] || "dist");
  const dryRun = process.argv.includes("--dry-run");

  if (!PUBLIC_BASE) {
    console.error("ERROR: 请先设置 PUBLIC_BASE（形如 https://plugins.example.com）");
    process.exit(1);
  }
  if (!fs.existsSync(distDir)) {
    console.error(
      `ERROR: 找不到产物目录 ${distDir}（先跑 python scripts/build_plugin_pack.py --all）`,
    );
    process.exit(1);
  }

  const archives = fs
    .readdirSync(distDir)
    .filter((n) => n.endsWith(".aeriepack"))
    .sort();
  if (!archives.length) {
    console.error("ERROR: 产物目录里没有 .aeriepack");
    process.exit(1);
  }

  const packs = [];
  for (const name of archives) {
    const file = path.join(distDir, name);
    const manifest = readManifest(file);
    const key = `${PACK_PREFIX}/${name}`;
    wranglerPut(file, key, dryRun);
    packs.push({
      id: manifest.id,
      available: true,
      sizeMb: Math.round((fs.statSync(file).size / (1024 * 1024)) * 10) / 10,
      api_level: manifest.api_level,
      min_core: manifest.min_core,
      restart_required: Boolean(manifest.restart_required),
      urls: [`${PUBLIC_BASE}/${key}`],
      sha256: sha256(file),
    });
  }

  const catalogPath = path.join(distDir, "catalog.json");
  fs.writeFileSync(catalogPath, JSON.stringify({ schema: 1, packs }, null, 2), "utf8");
  console.log(`catalog 已生成：${catalogPath}（${packs.length} 个包）`);

  wranglerPut(catalogPath, "catalog.json", dryRun);
  console.log(`客户端配置：AERIE_PLUGIN_CATALOG_URL=${PUBLIC_BASE}/catalog.json`);
}

main();

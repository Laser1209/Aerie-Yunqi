"use strict";
/*
 * Aerie · 云栖 — 功能包（.aeriepack）下载 / 校验 / 安装 / 卸载。
 *
 * 为什么在主进程而不是渲染进程：
 *   写 userData、原子替换目录、大文件断点续传都需要 Node 能力；渲染进程
 *   只通过 contextBridge 白名单 IPC 调用本模块，不直接接触文件系统。
 *
 * 安装流水线（每一步失败都不得留下"半装"目录）：
 *   下载(.part 可续传) → SHA256 校验 → 解压 .staging/<id>@<v>.new
 *   → 校验 pack.json 与 catalog 一致 → 写 .aerie-installed 准入标记
 *   → .trash 腾挪旧版本 → 原子 rename 到 plugins/<id>@<v>
 *
 * 原生 DLL/torch 加载后无法在进程内卸载，因此装/卸只落盘，
 * 由用户确认后重启后端生效（重启走既有 system:restart-backend 通道）。
 */

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");

const { extractZip } = require("./runtime-bootstrap");

const CATALOG_FILE = "plugin-catalog.json";
// 远程 catalog 的本地缓存（由 refreshCatalog 写入）。读路径**永远同步**，
// 这样 loadCatalog 的老调用点一行都不用改。
const CATALOG_CACHE_FILE = "plugin-catalog.cache.json";
const INSTALL_MARKER = ".aerie-installed";
const PACK_MANIFEST = "pack.json";
const MAX_REDIRECTS = 5;

// 进程内登记的安装位置（configure() 设置）。没设置时只认内置 catalog。
let _locations = null;

function configure(loc) {
  _locations = loc && typeof loc === "object" ? loc : null;
}

function _builtinCatalog() {
  const file = path.join(__dirname, CATALOG_FILE);
  const raw = JSON.parse(fs.readFileSync(file, "utf8"));
  return Array.isArray(raw.packs) ? raw.packs : [];
}

function _catalogCacheFile() {
  if (!_locations || !_locations.userData) return "";
  return path.join(_locations.userData, CATALOG_CACHE_FILE);
}

/**
 * 远程条目与内置条目**按 id 合并**，内置里远程没有的仍然保留。
 *
 * 为什么必须合并而不是替换：远程拉挂 / 拉到一个残缺 catalog 时，模块中心
 * 会整个变空 —— 用户看到的不是"更新失败"，而是"我这软件根本没这些功能"。
 * 远程只允许**增量或覆盖同名项**。
 */
function _mergeCatalog(remote) {
  const builtin = _builtinCatalog();
  const byId = new Map(builtin.map((p) => [p.id, p]));
  for (const pack of remote) {
    if (pack && typeof pack === "object" && pack.id) byId.set(pack.id, pack);
  }
  return Array.from(byId.values());
}

function loadCatalog() {
  const cacheFile = _catalogCacheFile();
  if (cacheFile) {
    const cached = _readJsonSafe(cacheFile);
    const packs = cached && Array.isArray(cached.packs) ? cached.packs : null;
    if (packs && packs.length) {
      try {
        return _mergeCatalog(packs);
      } catch (_) {
        // 缓存坏了就当没有：绝不让它挡住内置清单。
      }
    }
  }
  return _builtinCatalog();
}

/**
 * 拉远程 catalog 并写缓存；**任何失败都保持现状**（内置清单 + 旧缓存）。
 * @returns {Promise<{ok: boolean, count?: number, error?: string}>}
 */
async function refreshCatalog(url, { timeoutMs = 8000 } = {}) {
  const target = String(url || "").trim();
  if (!target) return { ok: false, error: "empty_url" };

  const cacheFile = _catalogCacheFile();
  if (!cacheFile) return { ok: false, error: "not_configured" };

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let payload;
    try {
      const res = await fetch(target, { signal: controller.signal });
      if (!res.ok) return { ok: false, error: `http_${res.status}` };
      payload = await res.json();
    } finally {
      clearTimeout(timer);
    }

    const packs = payload && Array.isArray(payload.packs) ? payload.packs : null;
    if (!packs || !packs.length) return { ok: false, error: "empty_catalog" };
    if (!packs.every((p) => p && typeof p === "object" && p.id)) {
      return { ok: false, error: "invalid_catalog" };
    }

    fs.mkdirSync(path.dirname(cacheFile), { recursive: true });
    fs.writeFileSync(cacheFile, JSON.stringify({ packs }, null, 2), "utf8");
    return { ok: true, count: _mergeCatalog(packs).length };
  } catch (err) {
    // 断网 / 超时 / JSON 坏 / 目录不可写，一律静默回退。
    return { ok: false, error: String((err && err.message) || err) };
  }
}

/**
 * @param {object} loc - { isPackaged, userData, projectRoot }
 * 与后端 core.paths.plugins_dir() 的默认值严格对齐：
 * 打包态 userData/plugins（data_dir=userData/data 的同级）；
 * 开发态 <projectRoot>/plugins。
 */
function getPluginsDir(loc) {
  return loc.isPackaged
    ? path.join(loc.userData, "plugins")
    : path.join(loc.projectRoot, "plugins");
}

function getStagingDir(loc) {
  return path.join(getPluginsDir(loc), ".staging");
}

function getTrashDir(loc) {
  return path.join(getPluginsDir(loc), ".trash");
}

function _readJsonSafe(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (_) {
    return null;
  }
}

/** 扫描已落盘的包目录（不依赖后端在线；状态以后端 /api/plugins 为准合并）。 */
function listInstalled(loc) {
  const root = getPluginsDir(loc);
  if (!fs.existsSync(root)) return [];
  const result = [];
  for (const name of fs.readdirSync(root)) {
    if (name.startsWith(".")) continue;
    const dir = path.join(root, name);
    if (!fs.statSync(dir).isDirectory()) continue;
    const manifest = _readJsonSafe(path.join(dir, PACK_MANIFEST));
    if (!manifest || !manifest.id) continue;
    const admitted = fs.existsSync(path.join(dir, INSTALL_MARKER));
    result.push({
      id: manifest.id,
      version: manifest.version || "0.0.0",
      dirName: name,
      dir,
      admitted,
      restartRequired: !!manifest.restart_required,
      state: admitted ? "installed" : "unadmitted",
    });
  }
  return result;
}

function _sha256(file) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(file));
  return hash.digest("hex");
}

/**
 * 下载到 dest，已存在的 .part 走 Range 续传；服务器不支持时从头重下。
 * token = { cancelled:boolean }，cancel 时主动 destroy 请求。
 */
function downloadWithResume(urls, dest, token, onProgress) {
  return new Promise((resolve, reject) => {
    let attemptIndex = 0;

    const tryUrl = (targetUrl, redirectsLeft) => {
      if (token.cancelled) return reject(new Error("cancelled"));
      const lib = /^https:/i.test(targetUrl) ? https : http;
      const existingSize = fs.existsSync(dest) ? fs.statSync(dest).size : 0;
      const headers = existingSize > 0 ? { Range: `bytes=${existingSize}-` } : {};

      const req = lib.get(targetUrl, { headers, timeout: 30000 }, (res) => {
        const status = res.statusCode || 0;
        if ([301, 302, 303, 307, 308].includes(status) && res.headers.location && redirectsLeft > 0) {
          res.resume();
          const next = new URL(res.headers.location, targetUrl).toString();
          tryUrl(next, redirectsLeft - 1);
          return;
        }
        if (status !== 200 && status !== 206) {
          res.resume();
          reject(new Error(`HTTP ${status}`));
          return;
        }

        // 200 = 服务器无视 Range，截断重下；206 = 续传。
        const resumeFrom = status === 206 ? existingSize : 0;
        if (resumeFrom === 0 && existingSize > 0) {
          try { fs.unlinkSync(dest); } catch (_) {}
        }
        const total = Number(res.headers["content-length"] || 0) + resumeFrom;
        const out = fs.createWriteStream(dest, { flags: status === 206 ? "a" : "w" });
        let received = resumeFrom;
        let lastEmit = 0;

        res.on("data", (chunk) => {
          if (token.cancelled) {
            req.destroy(new Error("cancelled"));
            return;
          }
          received += chunk.length;
          const now = Date.now();
          if (onProgress && (now - lastEmit > 200 || received === total)) {
            lastEmit = now;
            onProgress({ received, total, percent: total > 0 ? received / total : 0 });
          }
        });
        res.pipe(out);
        out.on("finish", () => resolve({ received, total }));
        out.on("error", reject);
      });

      req.on("timeout", () => req.destroy(new Error("timeout")));
      req.on("error", (err) => {
        if (token.cancelled || err.message === "cancelled") {
          reject(new Error("cancelled"));
          return;
        }
        // 网络错误时保留 .part，尝试下一个镜像；全部失败才 reject（续传不浪费）。
        if (attemptIndex + 1 < urls.length) {
          attemptIndex += 1;
          tryUrl(urls[attemptIndex], MAX_REDIRECTS);
        } else {
          reject(err);
        }
      });
    };

    fs.mkdirSync(path.dirname(dest), { recursive: true });
    tryUrl(urls[attemptIndex], MAX_REDIRECTS);
  });
}

function _rmrf(target) {
  if (target && fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: true });
}

/** 把已解压并校验过的包原子提交到最终位置。 */
function _commitPack(loc, tempExtract, packRoot, manifest, markerData) {
  const pluginsRoot = getPluginsDir(loc);
  const trash = getTrashDir(loc);
  fs.mkdirSync(pluginsRoot, { recursive: true });
  fs.mkdirSync(trash, { recursive: true });

  fs.writeFileSync(
    path.join(packRoot, INSTALL_MARKER),
    JSON.stringify({ ...markerData, installedAt: new Date().toISOString() }, null, 2),
    "utf8",
  );

  // 原子替换：旧版本先挪进 .trash，新版本 rename 到位，再清 trash。
  const finalDir = path.join(pluginsRoot, `${manifest.id}@${manifest.version}`);
  if (fs.existsSync(finalDir)) {
    const aside = path.join(trash, `${manifest.id}@${manifest.version}-${Date.now()}`);
    fs.renameSync(finalDir, aside);
  }
  fs.renameSync(packRoot, finalDir);
  _rmrf(tempExtract);
  _rmrf(trash);

  return { id: manifest.id, version: manifest.version, dir: finalDir };
}

/** 解压并定位 pack.json（清单允许位于压缩包根或单层包裹目录）。 */
function _extractAndLocate(loc, zipFile, tag) {
  const staging = getStagingDir(loc);
  fs.mkdirSync(staging, { recursive: true });
  const tempExtract = path.join(staging, `${tag}.new`);
  _rmrf(tempExtract);

  // PowerShell Expand-Archive 只认 .zip 扩展名；.aeriepack 是 zip 容器，
  // 在 staging 内复制一份 .zip 临时文件再解压（不改动共享的 extractZip）。
  const zipAlias = path.join(staging, `${tag}.zip`);
  try { _rmrf(zipAlias); } catch (_) {}
  fs.copyFileSync(zipFile, zipAlias);

  const unzipped = extractZip(zipAlias, tempExtract);
  _rmrf(zipAlias);
  if (!unzipped.ok) {
    _rmrf(tempExtract);
    throw new Error(`解压失败 / extract failed: ${unzipped.reason || "unknown"}`);
  }

  let packRoot = tempExtract;
  if (!fs.existsSync(path.join(packRoot, PACK_MANIFEST))) {
    const nested = fs.readdirSync(tempExtract)
      .map((n) => path.join(tempExtract, n))
      .find((p) => fs.statSync(p).isDirectory() && fs.existsSync(path.join(p, PACK_MANIFEST)));
    if (nested) packRoot = nested;
  }
  const manifest = _readJsonSafe(path.join(packRoot, PACK_MANIFEST));
  if (!manifest) {
    _rmrf(tempExtract);
    throw new Error("包内缺少 pack.json / pack.json missing");
  }
  return { tempExtract, packRoot, manifest };
}

/**
 * 安装 catalog 来源的 zip：必须与目录条目 id/version 精确一致。
 * @returns {Promise<{id:string,version:string,dir:string}>}
 */
async function installFromZip(loc, zipFile, catalogEntry) {
  const { tempExtract, packRoot, manifest } = await _extractAndLocate(
    loc, zipFile, `${catalogEntry.id}@${catalogEntry.version}`,
  );
  if (manifest.id !== catalogEntry.id) {
    _rmrf(tempExtract);
    throw new Error(`包 id 不符: ${manifest.id} != ${catalogEntry.id}`);
  }
  if (String(manifest.version) !== String(catalogEntry.version)) {
    _rmrf(tempExtract);
    throw new Error(`包版本不符: ${manifest.version} != ${catalogEntry.version}`);
  }
  return _commitPack(loc, tempExtract, packRoot, manifest, {
    sha256: catalogEntry.sha256 || "",
    source: catalogEntry._source || "catalog",
  });
}

/**
 * 本地 zip 安装（QA / 弱网手动安装兜底）：信任包内清单，
 * 以文件自身 SHA256 作为准入凭据写入标记。
 */
async function installLocalZip(loc, zipFile) {
  const tag = `local-${Date.now()}`;
  const { tempExtract, packRoot, manifest } = await _extractAndLocate(loc, zipFile, tag);
  const result = _commitPack(loc, tempExtract, packRoot, manifest, {
    sha256: _sha256(zipFile),
    source: "local",
  });
  return result;
}

/** 远程安装：catalog 条目 → 下载校验 → 落盘。 */
async function installFromCatalog(loc, entry, token, onProgress) {
  if (!entry || !Array.isArray(entry.urls) || entry.urls.length === 0) {
    throw new Error("该模块尚未发布 / pack not published yet");
  }
  const staging = getStagingDir(loc);
  fs.mkdirSync(staging, { recursive: true });
  const partFile = path.join(staging, `${entry.id}@${entry.version}.aeriepack.part`);

  await downloadWithResume(entry.urls, partFile, token, (p) => {
    if (onProgress) onProgress({ phase: "downloading", ...p });
  });

  if (entry.sha256) {
    if (onProgress) onProgress({ phase: "verifying", percent: 0 });
    const actual = _sha256(partFile);
    if (actual.toLowerCase() !== String(entry.sha256).toLowerCase()) {
      _rmrf(partFile);
      throw new Error("SHA256 校验失败，安装包可能已损坏 / checksum mismatch");
    }
  }
  if (onProgress) onProgress({ phase: "installing", percent: 0 });
  const result = await installFromZip(loc, partFile, { ...entry, _source: "catalog" });
  _rmrf(partFile);
  if (onProgress) onProgress({ phase: "done", percent: 1 });
  return result;
}

/** 卸载：只允许删除受管目录（必须含 pack.json 且 id 匹配）。 */
function removePack(loc, id) {
  const root = getPluginsDir(loc);
  if (!fs.existsSync(root)) return false;
  let removed = false;
  for (const name of fs.readdirSync(root)) {
    if (name.startsWith(".")) continue;
    const dir = path.join(root, name);
    if (!fs.statSync(dir).isDirectory()) continue;
    const manifest = _readJsonSafe(path.join(dir, PACK_MANIFEST));
    if (manifest && manifest.id === id) {
      _rmrf(dir);
      removed = true;
    }
  }
  // 同时清理该 id 的暂存分片。
  const staging = getStagingDir(loc);
  if (fs.existsSync(staging)) {
    for (const name of fs.readdirSync(staging)) {
      if (name.startsWith(`${id}@`)) _rmrf(path.join(staging, name));
    }
  }
  return removed;
}

module.exports = {
  CATALOG_FILE,
  CATALOG_CACHE_FILE,
  configure,
  getPluginsDir,
  getStagingDir,
  loadCatalog,
  refreshCatalog,
  listInstalled,
  installFromCatalog,
  installFromZip,
  installLocalZip,
  removePack,
  downloadWithResume,
};

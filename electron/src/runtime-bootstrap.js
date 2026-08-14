"use strict";

/**
 * Aerie · 云栖 — Python 运行时自举（environment bootstrap）
 *
 * 打包产物里的 `.venv` 是开发机生成的虚拟环境，其 `Scripts/python.exe`
 * 只是"重定向器"，会按 `pyvenv.cfg` 里的 `home` 字段去找基础解释器
 * （例如开发机的 `C:\Python314\python.exe`）。换到一台没装 Python 的机器
 * 上，这个重定向器就起不来，后端直接 `ECONNREFUSED 127.0.0.1:7890`。
 *
 * 本模块负责：
 *   1. 检测当前 `python.exe` 能否真正运行；
 *   2. 不能运行时，从官方/国内镜像/第三方源依次下载 Windows embeddable
 *      Python（含 sqlite3.dll / _sqlite3.pyd，满足后端 SQLite 需求）；
 *   3. 解压到 `<pythonRoot>/runtime/`，并改写 `pythonXXX._pth`，让嵌入式
 *      Python 能加载已随包分发的 `.venv/Lib/site-packages` 三方依赖；
 *   4. 三个源全部失败时，返回教程文本，由主进程弹窗并落盘。
 */

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const https = require("https");
const http = require("http");

const DEFAULT_PYTHON_VERSION = "3.14.3";
const PER_SOURCE_TIMEOUT_MS = 5 * 60 * 1000; // 每个源 5 分钟
const DETECT_TIMEOUT_MS = 15 * 1000; // 检测 15 秒
const MAX_REDIRECTS = 5;

// 下载源顺序：官方 → 国内镜像 → 第三方。依次尝试，每个源独立超时。
const SOURCES = [
  {
    name: "官方 python.org",
    url: (ver) =>
      `https://www.python.org/ftp/python/${ver}/python-${ver}-embed-amd64.zip`,
  },
  {
    name: "华为云镜像",
    url: (ver) =>
      `https://mirrors.huaweicloud.com/python/${ver}/python-${ver}-embed-amd64.zip`,
  },
  {
    name: "清华 TUNA 镜像",
    url: (ver) =>
      `https://mirrors.tuna.tsinghua.edu.cn/python/${ver}/python-${ver}-embed-amd64.zip`,
  },
];

function _pthFilename(version) {
  const parts = String(version || DEFAULT_PYTHON_VERSION).split(".");
  const major = parts[0] || "3";
  const minor = parts[1] || "0";
  return `python${major}${minor}._pth`;
}

function _stdlibZipName(version) {
  const parts = String(version || DEFAULT_PYTHON_VERSION).split(".");
  const major = parts[0] || "3";
  const minor = parts[1] || "0";
  return `python${major}${minor}.zip`;
}

/**
 * 检测给定 python.exe 是否能正常执行 `--version`。
 * venv 重定向器找不到基础解释器时，要么 spawn 直接失败，要么非零退出。
 */
function detectPythonRuntime(pythonExe) {
  if (!pythonExe || !fs.existsSync(pythonExe)) {
    return { ok: false, reason: "python executable missing: " + pythonExe };
  }
  try {
    const r = spawnSync(pythonExe, ["--version"], {
      encoding: "utf8",
      timeout: DETECT_TIMEOUT_MS,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (r.error) {
      return { ok: false, reason: r.error.message };
    }
    if (r.status !== 0) {
      const stderr = String(r.stderr || "").trim();
      return { ok: false, reason: stderr || `exit code ${r.status}` };
    }
    const out = String(r.stdout || "").trim() || String(r.stderr || "").trim();
    if (!out) {
      return { ok: false, reason: "no version output" };
    }
    return { ok: true, version: out };
  } catch (err) {
    return { ok: false, reason: err && err.message };
  }
}

/**
 * 从 `<pythonRoot>/.venv/pyvenv.cfg` 读取基础解释器版本，用于拼接下载 URL。
 */
function readRequiredPythonVersion(pythonRoot) {
  const candidates = [
    path.join(pythonRoot, ".venv", "pyvenv.cfg"),
    path.join(pythonRoot, "pyvenv.cfg"),
  ];
  for (const cfgPath of candidates) {
    try {
      const text = fs.readFileSync(cfgPath, "utf8");
      const m = text.match(/^version\s*=\s*([^\r\n]+)/im);
      if (m && m[1]) return m[1].trim();
    } catch (_) {
      /* try next */
    }
  }
  return DEFAULT_PYTHON_VERSION;
}

/**
 * 下载单个 URL 到本地文件。支持 301/302 重定向与总超时。
 * 返回 Promise<{ ok: boolean, reason?: string }>。
 */
function downloadFile(url, destPath, timeoutMs) {
  return new Promise((resolve) => {
    let lastError = null;
    let settled = false;

    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    const attempt = (targetUrl, redirectsLeft) => {
      const isHttps = /^https:/i.test(targetUrl);
      const lib = isHttps ? https : http;

      const req = lib.get(targetUrl, (res) => {
        const status = res.statusCode || 0;

        // 重定向跟随
        if (
          (status === 301 || status === 302 || status === 303 || status === 307 || status === 308) &&
          res.headers.location &&
          redirectsLeft > 0
        ) {
          res.resume();
          const next = new URL(res.headers.location, targetUrl).toString();
          attempt(next, redirectsLeft - 1);
          return;
        }

        if (status !== 200) {
          res.resume();
          finish({ ok: false, reason: `HTTP ${status}` });
          return;
        }

        const out = fs.createWriteStream(destPath);
        out.on("error", (err) => {
          finish({ ok: false, reason: err.message });
        });
        out.on("finish", () => {
          finish({ ok: true });
        });
        res.pipe(out);
      });

      req.on("error", (err) => {
        lastError = err;
        finish({ ok: false, reason: err.message });
      });
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error("timeout"));
        finish({ ok: false, reason: "timeout" });
      });
    };

    attempt(url, MAX_REDIRECTS);
  });
}

/**
 * 用 PowerShell 的 Expand-Archive 解压（Windows 内置，无需额外依赖）。
 */
function extractZip(zipPath, destDir) {
  try {
    fs.mkdirSync(destDir, { recursive: true });
    const script =
      `Expand-Archive -LiteralPath '${zipPath.replace(/'/g, "''")}' ` +
      `-DestinationPath '${destDir.replace(/'/g, "''")}' -Force`;
    const r = spawnSync(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      { encoding: "utf8", timeout: 5 * 60 * 1000, windowsHide: true }
    );
    if (r.error) return { ok: false, reason: r.error.message };
    if (r.status !== 0) {
      return { ok: false, reason: String(r.stderr || "").trim() || `exit ${r.status}` };
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, reason: err && err.message };
  }
}

/**
 * 改写 embeddable 的 `pythonXXX._pth`，使其加载已随包分发的
 * `.venv/Lib/site-packages`。相对路径 `..\.venv\Lib\site-packages` 相对于
 * runtime 目录（python.exe 所在处），因此整个安装目录被移动也依然有效。
 */
function configureEmbeddablePth(runtimeDir, venvSitePackages, version) {
  const pthPath = path.join(runtimeDir, _pthFilename(version));
  const stdlibZip = _stdlibZipName(version);
  // 相对 runtime 目录指到 .venv/Lib/site-packages
  const relSite = path.relative(runtimeDir, venvSitePackages) || ".";
  const content = [stdlibZip, ".", relSite, "import site", ""].join("\r\n");
  try {
    fs.writeFileSync(pthPath, content, "utf8");
    return { ok: true, pthPath };
  } catch (err) {
    return { ok: false, reason: err && err.message };
  }
}

/**
 * 主入口：确保存在可用的 Python 运行时。
 *
 * @param {object} opts
 * @param {string} opts.pythonRoot   PYTHON_ROOT（打包态 resources/python）
 * @param {string} opts.pythonExe    当前期望的 python.exe 路径
 * @param {Function} [opts.log]      日志回调 (msg) => void
 * @returns {Promise<{ok:boolean, pythonExe?:string, reason?:string, tutorial?:string}>}
 */
async function ensurePythonRuntime(opts) {
  const pythonRoot = opts.pythonRoot;
  const log = opts.log || (() => {});
  const venvExe = opts.pythonExe;
  const runtimeDir = path.join(pythonRoot, "runtime");
  const runtimeExe = path.join(runtimeDir, "python.exe");
  const venvSitePackages = path.join(pythonRoot, ".venv", "Lib", "site-packages");

  // 1) 现有 venv 重定向器可用 → 直接用，无需下载。
  const det = detectPythonRuntime(venvExe);
  if (det.ok) {
    log("[runtime] venv python usable: " + det.version);
    return { ok: true, pythonExe: venvExe };
  }
  log("[runtime] venv python unusable: " + (det.reason || "unknown"));

  // 2) 若之前已经自举过 runtime，直接复用。
  const det2 = detectPythonRuntime(runtimeExe);
  if (det2.ok) {
    log("[runtime] existing runtime python usable: " + det2.version);
    return { ok: true, pythonExe: runtimeExe };
  }

  // 3) 依次从三个源下载 embeddable Python。
  const version = readRequiredPythonVersion(pythonRoot);
  const zipName = `python-${version}-embed-amd64.zip`;
  const zipPath = path.join(runtimeDir, zipName);
  let lastReason = "";

  for (const src of SOURCES) {
    const url = src.url(version);
    log(`[runtime] downloading ${zipName} from ${src.name} ...`);
    fs.mkdirSync(runtimeDir, { recursive: true });
    try {
      fs.rmSync(zipPath, { force: true });
    } catch (_) {}

    const dl = await downloadFile(url, zipPath, PER_SOURCE_TIMEOUT_MS);
    if (!dl.ok) {
      lastReason = `${src.name}: ${dl.reason || "download failed"}`;
      log(`[runtime] source failed (${lastReason})`);
      continue;
    }
    log(`[runtime] downloaded OK from ${src.name}`);

    const ex = extractZip(zipPath, runtimeDir);
    try {
      fs.rmSync(zipPath, { force: true });
    } catch (_) {}

    if (!ex.ok) {
      lastReason = `${src.name}: extract failed (${ex.reason || "unknown"})`;
      log(`[runtime] ${lastReason}`);
      continue;
    }

    const cfg = configureEmbeddablePth(runtimeDir, venvSitePackages, version);
    if (!cfg.ok) {
      lastReason = `${src.name}: pth config failed (${cfg.reason || "unknown"})`;
      log(`[runtime] ${lastReason}`);
      continue;
    }

    const det3 = detectPythonRuntime(runtimeExe);
    if (det3.ok) {
      log("[runtime] bootstrap complete: " + det3.version);
      return { ok: true, pythonExe: runtimeExe };
    }
    lastReason = `${src.name}: runtime still unusable (${det3.reason || "unknown"})`;
    log(`[runtime] ${lastReason}`);
  }

  // 4) 全部源失败 → 返回教程。
  log("[runtime] all sources failed. Giving up.");
  return {
    ok: false,
    reason: lastReason || "all download sources failed",
    tutorial: buildManualTutorial(version),
  };
}

/**
 * 生成手动安装教程（全崩兜底）。
 */
function buildManualTutorial(version) {
  const ver = version || DEFAULT_PYTHON_VERSION;
  const zipName = `python-${ver}-embed-amd64.zip`;
  return [
    `Aerie · 云栖 运行环境安装教程`,
    ``,
    `自动下载失败，请手动补齐 Python 运行环境（${ver} / Windows 64 位）：`,
    ``,
    `1. 下载 embeddable 安装包（任选一个地址）：`,
    `   · 官方：  https://www.python.org/ftp/python/${ver}/${zipName}`,
    `   · 华为云：https://mirrors.huaweicloud.com/python/${ver}/${zipName}`,
    `   · 清华：  https://mirrors.tuna.tsinghua.edu.cn/python/${ver}/${zipName}`,
    ``,
    `2. 解压到：`,
    `   <安装目录>\\resources\\python\\runtime\\`,
    `   （解压后应能看到 python.exe、python*.zip、python*._pth 等文件）`,
    ``,
    `3. 编辑该目录下的 python*._pth 文件，加入以下两行：`,
    `   import site`,
    `   ..\\.venv\\Lib\\site-packages`,
    ``,
    `4. 重启应用即可。`,
  ].join("\r\n");
}

module.exports = {
  ensurePythonRuntime,
  detectPythonRuntime,
  readRequiredPythonVersion,
  buildManualTutorial,
  downloadFile,
  extractZip,
  configureEmbeddablePth,
  SOURCES,
};

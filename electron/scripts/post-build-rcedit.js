#!/usr/bin/env node
/* Aerie · 云栖 v9.0 — Post-build rcedit icon injector.
 *
 * electron-builder 24.x occasionally fails to inject the .ico into the
 * launcher EXE (Win11 24H2 / 15-section PE). This script forces
 * re-injection via rcedit, idempotent and safe to re-run.
 */

'use strict';

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const ICON = path.join(ROOT, 'builder', 'icon.ico');

// electron-builder 会根据 productName 生成可执行文件名，含中文与「·」等
// 特殊字符（如 `Aerie · 云栖.exe`），且不同版本命名可能变化。这里改为
// 扫描 win-unpacked 顶层 *.exe，避免硬编码文件名导致找不到图标注入目标。
const dirs = ['dist', 'dist-final'];
const found = [];
for (const dir of dirs) {
  const unpacked = path.join(ROOT, dir, 'win-unpacked');
  if (!fs.existsSync(unpacked)) continue;
  for (const f of fs.readdirSync(unpacked)) {
    if (f.toLowerCase().endsWith('.exe')) found.push(path.join(unpacked, f));
  }
}
found.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
const exe = found[0];

if (!exe) {
  console.error('[rcedit] Could not locate main exe under', dirs.map((d) => path.join(ROOT, d)).join(', '));
  process.exit(1);
}
if (!fs.existsSync(ICON)) {
  console.error('[rcedit] icon not found:', ICON);
  process.exit(1);
}

const rcedit = path.join(
  ROOT,
  'node_modules', 'rcedit', 'bin', 'rcedit.exe',
);

if (!fs.existsSync(rcedit)) {
  try {
    require('child_process').execSync('npm install --no-save rcedit', { cwd: ROOT, stdio: 'inherit' });
  } catch (e) {
    console.error('[rcedit] install failed:', e.message);
    process.exit(2);
  }
}

try {
  console.log('[rcedit] injecting icon into:', exe);
  execSync(`"${rcedit}" "${exe}" --set-icon "${ICON}"`, { stdio: 'inherit' });
  console.log('[rcedit] OK');
} catch (e) {
  console.error('[rcedit] failed:', e.message);
  process.exit(3);
}

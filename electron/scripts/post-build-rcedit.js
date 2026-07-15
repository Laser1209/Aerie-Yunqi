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

const dirs = ['dist', 'dist-final', 'dist-v9', 'dist-new', 'dist-build2'];
const found = dirs
  .map((dir) => path.join(ROOT, dir, 'win-unpacked', 'Aerie · 云栖.exe'))
  .filter((p) => fs.existsSync(p));
found.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
const exe = found[0];

if (!exe) {
  console.error('[rcedit] Could not locate Aerie · 云栖.exe under', candidates);
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

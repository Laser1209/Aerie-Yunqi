'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const outputDir = 'D:/aerie-dist-v046';
const cacheDir = 'D:/aerie-cache/electron-builder';
const tempDir = 'D:/aerie-cache/tmp';
for (const dir of [outputDir, cacheDir, tempDir]) fs.mkdirSync(dir, { recursive: true });

const env = {
  ...process.env,
  AERIE_BUILD_OUTPUT_DIR: outputDir,
  ELECTRON_BUILDER_CACHE: cacheDir,
  TEMP: tempDir,
  TMP: tempDir,
};
const npm = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const result = spawnSync(npm, ['electron-builder', '--win', '--x64', '--config.directories.output=' + outputDir], {
  cwd: path.resolve(__dirname, '..'),
  env,
  // Windows cannot spawn a .cmd shim directly with newer Node releases.
  // Use the shell so npx.cmd resolves consistently on developer machines.
  shell: process.platform === 'win32',
  stdio: 'inherit',
});
if (result.status !== 0) process.exit(result.status || 1);

const post = spawnSync(process.execPath, [path.join(__dirname, 'post-build-rcedit.js')], {
  cwd: path.resolve(__dirname, '..'),
  env,
  stdio: 'inherit',
});
process.exit(post.status || 0);

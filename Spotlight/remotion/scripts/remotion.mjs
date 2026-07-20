import {existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

const browserCandidates = process.platform === 'win32'
  ? [
      join(process.env.PROGRAMFILES ?? 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
      join(process.env['PROGRAMFILES(X86)'] ?? 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe'),
      join(process.env.LOCALAPPDATA ?? '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
      join(process.env.PROGRAMFILES ?? 'C:\\Program Files', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    ]
  : ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'];

const browser = browserCandidates.find((candidate) => existsSync(candidate));
const cli = fileURLToPath(new URL('../node_modules/@remotion/cli/remotion-cli.js', import.meta.url));
const args = [cli, ...process.argv.slice(2)];
const command = process.argv[2];
const needsBrowser = new Set(['studio', 'render', 'still', 'benchmark']).has(command);

if (needsBrowser && browser && !args.some((arg) => arg.startsWith('--browser-executable'))) {
  args.push(`--browser-executable=${browser}`);
}

const child = spawn(process.execPath, args, {stdio: 'inherit', cwd: process.cwd(), env: process.env});
child.on('error', (error) => {
  console.error(error);
  process.exit(1);
});
child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  }
  process.exit(code ?? 1);
});

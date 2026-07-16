// Aerie · 云栖 — Phase 7: check-emojis.js
// Static scan to prevent emoji regression in user-facing UI files.
// Whitelist: backend log files + LLM prompt content.
// Exit code: 0 = OK, 1 = violations found.

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SCAN_DIRS = [
  path.join(ROOT, "src", "renderer"),
  path.join(ROOT, "src", "main.js"),
  path.join(ROOT, "src", "preload.js"),
];

// Emoji ranges (unicode blocks)
const EMOJI_REGEX = /[\u{1F300}-\u{1F9FF}]|[\u{1FA00}-\u{1FAFF}]|[\u{2600}-\u{27BF}]|[\u{1F000}-\u{1F02F}]|[\u{1F100}-\u{1F1FF}]/gu;

// Files allowed to keep emojis (with specific line context)
const WHITELIST = [
  // LLM prompt content (semantic warning marker for AI)
  { file: "core/context_builder.py", line: 150, reason: "LLM 提示符；保留 ⚠ 作为警告段落开头标记" },
];

function listFiles(dir, results = []) {
  if (!fs.existsSync(dir)) return results;
  const stat = fs.statSync(dir);
  if (stat.isFile()) {
    if (/\.(html|js|jsx|ts|tsx|css|md|svg)$/i.test(dir)) results.push(dir);
    return results;
  }
  for (const entry of fs.readdirSync(dir)) {
    listFiles(path.join(dir, entry), results);
  }
  return results;
}

function isWhitelisted(file, line) {
  const rel = path.relative(ROOT, file).replace(/\\/g, "/");
  return WHITELIST.some(
    (w) => w.file.replace(/\\/g, "/") === rel && w.line === line,
  );
}

function scan() {
  const violations = [];
  for (const target of SCAN_DIRS) {
    if (!fs.existsSync(target)) continue;
    const files = listFiles(target);
    for (const file of files) {
      // Skip the icons dir (we WANT emojis in icon names? no — names are svg filenames; safe)
      if (file.includes(`${path.sep}assets${path.sep}icons${path.sep}`)) continue;
      // Skip the sprite itself (it doesn't contain emoji)
      const source = fs.readFileSync(file, "utf-8");
      const lines = source.split(/\r?\n/);
      lines.forEach((lineText, i) => {
        const matches = lineText.match(EMOJI_REGEX);
        if (matches && matches.length > 0) {
          const lineNo = i + 1;
          if (!isWhitelisted(file, lineNo)) {
            violations.push({
              file: path.relative(ROOT, file),
              line: lineNo,
              emoji: matches.join(" "),
              context: lineText.trim().slice(0, 100),
            });
          }
        }
      });
    }
  }
  return violations;
}

function main() {
  const violations = scan();
  if (violations.length === 0) {
    console.log("✓ No emojis found in UI files (renderer + main process)");
    process.exit(0);
  }
  console.error(`✗ Found ${violations.length} emoji usage(s) in UI:`);
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}  [${v.emoji}]`);
    console.error(`    > ${v.context}`);
  }
  console.error("\nHint: Replace with <svg class='icon icon--16'><use href='#icon-...'/></svg> referencing the sprite.");
  process.exit(1);
}

if (require.main === module) {
  main();
}

module.exports = { scan, EMOJI_REGEX, WHITELIST };

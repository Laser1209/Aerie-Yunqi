"use strict";

/* 回归：`hidden` 属性必须真的等于"不渲染、不吃点击"。
 *
 * 背景：`[hidden]` 只是 UA 样式表里的 `display: none`，优先级最低，作者 CSS 里
 * 任何一句 `.foo { display: flex }` 都能把它顶掉。图片光箱（.image-lightbox）
 * 就是这么变成一层永久铺满全屏、z-index 9500 的遮罩的 —— 它压在日报抽屉的
 * backdrop（9000）之上，于是"点左侧模糊区关不掉抽屉"；ESC 关掉抽屉后它还在，
 * 于是"程序内任何地方都点不动"。两个症状同一个根因。
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const RENDERER = path.join(__dirname, "..", "src", "renderer");
const html = fs.readFileSync(path.join(RENDERER, "index.html"), "utf8");

/* index.html 实际 <link> 加载的样式表 —— 别的窗口的样式表在本窗口不生效，
   不能拿它们（比如 dynamic-island.css）当"已有守卫"。 */
const linkedCss = [...html.matchAll(/<link[^>]+href="(styles\/[^"]+\.css)"/g)]
  .map((m) => m[1])
  .filter((rel, idx, all) => all.indexOf(rel) === idx)
  .map((rel) => ({ name: path.basename(rel), text: fs.readFileSync(path.join(RENDERER, rel), "utf8") }));

function displayRules(css) {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [];
  for (const [, selector, body] of stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const display = body.match(/(?:^|;)\s*display\s*:\s*([^;!]+)/);
    if (display) rules.push({ selector: selector.trim(), display: display[1].trim() });
  }
  return rules;
}

const allRules = linkedCss.flatMap((file) =>
  displayRules(file.text).map((rule) => ({ ...rule, file: file.name })),
);

function hiddenTargets() {
  const found = [];
  for (const [, tag, attrs] of html.matchAll(/<(\w+)([^>]*?)\shidden(\s[^>]*)?>/gi)) {
    const classes = [...attrs.matchAll(/class="([^"]*)"/g)]
      .flatMap((m) => m[1].split(/\s+/))
      .filter(Boolean);
    const id = attrs.match(/id="([^"]*)"/);
    found.push({ tag, classes, id: id ? id[1] : "" });
  }
  return found;
}

/* 全局守卫：必须带 !important，否则特异性更低、会被 `.foo { display: flex }` 盖掉。 */
function globalHiddenGuard() {
  return linkedCss.some((file) =>
    /(?:^|[^-\w])\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important/.test(file.text),
  );
}

test("a linked stylesheet pins [hidden] to display:none!important", () => {
  const named = allRules.filter((rule) => rule.selector === "[hidden]");
  assert.ok(named.length > 0, "no `[hidden]` rule found in any stylesheet linked by index.html");
  assert.ok(
    globalHiddenGuard(),
    "the `[hidden]` guard must be `display: none !important` in a stylesheet index.html actually loads",
  );
});

const escape = (token) => token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const namesToken = (selector, token) => new RegExp(`${escape(token)}(?![\\w-])`).test(selector);

test("no hidden element is kept visible by an unguarded author display rule", () => {
  const targets = hiddenTargets();
  assert.ok(targets.length >= 5, `expected index.html to carry hidden elements, found ${targets.length}`);

  const problems = [];
  for (const target of targets) {
    const tokens = [...target.classes, target.id ? `#${target.id}` : ""].filter(Boolean);
    for (const rule of allRules) {
      if (rule.display === "none" || rule.display === "contents") continue;
      if (rule.selector.includes("[hidden]")) continue;
      const token = tokens.find((candidate) => namesToken(rule.selector, candidate));
      if (!token) continue;
      // 该元素若自带 `.foo[hidden] { display: none }` 这类逐元素守卫，就已经安全了
      const selfGuarded = allRules.some(
        (other) => other.selector.includes("[hidden]") && other.display === "none" && namesToken(other.selector, token),
      );
      if (selfGuarded) continue;
      problems.push(`<${target.tag}> ${target.classes.join(".") || "#" + target.id}: \`${rule.selector} { display: ${rule.display}; }\` (${rule.file})`);
    }
  }

  // 有全局 [hidden] 守卫时上面这些规则都被 !important 压住；这里断言的是
  // "要么有守卫，要么逐条不冲突"，两者任一缺失就会把光箱那类 bug 放回来。
  assert.ok(
    globalHiddenGuard() || problems.length === 0,
    `hidden elements are kept visible and no global guard exists:\n  ${problems.join("\n  ")}`,
  );
});

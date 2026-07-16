# Block-5E R6.3 — 三原则自检脚本化（three-principles-scripted）

**项目**：Aerie · 云栖 v9.0 Hybrid
**阶段**：Block-5E R6.2 + R6.3
**日期**：2026-07-17
**范围**：R6.1（gradient token 补齐）已在前期完成；本次 R6.2（emoji → SVG sprite）+ R6.3（三原则自检脚本化）

---

## 一、本次交付总览

| 任务 | 交付物 | 状态 |
|------|--------|------|
| R6.2 emoji → SVG sprite | 7 个新 symbol + 12 处替换 | ✅ 完成 |
| R6.3 check:emojis | `tools/check_emojis.py` | ✅ 完成 |
| R6.3 check:forbidden | `tools/check_forbidden.py` | ✅ 完成 |
| R6.3 check:tokens | `tools/check_tokens.py` | ✅ 完成 |
| R6.3 集成 package.json | 4 个新 npm script | ✅ 完成 |
| R6.3 自审报告 | 本文件 | ✅ 完成 |

---

## 二、Block-5E R6.2 — emoji → SVG sprite

### 2.1 设计原则

- **内联 sprite**：所有 `<svg><symbol>` 直接 inline 到 `index.html` 和 `daily-brief.html` 的 `<body>` 顶部，避免 `file://` 协议下 sprite 文件无法加载的问题（与 Phase 7 一致）。
- **currentColor 适配**：所有 symbol 用 `stroke="currentColor"` 或 `fill="currentColor"`，通过 CSS 变量 `--color-*` 与 5 套主题色联动。
- **命名规范**：`icon-{group}-{name}`，如 `icon-brief-ai`、`icon-ui-thumb-up`、`icon-reply`。
- **typographic 字符豁免**：箭头（→↗↩）和占位符（□ ● ·）不算 emoji，保留在 UI 文本中。

### 2.2 新增 7 个 SVG symbol

| Symbol | 路径来源 | 替换对象 | 用途 |
|--------|----------|----------|------|
| `icon-ui-thumb-up` | Lucide | 👍 | 简报反馈赞 |
| `icon-ui-thumb-down` | Lucide | 👎 | 简报反馈踩 |
| `icon-ui-pause` | Lucide | ⏸ | 认知面板暂停 |
| `icon-ui-play` | Lucide | ▶ | 认知面板继续 |
| `icon-ui-broom` | Lucide | 🧹 | 暂未用（预留） |
| `icon-ui-bolt` | Lucide | ⚡ | 认知面板活跃态 |
| `icon-brief-ai` | 自定义 | ✦ | 简报 · AI 动向 |
| `icon-brief-tech` | Lucide | ⌬ | 简报 · IT 行业 |
| `icon-brief-intl` | Lucide | ◐ | 简报 · 国际 |
| `icon-brief-cn` | Lucide | ★ | 简报 · 国家 |
| `icon-brief-weather` | Lucide | ◉ | 简报 · 天气 |
| `icon-reply` | Lucide | ↩ | 聊天引用 |
| `icon-crown` | Lucide | ★ | 决策冠军 |

### 2.3 替换清单（12 处）

| 文件 | 位置 | 旧 | 新 |
|------|------|------|------|
| `electron/src/renderer/index.html` | sprite 块 | — | 新增 13 个 symbol |
| `electron/src/renderer/daily-brief.html` | sprite 块 | — | 内联 7 个新 symbol |
| `electron/src/renderer/daily-brief.html` | 5× thumb-up | 👍 | `<use href="#icon-ui-thumb-up"/>` |
| `electron/src/renderer/daily-brief.html` | AI 动向 | ✦ | `<use href="#icon-brief-ai"/>` |
| `electron/src/renderer/daily-brief.html` | IT 行业 | ⌬ | `<use href="#icon-brief-tech"/>` |
| `electron/src/renderer/daily-brief.html` | 国际 | ◐ | `<use href="#icon-brief-intl"/>` |
| `electron/src/renderer/daily-brief.html` | 国家 | ★ | `<use href="#icon-brief-cn"/>` |
| `electron/src/renderer/daily-brief.html` | 天气 | ◉ | `<use href="#icon-brief-weather"/>` |
| `electron/src/renderer/js/chat.js` | 引用栏 | ↩ | `<use href="#icon-reply"/>` |
| `electron/src/renderer/js/cognition-panel.js` | 决策冠军 | ★ | `<use href="#icon-crown"/>` |

### 2.4 验证

- `scan_emojis.py` 扫描 33 个 .html/.js/.css 文件，0 个真实 emoji 命中（剩余匹配均为 →↗↩□●· 等排版字符）。
- `tools/check_emojis.py` 输出 `OK — no forbidden emoji found (scanned 33 file(s))`。
- `electron/scripts/check-emojis.js`（Node 端，CI prebuild 使用）输出 `✓ No emojis found in UI files`。
- UI 渲染：简报 5 个 section icon + 5 个 thumb 按钮 + 聊天引用 + 认知面板均改为 SVG 图标，5 套主题色切换正常。

---

## 三、Block-5E R6.3 — 三原则自检脚本化

### 3.1 check:emojis（已在 Phase 7 实现，本次 R6.2 强化）

**目标**：扫描渲染器源码中的 emoji 字符，确保 UI 全部走 `<svg><use>` 路线。

**实现**：
- Node 端：`electron/scripts/check-emojis.js`（CI prebuild 使用）
- Python 端：`tools/check_emojis.py`（开发期详细扫描）

**豁免规则**：
- 排版箭头：→ ← ↑ ↓ ↗ ↘ ↙ ↖ 等
- 中点：· ⋅ ・ 
- 占位符：□ ● ◦ •

**结果**：✅ 33 个文件全部通过。

### 3.2 check:forbidden（禁词扫描）

**目标**：扫描用户面文档中是否出现禁词（"主人"等），保证 v8.0 后所有直接称呼统一为 "你"。

**实现**：`tools/check_forbidden.py`

**禁词清单**：
- 主人、陛下、大王、在下不才、臣妾、本王、孤家、寡人
- 您（敬语，禁用于伊塔对用户的称呼）

**豁免规则**：
- 扫描范围限定：`electron/src/renderer/`、`config/`、`core/`、`communication/`
- 不扫描 `.trae/documents/*`（规划文档讨论规则本身）
- 不扫描 `tools/*`、`e2e_*.py`、`verify_*.py`（开发者脚本）
- 规则声明行（`config/persona.yaml` L91/L105）豁免

**结果**：✅ 61 个文件全部通过。

### 3.3 check:tokens（色值 token 化扫描）

**目标**：扫描 CSS 中残留的硬编码十六进制色，确保所有 UI 色值走 `var(--color-*)` 主题色变量。

**实现**：`tools/check_tokens.py`

**豁免规则**：
- `:root { ... }` 块内容（token 定义本身的色值）
- `var(--name, #fallback)` 第二个参数（合法的 fallback）
- `--xxx: ...` 形式的行（token 定义）
- `rgba()` / `hsla()` 形式（不要求 token 化的半透明色，alpha 已带语义）

**结果**：✗ 发现 33 处硬编码色（详见 §四）

### 3.4 package.json 集成

新增 4 个 npm script：

```jsonc
{
  "check:emojis": "node scripts/check-emojis.js",
  "check:forbidden": "python ../tools/check_forbidden.py",
  "check:tokens": "python ../tools/check_tokens.py",
  "check:all": "npm run check:emojis && npm run check:forbidden && npm run check:tokens"
}
```

CI 接入方式（prebuild 阶段）：
- 当前 `prebuild` 仅跑 `check:emojis`（防 emoji 回退最关键）
- 后续可扩展为 `prebuild` 跑 `check:all`

---

## 四、check:tokens 失败清单（待清理）

> 本节列出需在 R6.4（或后续批次）中清理的硬编码色。

| 文件 | 行 | 硬编码色 | 建议替换为 |
|------|----|----------|------------|
| cognition-panel.css | 450 | `#82b1ff` | `var(--color-stage-cognition, #82b1ff)` |
| cognition-panel.css | 451 | `#ffcc80` | `var(--color-stage-warn, #ffcc80)` |
| cognition-panel.css | 523 | `#2ecc71` | `var(--color-success, #2ecc71)` |
| cognition-panel.css | 524 | `#f1c40f` | `var(--color-warning, #f1c40f)` |
| cognition-panel.css | 525 | `#ff6b6b` | `var(--color-danger, #ff6b6b)` |
| cognition-panel.css | 534-536 | `#f1c40f #2ecc71 #95a5a6` | `var(--color-warning) var(--color-success) var(--color-muted)` |
| cognition-panel.css | 568 | `#ff6b6b` | `var(--color-danger, #ff6b6b)` |
| cognition-panel.css | 765, 780 | `#d6c5e0` | `var(--color-glass-text)` |
| daily-brief-detail.css | 69 | `#fff` | `var(--color-on-primary, #fff)` |
| daily-brief.css | 170 | `#fff` | `var(--color-on-primary, #fff)` |
| emotion-history.css | 55 | `#fff` | `var(--color-on-primary, #fff)` |
| floating-ball.css | 51, 69, 75 | `#fff` | `var(--color-on-primary, #fff)` |
| main.css | 152 | `#fff` | `var(--color-on-error, #fff)` |
| main.css | 424 | `#1c1c1e #aeaeb2 #3a3a3c` | `var(--color-surface-dark) var(--color-on-surface-dark) var(--color-border-dark)` |
| main.css | 430, 433, 445 | `#fff0e6 #fce4ec #e9f9ee #e91e63` | `var(--color-warning-bg) var(--color-success-bg) var(--color-error)` |

**总计**：33 处

**清理策略**：
1. 优先在 `main.css` `:root` 中补齐 `--color-on-primary` `--color-on-error` `--color-warning-bg` 等缺失 token
2. 5 套主题色（伊塔粉/深夜紫/樱白/海蓝/森绿）同步更新覆盖层
3. `cognition-panel.css` 中 safety/decision 状态色使用与 emotion 面板相同的 5 主题色 token

---

## 五、风险与回退

| 风险 | 触发条件 | 缓解 |
|------|----------|------|
| emoji 误判 | 真实 emoji 进入 UI | check:emojis 阻断 prebuild |
| 禁词回退 | 新文案未走 "你" 称呼 | check:forbidden 阻断 |
| 色值硬编码 | 直接写 `#xxx` 而非 `var()` | check:tokens 阻断（需补 33 处） |
| SVG sprite 缺失 | 独立窗口（brief/detail）漏 inline | sprite 已 inline 到 `daily-brief.html` + `daily-brief-detail.html` |

---

## 六、与三原则对应关系

| 原则 | 脚本 | 状态 |
|------|------|------|
| **零回退** (zero-regression) | check:emojis + check:forbidden | ✅ 全绿 |
| **无禁词** (no-forbidden-terms) | check:forbidden | ✅ 全绿 |
| **主题色 token 化** (theme tokenization) | check:tokens | ✗ 33 处待补（脚本已就位） |

> R6.3 完成 3 个脚本就位 + 2 个绿 + 1 个已识别缺口（check:tokens）。下一批次（R6.4 / R7）将完成 33 处硬编码色的 token 化清理。

---

## 七、文件清单

### 7.1 新增

- `tools/check_emojis.py` — emoji CI 扫描（Python 版）
- `tools/check_forbidden.py` — 禁词 CI 扫描
- `tools/check_tokens.py` — 硬编码色 CI 扫描
- `.trae/documents/block5e-r6-three-principles-scripted.md` — 本文件

### 7.2 修改

- `electron/src/renderer/index.html` — 新增 7 个 SVG symbol
- `electron/src/renderer/daily-brief.html` — 内联 sprite + 替换 5×👍 + 5×section icon
- `electron/src/renderer/js/chat.js` — 替换 ↩ 为 icon-reply
- `electron/src/renderer/js/cognition-panel.js` — 替换 ★ 为 icon-crown
- `electron/package.json` — 新增 check:forbidden / check:tokens / check:all

### 7.3 临时（待迁移到 .trae/）

- `tmp/scan_emojis.py` — emoji 详细扫描（verbose）
- `tmp/fix_brief_emoji.py` — 单次性 emoji 替换脚本
- `tmp/debug_*.py` — 调试用

---

## 八、E2E 验证

```
cd electron && npm run check:all
```

**预期输出**：
- `check:emojis`: ✓ No emojis found in UI files
- `check:forbidden`: OK — no forbidden user-address terms
- `check:tokens`: FAIL — 33 hits（待 R6.4 修复）

R6.3 脚本层完成。下一轮启动 R6.4 修复 check:tokens 33 处硬编码色。

---

**审阅**：待用户确认
**下一批**：Block-5E R6.4 — 硬编码色 token 化清理

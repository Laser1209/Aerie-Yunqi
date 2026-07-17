# R7.2 简报抽屉全面重做（Brief Drawer Rebuild）

> Aerie · 云栖 — Plan
> 触发：用户连续多轮反馈"弹窗丑 / 蓝色边框 / 选变色 / logo 难看 / 展开完整数据空 / 建议重写"
> 决策：用户已确认 — 保留右侧抽屉形态 / logo 用 `assets/logo.png` / 展开完整 = 抽屉内 92vw 全屏 + 拉 `/api/brief/run`

---

## 1. Summary

把 R7.1 那个"半成品"抽屉彻底拆掉重做：换真的 `logo.png`、去所有硬编码颜色（聚焦态的 `2px solid primary` 这种会变成蓝色描边）、干掉残留 emoji `📅`、真正接通"展开完整"（抽屉变宽 + 重拉 API）、真正把反馈 POST 出去、读 persona 名字。

完成后抽屉应做到：
- 没有蓝色硬编码、focus 态用品牌 token 走主题色
- logo 实际可见（28px 圆形裁剪）
- 展开完整能拉到 8-10 条/段
- 反馈按钮点完真入库
- 和主应用完全同源（token、icon、字体、节奏一致）

---

## 2. Current State Analysis（R7.1 半成品现状）

| 文件 | 现状 | 问题 |
|------|------|------|
| `electron/src/renderer/styles/brief-drawer.css` | 420px 右侧抽屉+stagger+skeleton，结构 OK | `.brief-drawer--expanded` 样式未定义（"展开完整"点了无反应）；focus 态用 `outline: 2px solid var(--color-primary)` 是 `brand-500 #FFB6C1` 粉但部分主题是蓝色系；存在硬编码 `0, 122, 255, 0.18` |
| `electron/src/renderer/js/brief-drawer.js` | drawer 逻辑+渲染 | L68 `<img src="Aerie · 云栖.svg">` — **文件不存在**；L225 "📅" emoji 残留；L217 "伊塔"硬编码；L262 反馈按钮只 toggle class 不发请求；L313 `_showExpanded()` 只 toggle class 没数据 |
| `core/location_resolver.py` | 已就绪 | 没问题，但需要在真机重启后端验证 |
| `core/brief_fetcher.py` | `run_all(city=None)` 走 resolver | OK |
| `core/api_server.py` | `/api/brief/today` + `/api/brief/run` + `/api/brief/feedback` 都在 | OK |
| `electron/src/main.js` | 已删 3 个 BrowserWindow | OK |
| `electron/src/renderer/index.html` | 已引入新 CSS/JS | OK，但 logo `<img src="../../../Aerie · 云栖.svg">`（index.html L131 / L407）也引用了不存在的 SVG |

---

## 3. Proposed Changes

### 3.1 `electron/src/renderer/styles/brief-drawer.css` — 抽屉内观重做

**目标：扁平、丝滑、和主应用 1:1 视觉一致**

变更点：
1. **加 `--expanded` 模式样式**（最关键，用户点"展开完整"才有反应）
   - `.brief-drawer--expanded { width: 92vw; max-width: 880px; transition: width 0.42s cubic-bezier(0.16,1,0.3,1), max-width 0.42s ...; }`
   - 抽屉展开时 `body { overflow: hidden; }` 已经存在，无需重做
2. **清掉所有硬编码蓝色**：
   - L286 `box-shadow: 0 0 0 2px rgba(0, 122, 255, 0.18)` → 改用 `var(--color-primary)` 派生，建议 `box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 28%, transparent)` 兜底仍可读
   - L9 `rgba(0, 0, 0, 0.42)` 遮罩 → 改用 `var(--color-overlay, rgba(20, 20, 28, 0.42))` token
   - L34 `rgba(0, 0, 0, 0.18)` 阴影 → `var(--color-shadow-md, rgba(0,0,0,0.18))` token
   - L174 `rgba(0, 0, 0, 0.08)` 卡片 hover 阴影 → 同上
3. **focus 态**：用 `outline-color: var(--color-primary)` + `outline-offset: 1px`，不要 `2px solid var(--color-primary)` 直接硬写（不同主题下视觉粗细可能错位），改成 `2px solid color-mix(in srgb, var(--color-primary) 60%, transparent)`
4. **logo 圆形裁剪**：`.brief-drawer__logo` 现有 `border-radius: 50%` + `box-shadow: 0 0 0 1px var(--color-border-soft)` 保留，确保 22x22 像素不被拉伸
5. **骨架屏**：当前用 3 色 shimmer 已 OK，不动
6. **新增 `.brief-drawer--expanded .brief-drawer__card` 内部 8px padding 收紧**让展开后视觉更紧凑

### 3.2 `electron/src/renderer/js/brief-drawer.js` — 行为重做

**目标：解决 5 个硬伤**

变更点：
1. **L68 logo 路径**：`src="Aerie · 云栖.svg"` → `src="assets/logo.png"`，并加 `onerror` 兜底（保留现有 onerror 行为）
2. **L225 日期 emoji**：`"📅 " + date` → 用内联 SVG `<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>` 替代
3. **L217 greeting 名字硬编码**：改成读 persona
   - 增加 `async _getDisplayName()` 方法，调用 `/api/persona/summary` 取 `name` 字段，失败时 fallback `"伊塔"`
   - 缓存到 `this._displayName`，仅首次打开时请求
4. **L262 反馈按钮**：
   - 改为 `async _onThumb(section, value)`，先 toggle class 立即给视觉反馈，然后 `await api({ method: "POST", path: "/api/brief/feedback", body: { section, value, ts: Date.now() } })`
   - 失败时只 `console.warn`，不要弹错
   - 同时把"已点过"的按钮锁住（`disabled = true`），避免重复发
5. **L313 `_showExpanded()` 改名为 `_expandDrawer()`**：
   - 第一次点击：`await api({ method: "POST", path: "/api/brief/run" })` → 用返回的 `brief` 重渲染（每段 8-10 条）
   - 加 `brief-drawer--expanded` class → 抽屉变 92vw
   - 按钮文字改"收起"/用 chevron 翻转 SVG
   - 第二次点击：收起回 420px + `brief-drawer--expanded` class 移除，但**不重拉**（保持用户已看过的状态）
6. **新增状态**：`this._expanded = false`、`this._expandedData = null`

### 3.3 `electron/src/renderer/index.html` — 修 2 处错误的 logo 引用

- L131 `statusbar-logo` 的 `src="../../../Aerie · 云栖.svg"` → `src="assets/logo.png"`（renderer 自己目录的相对路径）
- L407 `about-logo` 同上
- 这是为什么你之前在 statusbar 和 about 页可能也看不到 logo 的根因

### 3.4 `electron/src/renderer/styles/main.css` — 补缺失 token

- 检查 `--color-overlay` 是否存在，若没有就在 :root 加：`--color-overlay: rgba(20, 20, 28, 0.42);` + 暗色主题覆盖
- 检查 `--color-shadow-md` 是否存在，若没有：`--color-shadow-md: 0 8px 24px rgba(0,0,0,0.12);`
- 不引入新颜色，全部用现有 token 衍生

### 3.5 不动的东西（避免过度工程）

- `core/location_resolver.py` — 已对
- `core/brief_fetcher.py` — 已对
- `core/api_server.py` — 三个 endpoint 都对
- `electron/src/main.js` — 已对
- `electron/src/renderer/index.html` 的 `<link rel="stylesheet" href="styles/brief-drawer.css">` 引用顺序不动

---

## 4. Assumptions & Decisions

| 决策 | 选择 | 理由 |
|------|------|------|
| UI 形态 | 右侧抽屉 | 用户已选"重做内部" |
| logo | `assets/logo.png` | 用户已选 |
| 展开完整 | 抽屉内 92vw + 拉 `/api/brief/run` | 用户已选；该 endpoint 已存在返回 `brief`+`markdown` |
| 反馈提交 | POST `/api/brief/feedback` | 已存在但没被调用 |
| greeting 名字 | 读 `/api/persona/summary` → `name` 字段 | persona_loader 已支持，无需新接口 |
| 抽屉展开后的卡片数 | 8-10 条/段（拉 `/api/brief/run` 返回的默认 limit） | run_all 用 `DEFAULT_LIMIT_PER_SECTION=3`，需要新参数 `limit` 或展开模式用 8 |
| 抽屉 logo 形状 | 28x28 圆角 50% | 和主应用 statusbar-logo 一致 |

**注意**：`/api/brief/run` 当前调用 `run_all()` 默认 limit=3。如果展开模式要 8 条/段，需要给 `run_all()` 加可选参数：
- `core/brief_fetcher.py` `run_all(city=None, feedback=None, limit=None)` → 把 `limit` 透传给四个 `fetch_*_news` 函数
- 不引入 LIKED_SECTION_LIMIT/DISLIKED_SECTION_LIMIT 的逻辑
- `core/api_server.py` `brief_run` 加 `?limit=8` query param

这是最小改动。否则抽屉展开后还是只看到 3 条。

---

## 5. Verification Steps

1. **三原则自检**（必须全过）：
   ```bash
   cd e:\Agent_reply\electron
   npm run check:emojis    # 确认无 📅
   npm run check:forbidden # 确认无硬编码颜色
   npm run check:tokens    # 确认无硬编码 hex
   npm run check:all       # 一把梭
   ```
2. **零回归**：
   ```bash
   cd e:\Agent_reply
   python tools/verify_zero_regression.py   # 14/14
   ```
3. **E2E pacing**：
   ```bash
   python e2e_pacing.py                     # 96/96
   ```
4. **E2E self evolve**：
   ```bash
   python e2e_self_evolve.py                # 20/20
   ```
5. **手测**（重启后端 `tools/restart.bat` 后）：
   - 打开抽屉 → 看到 `assets/logo.png` 圆形 logo（不是空）
   - 日期前是 SVG 日历图标（不是 📅）
   - "早上好，<persona 名字>" 而不是硬编码"伊塔"
   - 点某 section 的 👍 → Network 面板看到 POST `/api/brief/feedback`
   - 点底部"展开完整" → 抽屉变宽到 92vw，每段 8 条；按钮文字变"收起"
   - 切到设置 → 城市输入框填"南京" → 保存 → 重新打开简报 → 天气显示南京
   - 切到设置 → 城市清空 → 保存 → 重新打开简报 → 天气显示 IP 检测结果（不是"上海"）
6. **浏览器焦点态检查**（重要）：
   - 用 Tab 键在抽屉内导航，确认 focus ring 是品牌色（不是 Windows 蓝色）

---

## 6. File Touch List

| 路径 | 行为 | 预计行数变化 |
|------|------|-------------|
| `electron/src/renderer/styles/brief-drawer.css` | 编辑 | +40 / -20 |
| `electron/src/renderer/js/brief-drawer.js` | 编辑 | +60 / -25 |
| `electron/src/renderer/index.html` | 编辑 2 处 | ±2 |
| `electron/src/renderer/styles/main.css` | 编辑（补 token） | +10 |
| `core/brief_fetcher.py` | 编辑 `run_all` 加 `limit` 参数 | +8 |
| `core/api_server.py` | 编辑 `brief_run` 加 query param | +3 |
| 总计 | 6 个文件 | ~+120 / -45 |

---

## 7. Out of Scope

- 不改 `/api/brief/feedback` 端点本身
- 不改 `location_resolver` 逻辑
- 不改主题文件（`themes/*.css`）— 改 token 在 main.css 即可
- 不引入新依赖（无 npm install）
- 不做"全屏独立窗口"展开（用户已选抽屉内 92vw）
- 不改 logo 图像本身（不重画）

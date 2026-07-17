# 简报 UI/UX 整改 — IP 定位 + 抽屉 + 自绘标题栏 + 动效

## Summary

把"3 套蓝框简报 UI + 硬编码上海"统一成"1 套主应用内右抽屉 + IP 自动定位 + 自绘品牌栏 + 丝滑动效"。删除独立 `BrowserWindow`(popup + detail)，改用主应用内的 `.brief-drawer` 滑入组件；城市来源先 IP 定位（`mcp_Bai_Du_Di_Tu.map_ip_location`），再读设置页手动覆盖，最后兜底默认城市。配色全部走 `main.css :root` 的 var(--color-*) token，扁平化+扁平阴影+丝滑 cubic-bezier 过渡。

## Current State (Phase 1 探查所得)

| 现状 | 文件 | 问题 |
|---|---|---|
| 右下小弹窗 360×640 | `electron/src/renderer/daily-brief-popup.html` + `main.js:283-317 createBriefPopupWindow` | 蓝框、logo 丑、独立进程 |
| 大窗口 1280×800 | `electron/src/renderer/daily-brief-detail.html` + `main.js:319-359 createBriefDetailWindow` | 蓝框、点开数据空（query.date 没用到）|
| 主应用内 iframe | `index.html:699-701` `<iframe id="brief-frame" src="daily-brief.html">` + `app.js:175-184` | 入口隐藏、风格与主应用脱节 |
| 城市硬编码 | `core/brief_fetcher.py:343, 403` `city: str = "上海"` | 没有 IP 定位/没有用户覆盖 |
| IPC 简报通道 | `main.js:684-736` 6 个 `brief:*` handler | 全部绑到独立窗口，全要删 |
| 拖拽区 CSS | `main.css` 已有 `.titlebar` + `data-tauri-drag-region` 模式 | 但 brief 页面没用 |
| IP 定位工具 | `mcp_Bai_Du_Di_Tu.map_ip_location` 已存在 | 没人调用 |

## Proposed Changes

### P1 · 城市来源 (IP 自动 + 手动覆盖)

**新文件** `e:\Agent_reply\core\location_resolver.py`
- `def resolve_city() -> str`：先读 `settings.yaml.weather.city`，空则调 `map_ip_location`（无参时 Baidu 用本机 IP），解析 `address_detail.city`，最后兜底 "上海"
- 解析容错：`address_detail.city` 缺失则降级到 `content.address` 正则提取
- 缓存：结果写 `data/cache/city.json`，TTL 24h，避免每次简报都打 IP API
- 导出 `get_weather_for_brief()` 包装：内部 `fetch_weather(resolve_city())`

**改** `e:\Agent_reply\core\brief_fetcher.py`
- `run_all(city: str = None)` 签名改 None，内部 `from .location_resolver import resolve_city`
- 删 `fetch_weather` 的 `city="上海"` 硬编码（仍保留参数向后兼容）
- `run_all` 改 `city = city or resolve_city()`

**改** `e:\Agent_reply\config\persona.yaml`（已在 L17 加载位置，不动）
**改** `e:\Agent_reply\config\settings.yaml`：新增字段
```yaml
weather:
  city: ""        # 留空 = IP 自动定位
  auto_detected: ""  # 系统记录上一次自动定位结果
```

**改** `e:\Agent_reply\electron\src\renderer\settings.html` + `settings.js`
- "我的位置 / My Location" 区块：input + 城市下拉提示（IP 自动时显示 "📍 已自动检测: <city> · 点击重测"）
- 保存时 PUT `/api/config/yaml?file=settings.yaml`

### P2 · 抽屉组件（删 popup+detail+iframe 入口）

**新文件** `e:\Agent_reply\electron\src\renderer\js\brief-drawer.js`
- 单例 `class BriefDrawer`
- `open()`：移入 `translateX(0)`，加 backdrop 黑色 40% 透明，`body` 加 `overflow:hidden` 锁滚动
- `close()`：移出 `translateX(100%)`，淡出 backdrop
- `loadData()`：调 `/api/brief/today`，渲染 5 个 section + 天气城市
- IPC 替代：主应用内 `bus.emit('brief:open')` / `bus.on('brief:close')`
- 拖拽区：顶栏 `-webkit-app-region: drag`，关闭按钮 `no-drag`

**新文件** `e:\Agent_reply\electron\src\renderer\styles\brief-drawer.css`
- `.brief-drawer` 右侧 420px 宽，最大占屏 90vw，背景 `var(--color-bg-50)`，圆角左 16px
- `.brief-drawer__backdrop` 全屏 fixed，半透明黑色，z-index 高于 chat
- `.brief-drawer__bar` 36px 高 = 主应用 statusbar 高度的镜像，左 logo + 中标题 + 右关闭（24px 圆形按钮）
- `.brief-drawer__body` padding 16px
- 入场：`transform: translateX(100%) → 0`，`transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1)`，backdrop `transition: opacity 0.3s ease`
- 卡片：背景 `var(--color-card-bg)`，border `1px solid var(--color-border-soft)`，圆角 12px，hover 时 `transform: translateY(-2px) scale(1.01)` + 阴影加深，过渡 0.25s

**改** `e:\Agent_reply\electron\src\renderer\index.html`
- 删 `<iframe id="brief-frame" ...>` (L699-701)
- 新增 `<aside id="brief-drawer" class="brief-drawer" hidden>...</aside>` + `<div id="brief-backdrop" class="brief-drawer__backdrop" hidden>`
- `<link rel="stylesheet" href="styles/brief-drawer.css">`
- `<script src="js/brief-drawer.js">`

**改** `e:\Agent_reply\electron\src\renderer\js\app.js`
- 删 `briefFrame` 整段 (L174-195)
- 新增 `import { briefDrawer } from './brief-drawer.js'`
- `bus.on('brief:open', () => briefDrawer.open())` / `'brief:close'` 同理
- 顶栏"今日简报"按钮 `onclick` 改派发 `bus.emit('brief:open')`

**改** `e:\Agent_reply\electron\src\main.js`
- 删 `createBriefPopupWindow` / `createBriefDetailWindow` / `showBriefPopup` (L283-363)
- 删 `briefPopupWindow` / `briefDetailWindow` 变量及 `closed` 监听
- 删 IPC handlers: `brief:open-detail`, `brief:hide`, `brief:detail-close`, `brief:export`, `brief:chat` (L684-736)
- 删 `brief:show` IPC 监听（app.js 还在用则改成 bus 事件）

### P3 · UI/UX 动效（丝滑/扁平/生动）

**改** `e:\Agent_reply\electron\src\renderer\styles\brief-drawer.css`
- 卡片入场：每张 section 卡片 `animation: briefCardIn 0.5s cubic-bezier(0.16, 1, 0.3, 1) both`
- `@keyframes briefCardIn { from { opacity: 0; transform: translateY(12px) } to { opacity: 1; transform: translateY(0) } }`
- stagger：`animation-delay: calc(var(--i) * 60ms)`，每张卡 `--i` 由 JS 注入
- 点赞按钮 hover 缩放 1.1，active 缩放 0.95
- 链接"展开完整" 加底色 underline transition：`background-size: 0 1px → 100% 1px` 0.3s
- 图标：所有用 SVG 不用 emoji，hover 旋转 8°，0.3s

**改** `e:\Agent_reply\electron\src\renderer\js\brief-drawer.js`
- 渲染时按 section 顺序注入 `el.style.setProperty('--i', i)`
- 关按钮 hover 旋转 90°，0.2s cubic-bezier
- 加载数据时 skeleton 骨架屏，3 个圆点 0.8s 循环呼吸

### P4 · 清理

**删** 整个 `e:\Agent_reply\electron\src\renderer\daily-brief-popup.html`
**删** 整个 `e:\Agent_reply\electron\src\renderer\daily-brief-popup.js`
**删** 整个 `e:\Agent_reply\electron\src\renderer\daily-brief.html`
**删** 整个 `e:\Agent_reply\electron\src\renderer\daily-brief.js`
**删** 整个 `e:\Agent_reply\electron\src\renderer\daily-brief-detail.html`
**删** 整个 `e:\Agent_reply\electron\src\renderer\daily-brief-detail.js`
**删** 整个 `e:\Agent_reply\electron\src\renderer\styles\daily-brief.css`
**删** 整个 `e:\Agent_reply\electron\src\renderer\styles\daily-brief-detail.css`

**改** `e:\Agent_reply\core\brief_fetcher.py` L562-700 `render_html()` —— 这是 detail 窗口用的，可以整体删
**改** `e:\Agent_reply\core\api_server.py` 删 `/api/brief/export` (如不再使用)

## Assumptions & Decisions

1. **不重做主应用配色** — 用户答"frame:false 自绘"而非"主应用跟着改"，所以主应用配色不变，只动简报相关
2. **logo 不重画** — 暂用主应用同样的 `Aerie · 云栖.svg`，但缩小到 24px 圆形，与主应用 statusbar 一致；用户后续要换再换
3. **不引入新依赖** — IP 定位走 MCP（已配），动画用纯 CSS
4. **下拉抽屉宽度 420px** — 不抢主对话区域，但够 5 段 + 天气 + 评论
5. **保留 `weather.city` 字段作为 override** — 即便 IP 失败也能跑

## Verification (实施完后跑)

1. `python tools\diag_f1_f4.py` — F1 应仍 12 条，且 `city` 不再硬编码
2. 手动 `curl http://127.0.0.1:7890/api/brief/today` — 看 weather.city 字段非"上海"或为自动定位值
3. 启动 Electron → 点主应用顶栏"今日简报"按钮 → 右侧抽屉 400ms 滑入
4. 抽屉内 5 section 数据齐全，天气城市正确
5. 点抽屉外灰色区 → 抽屉滑出
6. 按 Esc → 抽屉关闭
7. `npm run check:emojis / check:forbidden / check:tokens` — 0 命中
8. `python verify_zero_regression.py` — 14/14
9. `python e2e_pacing.py` — 96/96
10. `python e2e_self_evolve.py` — 20/20

## File list (实施时全部要改/建/删)

| 动作 | 路径 |
|---|---|
| 新建 | `e:\Agent_reply\core\location_resolver.py` |
| 新建 | `e:\Agent_reply\electron\src\renderer\js\brief-drawer.js` |
| 新建 | `e:\Agent_reply\electron\src\renderer\styles\brief-drawer.css` |
| 改 | `e:\Agent_reply\core\brief_fetcher.py` (硬编码 → resolve_city) |
| 改 | `e:\Agent_reply\core\api_server.py` (删 /api/brief/export) |
| 改 | `e:\Agent_reply\config\settings.yaml` (加 weather.city) |
| 改 | `e:\Agent_reply\electron\src\renderer\index.html` (iframe → drawer 容器) |
| 改 | `e:\Agent_reply\electron\src\renderer\js\app.js` (briefFrame 段 → bus 事件) |
| 改 | `e:\Agent_reply\electron\src\renderer\settings.html` (加城市输入) |
| 改 | `e:\Agent_reply\electron\src\renderer\js\settings.js` (加城市保存) |
| 改 | `e:\Agent_reply\electron\src\main.js` (删 3 个窗口创建 + 5 个 IPC) |
| 删 | `e:\Agent_reply\electron\src\renderer\daily-brief*.{html,js}` 6 个 |
| 删 | `e:\Agent_reply\electron\src\renderer\styles\daily-brief*.css` 2 个 |

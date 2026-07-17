# 简报抽屉视觉重做 · Liquid Glass（Plan 模式 v1）

> 用户诉求：保留右侧抽屉形态 → 重做视觉为「毛玻璃半透明 / Liquid Glass」 → Logo 沿用 `assets/logo.png`
> 数据通路（城市定位、展开完整）已在 R7.1 / R7.2 修好，本计划**只动视觉与少量动效**。

---

## 0. 范围与非范围

**做**
- 把 `brief-drawer.css` 完全重写成液态玻璃调性
- 调整 `brief-drawer.js` 内 _renderXxx 的 DOM 结构（去掉"卡片化"痕迹，改成"玻璃行 + 内发光"）
- 在 `index.html` 引入新 CSS 引用（无需新增 link，已存在）
- 顺手修两处 R7.2 残留：城市手动编辑入口不显眼、展开后空态文案

**不做**
- 不改抽屉形态（保留右侧抽屉）
- 不动 Logo（沿用 `assets/logo.png`）
- 不重写后端、不改 API
- 不动其他模块（主应用、聊天、情绪面板等）
- 不引入新依赖（不装 GSAP / Framer Motion）

---

## 1. 当前状态

- `e:\Agent_reply\electron\src\renderer\styles\brief-drawer.css` —— R7.2 版本，仍是"圆角白卡 + drop-shadow"形态，看着像普通网页
- `e:\Agent_reply\electron\src\renderer\js\brief-drawer.js` —— R7.2，DOM 结构正常，expand 走 `/api/brief/run?limit=8`，refresh 走 `/api/brief/today`
- `e:\Agent_reply\core\location_resolver.py` —— 已实现，优先级 manual → cache → IP → fallback
- 主题色 token 已齐：`--color-primary` / `--color-bg` / `--color-text-muted` / `--color-border-soft` / `--color-overlay` 都在 `themes/yita-pink.css` 等文件里

---

## 2. 视觉目标（Liquid Glass 调性板）

| 维度 | 当前（R7.2） | 目标（Liquid Glass） |
|---|---|---|
| 背景 | `var(--color-bg)` 实色 | `rgba(255,255,255,0.55)` + `backdrop-filter: blur(24px) saturate(160%)` |
| 边框 | 1px `var(--color-border-soft)` | 1px `rgba(255,255,255,0.45)` + 内层 1px 主题色 5% 染色 |
| 阴影 | `-10px 0 36px rgba(0,0,0,0.18)` | 删掉 drop shadow，改成 `inset 0 1px 0 rgba(255,255,255,0.5)` 高光 |
| 圆角 | 18px | 22px |
| 卡片 | 白底 + 1px 边 + 阴影 | 无背景，1px 半透边 + 0.5px 顶部高光线 |
| 动效曲线 | `cubic-bezier(0.16, 1, 0.3, 1)` | 改为 `cubic-bezier(0.34, 1.32, 0.64, 1)`（带过冲的 spring） |
| 字体 | 13px / 11px | 14px / 12px，更柔（行高 1.6） |

主题色适配：玻璃本身偏白，但用 `--color-primary` 做顶部 1px 高光和 hover 时的内发光，5 个主题都能套。

---

## 3. 改动清单

### 3.1 完全重写 [brief-drawer.css](file:///e:/Agent_reply/electron/src/renderer/styles/brief-drawer.css)

**关键改动：**
1. `.brief-drawer` 背景改 `rgba(255,255,255,0.55)` + `backdrop-filter: blur(24px) saturate(160%)`
2. 删除 `box-shadow: -10px 0 36px ...` 改成 `box-shadow: inset 0 1px 0 rgba(255,255,255,0.5), inset 1px 0 0 rgba(255,255,255,0.3)`
3. 顶部加 1px 主题色高光（`background: linear-gradient(180deg, var(--color-primary) 0%, transparent 1px)`）
4. `.brief-drawer__card` 改无背景，1px `rgba(255,255,255,0.5)` 边 + 顶部 0.5px `var(--color-primary)` 高光
5. 入场动画：stagger 60ms，曲线 `cubic-bezier(0.34, 1.32, 0.64, 1)` 持续 0.48s
6. hover 卡片：整片浮起 1px（`translateY(-1px)`），加 8% 主题色内发光（`box-shadow: inset 0 0 0 1px var(--color-primary)`，alpha 8%）
7. 反馈行（点赞按钮）：默认 `rgba(255,255,255,0.4)` 玻璃面，激活态用主题色填充
8. footer 区：玻璃条 + 顶部 1px 高光

**Win11 兜底**：检测 `backdrop-filter` 不支持时 fallback 到 `background: var(--color-bg)` 实色 + 加 1px 边保留层次。

### 3.2 微调 [brief-drawer.js](file:///e:/Agent_reply/electron/src/renderer/js/brief-drawer.js)

- `_renderSection` 把 `brief-drawer__card` 改成 `brief-drawer__row` 类名（语义从"卡片"改"行"），结构保持
- `_renderGreeting` 加一行小灰字显示当前定位城市（来自 `data.weather.city`），让用户看到定位生效
- `_renderError` 改成玻璃风格的"全行重试"按钮，不要红色错误块
- stagger 入场：每个 card 设置 `style.setProperty("--brief-i", String(idx))`，CSS 端用 `animation-delay: calc(var(--brief-i) * 60ms)` 触发
- 顶部 brand bar 加一个"重定位"小图标（点击触发 `GET /api/location/refresh` 把 IP 缓存清掉重抓，**前提是这个接口存在**——不存在就降级成"打开设置"）

### 3.3 城市手动入口

- 在 `brief-drawer__bar` 右侧"刷新"按钮旁加一个 📍 风格的 SVG pin 按钮（用 inline SVG，不用 emoji）
- 点击 → 弹出小输入框（玻璃风格 inline popover）让用户改城市，写入 `settings.yaml.weather.city`
- 后端需要新接口 `POST /api/location/set` 接受 `{city: str}` 并写入 settings.yaml + 清缓存
- **若新增后端接口超出范围**，降级为：pin 按钮直接打开设置 tab（已有路径）

### 3.4 兜底：定位状态显示

在 `_renderWeather` 上方加一行极小灰字："📍 [city] · 定位中" / "📍 [city] · 已设"
- 数据来源：API 返回的 `data.weather.city`
- 24h 内未变 → "已设"
- 否则 → "自动（可点右上角📍改）"

---

## 4. 验证步骤（按顺序）

1. **三原则自检**
   - `npm run check:emojis` —— 玻璃风用的是 SVG，不是 emoji
   - `npm run check:forbidden` —— 不引入新术语
   - `npm run check:tokens` —— 所有新颜色必须是变量；新加的玻璃 alpha 色写进 `:root` 作为 `--glass-bg-1/2/3` token
2. **零回归**
   - `python verify_zero_regression.py` —— 14/14
3. **E2E pacing + self-evolve**
   - `python e2e_pacing.py` —— 96/96
   - `python e2e_self_evolve.py` —— 20/20
4. **手动验收**
   - 启动 launcher-user.bat + Electron
   - 等 8s 自动弹出抽屉
   - 截图：默认态、hover 卡片、点击 📍 改城市、点击"展开完整" → 验证 8 条数据
   - 切换 5 个主题：forest-green / midnight-purple / ocean-blue / sakura-white / yita-pink —— 每个主题玻璃效果都成立
   - 切到 Win10 / 无 backdrop-filter 环境验证 fallback

---

## 5. 风险与决策

| 风险 | 缓解 |
|---|---|
| Win10 旧版不支持 backdrop-filter | `@supports not (backdrop-filter: blur(1px))` 兜底到实色 |
| 玻璃在深色主题上对比度差 | midnight-purple 主题下玻璃 alpha 改 0.28 + 加 1px 白色 30% 边 |
| Spring 曲线在低端机卡 | 改回 ease-out，持续时间从 0.48s 压到 0.32s |
| 改类名（card→row）影响其他样式 | 仅改 .brief-drawer 内样式，主应用不引用 .brief-drawer__card，无外溢 |

---

## 6. 决策点（不需要你再回答的）

- 抽屉形态：**右侧抽屉**（已选）
- 视觉调性：**毛玻璃半透明**（已选）
- Logo：**沿用现有**（已选）
- 城市定位策略：**保留 R7.1 三级优先级** + 抽屉内加 pin 入口
- 范围：**只动 brief-drawer 相关文件**，不外溢

---

## 7. 实施后产物

- [brief-drawer.css](file:///e:/Agent_reply/electron/src/renderer/styles/brief-drawer.css) 完全重写（≈ 280 行）
- [brief-drawer.js](file:///e:/Agent_reply/electron/src/renderer/js/brief-drawer.js) 微调（≈ 30 行新增/修改）
- 若新增 location 接口：[api_server.py](file:///e:/Agent_reply/core/api_server.py) + 1 个端点
- 截图：5 主题 × 3 状态 = 15 张视觉验收图（存 `.trae/documents/brief-glass-screenshots/`）
- 计划文件归档：`.trae/documents/plan-brief-drawer-liquid-glass.md`

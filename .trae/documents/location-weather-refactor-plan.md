---
title: 定位与天气系统重构实施计划
status: pending-review
tags:
  - plan
  - electron
  - location
  - weather
  - obsidian
created: 2026-07-20
---

# 定位与天气系统重构实施计划

> [!summary]
> 本计划用于重构 Aerie · 云栖的定位与天气模块：保证手动城市不会被自动定位覆盖；自动定位失败时提供友好兜底；定位成功后拉取实时天气与预报结构；每日简报界面提供现代化城市选择体验；并通过后端测试、静态检查和 Electron 端到端验证确认功能真实可用。

## 1. Summary

本次改造围绕每日简报中的天气/定位链路展开，覆盖：

- 后端定位解析：手动城市优先、IP 自动定位、缓存、兜底城市。
- 天气服务：统一天气数据结构，包含实时天气、来源、错误信息、`forecast: []` 预报字段。
- API：新增定位状态、城市搜索、当前天气接口；增强城市保存接口，使保存后立即刷新天气并更新当日简报缓存。
- 前端：重构每日简报城市选择器 UI，支持搜索/候选城市/恢复自动定位/加载与错误状态。
- 验证：以 `tests/test_location_weather.py` 为核心回归测试，并补充 Electron CDP 端到端检查。

## 2. Current State Analysis

### 2.1 后端定位现状

- [location_resolver.py](file:///e:/Agent_reply/core/location_resolver.py) 已有定位解析逻辑：
  - `resolve_location()` / `resolve_location_async()` 按 `manual -> cache -> ip -> fallback` 决策。
  - `clear_city_cache()` 已使用 [paths.py](file:///e:/Agent_reply/core/paths.py) 的 `city_cache_path()`。
  - 手动城市来自 `config.persona_loader.load_settings().weather.city`。
- [paths.py](file:///e:/Agent_reply/core/paths.py) 已提供：
  - `data_dir()`
  - `cache_dir()`
  - `briefs_dir()`
  - `city_cache_path()`
- 问题：
  - [location_resolver.py](file:///e:/Agent_reply/core/location_resolver.py#L167-L171) 引用了尚不存在的 `core.weather_service`。
  - 缺少保存手动城市的集中函数，API 当前直接调用 `save_settings()`。

### 2.2 天气与简报缓存现状

- [brief_fetcher.py](file:///e:/Agent_reply/core/brief_fetcher.py#L343-L388) 当前 `fetch_weather()` 直接调用 `mcp_Bai_Du_Di_Tu.map_weather`，失败时返回 stub。
- [brief_fetcher.py](file:///e:/Agent_reply/core/brief_fetcher.py#L418-L504) `run_all()` 同步解析城市后并发抓取天气与新闻。
- [brief_fetcher.py](file:///e:/Agent_reply/core/brief_fetcher.py#L507-L539) `save_brief()` / `load_brief()` 使用模块级 `_DATA_BRIEFS_DIR`，未接入 `AERIE_DATA_DIR`。
- 问题：
  - 缺少 `core/weather_service.py`。
  - 缺少 `brief_fetcher.update_brief_weather(date_str, weather)`。
  - 当天简报已有缓存时，更新城市后 `GET /api/brief/today` 仍可能返回旧天气。

### 2.3 API 现状

- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L2438-L2446) `PUT /api/settings` 保存 `weather.city` 时不清定位缓存。
- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L2605-L2634) `POST /api/location/set` 当前只保存城市并删除相对路径 `data/cache/city.json`。
- [api_server.py](file:///e:/Agent_reply/core/api_server.py#L3100-L3168) `GET /api/brief/today` 命中当日缓存后直接返回，不刷新天气。
- 问题：
  - `/api/location/set` 不支持 `AERIE_DATA_DIR` 缓存路径。
  - `/api/location/set` 不返回天气。
  - `/api/location/set` 不更新当日简报缓存。
  - 缺少 `/api/location/status`、`/api/location/search`、`/api/weather/current`。

### 2.4 前端现状

- [brief-drawer.js](file:///e:/Agent_reply/electron/src/renderer/js/brief-drawer.js#L107-L120) 当前城市弹窗是简单输入框。
- [brief-drawer.js](file:///e:/Agent_reply/electron/src/renderer/js/brief-drawer.js#L290-L330) 保存城市后调用 `this.refresh()`，可能因后端简报缓存返回旧天气。
- [brief-drawer.js](file:///e:/Agent_reply/electron/src/renderer/js/brief-drawer.js#L732-L751) 天气卡片只显示 `已设/自动`，无法区分 `manual/cache/ip/fallback/error/stub`。
- [brief-drawer.css](file:///e:/Agent_reply/electron/src/renderer/styles/brief-drawer.css#L720-L842) 位置弹窗样式偏轻量，缺少现代城市选择器所需的搜索、候选、状态、加载与错误样式。
- [settings.js](file:///e:/Agent_reply/electron/src/renderer/js/settings.js#L367-L386) 设置页仍通过 `PUT /api/settings` 保存 `weather.city`。

### 2.5 测试现状

- [test_location_weather.py](file:///e:/Agent_reply/tests/test_location_weather.py) 已覆盖：
  - `AERIE_DATA_DIR` 下城市缓存路径。
  - 手动城市优先于 IP 缓存。
  - 清空手动城市后走自动定位。
  - 天气服务 stub 标准结构。
  - 更新当日 brief weather 缓存。
  - `/api/location/set` 返回天气并更新缓存。
- 当前测试仍需实现缺失模块/函数后通过。

## 3. Proposed Changes

### 3.1 `core/weather_service.py`：新增统一天气服务

**文件**：`e:/Agent_reply/core/weather_service.py`

**What**

新增天气服务模块，提供：

- `normalize_weather(city, result, location)`：将 MCP 返回标准化。
- `fallback_weather(city, location, error="")`：MCP 不可用或失败时返回友好 stub。
- `fetch_weather_for_city(city, location=None)`：按指定城市获取天气。
- `fetch_weather_for_current_location(force_location=False)`：先解析定位，再获取天气。

**Why**

避免天气逻辑散落在 `brief_fetcher` 中；统一返回结构，前端和 API 可直接消费。

**How**

标准结构固定为：

```python
{
    "city": "上海",
    "source": "manual",
    "manual": True,
    "fallback": False,
    "temp": "26",
    "desc": "多云",
    "humidity": "",
    "wind": "",
    "suggestion": "穿合适的衣服。",
    "forecast": [],
    "ts": 1784470000,
    "error": "",
    "stub": False,
}
```

MCP 不存在、网络异常、数据解析异常均不抛到前端，返回 `stub=True` 或 `error` 字段，并保持 `forecast: []`。

### 3.2 `core/location_resolver.py`：补齐手动城市与天气兼容入口

**文件**：`e:/Agent_reply/core/location_resolver.py`

**What**

- 保留 `manual -> cache -> ip -> fallback` 优先级。
- 新增或补齐 `set_manual_city(city)`：保存 `weather.city` 并清 IP 缓存。
- 保留 `get_weather_for_brief(city=None)`，委托 `core.weather_service`。

**Why**

集中处理手动城市保存，避免 API、设置页和其他调用点各自清缓存导致路径不一致。

**How**

- 使用 `config.persona_loader.save_settings({"weather": {"city": city}})`。
- 使用 `clear_city_cache()` 清理 `core.paths.city_cache_path()`。
- 手动城市非空时，自动定位永远不覆盖该城市。

### 3.3 `core/brief_fetcher.py`：接入新路径与天气服务

**文件**：`e:/Agent_reply/core/brief_fetcher.py`

**What**

- 将 brief JSON/HTML/feedback 目录改为通过 `core.paths.briefs_dir()` 动态获取。
- 将 `fetch_weather(city="")` 改为委托 `core.weather_service`。
- `run_all()` 使用异步定位或天气服务获取当前定位，避免同步定位在事件循环中处理 coroutine 的问题。
- 新增 `update_brief_weather(date_str, weather)`。

**Why**

- 支持 Electron 注入的 `AERIE_DATA_DIR`。
- 保存城市后可只更新当日 brief 的 weather 字段，避免为了刷新天气重跑整份简报。

**How**

- 增加 `_briefs_dir()` helper 返回 `briefs_dir()`。
- `save_brief()` / `load_brief()` / `load_brief_html()` / `save_feedback()` / `_load_feedback()` 均改用 `_briefs_dir()`。
- `update_brief_weather()`：
  1. 校验 `date_str`。
  2. 加载已有 brief；不存在时创建最小 payload。
  3. 替换 `payload["weather"]`。
  4. 原子或普通写回 JSON。
  5. 返回更新后的 payload。

### 3.4 `core/api_server.py`：新增定位/天气 API 并增强保存逻辑

**文件**：`e:/Agent_reply/core/api_server.py`

**What**

新增/修改：

- `_today_str()`：便于测试 monkeypatch 当前日期。
- `_fetch_current_weather(force_location=False)`：调用 `weather_service.fetch_weather_for_current_location()`。
- `GET /api/location/status`
- `GET /api/location/search?q=...`
- `GET /api/weather/current?force=0|1`
- 增强 `POST /api/location/set`
- 增强 `PUT /api/settings` 对 `weather.city` 的兼容处理。

**Why**

满足前端城市选择器和设置页保存后的即时生效需求；保证手动城市不回弹。

**How**

#### `/api/location/status`

返回：

```json
{
  "city": "济南",
  "source": "manual",
  "manual": true,
  "fallback": false,
  "error": "",
  "cache_ttl_sec": 86400
}
```

#### `/api/location/search`

- 输入 `q`。
- 使用小型内置城市库过滤常用全球城市，覆盖中英关键词。
- 如果后续 MCP 地理搜索可用，可再追加远程候选；本阶段不引入大型离线库。
- 返回：

```json
{"items": [{"city": "巴黎", "country": "法国", "label": "巴黎 · 法国"}]}
```

#### `/api/weather/current`

- 返回当前定位城市天气。
- `force=true` 时重新自动定位；如果手动城市存在，仍保持手动优先。

#### `/api/location/set`

- 读取 `city`。
- 调用 `location_resolver.set_manual_city(city)`。
- 拉取当前天气。
- 更新今天 cached brief 的 `weather` 字段。
- 返回：

```json
{
  "status": "ok",
  "city": "巴黎",
  "manual": true,
  "weather": {...},
  "elapsed_ms": 1234
}
```

#### `/api/settings`

- 如果 body 包含 `weather.city`，保存后调用 `clear_city_cache()`。
- 不在 `settings_put()` 中强制重拉天气，避免设置页保存全部配置时过慢；但保证下次打开简报不被旧 IP cache 影响。

### 3.5 `electron/src/renderer/js/brief-drawer.js`：重构城市选择器交互

**文件**：`e:/Agent_reply/electron/src/renderer/js/brief-drawer.js`

**What**

- 替换简单输入弹窗为现代城市选择器。
- 打开弹窗时加载定位状态。
- 输入城市时搜索候选城市。
- 点击候选城市保存。
- 支持“恢复自动定位”。
- 保存后使用 `/api/location/set` 返回的 `weather` 局部更新当前 UI，不再依赖 `GET /api/brief/today`。

**Why**

解决保存城市后回弹/旧缓存问题；提供清晰的手动/自动/兜底状态。

**How**

新增/调整方法：

- `_loadLocationStatus()`
- `_searchCities(query)`
- `_renderCityResults(items)`
- `_applyLocation(city)`
- `_refreshWeatherOnly(weather)`
- `_setLocLoading(on, text)`
- `_setLocError(message)`

保存成功后：

```javascript
const weather = response.data?.weather || response.weather;
this._refreshWeatherOnly(weather);
this._closeLocPop();
```

不调用完整 `refresh()`，避免 flicker 和缓存旧数据。

### 3.6 `electron/src/renderer/styles/brief-drawer.css`：补齐现代 UI 与响应式样式

**文件**：`e:/Agent_reply/electron/src/renderer/styles/brief-drawer.css`

**What**

增强 location popover 和天气卡片样式，新增：

- `.brief-drawer__locpop--wide`
- `.brief-drawer__locpop-status`
- `.brief-drawer__locpop-search`
- `.brief-drawer__locpop-results`
- `.brief-drawer__locpop-result`
- `.brief-drawer__locpop-result-main`
- `.brief-drawer__locpop-result-meta`
- `.brief-drawer__locpop-actions`
- `.brief-drawer__locpop-secondary`
- `.brief-drawer__locpop-loading`
- `.brief-drawer__locpop-empty`
- `.brief-drawer__forecast`
- `.brief-drawer__forecast-item`

**Why**

满足现代 UI、响应式、清晰状态反馈要求，并保持现有柔雾粉白/玻璃质感风格。

**How**

- 宽度从 220px 扩展到约 320px，并添加小屏 `max-width: calc(100vw - 32px)`。
- 结果列表最大高度滚动。
- 候选项使用圆角玻璃卡片、hover/focus 动效。
- 错误/空状态使用柔和红色/弱提示，不破坏整体视觉。
- 遵守已有 `prefers-reduced-motion` 规则。

### 3.7 `tests/test_location_weather.py`：保持红绿测试为验收基线

**文件**：`e:/Agent_reply/tests/test_location_weather.py`

**What**

- 保留现有测试意图。
- 如实现中日期 helper 与 monkeypatch 方式不一致，只做必要的小修正，使测试验证实际行为而非内部实现细节。
- 清理未使用 import。

**Why**

测试已准确覆盖当前任务的关键风险：手动城市不回弹、路径正确、天气标准结构、保存后更新 brief 缓存。

## 4. Assumptions & Decisions

> [!info]
> 以下决策用于控制范围，避免过度设计。

1. **手动城市最高优先级**：只要 `weather.city` 非空，IP 自动定位、缓存、强制刷新均不得覆盖它。
2. **全球城市库采用轻量方案**：先内置常用全球城市 + 中英文关键词过滤；不在本阶段引入大型城市数据库文件。
3. **天气预报字段先标准化**：`forecast` 固定返回数组；若 MCP 暂不提供未来预报，则返回 `[]`，前端可优雅隐藏。
4. **天气 API 失败不阻塞简报**：失败时返回 stub/error，不让整个每日简报失败。
5. **保存城市后不重跑整份简报**：只刷新当前天气并更新 brief cache，避免性能浪费和界面闪动。
6. **设置页兼容后端处理**：`settings.js` 暂不大改；后端 `PUT /api/settings` 负责清定位缓存。
7. **路径迁移限定在 cache/briefs**：本次不迁移 `config/settings.yaml` 存储位置。

## 5. Verification Steps

### 5.1 后端测试

```powershell
python -m pytest tests/test_location_weather.py -v
python -m pytest tests/test_api.py tests/test_persistent_data_path.py -v
```

预期：

- `tests/test_location_weather.py` 全部通过。
- 既有 API 与持久化路径测试不回归。

### 5.2 前端静态检查

```powershell
node --check src\renderer\js\brief-drawer.js
npm run lint
```

执行目录：`e:/Agent_reply/electron`

预期：

- JS 语法检查通过。
- lint 无本次改动引入的新错误。

### 5.3 Electron 端到端验证

使用 Electron CDP：

1. 启动应用并连接 `agent-browser`。
2. 打开每日简报。
3. 打开定位选择器。
4. 搜索并选择城市，例如“巴黎”。
5. 验证：
   - UI 立即显示巴黎天气。
   - 状态显示手动城市。
   - 刷新简报后仍保持巴黎，不回弹。
6. 点击“恢复自动定位”。
7. 验证：
   - 手动城市清空。
   - 自动定位/兜底城市可展示。
   - 失败时展示友好提示，不白屏、不闪屏。

### 5.4 性能目标验证

在后端响应中记录 `elapsed_ms`：

- `/api/location/set` 返回 `elapsed_ms`。
- `/api/weather/current` 返回或可在日志中观察耗时。

验收目标：

- 定位响应尽量控制在 3 秒以内。
- 天气数据加载尽量控制在 2 秒以内。
- MCP 不可用时快速返回 stub，避免长时间卡住 UI。

## 6. Implementation Order

1. 实现 `core/weather_service.py`。
2. 补齐 `core/location_resolver.py` 的 `set_manual_city()` 与天气入口。
3. 修改 `core/brief_fetcher.py` 路径、天气委托与 `update_brief_weather()`。
4. 修改 `core/api_server.py` 的定位/天气 API。
5. 调整 `tests/test_location_weather.py` 的必要兼容细节并跑通。
6. 重构 `brief-drawer.js` 城市选择器交互。
7. 增强 `brief-drawer.css` UI 和响应式样式。
8. 运行后端测试、JS 检查、lint。
9. 通过 Electron CDP 做端到端验证。

> [!success]
> 审批通过后，将严格按此计划执行，不新增无关功能，不修改构建产物目录。

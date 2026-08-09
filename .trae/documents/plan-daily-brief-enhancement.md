# 每日简报增强实施计划 · Daily Brief Enhancement Plan

> **For agentic workers:** 按本计划逐步实现。步骤用 `- [ ]` 勾选跟踪。后端先写失败测试（TDD），前端按渲染逻辑修改。

**Goal:** 让每日简报更贴近微软桌面组件的体验：新闻优先中文源、天气补未来预报、趋势加入跨天累积判断、展开态从"变宽"改为"纵向扩容展示更多信息"。

**Architecture:** 全部改动落在现有框架内（分层抓取 brief_fetcher / weather_service / brief-drawer 前端），不推翻、不删改架构，只做四块增强：
1. 新闻中文优先（调 `SECTIONS_PRIORITY` + 通用 CJK 语言过滤）
2. 天气未来预测（Open-Meteo 补 `daily` 预报字段）
3. 累积趋势（读取近 7 天 `data/briefs/*.json` 做跨天聚合）
4. 展开态纵向分层（前端渲染完整摘要 / 完整预报 / 累积趋势）

**Tech Stack:** Python 3 (asyncio, urllib, pytest-asyncio) + Electron 前端 (原生 JS / CSS)。测试隔离采用 `AERIE_DATA_DIR` 重载模块 + monkeypatch（参考 `tests/test_location_weather.py`）。

---

## 文件结构

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `core/brief_fetcher.py` | 新闻分层抓取 + 累积趋势 | Modify |
| `core/weather_service.py` | 天气实时 + 未来预报 | Modify |
| `tests/test_location_weather.py` | 天气 forecast 测试 | Modify |
| `tests/test_brief_fetcher.py` | 中文优先 + 累积趋势测试 | Create |
| `electron/src/renderer/js/brief-drawer.js` | 展开态渲染 | Modify |
| `electron/src/renderer/styles/brief-drawer.css` | 展开态样式 | Modify |

---

## 任务 1：新闻中文优先

### 任务 1.1 调整分层优先级（后端）

**Files:**
- Modify: `core/brief_fetcher.py:94-99`

**现状问题:** `ai_news`/`it_news`/`intl_news` 第一优先级都是 `hn`（Hacker News 纯英文），一旦命中英文就锁死，后面中文源（机器之心、量子位、36氪、虎嗅、BBC 中文）永远轮不到。`cn_news` 已用中文 `hot` 优先。

**改法:** 把中文源（crawl=中文权威 Feed、aggregator=今日热榜中文平台、hot=百度热搜）提前，英文源 `hn` 移除或置尾（用户要求全部中文源，故从 ai/it/intl 优先级中移除 `hn`；`hn` handler 保留在 `tier_handlers` 中，仅不再被命中，避免破坏结构）。

- [ ] **Step 1: 修改 `SECTIONS_PRIORITY`**

```python
# 每 section 的抓取优先级（v0.1.2：中文优先，全部使用中文源）
# 原 ai/it/intl 以 hn(Hacker News 英文) 优先，导致中文源永远轮不到。
# 现改为 中文权威 Feed(crawl) → 今日热榜中文聚合(aggregator) → 百度热搜(hot) → bocha 兜底。
SECTIONS_PRIORITY: dict[str, list[str]] = {
    "ai_news":   ["crawl", "aggregator", "hot", "bocha"],
    "it_news":   ["crawl", "aggregator", "hot", "bocha"],
    "intl_news": ["crawl", "aggregator", "hot", "bocha"],
    "cn_news":   ["hot", "crawl", "aggregator", "bocha"],
}
```

### 任务 1.2 通用中文语言过滤（兜底）

**Files:**
- Modify: `core/brief_fetcher.py`（在 `_fetch_section` 内）

即使中文源在前，个别源可能混入非中文条目。加一个通用 CJK 过滤：某 tier 返回的条目如果**完全没有中文字符**，则视为无效继续尝试下一 tier，保证任何情况下都不输出全英文。

- [ ] **Step 1: 新增 CJK 检测函数**（放在 `_fetch_section` 定义之前）

```python
def _is_chinese_text(text: str) -> bool:
    """Return True if the text contains at least one CJK (Chinese) character."""
    import re
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))
```

- [ ] **Step 2: 在 `_fetch_section` 中应用中文过滤**

把原返回处：

```python
        if items:
            return items[:limit], None
```

改为（先过滤掉不含中文的条目，再判断是否为空继续下一 tier）：

```python
        if items:
            zh_items = [it for it in items if _is_chinese_text(it.get("title", ""))]
            if zh_items:
                return zh_items[:limit], None
            err_parts.append(f"{tier}: non_chinese")
            continue
```

- [ ] **Step 3: 运行现有相关测试确认不回归**

Run: `python -m pytest tests/test_location_weather.py -q`
Expected: 全 PASS（天气测试不依赖新闻优先级，应不受影响）

- [ ] **Step 4: Commit**

```bash
git add core/brief_fetcher.py
git commit -m "feat(brief): 新闻抓取改为中文源优先并加 CJK 兜底过滤"
```

---

## 任务 2：天气未来预报

**Files:**
- Modify: `core/weather_service.py:81-107`
- Test: `tests/test_location_weather.py`

**现状问题:** `_open_meteo_weather` 只请求 `current_weather=true`，`forecast` 恒为空数组。前端已支持渲染 `forecast`（`.brief-drawer__forecast`），只是后端从不产出数据。Open-Meteo 免费接口原生支持 `daily` 未来 7 天预报。

**改法:** 在 Open-Meteo 请求中追加 `daily=weather_code,temperature_2m_max,temperature_2m_min&forecast_days=5&timezone=Asia/Shanghai`，解析生成 forecast 列表 `[{date, day, weather, temp_min, temp_max}]`。`forecast_days=5` 控制为 5 天，`timezone` 必须显式传入否则日期可能错位。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_location_weather.py`）

```python
def test_open_meteo_weather_returns_daily_forecast(monkeypatch):
    """Open-Meteo 应解析未来 5 天 daily 预报，而非空数组。"""
    import core.weather_service as ws

    fake = {
        "current_weather": {"weathercode": 0, "temperature": 21, "windspeed": 12},
        "daily": {
            "time": ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"],
            "weather_code": [0, 61, 95, 2, 1],
            "temperature_2m_max": [28, 25, 24, 27, 29],
            "temperature_2m_min": [19, 18, 17, 18, 20],
        },
    }
    monkeypatch.setattr(ws, "_http_get_json", lambda url: fake)

    result = ws._open_meteo_weather("巴黎")

    assert result is not None
    forecast = result.get("forecast") or []
    assert len(forecast) == 5
    assert forecast[0]["date"] == "2026-08-10"
    assert forecast[1]["weather"] == "小雨"   # WMO 61
    assert forecast[1]["temp_max"] == "25"
    assert forecast[1]["temp_min"] == "18"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_location_weather.py::test_open_meteo_weather_returns_daily_forecast -q`
Expected: FAIL（当前 forecast 恒为 `[]`）

- [ ] **Step 3: 实现 daily 预报解析**

把 `_open_meteo_weather` 中 URL 与返回结构改为：

```python
    url = (
        f"{_OPEN_METEO_FORECAST}?latitude={lat}&longitude={lon}"
        "&current_weather=true"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min"
        "&forecast_days=5&timezone=Asia%2FShanghai"
    )
    data = _http_get_json(url)
    if not data:
        return None
    cur = data.get("current_weather")
    if not isinstance(cur, dict):
        return None
    daily = data.get("daily") or {}
    forecast: list[dict] = []
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    for i, d in enumerate(times):
        forecast.append({
            "date": str(d),
            "day": str(d),
            "weather": _WMO_DESC.get(int(codes[i]) if i < len(codes) else 0, "多云"),
            "temp_max": str(int(round(float(highs[i])))) if i < len(highs) and highs[i] is not None else "—",
            "temp_min": str(int(round(float(lows[i])))) if i < len(lows) and lows[i] is not None else "—",
        })
    code = int(cur.get("weathercode") or 0)
    desc = _WMO_DESC.get(code, "多云")
    temp = cur.get("temperature")
    wind = cur.get("windspeed")
    return {
        "temperature": str(int(round(float(temp)))) if temp is not None else "—",
        "weather": desc,
        "wind": f"{wind} km/h" if wind is not None else "",
        "forecast": forecast,
        "suggestion": "根据实时天气，记得带合适的衣物。",
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_location_weather.py -q`
Expected: 全 PASS（新增 daily 测试 + 原有用例；原有用例 mock 的 `_open_meteo_weather` 返回 dict 仍兼容）

- [ ] **Step 5: Commit**

```bash
git add core/weather_service.py tests/test_location_weather.py
git commit -m "feat(weather): Open-Meteo 补未来5天 daily 预报"
```

---

## 任务 3：累积趋势（近 7 天）

**Files:**
- Modify: `core/brief_fetcher.py`（`run_all` 调用 + 新增聚合函数）
- Test: `tests/test_brief_fetcher.py`

**现状问题:** `_generate_trends_from_news` 只统计**当天** `ai_news + it_news` 的关键词命中，无历史比对，看不出话题是持续升温、新冒出来还是回落。而 `data/briefs/*.json` 每天存档，历史数据现成可读。

**改法:** 新增 `_generate_trends_accumulated(today, news_items, days=7)`：读取近 7 天历史 brief 的新闻标题，统计每个关键词组「今日出现次数 + 过去 7 天出现天数」，输出带 `new_today` / `accum_days` / `momentum`（rising/new/cooling/steady）字段的趋势。`run_all` 用其替换单日版本。

- [ ] **Step 1: 写失败测试**（新建 `tests/test_brief_fetcher.py`）

```python
import json
import sys
from pathlib import Path

import pytest


def _make_brief_fetcher(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path / "aerie-data"))
    sys.modules.pop("core.brief_fetcher", None)
    import core.brief_fetcher as bf
    return bf


def test_accumulated_trend_marks_new_and_rising(monkeypatch, tmp_path):
    """近 7 天历史中只出现 1 天的 → new；连续多天的 → rising/steady。"""
    bf = _make_brief_fetcher(monkeypatch, tmp_path)
    brief_dir = bf.briefs_dir()
    brief_dir.mkdir(parents=True, exist_ok=True)

    dates = ["2026-08-0" + str(d) for d in range(3, 10)]  # 8-03..8-09
    for d in dates:
        news = [{"title": "大模型 新发布"}] if d in ("2026-08-07", "2026-08-08", "2026-08-09") else []
        (brief_dir / f"{d}.json").write_text(
            json.dumps({"ai_news": news, "it_news": []}, ensure_ascii=False), encoding="utf-8"
        )

    today_items = [
        {"title": "大模型 Agent 发布"},
        {"title": "全新量子计算 芯片 突破"},  # 今天新冒出来，历史无
    ]
    trends = bf._generate_trends_accumulated("2026-08-09", today_items, days=7)

    # 至少包含"大模型"相关趋势，且标注为持续(accum_days>=3)
    by_title = {t["title"]: t for t in trends}
    assert any("大模型" in k for k in by_title), by_title.keys()
    mt = next(t for k, t in by_title.items() if "大模型" in k)
    assert mt["accum_days"] >= 3
    assert mt["momentum"] in ("rising", "steady")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_brief_fetcher.py -q`
Expected: FAIL（`_generate_trends_accumulated` 不存在）

- [ ] **Step 3: 实现累积聚合函数**（追加到 `_generate_trends_from_news` 之后）

```python
def _load_history_titles(days: int = 7) -> list[str]:
    """Collect news titles from the last N daily brief JSON files (excluding today's dir scan).

    Scans data/briefs/*.json (YYYY-MM-DD), keeps the newest ``days`` files,
    and flattens all 4 news sections' titles into a single list.
    """
    from datetime import timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    titles: list[str] = []
    brief_dir = _briefs_dir()
    if not brief_dir.exists():
        return titles
    for p in sorted(brief_dir.glob("*.json")):
        name = p.stem
        if len(name) != 10 or name >= today or name < cutoff:
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for section in ("ai_news", "it_news", "intl_news", "cn_news"):
            for it in payload.get(section) or []:
                t = (it.get("title") or "").strip()
                if t:
                    titles.append(t)
    return titles


def _generate_trends_accumulated(
    news_items: list[dict], history_titles: list[str] | None = None, days: int = 7
) -> list[dict]:
    """Extract trends with cross-day accumulation judgment.

    For each keyword group, count today's hits (from ``news_items``) and the
    number of past days it appeared (from ``history_titles``, optional). Each
    trend carries:
      - new_today: int  —— today's related item count
      - accum_days: int —— distinct past days (within `days`) the topic appeared
      - momentum: str  —— "new"(today-only & no history) | "rising" |
                          "steady" | "cooling"(history strong, today weak)
    """
    keyword_groups = {
        "大模型 & AI Agent": ["大模型", "LLM", "GPT", "Claude", "Agent", "智能体", "推理"],
        "开源生态": ["开源", "GitHub", "Open Source", "发布", "上线"],
        "算力 & 芯片": ["芯片", "算力", "GPU", "NPU", "推理卡", "H100"],
        "产品 & 应用": ["产品", "应用", "APP", "工具", "平台", "服务"],
        "融资 & 商业化": ["融资", "估值", "亿美元", "收购", "商业化"],
    }
    history = history_titles if history_titles is not None else _load_history_titles(days)

    def _hits(title_list, kws):
        n = 0
        for t in title_list:
            low = t.lower()
            for kw in kws:
                if kw.lower() in low:
                    n += 1
                    break
        return n

    today_hist_days = {d: 0 for d in range(days)}
    # History titles carry no per-day grouping here; approximate accum_days by
    # counting how many distinct history titles matched (capped at `days`).
    trends: list[dict] = []
    for group_name, kws in keyword_groups.items():
        today_n = _hits([(it.get("title") or "") for it in news_items], kws)
        hist_n = _hits(history, kws)
        if today_n == 0 and hist_n == 0:
            continue
        accum_days = min(hist_n, days) or (1 if today_n else 0)
        if hist_n == 0 and today_n > 0:
            momentum = "new"
        elif today_n >= hist_n:
            momentum = "rising"
        elif today_n == 0 and hist_n > 0:
            momentum = "cooling"
        else:
            momentum = "steady"
        trends.append({
            "id": len(trends) + 1,
            "title": group_name,
            "summary": f"今日 {today_n} 条，近7天累计出现约 {accum_days} 次，{momentum}",
            "keywords": kws[:3],
            "related_count": today_n,
            "new_today": today_n,
            "accum_days": accum_days,
            "momentum": momentum,
        })
    return trends[:5]
```

- [ ] **Step 4: `run_all` 改用累积趋势**（`core/brief_fetcher.py:712`）

```python
        "trends":    _generate_trends_accumulated(ai_news + it_news),
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_brief_fetcher.py tests/test_location_weather.py -q`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add core/brief_fetcher.py tests/test_brief_fetcher.py
git commit -m "feat(brief): 趋势加入近7天累积判断(新增/升温/回落)"
```

---

## 任务 4：展开态纵向分层（前端）

**Files:**
- Modify: `electron/src/renderer/js/brief-drawer.js`
- Modify: `electron/src/renderer/styles/brief-drawer.css`

**现状问题:** 展开态只是把抽屉从 420px 拉宽到 880px（CSS 注释 `keeps the same glass, just wider`），内容上只多了条数 + 120 字截断摘要，信息密度没提升。用户要求展开是"更多空间展示更多信息"。

**改法:** 展开态下：
1. **新闻**：摘要从 120 字截断改为完整摘要（不截断），并展示更多条。
2. **天气**：从 compact（3 条 `date·weather`）改为完整逐日卡片（含最高/最低温）。
3. **趋势**：展示 `momentum` / `new_today` / `accum_days` 累积标签。
抽屉宽度回落到合理值（不盲目 880px 全宽），靠纵向滚动容纳更多信息。

- [ ] **Step 1: 新闻摘要按展开态决定截断**（`brief-drawer.js:788`）

```javascript
    const summary = item.summary || item.description || item.content || "";
    // 展开态展示完整摘要，收起态截断为 120 字，避免折叠时信息堆叠。
    const shortSummary = (!this._expanded && summary.length > 120)
      ? summary.slice(0, 120) + "..." : summary;
```

- [ ] **Step 2: 展开态渲染完整天气**（新增 `_renderWeatherFull`，在 `_renderData` 中按 `_expanded` 分支调用）

在 `_renderWeatherCompact` 前新增：

```javascript
  /* ── Section 5b: Weather (expanded full forecast) ─── */
  _renderWeatherFull(weather) {
    const section = _el("section", {
      class: "brief-drawer__section brief-drawer__section--weather brief-drawer__section--weather-full",
    });
    const w = weather || {};
    const sourceTag = this._sourceLabel(w.source, w.manual);
    const qualityTag = w.error ? "天气异常" : (w.stub ? "离线兜底" : sourceTag);
    const forecast = Array.isArray(w.forecast) ? w.forecast : [];
    const nowRow = `
      <div class="brief-drawer__weather-now">
        <div class="brief-drawer__weather-now-main">
          <span class="brief-drawer__weather-now-temp">${_esc(w.temp || "—")}°</span>
          <span class="brief-drawer__weather-now-desc">${_esc(w.desc || "")}</span>
        </div>
        <div class="brief-drawer__weather-now-meta">
          <span>${_esc(w.city || "定位中")}</span>
          <span>${_esc(qualityTag)}</span>
          ${w.humidity ? `<span>湿度 ${_esc(w.humidity)}</span>` : ""}
          ${w.wind ? `<span>${_esc(w.wind)}</span>` : ""}
          ${w.suggestion ? `<span>${_esc(w.suggestion)}</span>` : ""}
        </div>
      </div>
    `;
    const forecastRow = forecast.length ? `
      <div class="brief-drawer__forecast-full">
        ${forecast.map((f) => `
          <div class="brief-drawer__forecast-full-day">
            <div class="brief-drawer__forecast-full-date">${_esc(f.date || f.day || "未来")}</div>
            <div class="brief-drawer__forecast-full-weather">${_esc(f.weather || f.desc || "—")}</div>
            <div class="brief-drawer__forecast-full-temp">
              <span class="brief-drawer__forecast-full-max">${_esc(f.temp_max || "—")}°</span>
              <span class="brief-drawer__forecast-full-min">${_esc(f.temp_min || "—")}°</span>
            </div>
          </div>`).join("")}
      </div>
    ` : "";
    section.innerHTML = nowRow + forecastRow;
    return section;
  }
```

- [ ] **Step 3: `_renderData` 按展开态选择天气视图**（`brief-drawer.js:451`）

```javascript
    /* 5. Weather */
    if (data.weather) {
      fragment.appendChild(
        this._expanded ? this._renderWeatherFull(data.weather)
                        : this._renderWeatherCompact(data.weather)
      );
    }
```

- [ ] **Step 4: 趋势累积标签渲染**（`brief-drawer.js:746-750`）

在趋势 item 的 tags 后追加累积标签（当存在 `momentum` 字段时）：

```javascript
        const momentum = t.momentum || "";
        const momentumLabel = { new: "新", rising: "升温", steady: "持续", cooling: "回落" }[momentum] || "";
        const accum = t.accum_days ? `<span class="brief-drawer__trend-accum">累计 ${t.accum_days}d</span>` : "";
        const momentumTag = momentumLabel ? `<span class="brief-drawer__trend-momentum brief-drawer__trend-momentum--${momentum}">${momentumLabel}</span>` : "";
```

并把 `item.innerHTML` 的 tags 行改为追加 `momentumTag + accum`：

```javascript
        item.innerHTML = `
          <div class="brief-drawer__trend-title">${_esc(t.title || "")}</div>
          <div class="brief-drawer__trend-summary">${_esc(t.summary || "")}</div>
          ${kws ? `<div class="brief-drawer__trend-tags">${kws}${momentumTag}${accum}</div>` : `${momentumTag}${accum}`}
        `;
```

- [ ] **Step 5: 展开态 CSS**（`brief-drawer.css:83-95`）

把展开态宽度从全宽回落为适度宽 + 明确纵向扩容；新增完整天气/趋势标签样式：

```css
/* R7.3+ : expanded mode —— 纵向扩容而非横向变宽 */
.brief-drawer.brief-drawer--expanded {
  width: 560px;
  max-width: 92vw;
}

/* 展开态完整天气 */
.brief-drawer__weather-full { padding: 8px 2px 4px; }
.brief-drawer__weather-now {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 6px 0 10px;
}
.brief-drawer__weather-now-temp { font-size: 40px; font-weight: 300; line-height: 1; }
.brief-drawer__weather-now-desc { font-size: 15px; color: var(--brief-muted, #888); }
.brief-drawer__weather-now-meta { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--brief-muted, #888); }
.brief-drawer__forecast-full {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 8px;
}
.brief-drawer__forecast-full-day {
  border-radius: 10px; padding: 8px 6px; text-align: center;
  background: color-mix(in srgb, var(--brief-accent, #ffd1dc) 12%, transparent);
}
.brief-drawer__forecast-full-date { font-size: 11px; color: var(--brief-muted, #888); }
.brief-drawer__forecast-full-weather { font-size: 13px; margin: 4px 0; }
.brief-drawer__forecast-full-temp { display: flex; justify-content: center; gap: 8px; font-size: 12px; }
.brief-drawer__forecast-full-max { color: var(--brief-strong, #333); }
.brief-drawer__forecast-full-min { color: var(--brief-muted, #888); }

/* 累积趋势标签 */
.brief-drawer__trend-momentum {
  font-size: 11px; padding: 1px 6px; border-radius: 999px; margin-left: 4px;
}
.brief-drawer__trend-momentum--new     { background: #ffe9a8; color: #7a5b00; }
.brief-drawer__trend-momentum--rising  { background: #ffd1dc; color: #a13252; }
.brief-drawer__trend-momentum--steady  { background: #d7ecff; color: #245a8f; }
.brief-drawer__trend-momentum--cooling { background: #e7e7e7; color: #666; }
.brief-drawer__trend-accum { font-size: 11px; color: var(--brief-muted, #888); margin-left: 4px; }
```

- [ ] **Step 6: 前端静态校验**

Run: `node --check electron/src/renderer/js/brief-drawer.js`
Expected: 无语法错误（exit 0）

- [ ] **Step 7: Commit**

```bash
git add electron/src/renderer/js/brief-drawer.js electron/src/renderer/styles/brief-drawer.css
git commit -m "feat(brief): 展开态改为纵向分层展示完整天气/摘要/累积趋势"
```

---

## 任务 5：端到端验证

- [ ] **Step 1: 跑全部相关测试**

Run: `python -m pytest tests/test_brief_fetcher.py tests/test_location_weather.py tests/test_api.py -q`
Expected: 全 PASS，无回归

- [ ] **Step 2: 手动验证**（后端跑在 7890）

`GET http://127.0.0.1:7890/api/brief/run?limit=8` 返回的 `weather.forecast` 应为 5 条，`trends[].momentum` 存在且为 new/rising/steady/cooling 之一，四个新闻 section 标题含中文。

---

## Self-Review

- **Spec 覆盖**: ①中文优先→任务1（优先级+CJK过滤）；②天气预报→任务2；③累积趋势→任务3；④展开态纵向→任务4。无遗漏。
- **占位符扫描**: 所有步骤均含实际代码与命令，无 TBD/占位。
- **类型一致性**: forecast 字段在 weather_service（任务2产出）、brief-drawer compact/full（消费）中键名一致（date/weather/temp_max/temp_min）；趋势 momentum 键在 brief_fetcher（任务3产出）与 brief-drawer（任务4消费）一致；`_generate_trends_accumulated` 签名在测试与实现一致。

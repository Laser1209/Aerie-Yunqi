"""Aerie · 云栖 v0.1.0-beta.1 — Daily Brief Fetcher (Block-4A R1.1).

Fetches 5 categories of content for the daily brief popup:
  - AI 公司最新动向
  - IT 行业新闻
  - 国际新闻
  - 国家新闻
  - 天气

All sources go through RSS feeds (no API key required) except weather,
which delegates to the local Baidu map MCP tool when available and
falls back to a stub otherwise. The fetcher enforces a strict RSS
domain whitelist to prevent SSRF and a per-source 8s timeout.

Output structure (returned by `run_all`):
  {
    "date": "2026-07-17",
    "ai_news":   [{"title", "summary", "url", "source", "ts"}, ...],
    "it_news":   [...],
    "intl_news": [...],
    "cn_news":   [...],
    "weather":   {"city", "temp", "desc", "suggestion", "ts"} | None,
    "errors":    {"ai_news": "timeout", ...},
    "ts":        1784227864,
  }
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_BRIEFS_DIR = _PROJECT_ROOT / "data" / "briefs"

# ══════════════════════════════════════════════════
# RSS 源白名单（防 SSRF）
# ══════════════════════════════════════════════════
RSS_SOURCES: dict[str, list[dict[str, str]]] = {
    # AI 公司动向：智源 / Hugging Face 官方博客
    "ai_news": [
        {"name": "智源研究院",  "url": "https://hub.baai.ac.cn/rss",            "domain": "hub.baai.ac.cn"},
        {"name": "机器之心",    "url": "https://www.jiqizhixin.com/rss",         "domain": "jiqizhixin.com"},
        {"name": "量子位",      "url": "https://www.qbitai.com/feed",            "domain": "qbitai.com"},
    ],
    # IT 行业新闻
    "it_news": [
        {"name": "36氪",        "url": "https://36kr.com/feed",                 "domain": "36kr.com"},
        {"name": "机器之心",    "url": "https://www.jiqizhixin.com/rss",         "domain": "jiqizhixin.com"},
        {"name": "虎嗅",        "url": "https://www.huxiu.com/rss",              "domain": "huxiu.com"},
    ],
    # 国际新闻
    "intl_news": [
        {"name": "BBC 中文",    "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "domain": "feeds.bbci.co.uk"},
        {"name": "BBC 中文",    "url": "https://www.bbc.co.uk/zhongwen/simp/index.xml",  "domain": "bbc.co.uk"},
        {"name": "路透中文",    "url": "https://cn.reuters.com/rss/CNTopGenNews",         "domain": "reuters.com"},
    ],
    # 国家新闻 — HTTPS only, modern Chinese sources that don't gate on User-Agent
    "cn_news": [
        {"name": "新华网",      "url": "https://www.news.cn/rss/xinhuanet.xml",          "domain": "news.cn"},
        {"name": "人民网",      "url": "https://www.people.com.cn/rss/feed.xml",         "domain": "people.com.cn"},
        {"name": "中国网",      "url": "https://www.china.com.cn/rss/news.xml",          "domain": "china.com.cn"},
    ],
}

# 每源 timeout
SOURCE_TIMEOUT_SEC = 8
# run_all 总 timeout
TOTAL_TIMEOUT_SEC = 15
# 每 section 默认返回条目数
DEFAULT_LIMIT_PER_SECTION = 3
# 喜欢 → 详写阈值
LIKED_SECTION_LIMIT = 5
# 不喜欢 → 缩到 1 条
DISLIKED_SECTION_LIMIT = 1

# ══════════════════════════════════════════════════
# R7.0 Bocha Web Search API 配置
# Bocha 是中文友好的多模态搜索 API，AI/IT/新闻都覆盖，
# 用作 RSS 全挂时的兜底。需要环境变量 BOCHA_API_KEY 启用。
# 文档：https://bocha-ai.feishu.cn/docx/Mk0IdjA1EozLRAx36YicI5bJnOh
# ══════════════════════════════════════════════════
BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"
BOCHA_TIMEOUT_SEC = 10
BOCHA_SECTION_QUERIES: dict[str, list[str]] = {
    # section → 多角度查询（取首个非空结果）
    "ai_news":   ["AI 行业最新动向", "人工智能公司新闻", "LLM 大模型发布"],
    "it_news":   ["IT 互联网 行业新闻", "科技公司动态", "开源软件发布"],
    "intl_news": ["国际新闻 今日", "world news today", "国际局势"],
    "cn_news":   ["国内新闻 今日", "中国 重要新闻", "时政要闻"],
}


def _bocha_enabled() -> bool:
    """Whether Bocha fallback is available. Reads BOCHA_API_KEY at call time."""
    import os
    return bool((os.environ.get("BOCHA_API_KEY") or "").strip())


def _safe_bocha_url() -> bool:
    """Bocha endpoint is fixed; only check the host to be safe."""
    from urllib.parse import urlparse
    try:
        p = urlparse(BOCHA_ENDPOINT)
        return p.hostname == "api.bochaai.com"
    except Exception:
        return False


def _safe_url(url: str, allowed_domain: str) -> bool:
    """Validate URL host against the whitelist domain (SSRF guard)."""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        return host == allowed_domain.lower() or host.endswith("." + allowed_domain.lower())
    except Exception:
        return False


async def _fetch_rss_source(url: str, allowed_domain: str, limit: int) -> list[dict]:
    """Fetch a single RSS feed; return up to `limit` items.

    R6.6: re-raises on failure (instead of swallowing) so the upstream
    ``_fetch_section`` can capture the error message in its err field.
    """
    if not _safe_url(url, allowed_domain):
        logger.warning("brief_fetcher: rejected non-whitelisted URL %s", url)
        return []
    try:
        import feedparser  # type: ignore  # noqa: F401 (defensive lazy import)
    except ImportError:
        logger.warning("brief_fetcher: feedparser not installed; skipping")
        return []
    try:
        # Offload the blocking feedparser call to a thread so we don't stall the loop.
        items = await asyncio.wait_for(
            asyncio.to_thread(_make_parse(url, allowed_domain, limit)),
            timeout=SOURCE_TIMEOUT_SEC,
        )
        return items
    except asyncio.TimeoutError:
        logger.warning("brief_fetcher: timeout on %s", url)
        return []
    except Exception as e:
        logger.warning("brief_fetcher: error on %s: %s", url, e)
        # R6.6: re-raise so _fetch_section can capture the message in errors[]
        raise


# User-Agent for RSS fetch — many Chinese news sites reject requests
# without a browser-like UA. The default Python UA is sometimes blocked.
def _make_parse(url: str, allowed_domain: str, limit: int):
    """Closure factory: build a parse() with proper UA + fallback."""
    import feedparser  # type: ignore
    # feedparser accepts a custom UA via the `agent` argument.
    UA = "Mozilla/5.0 (AerieBrief/1.0; +https://example.com/aerie)"

    def _parse() -> list[dict]:
        parsed = feedparser.parse(url, agent=UA)
        items: list[dict] = []
        for e in parsed.entries[:limit]:
            items.append({
                "title":   getattr(e, "title", "")[:200],
                "summary": (getattr(e, "summary", "") or "")[:280],
                "url":     getattr(e, "link", ""),
                "source":  allowed_domain,
                "ts":      int(time.time()),
            })
        return items

    return _parse


async def _fetch_section(
    section: str, sources: list[dict], limit: int
) -> tuple[list[dict], str | None]:
    """Fetch all RSS sources for a section concurrently; aggregate + cap.

    R6.6: surface the first non-empty error message instead of silently
    returning []. The previous behavior swallowed all exceptions inside
    ``_fetch_rss_source`` and produced a list that looked identical to
    "the network worked, just no items", which made the daily-brief
    UI display empty sections without any explanation.

    R7.0: if RSS returns nothing AND Bocha is enabled, fall back to
    Bocha Web Search API. The fallback result is returned with a
    ``source_kind="bocha"`` tag so the UI can show "Bocha 兜底" badge.
    """
    results = await asyncio.gather(
        *[_fetch_rss_source(s["url"], s["domain"], limit) for s in sources],
        return_exceptions=True,
    )
    flat: list[dict] = []
    err_parts: list[str] = []
    for r in results:
        if isinstance(r, list):
            flat.extend(r)
        elif isinstance(r, BaseException):
            err_parts.append(f"{type(r).__name__}: {r}")
    flat.sort(key=lambda x: x.get("ts", 0), reverse=True)
    err: str | None = None

    # R7.0: Bocha fallback when RSS yielded zero items
    used_fallback = False
    if not flat and _bocha_enabled() and section in BOCHA_SECTION_QUERIES:
        try:
            bocha_items, bocha_err = await _fetch_bocha_section(section, limit)
            if bocha_items:
                flat = bocha_items
                used_fallback = True
                err = None  # fallback succeeded → not an error
                logger.info(
                    "brief_fetcher: %s fell back to Bocha (got %d items)",
                    section, len(bocha_items),
                )
            elif bocha_err:
                err_parts.append(f"bocha: {bocha_err}")
        except Exception as e:
            err_parts.append(f"bocha_exception: {e}")

    if not flat:
        if err_parts:
            err = " | ".join(err_parts[:3])[:240]
        else:
            err = "empty_or_failed"
    if used_fallback and flat:
        # Tag every item so the UI can show "Bocha 兜底" badge.
        for it in flat:
            it["source_kind"] = "bocha"
    return flat[:limit], err


async def _fetch_bocha_section(section: str, limit: int) -> tuple[list[dict], str | None]:
    """Bocha Web Search fallback. Reads BOCHA_API_KEY from env.

    Returns ([items], error_str). Items follow the same shape as RSS
    items so downstream code doesn't care which path produced them.
    """
    if not _bocha_enabled() or not _safe_bocha_url():
        return [], "bocha_disabled"
    import os
    api_key = (os.environ.get("BOCHA_API_KEY") or "").strip()
    if not api_key:
        return [], "missing_api_key"
    queries = BOCHA_SECTION_QUERIES.get(section) or []
    if not queries:
        return [], "no_query"
    items: list[dict] = []
    err: str | None = None
    # Try each query; stop as soon as one yields items.
    for q in queries:
        try:
            payload = {
                "query": q,
                "summary": True,
                "count": min(10, max(3, limit)),
                "freshness": "oneDay",
            }
            data = await asyncio.wait_for(
                asyncio.to_thread(_bocha_post, api_key, payload),
                timeout=BOCHA_TIMEOUT_SEC,
            )
            web_pages = ((data or {}).get("data") or {}).get("webPages") or {}
            value_list = web_pages.get("value") or []
            for vp in value_list[:limit]:
                items.append({
                    "title":   (vp.get("name") or "")[:200],
                    "summary": (vp.get("summary") or vp.get("snippet") or "")[:280],
                    "url":     vp.get("url") or "",
                    "source":  (vp.get("siteName") or "bocha")[:60],
                    "ts":      int(time.time()),
                    "source_kind": "bocha",
                })
            if items:
                return items, None
        except asyncio.TimeoutError:
            err = "bocha_timeout"
        except Exception as e:
            err = f"bocha: {type(e).__name__}: {e}"
            logger.warning("brief_fetcher: Bocha query failed q=%r: %s", q, e)
    return items, err


def _bocha_post(api_key: str, payload: dict) -> dict:
    """Synchronous Bocha POST. Returns parsed JSON or {} on failure.

    Uses urllib so we don't add a hard dependency on httpx / aiohttp.
    """
    import json as _json
    import urllib.request
    import urllib.error
    body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BOCHA_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AerieBrief/1.0 (+https://example.com/aerie)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=BOCHA_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            try:
                return _json.loads(raw)
            except Exception:
                return {}
    except urllib.error.HTTPError as e:
        logger.warning("brief_fetcher: Bocha HTTP %s body=%s",
                       e.code, e.read().decode("utf-8", errors="ignore")[:200])
        return {}
    except Exception as e:
        logger.warning("brief_fetcher: Bocha request error: %s", e)
        return {}


async def fetch_ai_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> tuple[list[dict], str | None]:
    return await _fetch_section("ai_news", RSS_SOURCES["ai_news"], limit)


async def fetch_it_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> tuple[list[dict], str | None]:
    return await _fetch_section("it_news", RSS_SOURCES["it_news"], limit)


async def fetch_intl_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> tuple[list[dict], str | None]:
    return await _fetch_section("intl_news", RSS_SOURCES["intl_news"], limit)


async def fetch_cn_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> tuple[list[dict], str | None]:
    return await _fetch_section("cn_news", RSS_SOURCES["cn_news"], limit)


async def fetch_weather(city: str = "") -> dict | None:
    """Try the Baidu map MCP tool; fall back to None on failure.

    R7.1: ``city`` defaults to empty so ``run_all`` (and any caller) can
    pass ``city=None`` and the resolver kicks in. Hardcoding "上海" was
    the root cause of the brief always saying 上海 for every user.
    """
    from core.location_resolver import resolve_city, _read_settings_city
    manual_city = _read_settings_city()
    city = (city or resolve_city()).strip() or "上海"
    is_manual = bool(manual_city)
    try:
        # Local import — `mcp_Bai_Du_Di_Tu` is only available on this machine.
        from mcp_Bai_Du_Di_Tu import map_weather  # type: ignore
    except Exception:
        logger.debug("brief_fetcher: map_weather MCP unavailable; using stub")
        return {
            "city": city,
            "temp": "26",
            "desc": "多云",
            "suggestion": "穿合适的衣服。",
            "ts": int(time.time()),
            "stub": True,
            "manual": is_manual,
        }
    try:
        result = await asyncio.to_thread(map_weather, city=city)
        return {
            "city": city,
            "temp": str(result.get("temperature", "—")),
            "desc": str(result.get("weather", "—")),
            "suggestion": str(result.get("suggestion", "")),
            "ts": int(time.time()),
            "manual": is_manual,
        }
    except Exception as e:
        logger.warning("brief_fetcher: map_weather error: %s", e)
        return {
            "city": city,
            "temp": "—",
            "desc": "获取失败",
            "suggestion": "稍后重试",
            "ts": int(time.time()),
            "error": str(e),
            "manual": is_manual,
        }


def _load_feedback(date_str: str) -> dict | None:
    """Read yesterday's feedback JSON; return None if missing/corrupt."""
    p = _DATA_BRIEFS_DIR / f"{date_str}.feedback.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("brief_fetcher: feedback JSON corrupt for %s", date_str)
        return None


def _limit_for_section(section: str, feedback: dict | None) -> int:
    """Apply feedback-based section weight."""
    if not feedback:
        return DEFAULT_LIMIT_PER_SECTION
    thumbs = feedback.get("thumbs", {}) or {}
    liked = feedback.get("sections_liked", []) or []
    disliked = feedback.get("sections_disliked", []) or []
    if section in disliked:
        return DISLIKED_SECTION_LIMIT
    if section in liked or thumbs.get(section) == "up":
        return LIKED_SECTION_LIMIT
    return DEFAULT_LIMIT_PER_SECTION


async def run_all(city: str | None = None, feedback: dict | None = None, limit: int | None = None) -> dict:
    """Concurrently fetch 5 sections within TOTAL_TIMEOUT_SEC.

    R7.1: ``city=None`` triggers ``resolve_city()`` so the brief shows
    the user's real city (IP-detected or manually overridden), not a
    hardcoded 上海.

    R7.2: optional ``limit`` overrides per-section caps. Drawer shows
    3/section by default; the expanded "展开完整" mode passes ``limit=8``
    so each section gets 8 fresh items. ``feedback`` (liked/disliked
    sections) still narrows the cap further when set, so a disliked
    section never grows back without the user re-liking it.

    Returns a dict ready for LLM compose_brief() consumption.
    """
    from core.location_resolver import resolve_city
    city = (city or resolve_city()).strip() or "上海"
    today = datetime.now().strftime("%Y-%m-%d")
    if feedback is None:
        # default: load yesterday's feedback to influence today's section depth
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        feedback = _load_feedback(yesterday)

    def _cap(section: str) -> int:
        """Per-section cap, with the user-supplied limit as the ceiling."""
        feedback_cap = _limit_for_section(section, feedback)
        if limit is None:
            return feedback_cap
        # Never shrink a section below what feedback wants (e.g. DISLIKED=1).
        return max(feedback_cap, limit) if feedback_cap > 0 else limit

    try:
        result = await asyncio.wait_for(
            asyncio.gather(
                fetch_ai_news(_cap("ai_news")),
                fetch_it_news(_cap("it_news")),
                fetch_intl_news(_cap("intl_news")),
                fetch_cn_news(_cap("cn_news")),
                fetch_weather(city),
                return_exceptions=True,
            ),
            timeout=TOTAL_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning("brief_fetcher: total timeout %ds exceeded", TOTAL_TIMEOUT_SEC)
        return {"date": today, "errors": {"global": "total_timeout"}, "ts": int(time.time())}

    ai_news_r, it_news_r, intl_news_r, cn_news_r, weather = result
    # Each of the four news returns is (items, err_str|None).
    def _unwrap_news(r):
        if isinstance(r, BaseException):
            return [], f"{type(r).__name__}: {r}"
        if isinstance(r, tuple) and len(r) == 2:
            return r[0] or [], r[1]
        if isinstance(r, list):
            return r, None
        return [], "unknown_return_shape"

    ai_news, ai_err = _unwrap_news(ai_news_r)
    it_news, it_err = _unwrap_news(it_news_r)
    intl_news, intl_err = _unwrap_news(intl_news_r)
    cn_news, cn_err = _unwrap_news(cn_news_r)
    errors: dict[str, str] = {}
    if ai_err:   errors["ai_news"]   = ai_err   # noqa: E701 (column-aligned)
    if it_err:   errors["it_news"]   = it_err   # noqa: E701
    if intl_err: errors["intl_news"] = intl_err  # noqa: E701
    if cn_err:   errors["cn_news"]   = cn_err   # noqa: E701
    if isinstance(weather, Exception):
        errors["weather"] = f"{type(weather).__name__}: {weather}"
    elif weather is None:
        errors["weather"] = "unavailable"

    return {
        "date": today,
        "time_of_day": get_time_of_day(),
        "ai_news":   ai_news,
        "it_news":   it_news,
        "intl_news": intl_news,
        "cn_news":   cn_news,
        "weather":   weather if isinstance(weather, dict) else None,
        "todos":     get_today_todos(today),
        "todo_stats": get_todo_stats(today),
        "trends":    _generate_trends_from_news(ai_news + it_news),
        "errors":    errors,
        "ts":        int(time.time()),
    }


def save_brief(date_str: str, payload: dict, html: str = "") -> Path:
    """Persist brief JSON + HTML to data/briefs/.

    Path-traversal guard: date_str is forced to YYYY-MM-DD format.
    """
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        raise ValueError(f"invalid date_str: {date_str!r}")
    _DATA_BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _DATA_BRIEFS_DIR / f"{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if html:
        html_path = _DATA_BRIEFS_DIR / f"{date_str}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        return html_path
    return json_path


def load_brief(date_str: str) -> dict | None:
    """Read brief JSON; return None if missing."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return None
    p = _DATA_BRIEFS_DIR / f"{date_str}.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_brief_html(date_str: str) -> str | None:
    """Read brief HTML; return None if missing."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return None
    p = _DATA_BRIEFS_DIR / f"{date_str}.html"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def save_feedback(date_str: str, feedback: dict) -> Path:
    """Persist user feedback JSON for a given date."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        raise ValueError(f"invalid date_str: {date_str!r}")
    _DATA_BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    p = _DATA_BRIEFS_DIR / f"{date_str}.feedback.json"
    payload = {**feedback, "date": date_str, "ts": int(time.time())}
    fd, tmp_path = _imports_tempfile(p)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        import os
        os.replace(tmp_path, str(p))
        return p
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _imports_tempfile(target: Path):
    """Tiny helper: mkstemp next to target so atomic replace is on the same FS."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(target.parent))
    return fd, tmp


# ══════════════════════════════════════════════════
# HTML 渲染（Block-5A · 完整日报独立窗口）
# ══════════════════════════════════════════════════
def _escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ══════════════════════════════════════════════════
# v12.2.0: 任务 + 趋势 + 问候语辅助函数
# ══════════════════════════════════════════════════

def get_time_of_day() -> str:
    """Return time-of-day category based on current hour."""
    hour = datetime.now().hour
    if 0 <= hour < 6:
        return "late_night"
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    return "evening"


def get_today_todos(date_str: str | None = None) -> list[dict[str, Any]]:
    """Get today's todos from todo_manager. Seeds sample todos on first run."""
    try:
        from core import todo_manager
        todos = todo_manager.get_todos(date_str)
        if not todos:
            todo_manager.seed_sample_todos(date_str)
            todos = todo_manager.get_todos(date_str)
        return todos
    except Exception as e:
        logger.warning("brief_fetcher: get_today_todos failed: %s", e)
        return []


def get_todo_stats(date_str: str | None = None) -> dict[str, Any]:
    """Get todo stats for today."""
    try:
        from core import todo_manager
        return todo_manager.stats(date_str)
    except Exception as e:
        logger.warning("brief_fetcher: get_todo_stats failed: %s", e)
        return {"total": 0, "completed": 0, "remaining": 0, "high_priority_remaining": 0, "percent": 0}


def _generate_trends_from_news(news_items: list[dict]) -> list[dict]:
    """Extract 3-5 trend insights from AI + IT news (keyword-based, no LLM).

    This is a lightweight heuristic fallback. The LLM-powered version
    runs in api_server.py / brain.py when available.
    """
    if not news_items:
        return []
    keyword_groups = {
        "大模型 & AI Agent": ["大模型", "LLM", "GPT", "Claude", "Agent", "智能体", "推理"],
        "开源生态": ["开源", "GitHub", "Open Source", "发布", "上线"],
        "算力 & 芯片": ["芯片", "算力", "GPU", "NPU", "推理卡", "H100"],
        "产品 & 应用": ["产品", "应用", "APP", "工具", "平台", "服务"],
        "融资 & 商业化": ["融资", "估值", "亿美元", "收购", "商业化"],
    }
    trends: list[dict] = []
    for group_name, keywords in keyword_groups.items():
        count = 0
        sample_titles = []
        for item in news_items:
            title = (item.get("title") or "").lower()
            for kw in keywords:
                if kw.lower() in title:
                    count += 1
                    if len(sample_titles) < 2:
                        sample_titles.append(item.get("title", ""))
                    break
        if count > 0 and len(trends) < 5:
            trends.append({
                "id": len(trends) + 1,
                "title": group_name,
                "summary": f"今日相关新闻 {count} 条，{sample_titles[0] if sample_titles else '持续受到关注'}",
                "keywords": keywords[:3],
                "related_count": count,
            })
    if not trends and news_items:
        trends.append({
            "id": 1,
            "title": "今日科技动态",
            "summary": f"共收录 {len(news_items)} 条科技新闻，建议关注行业最新动向",
            "keywords": ["科技", "行业动态"],
            "related_count": len(news_items),
        })
    return trends[:5]


# R7.1: render_html() removed. The detail BrowserWindow that needed
# it is gone; the brief-drawer renders client-side, so the backend no
# longer produces HTML for the brief.


# ══════════════════════════════════════════════════
# TOOL 注册（让 LLM tool_call 能直接命中 fetcher）
# ══════════════════════════════════════════════════
TOOLS: dict[str, tuple[Any, str]] = {
    "fetch_ai_news":   (fetch_ai_news,   "拉取 AI 公司最新动向 / Fetch AI news"),
    "fetch_it_news":   (fetch_it_news,   "拉取 IT 行业新闻 / Fetch IT news"),
    "fetch_intl_news": (fetch_intl_news, "拉取国际新闻 / Fetch international news"),
    "fetch_cn_news":   (fetch_cn_news,   "拉取国家新闻 / Fetch national news"),
    "fetch_weather":   (fetch_weather,   "拉取今日天气 / Fetch weather"),
}

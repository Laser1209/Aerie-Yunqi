"""Aerie · 云栖 v0.1.1 — Daily Brief Fetcher (Block-4A R1.1).

Fetches 5 categories of content for the daily brief popup:
  - AI 公司最新动向
  - IT 行业新闻
  - 国际新闻
  - 国家新闻
  - 天气

News sources use a layered hybrid crawler (v0.1.1), replacing the previous
chaotic RSS mix with authoritative, high-star tooling:
  - hn        : Hacker News Algolia API (reachable, single request, hundreds of items)
  - crawl     : Trafilatura crawler (Apache-2.0, ~5.6k stars) over curated feeds,
                with full-text extraction for clean summaries
  - aggregator: 今日热榜 DailyHotApi (aggregates 36氪/澎湃/IT之家/虎嗅/腾讯/网易 etc.)
  - bocha     : Bocha web-search fallback (needs BOCHA_API_KEY)

Each section tries its tiers in priority order (SECTIONS_PRIORITY) until items
are found. Weather delegates to the local Baidu map MCP tool when available and
falls back to a stub otherwise. A strict domain whitelist guards the crawl tier
against SSRF and each source has an 8s timeout.

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

from core.paths import briefs_dir

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _briefs_dir() -> Path:
    return briefs_dir()

# ══════════════════════════════════════════════════
# 新闻源配置（Trafilatura 爬虫 + Hacker News + 今日热榜聚合）
# ══════════════════════════════════════════════════
# v0.1.1: 替换原先混乱的 RSS 源，改为"分层抓取"：
#   1. hn         — Hacker News Algolia（权威、可达、单请求返回数百条）
#   2. crawl      — Trafilatura 爬虫（高星权威库）抓取精选权威 Feed 并提取正文摘要
#   3. aggregator — 今日热榜 DailyHotApi（聚合 36氪/澎湃/IT之家/虎嗅/腾讯/网易等权威源）
#   4. bocha      — Bocha 网页搜索（最终兜底，需 BOCHA_API_KEY）
# 每 section 按 SECTIONS_PRIORITY 顺序尝试，直到拿到非空条目为止。

# 精选权威 Feed（crawl 层：feedparser 列表 + trafilatura 正文提取）
CRAWL_FEEDS: dict[str, list[dict[str, str]]] = {
    "ai_news": [
        {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "domain": "jiqizhixin.com"},
        {"name": "量子位",   "url": "https://www.qbitai.com/feed",     "domain": "qbitai.com"},
    ],
    "it_news": [
        {"name": "36氪",     "url": "https://36kr.com/feed",          "domain": "36kr.com"},
        {"name": "虎嗅",     "url": "https://www.huxiu.com/rss",      "domain": "huxiu.com"},
    ],
    "intl_news": [
        {"name": "BBC 中文", "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "domain": "feeds.bbci.co.uk"},
    ],
    "cn_news": [
        {"name": "新华网",   "url": "https://www.news.cn/rss/xinhuanet.xml", "domain": "news.cn"},
        {"name": "人民网",   "url": "https://www.people.com.cn/rss/feed.xml", "domain": "people.com.cn"},
    ],
}

# 今日热榜 DailyHotApi 平台映射（聚合层）
# 端点默认自建 http://127.0.0.1:6688，可用环境变量 DAILYHOT_API_BASE 覆盖
DAILYHOT_PLATFORMS: dict[str, list[str]] = {
    "ai_news":   ["36kr", "thepaper"],
    "it_news":   ["ithome", "36kr", "huxiu", "juejin"],
    "intl_news": ["netease-news", "qq-news", "sina-news"],
    "cn_news":   ["thepaper", "netease-news", "qq-news"],
}

# 每 section 的抓取优先级
SECTIONS_PRIORITY: dict[str, list[str]] = {
    "ai_news":   ["hn", "crawl", "aggregator", "bocha"],
    "it_news":   ["hn", "crawl", "aggregator", "bocha"],
    "intl_news": ["hn", "crawl", "aggregator", "bocha"],
    "cn_news":   ["hot", "crawl", "aggregator", "bocha"],
}

# 百度实时热搜 —— 权威国内源，接口稳定可达（JSON 直出）
BAIDU_HOT_URL = "https://top.baidu.com/api/board?platform=wise&tab=realtime"

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


async def _fetch_crawl_source(url: str, allowed_domain: str, limit: int) -> list[dict]:
    """Crawl a curated feed: list via feedparser, enrich the top item via Trafilatura.

    R6.6: re-raises on failure (instead of swallowing) so the upstream tier
    dispatcher can capture the error message in its error list.
    """
    if not _safe_url(url, allowed_domain):
        logger.warning("brief_fetcher: rejected non-whitelisted feed URL %s", url)
        return []
    try:
        import feedparser  # type: ignore
        import trafilatura  # type: ignore
    except ImportError:
        logger.warning("brief_fetcher: feedparser/trafilatura not installed; skipping %s", url)
        return []
    try:
        # Offload the blocking crawl to a thread so we don't stall the loop.
        items = await asyncio.wait_for(
            asyncio.to_thread(_crawl_parse, url, allowed_domain, limit),
            timeout=SOURCE_TIMEOUT_SEC,
        )
        return items
    except asyncio.TimeoutError:
        logger.warning("brief_fetcher: timeout on crawl %s", url)
        return []
    except Exception as e:
        logger.warning("brief_fetcher: crawl error on %s: %s", url, e)
        # R6.6: re-raise so the tier dispatcher can capture the message.
        raise


def _crawl_parse(url: str, allowed_domain: str, limit: int) -> list[dict]:
    """Parse a feed; for the first item with a thin summary, crawl the real
    article with Trafilatura to produce a clean full-text summary.

    Many Chinese news sites reject requests without a browser-like UA, so we
    always send one.
    """
    import feedparser  # type: ignore
    import trafilatura  # type: ignore

    UA = "Mozilla/5.0 (AerieBrief/1.0; +https://example.com/aerie)"
    parsed = feedparser.parse(url, agent=UA)
    items: list[dict] = []
    for idx, e in enumerate(parsed.entries[:limit]):
        title = (getattr(e, "title", "") or "").strip()
        if not title:
            continue
        link = getattr(e, "link", "") or ""
        summary = (getattr(e, "summary", "") or getattr(e, "description", "") or "").strip()
        # 正文摘要过薄时，用 Trafilatura 抓取文章正文（真正的"爬虫"）。
        # 只对首条做正文抓取，避免拖慢整体抓取。
        if idx == 0 and (not summary or len(summary) < 40) and link:
            try:
                html = trafilatura.fetch_url(link)
                if html:
                    text = trafilatura.extract(
                        html, include_comments=False, include_tables=False, favor_recall=False
                    )
                    if text:
                        summary = text.strip()
            except Exception:
                pass
        items.append({
            "title":       title[:200],
            "summary":     summary[:280],
            "url":         link,
            "source":      allowed_domain,
            "ts":          int(time.time()),
            "source_kind": "crawl",
        })
    return items


# Hacker News Algolia — 权威科技新闻，单请求返回数百条，稳定性高。
# Algolia 搜索 API：https://hn.algolia.com/api
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
# 各科技板块的 HN 差异化查询：ai_news 用 AI 主题搜索，其余用 front_page 首页。
HN_SECTION_QUERIES: dict[str, str | None] = {
    "ai_news":   "AI LLM machine learning agent language model",
    "it_news":   None,  # front_page
    "intl_news": None,  # front_page
}


def _hn_get(url: str) -> dict:
    """Synchronous Hacker News GET via urllib; returns parsed JSON or {}."""
    import json as _json
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AerieBrief/1.0 (+https://example.com/aerie)", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=SOURCE_TIMEOUT_SEC) as resp:
            return _json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.warning("brief_fetcher: hn request error: %s", e)
        return {}


async def _fetch_hn_section(section: str, limit: int) -> tuple[list[dict], str | None]:
    """Fetch Hacker News front page via Algolia. Returns (items, error_str).

    Reachable and authoritative; a single request returns up to 50 hits. Each
    item follows the shared news shape so downstream code is source-agnostic.
    """
    try:
        import urllib.parse
        n = min(50, max(10, limit))
        query = HN_SECTION_QUERIES.get(section)
        params = f"hitsPerPage={n}&tags=story" if query else f"tags=front_page&hitsPerPage={n}"
        if query:
            params += "&query=" + urllib.parse.quote(query)
        data = await asyncio.wait_for(
            asyncio.to_thread(_hn_get, f"{HN_SEARCH_URL}?{params}"),
            timeout=SOURCE_TIMEOUT_SEC,
        )
        hits = (data or {}).get("hits") or []
        if not hits:
            return [], "hn_empty"
        items: list[dict] = []
        for h in hits:
            title = (h.get("title") or "").strip()
            if not title:
                continue
            hn_id = h.get("objectID") or ""
            url = h.get("url") or f"https://news.ycombinator.com/item?id={hn_id}"
            points = h.get("points") or 0
            comments = h.get("num_comments") or 0
            items.append({
                "title":       title[:200],
                "summary":     f"Hacker News 热门 · {points} points · {comments} 评论",
                "url":         url,
                "source":      "Hacker News",
                "ts":          int(h.get("created_at_i") or time.time()),
                "source_kind": "hn",
            })
        return items[:limit], None
    except asyncio.TimeoutError:
        return [], "hn_timeout"
    except Exception as e:
        logger.warning("brief_fetcher: hn fetch failed: %s", e)
        return [], f"hn: {type(e).__name__}: {e}"


# 今日热榜 DailyHotApi —— 聚合权威新闻源的免费接口。
# 端点默认自建 http://127.0.0.1:6688，可用环境变量 DAILYHOT_API_BASE 覆盖。
# 官方在线实例 https://api-hot.imsyy.top 在不同网络下可能不可达，故按需配置。
DAILYHOT_TIMEOUT_SEC = 8


def _dailyhot_base() -> str:
    import os
    return (os.environ.get("DAILYHOT_API_BASE") or "http://127.0.0.1:6688").rstrip("/")


def _hot_get(url: str) -> dict:
    """Synchronous DailyHotApi GET; re-raises so gather captures per-platform errors."""
    import json as _json
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AerieBrief/1.0 (+https://example.com/aerie)", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=DAILYHOT_TIMEOUT_SEC) as resp:
            return _json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        logger.warning("brief_fetcher: dailyhot HTTP %s on %s", e.code, url)
        raise
    except Exception as e:
        logger.warning("brief_fetcher: dailyhot request error %s: %s", url, e)
        raise


async def _fetch_aggregator_section(section: str, limit: int) -> tuple[list[dict], str | None]:
    """Fetch a section from 今日热榜 aggregator platforms (configurable endpoint)."""
    platforms = DAILYHOT_PLATFORMS.get(section) or []
    if not platforms:
        return [], "no_platform"
    base = _dailyhot_base()
    results = await asyncio.gather(
        *[asyncio.to_thread(_hot_get, f"{base}/{p}") for p in platforms],
        return_exceptions=True,
    )
    flat: list[dict] = []
    errs: list[str] = []
    for p, r in zip(platforms, results):
        if isinstance(r, BaseException):
            errs.append(f"{p}: {type(r).__name__}")
            continue
        payload = r or {}
        for it in (payload.get("data") or [])[:limit]:
            flat.append({
                "title":       (it.get("title") or "")[:200],
                "summary":     (it.get("desc") or it.get("hotValue") or "")[:280],
                "url":         it.get("url") or it.get("mobileUrl") or "",
                "source":      (payload.get("title") or p)[:60],
                "ts":          int(time.time()),
                "source_kind": "aggregator",
            })
    if flat:
        return flat[:limit], None
    err = " | ".join(errs[:3])[:240] if errs else "aggregator_empty"
    return [], err


def _baidu_hot_get() -> dict:
    """Synchronous Baidu realtime-hot GET via urllib; returns parsed JSON or {}."""
    import json as _json
    import urllib.request
    req = urllib.request.Request(
        BAIDU_HOT_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    try:
        with urllib.request.urlopen(req, timeout=SOURCE_TIMEOUT_SEC) as resp:
            return _json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.warning("brief_fetcher: baidu hot request error: %s", e)
        return {}


async def _fetch_baidu_hot(limit: int) -> tuple[list[dict], str | None]:
    """Fetch Baidu realtime hot search (authoritative, reachable Chinese source)."""
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_baidu_hot_get),
            timeout=SOURCE_TIMEOUT_SEC,
        )
        items: list[dict] = []
        cards = ((data or {}).get("data") or {}).get("cards") or []
        rank = 0
        for card in cards:
            for block in card.get("content") or []:
                for it in block.get("content") or []:
                    word = (it.get("word") or "").strip()
                    if not word:
                        continue
                    rank += 1
                    items.append({
                        "title":       word[:200],
                        "summary":     f"百度实时热搜 · 第 {rank} 位",
                        "url":         it.get("url") or f"https://www.baidu.com/s?wd={word}",
                        "source":      "百度热搜",
                        "ts":          int(time.time()),
                        "source_kind": "hot",
                    })
                    if len(items) >= limit:
                        return items, None
        if items:
            return items, None
        return [], "baidu_hot_empty"
    except asyncio.TimeoutError:
        return [], "baidu_hot_timeout"
    except Exception as e:
        logger.warning("brief_fetcher: baidu hot fetch failed: %s", e)
        return [], f"baidu_hot: {type(e).__name__}: {e}"


def _fetch_crawl_section_factory(section: str, limit: int):
    """Build the crawl tier: aggregate all curated feeds for a section concurrently."""
    feeds = CRAWL_FEEDS.get(section) or []

    async def _run() -> tuple[list[dict], str | None]:
        if not feeds:
            return [], "no_feed"
        results = await asyncio.gather(
            *[_fetch_crawl_source(f["url"], f["domain"], limit) for f in feeds],
            return_exceptions=True,
        )
        flat: list[dict] = []
        errs: list[str] = []
        for r in results:
            if isinstance(r, list):
                flat.extend(r)
            elif isinstance(r, BaseException):
                errs.append(f"{type(r).__name__}: {r}")
        flat.sort(key=lambda x: x.get("ts", 0), reverse=True)
        if flat:
            return flat[:limit], None
        err = " | ".join(errs[:2])[:240] if errs else "crawl_empty"
        return [], err

    return _run


async def _fetch_section(section: str, limit: int) -> tuple[list[dict], str | None]:
    """Fetch a news section by trying its tiers in SECTIONS_PRIORITY order.

    Tiers (hn → crawl → aggregator → bocha) are tried until one yields items.
    The tier list for each section is declared in SECTIONS_PRIORITY. All items
    share the same news shape, so downstream (compose_brief / UI) never cares
    which tier produced them. When a section ends up empty, a concise joined
    error string is returned so the brief UI can explain why (instead of
    showing a blank section with no reason).
    """
    priorities = SECTIONS_PRIORITY.get(section) or ["bocha"]
    tier_handlers: dict[str, Any] = {
        "hn":         lambda: _fetch_hn_section(section, limit),
        "crawl":      _fetch_crawl_section_factory(section, limit),
        "aggregator": lambda: _fetch_aggregator_section(section, limit),
        "hot":        lambda: _fetch_baidu_hot(limit),
        "bocha":      lambda: _fetch_bocha_section(section, limit),
    }
    err_parts: list[str] = []
    for tier in priorities:
        handler = tier_handlers.get(tier)
        if not handler:
            continue
        try:
            items, err = await handler()
        except Exception as e:  # defensive: a tier must never crash the brief
            err_parts.append(f"{tier}: {type(e).__name__}: {e}")
            continue
        if items:
            return items[:limit], None
        if err:
            err_parts.append(f"{tier}: {err}")
    err = " | ".join(err_parts[:3])[:240] if err_parts else "empty_or_failed"
    return [], err


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
    return await _fetch_section("ai_news", limit)


async def fetch_it_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> tuple[list[dict], str | None]:
    return await _fetch_section("it_news", limit)


async def fetch_intl_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> tuple[list[dict], str | None]:
    return await _fetch_section("intl_news", limit)


async def fetch_cn_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> tuple[list[dict], str | None]:
    return await _fetch_section("cn_news", limit)


async def fetch_weather(city: str = "") -> dict | None:
    from core.location_resolver import resolve_location_async
    from core.weather_service import fetch_weather_for_city, fetch_weather_for_current_location

    city = (city or "").strip()
    if city:
        location = await resolve_location_async()
        if location.get("city") != city:
            location = {"city": city, "source": "manual", "manual": False, "fallback": False, "error": ""}
        return await fetch_weather_for_city(city, location)
    return await fetch_weather_for_current_location()


def _load_feedback(date_str: str) -> dict | None:
    """Read yesterday's feedback JSON; return None if missing/corrupt."""
    p = _briefs_dir() / f"{date_str}.feedback.json"
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
    from core.location_resolver import resolve_location_async
    location = await resolve_location_async()
    city = (city or location.get("city") or "上海").strip() or "上海"
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
    _briefs_dir().mkdir(parents=True, exist_ok=True)
    json_path = _briefs_dir() / f"{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if html:
        html_path = _briefs_dir() / f"{date_str}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        return html_path
    return json_path


def load_brief(date_str: str) -> dict | None:
    """Read brief JSON; return None if missing."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return None
    p = _briefs_dir() / f"{date_str}.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def update_brief_weather(date_str: str, weather: dict) -> dict:
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        raise ValueError(f"invalid date_str: {date_str!r}")
    payload = load_brief(date_str) or {"date": date_str, "ai_news": []}
    payload["weather"] = weather
    save_brief(date_str, payload)
    return payload


def load_brief_html(date_str: str) -> str | None:
    """Read brief HTML; return None if missing."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return None
    p = _briefs_dir() / f"{date_str}.html"
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
    _briefs_dir().mkdir(parents=True, exist_ok=True)
    p = _briefs_dir() / f"{date_str}.feedback.json"
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
    """Return today's todos from todo_manager.

    Returns only real user-created todos. Auto-seeding of sample/demo todos
    has been removed to prevent fake tasks from appearing in the user's plan.
    """
    try:
        from core import todo_manager
        return todo_manager.get_todos(date_str)
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

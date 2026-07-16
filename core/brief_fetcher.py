"""Aerie · 云栖 v9.0 — Daily Brief Fetcher (Block-4A R1.1).

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
        {"name": "BBC 中文",    "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "domain": "bbc.co.uk"},
        {"name": "路透中文",    "url": "https://cn.reuters.com/rss/CNTopGenNews", "domain": "reuters.com"},
    ],
    # 国家新闻
    "cn_news": [
        {"name": "新华网",      "url": "http://www.news.cn/rss/xinhuanet.xml",   "domain": "news.cn"},
        {"name": "人民网",      "url": "http://www.people.com.cn/rss/feed.xml",  "domain": "people.com.cn"},
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
    """Fetch a single RSS feed; return up to `limit` items."""
    if not _safe_url(url, allowed_domain):
        logger.warning("brief_fetcher: rejected non-whitelisted URL %s", url)
        return []
    try:
        import feedparser  # type: ignore
    except ImportError:
        logger.warning("brief_fetcher: feedparser not installed; skipping")
        return []
    try:
        # Offload the blocking feedparser call to a thread so we don't stall the loop.
        def _parse() -> list[dict]:
            parsed = feedparser.parse(url)
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

        items = await asyncio.wait_for(
            asyncio.to_thread(_parse),
            timeout=SOURCE_TIMEOUT_SEC,
        )
        return items
    except asyncio.TimeoutError:
        logger.warning("brief_fetcher: timeout on %s", url)
        return []
    except Exception as e:
        logger.warning("brief_fetcher: error on %s: %s", url, e)
        return []


async def _fetch_section(
    section: str, sources: list[dict], limit: int
) -> tuple[list[dict], str | None]:
    """Fetch all RSS sources for a section concurrently; aggregate + cap."""
    results = await asyncio.gather(
        *[_fetch_rss_source(s["url"], s["domain"], limit) for s in sources],
        return_exceptions=True,
    )
    flat: list[dict] = []
    for r in results:
        if isinstance(r, list):
            flat.extend(r)
    flat.sort(key=lambda x: x.get("ts", 0), reverse=True)
    err: str | None = None
    if not flat:
        err = "empty_or_failed"
    return flat[:limit], err


async def fetch_ai_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> list[dict]:
    items, _ = await _fetch_section("ai_news", RSS_SOURCES["ai_news"], limit)
    return items


async def fetch_it_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> list[dict]:
    items, _ = await _fetch_section("it_news", RSS_SOURCES["it_news"], limit)
    return items


async def fetch_intl_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> list[dict]:
    items, _ = await _fetch_section("intl_news", RSS_SOURCES["intl_news"], limit)
    return items


async def fetch_cn_news(limit: int = DEFAULT_LIMIT_PER_SECTION) -> list[dict]:
    items, _ = await _fetch_section("cn_news", RSS_SOURCES["cn_news"], limit)
    return items


async def fetch_weather(city: str = "上海") -> dict | None:
    """Try the Baidu map MCP tool; fall back to None on failure.

    R1.1 keeps the call dynamic (importlib) so the brief still runs when
    the MCP server is offline.
    """
    try:
        # Local import — `mcp_Bai_Du_Di_Tu` is only available on this machine.
        from mcp_Bai_Du_Di_Tu import map_weather  # type: ignore
    except Exception:
        logger.debug("brief_fetcher: map_weather MCP unavailable; using stub")
        return {
            "city": city,
            "temp": "—",
            "desc": "暂无 / unavailable",
            "suggestion": "穿合适的衣服。",
            "ts": int(time.time()),
            "stub": True,
        }
    try:
        result = await asyncio.to_thread(map_weather, city=city)
        return {
            "city": city,
            "temp": str(result.get("temperature", "—")),
            "desc": str(result.get("weather", "—")),
            "suggestion": str(result.get("suggestion", "")),
            "ts": int(time.time()),
        }
    except Exception as e:
        logger.warning("brief_fetcher: map_weather error: %s", e)
        return None


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


async def run_all(city: str = "上海", feedback: dict | None = None) -> dict:
    """Concurrently fetch 5 sections within TOTAL_TIMEOUT_SEC.

    Returns a dict ready for LLM compose_brief() consumption.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if feedback is None:
        # default: load yesterday's feedback to influence today's section depth
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        feedback = _load_feedback(yesterday)

    try:
        result = await asyncio.wait_for(
            asyncio.gather(
                fetch_ai_news(_limit_for_section("ai_news", feedback)),
                fetch_it_news(_limit_for_section("it_news", feedback)),
                fetch_intl_news(_limit_for_section("intl_news", feedback)),
                fetch_cn_news(_limit_for_section("cn_news", feedback)),
                fetch_weather(city),
                return_exceptions=True,
            ),
            timeout=TOTAL_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning("brief_fetcher: total timeout %ds exceeded", TOTAL_TIMEOUT_SEC)
        return {"date": today, "errors": {"global": "total_timeout"}, "ts": int(time.time())}

    ai_news, it_news, intl_news, cn_news, weather = result
    errors: dict[str, str] = {}
    if isinstance(ai_news, Exception):   errors["ai_news"]   = str(ai_news)
    if isinstance(it_news, Exception):   errors["it_news"]   = str(it_news)
    if isinstance(intl_news, Exception): errors["intl_news"] = str(intl_news)
    if isinstance(cn_news, Exception):   errors["cn_news"]   = str(cn_news)
    if isinstance(weather, Exception):   errors["weather"]   = str(weather)

    return {
        "date": today,
        "ai_news":   ai_news if isinstance(ai_news, list) else [],
        "it_news":   it_news if isinstance(it_news, list) else [],
        "intl_news": intl_news if isinstance(intl_news, list) else [],
        "cn_news":   cn_news if isinstance(cn_news, list) else [],
        "weather":   weather if isinstance(weather, dict) else None,
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


def render_html(payload: dict) -> str:
    """Render a full daily-brief HTML page for the 1280x800 detail window.

    输入: run_all() 的输出 dict (date / ai_news / it_news / intl_news /
    cn_news / weather / errors)。
    输出: 完整 HTML 字符串（不依赖 jinja2，纯 f-string 拼装）。
    """
    date = payload.get("date", "")
    sections = [
        ("AI 动向 / AI Trends",   "ai_news",   payload.get("ai_news")),
        ("IT 行业 / Tech Industry", "it_news",   payload.get("it_news")),
        ("国际新闻 / International", "intl_news", payload.get("intl_news")),
        ("国家新闻 / National",    "cn_news",   payload.get("cn_news")),
    ]

    def _items_html(items):
        if not isinstance(items, list) or not items:
            return '<p class="bd-empty">（暂无）</p>'
        out = []
        for i, it in enumerate(items, 1):
            title = _escape((it.get("title") or "").strip())
            summary = _escape((it.get("summary") or "").strip())
            url = _escape(it.get("url") or "")
            source = _escape(it.get("source") or "")
            link = (
                f'<a href="{url}" target="_blank" rel="noopener">{title}</a>'
                if url else title
            )
            out.append(
                f'<li class="bd-item">'
                f'<span class="bd-idx">{i:02d}</span>'
                f'<div class="bd-body"><h3 class="bd-title">{link}</h3>'
                + (f'<p class="bd-summary">{summary}</p>' if summary else "")
                + f'<span class="bd-src">{source}</span></div></li>'
            )
        return "<ul class='bd-list'>" + "".join(out) + "</ul>"

    weather = payload.get("weather") or {}
    w_city = _escape(weather.get("city", "—"))
    w_desc = _escape(f"{weather.get('desc', '—')} · {weather.get('temp', '—')}℃")
    w_hint = _escape(weather.get("suggestion", "") or "")

    sections_html = "".join(
        f'<section class="bd-section" id="bd-{sid}">'
        f'<header><h2>{title}</h2><span class="bd-count">'
        f'{len(items) if isinstance(items, list) else 0}</span></header>'
        f'{_items_html(items)}</section>'
        for (title, sid, items) in sections
    )

    errors = payload.get("errors") or {}
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_escape(k)}: {_escape(v)}</li>" for k, v in errors.items())
        errors_html = (
            f'<section class="bd-errors"><h3>抓取异常 / Fetch errors</h3>'
            f'<ul>{items}</ul></section>'
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<title>完整日报 / Full Daily Brief · {date}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #fafafa; color: #1a1a1a; margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  .bd-meta {{ color: #888; font-size: 12px; margin-bottom: 18px; }}
  .bd-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  .bd-section {{ background: #fff; border: 1px solid #eee; border-radius: 12px;
                padding: 16px 18px; }}
  .bd-section header {{ display: flex; justify-content: space-between;
                        align-items: center; border-bottom: 1px dashed #eee;
                        padding-bottom: 8px; margin-bottom: 10px; }}
  .bd-section h2 {{ font-size: 14px; margin: 0; }}
  .bd-count {{ font-size: 11px; color: #888; background: #f4f4f4;
               border-radius: 999px; padding: 1px 8px; }}
  .bd-list {{ list-style: none; padding: 0; margin: 0; display: flex;
              flex-direction: column; gap: 10px; }}
  .bd-item {{ display: flex; gap: 10px; }}
  .bd-idx {{ font-size: 11px; color: #007aff; background: #e8f1ff;
             border-radius: 6px; padding: 2px 6px; min-width: 22px;
             text-align: center; font-family: ui-monospace, monospace; }}
  .bd-title {{ font-size: 13.5px; margin: 0 0 4px 0; }}
  .bd-title a {{ color: #1a1a1a; text-decoration: none;
                 border-bottom: 1px dashed #aaa; }}
  .bd-summary {{ font-size: 12px; color: #555; margin: 0 0 4px 0; }}
  .bd-src {{ font-size: 10.5px; color: #aaa; }}
  .bd-empty {{ color: #aaa; font-style: italic; padding: 8px 0; }}
  .bd-weather {{ display: flex; gap: 12px; align-items: center;
                 background: #fff; border: 1px solid #eee; border-radius: 12px;
                 padding: 14px 18px; margin-top: 18px; }}
  .bd-weather strong {{ font-size: 14px; }}
  .bd-errors {{ margin-top: 18px; padding: 12px 16px; background: #fff8e1;
                border: 1px solid #ffe082; border-radius: 8px; font-size: 12px; }}
</style>
</head>
<body>
<h1>完整日报 / Full Daily Brief</h1>
<p class="bd-meta">日期 / Date: <strong>{date}</strong></p>
<div class="bd-grid">
  {sections_html}
</div>
<div class="bd-weather">
  <strong>天气 / Weather</strong>
  <span>{w_city}</span>
  <span>{w_desc}</span>
  <span style="color:#888; font-size: 12px;">{w_hint}</span>
</div>
{errors_html}
</body>
</html>"""


def export_brief_html(date_str: str, payload: dict) -> str:
    """Render + persist full HTML; return file path string.

    Path-traversal guard via date_str regex.
    """
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        raise ValueError(f"invalid date_str: {date_str!r}")
    html = render_html(payload)
    _DATA_BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    p = _DATA_BRIEFS_DIR / f"{date_str}.full.html"
    p.write_text(html, encoding="utf-8")
    return str(p)


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

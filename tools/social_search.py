"""通用多平台关键词搜索（JustOneAPI 聚合 API 主通道）。

覆盖 26 个平台的搜索端点（path 与参数参考仓库 justoneapi-mcp/ 的 catalog）。
不同平台返回结构差异大，这里做通用字段抽取（title/url/指标），尽力而为；
对抖音等已精确解析的平台建议直接用 douyin_search。
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import httpx

from tools.douyin_search import _get_base_url, _get_token

logger = logging.getLogger(__name__)

# 平台 -> 搜索端点配置：path, 关键词参数名, 显示名
PLATFORMS: dict[str, dict] = {
    "douyin": {"path": "/api/douyin/search-video/v4", "kw": "keyword", "label": "抖音"},
    "taobao": {"path": "/api/taobao/search-item-list/v1", "kw": "keyword", "label": "淘宝"},
    "xiaohongshu": {"path": "/api/xiaohongshu/search-note/v4", "kw": "keyword", "label": "小红书", "parser": "xiaohongshu"},
    "xiaohongshu_pgy": {
        "path": "/api/xiaohongshu-pgy/api/pgy/content_square/search_note_v2/v1",
        "kw": "search_word",
        "label": "小红书蒲公英",
    },
    "douyin_ec": {"path": "/api/douyin-ec/search-item-list/v1", "kw": "keyword", "label": "抖音电商"},
    "douyin_xingtu": {
        "path": "/api/douyin-xingtu/gw/api/gsearch/search_for_author_square/v1",
        "kw": "keyword",
        "label": "抖音星图",
    },
    "kuaishou": {"path": "/api/kuaishou/search-video/v2", "kw": "keyword", "label": "快手"},
    "weixin": {"path": "/api/weixin/search-article/v2", "kw": "keyword", "label": "微信公众号"},
    "weixin_channels": {"path": "/api/weixin-channels/search-video/v2", "kw": "keyword", "label": "微信视频号"},
    "qq_huxuan": {
        "path": "/api/qq-huxuan/cgi-bin/advertiser/finder_publisher/search/v1",
        "kw": "keyword",
        "label": "腾讯互选",
    },
    "weibo": {"path": "/api/weibo/search-all/v2", "kw": "q", "label": "微博", "special": "weibo"},
    "bilibili": {"path": "/api/bilibili/search-video/v2", "kw": "keyword", "label": "哔哩哔哩"},
    "jd": {"path": "/api/jd/search-item-list/v2", "kw": "keyword", "label": "京东"},
    "xianyu": {"path": "/api/xianyu/search-item-list/v1", "kw": "keyword", "label": "闲鱼"},
    "alibaba1688": {"path": "/api/1688/search-item-list/v1", "kw": "keyword", "label": "阿里巴巴1688"},
    "tiktok": {"path": "/api/tiktok/search-post/v1", "kw": "keyword", "label": "TikTok"},
    "tiktok_shop": {"path": "/api/tiktok-shop/search-products/v1", "kw": "keyword", "label": "TikTok Shop"},
    "youku": {"path": "/api/youku/search-video/v1", "kw": "keyword", "label": "优酷"},
    "instagram": {"path": "/api/instagram/search-reels/v1", "kw": "keyword", "label": "Instagram"},
    "youtube": {"path": "/api/youtube/search/v1", "kw": "keyword", "label": "YouTube"},
    "reddit": {"path": "/api/reddit/search/v1", "kw": "keyword", "label": "Reddit"},
    "toutiao": {"path": "/api/toutiao/search/v2", "kw": "keyword", "label": "今日头条"},
    "zhihu": {"path": "/api/zhihu/search/v1", "kw": "keyword", "label": "知乎"},
    "amazon": {"path": "/api/amazon/search-products/v1", "kw": "keyword", "label": "亚马逊"},
    "facebook": {"path": "/api/facebook/search-post/v1", "kw": "keyword", "label": "Facebook"},
    "twitter": {"path": "/api/twitter/search/v1", "kw": "keyword", "label": "Twitter"},
}

_METRIC_KEYS = (
    "digg_count", "like_count", "liked_count", "likeCount", "likes",
    "play_count", "playCount", "view_count", "views", "watch_num",
    "comment_count", "commentCount", "comments",
    "share_count", "collect_count", "sale_count", "price",
)
_TITLE_KEYS = (
    "title", "description", "desc", "name", "text", "note_title",
    "video_title", "item_title", "note", "content", "caption", "brief",
)
_URL_KEYS = (
    "share_url", "shareUrl", "url", "link", "web_url", "video_url",
    "note_url", "href", "jump_url", "page_url", "aweme_url",
)


def _first(*values: Any) -> Any:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _pick_text(node: Any) -> str:
    if isinstance(node, str):
        return _strip_html(node)
    if not isinstance(node, dict):
        return ""
    for k in _TITLE_KEYS:
        v = node.get(k)
        if isinstance(v, str) and len(v) > 1:
            return _strip_html(v)
    return ""


def _pick_url(node: Any) -> str:
    """递归查找第一个 http 链接。"""
    if isinstance(node, str):
        return node if node.startswith("http") else ""
    if isinstance(node, dict):
        for v in node.values():
            u = _pick_url(v)
            if u:
                return u
    elif isinstance(node, list):
        for v in node:
            u = _pick_url(v)
            if u:
                return u
    return ""


_METRIC_LOWER = {k.lower() for k in _METRIC_KEYS}


def _extract_metrics(node: Any, depth: int = 0) -> dict:
    """递归收集常见数值指标（键名大小写不敏感）。"""
    out: dict[str, Any] = {}
    if not isinstance(node, dict) or depth > 3:
        return out
    for k, v in node.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and k.lower() in _METRIC_LOWER:
            out.setdefault(k, v)
        elif isinstance(v, dict):
            for kk, vv in _extract_metrics(v, depth + 1).items():
                out.setdefault(kk, vv)
    return out


def _walk_lists(obj: Any):
    """DFS 产出所有 list 值。"""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_lists(v)
    elif isinstance(obj, list):
        yield obj
        for x in obj:
            yield from _walk_lists(x)


_NOISE = {
    "屏蔽推广", "我要投诉", "我为什么会看到此推广", "详细了解", "立即查看",
    "为您推荐", "广告", "热门话题", "点击查看", "展开更多",
}


def _extract_generic_items(data: Any, limit: int) -> list[dict]:
    """从响应 data 中启发式抽取记录列表（title/url/指标）。"""
    candidates: list[list[dict]] = []
    for lst in _walk_lists(data):
        if not lst or not isinstance(lst[0], dict):
            continue
        items: list[dict] = []
        for x in lst[:limit]:
            if not isinstance(x, dict):
                continue
            title = _pick_text(x)
            if not title or title in _NOISE:
                continue
            url = _pick_url(x)
            metrics = _extract_metrics(x)
            items.append({"title": title, "url": url, "metrics": metrics, "raw": x})
        if items:
            candidates.append(items)
    if not candidates:
        return []
    # 取最完整（条数最多）的候选列表
    best = max(candidates, key=len)
    return best[:limit]


def _extract_xiaohongshu(data: Any, limit: int) -> list[dict]:
    """小红书笔记搜索精确解析：data.notes[]。"""
    notes = data.get("notes") or [] if isinstance(data, dict) else []
    out: list[dict] = []
    for n in notes[:limit]:
        if not isinstance(n, dict):
            continue
        user = n.get("user") or {}
        nid = n.get("id") or ""
        out.append({
            "title": n.get("title") or n.get("desc") or "",
            "url": f"https://www.xiaohongshu.com/explore/{nid}" if nid else "",
            "metrics": {
                "liked_count": n.get("liked_count"),
                "comments_count": n.get("comments_count"),
                "collected_count": n.get("collected_count"),
                "shared_count": n.get("shared_count"),
            },
            "author": user.get("nickname") if isinstance(user, dict) else "",
            "note_type": n.get("type"),
        })
    return out


_EXTRACTORS = {
    "xiaohongshu": _extract_xiaohongshu,
}


def _render_markdown(label: str, keyword: str, items: list[dict]) -> str:
    """以 Obsidian markdown + mermaid 图表呈现结果。"""
    from datetime import datetime

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {label}搜索 · {keyword}")
    lines.append("tags:")
    lines.append("  - social-search")
    lines.append("  - justoneapi")
    lines.append(f"date: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {label}搜索：{keyword}")
    lines.append("")
    lines.append("> [!abstract] 搜索概览")
    lines.append(f"> **平台**：{label}　**关键词**：{keyword}　**返回**：{len(items)} 条")
    lines.append("")

    # 尝试用第一个有数值的指标画 mermaid 柱状图
    top = items[:8]
    metric_key = None
    for it in top:
        for k in _METRIC_KEYS:
            if k in it.get("metrics", {}):
                metric_key = k
                break
        if metric_key:
            break
    if metric_key:
        vals = []
        for it in top:
            v = it["metrics"].get(metric_key)
            try:
                vals.append(int(float(v)) if v is not None else 0)
            except (TypeError, ValueError):
                vals.append(0)
        if any(vals):
            y_max = int(max(vals) * 1.2) + 1
            lines.append("## 数据对比")
            lines.append("")
            lines.append("```mermaid")
            lines.append("xychart-beta")
            lines.append(f'    title "{metric_key}（Top {len(top)}）"')
            labels = "[" + ", ".join(f'"{i + 1}"' for i in range(len(top))) + "]"
            lines.append(f"    x-axis {labels}")
            lines.append(f'    y-axis "{metric_key}" 0 --> {y_max}')
            lines.append("    bar [" + ", ".join(str(v) for v in vals) + "]")
            lines.append("```")
            lines.append("")

    lines.append("## 结果列表")
    lines.append("")
    lines.append("| # | 标题 | 链接 |")
    lines.append("|---|------|------|")
    for i, it in enumerate(items, start=1):
        title = (it.get("title") or "(无标题)").replace("|", "/")[: 60]
        url = it.get("url") or ""
        link = f"[打开]({url})" if url else "-"
        lines.append(f"| {i} | {title} | {link} |")
    lines.append("")
    return "\n".join(lines)


async def social_platform_search(
    keyword: str,
    platform: str = "douyin",
    count: int = 10,
    page: int = 1,
    **filters: Any,
) -> dict:
    """在指定平台按关键词搜索并返回结果（JustOneAPI 主通道）。

    Args:
        keyword: 搜索关键词。
        platform: 平台 key，见 PLATFORMS。
        count: 返回条数上限(1-30)。
        page: 页码(>=1)。
        filters: 平台可选筛选参数（透传给上游）。
    """
    token = _get_token()
    if not token:
        return {"error": "JUSTONEAPI_TOKEN 未配置，请在 settings.yaml 的 douyin.api_token 或环境变量设置"}

    cfg = PLATFORMS.get(platform)
    if not cfg:
        return {"error": f"不支持的平台: {platform}，可选: {', '.join(PLATFORMS)}", "platforms": sorted(PLATFORMS)}
    if count < 1 or count > 30:
        return {"error": "count 需在 1-30 之间"}

    params: dict = {"token": token}
    if cfg.get("special") == "weibo":
        today = date.today()
        start = today - timedelta(days=30)
        params.update({
            "q": keyword,
            "start_day": filters.get("start_day", start.strftime("%Y-%m-%d")),
            "start_hour": filters.get("start_hour", 0),
            "end_day": filters.get("end_day", today.strftime("%Y-%m-%d")),
            "end_hour": filters.get("end_hour", 23),
        })
    else:
        params[cfg["kw"]] = keyword
        params["page"] = int(page)
    # 透传额外筛选参数
    for k, v in filters.items():
        if v is not None and k not in params:
            params[k] = v

    base = _get_base_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(f"{base}{cfg['path']}", params=params)
            r.raise_for_status()
            payload = r.json()
    except httpx.HTTPError as e:
        logger.warning("social search http error (%s): %s", platform, e)
        return {"error": f"HTTP error: {e}"}
    except Exception as e:  # noqa: BLE001
        logger.exception("social search error (%s)", platform)
        return {"error": str(e)}

    if str(payload.get("code")) != "0":
        return {"error": payload.get("message") or "search failed", "code": payload.get("code")}

    data = payload.get("data")
    extractor = _EXTRACTORS.get(cfg.get("parser")) or _extract_generic_items
    items = extractor(data, count)
    return {
        "code": 0,
        "platform": platform,
        "platform_label": cfg["label"],
        "keyword": keyword,
        "count": len(items),
        "items": items,
        "provider": "justoneapi",
        "markdown": _render_markdown(cfg["label"], keyword, items),
    }


def register_social_search_tools(registry) -> None:
    """Register generic multi-platform search tool."""
    registry.register(
        "social_platform_search",
        social_platform_search,
        {
            "description": "在26个平台（抖音/淘宝/小红书/快手/微信/微博/B站/京东/TikTok/YouTube等）按关键词统一搜索并返回结果，含 Obsidian markdown 呈现。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "platform": {
                        "type": "string",
                        "description": "平台 key: " + ", ".join(PLATFORMS),
                        "default": "douyin",
                    },
                    "count": {"type": "integer", "description": "返回条数上限(1-30)", "default": 10},
                    "page": {"type": "integer", "description": "页码(>=1)", "default": 1},
                },
                "required": ["keyword"],
            },
        },
        provider_hint="text",
        category="douyin",
    )
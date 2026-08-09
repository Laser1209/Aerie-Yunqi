"""Douyin search via JustOneAPI — 进程内桥接（直接调 JustOneAPI REST）.

对接参考资料（接口参数/返回结构）保留在仓库 justoneapi-mcp/ 下：
  - endpont: douyin.search_video_v4  -> GET /api/douyin/search-video/v4
  - 返回: {code(0=成功), message, data:{...}, requestId}
认证：JustOneAPI token，优先取环境变量 JUSTONEAPI_TOKEN，否则取 settings.yaml 的 douyin.api_token。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.justoneapi.com"
_SEARCH_PATH = "/api/douyin/search-video/v4"

# 枚举值映射（与 catalog 一致），便于 model 用人类可读值
_SORT_VALUES = {"_0": "综合", "_1": "点赞最多", "_2": "最新"}
_PUBLISH_VALUES = {"_0": "不限", "_1": "最近24小时", "_7": "最近7天", "_180": "最近6个月"}
_DURATION_VALUES = {"_0": "不限时长", "_1": "1分钟以内", "_2": "1-5分钟", "_3": "超过5分钟"}


def _get_token() -> str | None:
    """Read JustOneAPI token from env or settings.yaml."""
    token = (os.environ.get("JUSTONEAPI_TOKEN") or "").strip()
    if token:
        return token
    try:
        from config.persona_loader import load_settings
        settings = load_settings() or {}
        token = ((settings.get("douyin") or {}).get("api_token") or "").strip()
        return token or None
    except Exception as e:  # noqa: BLE001
        logger.debug("douyin token load failed: %s", e)
        return None


def _get_base_url() -> str:
    try:
        from config.persona_loader import load_settings
        settings = load_settings() or {}
        base = ((settings.get("douyin") or {}).get("api_base_url") or "").strip()
        return base or _DEFAULT_BASE
    except Exception:  # noqa: BLE001
        return _DEFAULT_BASE


def _first(*values: Any) -> Any:
    """Return the first non-empty value."""
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def _extract_string(node: Any, *keys: str) -> str:
    if not isinstance(node, dict):
        return ""
    for k in keys:
        v = node.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _extract_video(v: Any) -> dict:
    """抽取单条抖音视频通用字段（适配 JustOneAPI aweme_info 结构，兼容旧字段）。"""
    if not isinstance(v, dict):
        return {}

    video_id = _first(
        v.get("aweme_id"), v.get("video_id"), v.get("videoId"),
        v.get("id"), v.get("item_id"),
    )
    title = _extract_string(v, "title", "desc", "description", "caption", "brief", "item_title")
    author_node = v.get("author")
    author = ""
    author_id = ""
    if isinstance(author_node, dict):
        author = _first(
            author_node.get("nickname"), author_node.get("nick_name"),
            author_node.get("name"), author_node.get("unique_id"),
        )
        author_id = author_node.get("sec_uid") or author_node.get("uid") or ""
    elif isinstance(author_node, str):
        author = author_node

    stats = v.get("statistics")
    if not isinstance(stats, dict):
        stats = {}
    play = _first(stats.get("play_count"), stats.get("playCount"), stats.get("view_count"), stats.get("vv"))
    like = _first(stats.get("digg_count"), stats.get("liked_count"), stats.get("likeCount"))
    comment = _first(stats.get("comment_count"), stats.get("commentCount"))
    share = _first(stats.get("share_count"), stats.get("shareCount"))
    collect = _first(stats.get("collect_count"), stats.get("collectCount"))

    # 封面：优先 video.cover.url_list，其次顶层 cover
    cover = ""
    video_node = v.get("video")
    if isinstance(video_node, dict):
        cover_node = video_node.get("cover")
        if isinstance(cover_node, dict):
            urls = cover_node.get("url_list") or []
            cover = urls[0] if urls else (cover_node.get("url") or "")
    if not cover:
        cover_node = v.get("cover")
        if isinstance(cover_node, dict):
            urls = cover_node.get("url_list") or []
            cover = urls[0] if urls else (cover_node.get("url") or "")
        elif isinstance(cover_node, str):
            cover = cover_node

    hashtags = []
    for h in (v.get("cha_list") or []):
        if isinstance(h, dict):
            hashtags.append(h.get("cha_name") or h.get("name") or h.get("hashtag_name"))
    if not hashtags:
        hashtags = [h.get("hashtag_name") or h.get("name") for h in (v.get("hashtags") or []) if isinstance(h, dict)]

    return {
        "video_id": str(video_id) if video_id is not None else "",
        "title": title,
        "author": str(author) if author is not None else "",
        "author_id": str(author_id) if author_id else "",
        "play_count": play,
        "like_count": like,
        "comment_count": comment,
        "share_count": share,
        "collect_count": collect,
        "share_url": _extract_string(v, "share_url", "shareUrl"),
        "cover_url": cover,
        "create_time": _first(v.get("create_time"), v.get("createTime")),
        "duration": _first(v.get("duration"), v.get("video_duration")),
        "hashtags": [h for h in hashtags if h],
    }


def _extract_search_data(data: Any) -> tuple[list[dict], dict]:
    """从 data 中抽取视频列表与分页配置（适配 JustOneAPI 真实结构）。

    真实结构: data.business_data[] -> {"data": {"aweme_info": {...}}}
    """
    if not isinstance(data, dict):
        return [], {}

    videos: list[dict] = []
    business_data = data.get("business_data")
    if isinstance(business_data, list):
        for item in business_data:
            if not isinstance(item, dict):
                continue
            inner = item.get("data")
            if not isinstance(inner, dict):
                continue
            aw = inner.get("aweme_info") or inner.get("aweme") or {}
            if isinstance(aw, dict) and aw.get("aweme_id"):
                videos.append(_extract_video(aw))

    # 兜底：兼容旧 flat list 结构
    if not videos:
        raw_list = _first(data.get("list"), data.get("video_list"), data.get("items"), data.get("data"))
        if isinstance(raw_list, list):
            videos = [_extract_video(x) for x in raw_list if isinstance(x, dict)]

    biz = data.get("business_config") or {}
    if not isinstance(biz, dict):
        biz = {}
    next_page = biz.get("next_page") or {}
    if not isinstance(next_page, dict):
        next_page = {}
    return videos, {
        "has_more": biz.get("has_more"),
        "search_id": next_page.get("search_id"),
    }


async def douyin_search(
    keyword: str,
    sort_type: str = "_0",
    publish_time: str = "_0",
    duration: str = "_0",
    page: int = 1,
    count: int = 10,
) -> dict:
    """按关键词搜索抖音视频（JustOneAPI 主通道）。

    Args:
        keyword: 搜索关键词。
        sort_type: _0 综合 / _1 点赞最多 / _2 最新。
        publish_time: _0 不限 / _1 24小时 / _7 7天 / _180 6个月。
        duration: _0 不限 / _1 1分钟内 / _2 1-5分钟 / _3 5分钟以上。
        page: 页码(>=1)。
        count: 返回条数上限(1-30)。
    """
    token = _get_token()
    if not token:
        return {"error": "JUSTONEAPI_TOKEN 未配置，请在 settings.yaml 的 douyin.api_token 或环境变量设置"}

    if sort_type not in _SORT_VALUES:
        return {"error": f"无效 sort_type，可选: {list(_SORT_VALUES.keys())}"}
    if publish_time not in _PUBLISH_VALUES:
        return {"error": f"无效 publish_time，可选: {list(_PUBLISH_VALUES.keys())}"}
    if duration not in _DURATION_VALUES:
        return {"error": f"无效 duration，可选: {list(_DURATION_VALUES.keys())}"}
    if count < 1 or count > 30:
        return {"error": "count 需在 1-30 之间"}

    params = {
        "token": token,
        "keyword": keyword,
        "sortType": sort_type,
        "publishTime": publish_time,
        "duration": duration,
        "page": int(page),
    }
    base = _get_base_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(f"{base}{_SEARCH_PATH}", params=params)
            r.raise_for_status()
            payload = r.json()
    except httpx.HTTPError as e:
        logger.warning("douyin search http error: %s", e)
        return {"error": f"HTTP error: {e}"}
    except Exception as e:  # noqa: BLE001
        logger.exception("douyin search error")
        return {"error": str(e)}

    if str(payload.get("code")) != "0":
        return {"error": payload.get("message") or "search failed", "code": payload.get("code")}

    videos, pagination = _extract_search_data(payload.get("data"))
    selected = videos[: count]
    sort_label = _SORT_VALUES.get(sort_type)
    return {
        "keyword": keyword,
        "code": 0,
        "total": len(videos),
        "items": selected,
        "pagination": pagination,
        "sort_type": sort_label,
        "publish_time": _PUBLISH_VALUES.get(publish_time),
        "duration": _DURATION_VALUES.get(duration),
        "provider": "justoneapi",
        "markdown": _render_obsidian(keyword, selected, sort_label),
    }


def _fmt_num(value: Any) -> str:
    """Format a number into 万/亿 human-readable form."""
    if value is None:
        return "0"
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def _render_obsidian(keyword: str, videos: list[dict], sort_label: str) -> str:
    """Render search results as Obsidian-flavoured Markdown with a mermaid chart."""
    from datetime import datetime

    top = videos[: 8]
    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: 抖音搜索 · {keyword}")
    lines.append("tags:")
    lines.append("  - douyin-search")
    lines.append("  - justoneapi")
    lines.append(f"date: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("---")
    lines.append("")
    lines.append(f"# 抖音搜索：{keyword}")
    lines.append("")
    lines.append("> [!abstract] 搜索概览")
    lines.append(f"> **关键词**：{keyword}　**排序**：{sort_label}　**返回**：{len(videos)} 条")
    lines.append("")

    # Mermaid 图表：点赞数对比
    if top:
        likes = []
        for v in top:
            try:
                likes.append(int(float(v.get("like_count") or 0)))
            except (TypeError, ValueError):
                likes.append(0)
        max_like = max(likes) if likes else 0
        y_max = int(max_like * 1.2) + 1
        lines.append("## 数据对比")
        lines.append("")
        lines.append("```mermaid")
        lines.append("xychart-beta")
        lines.append(f'    title "点赞数对比（Top {len(top)}）"')
        labels = "[" + ", ".join(f'"{i + 1}"' for i in range(len(top))) + "]"
        lines.append(f"    x-axis {labels}")
        lines.append(f'    y-axis "点赞数" 0 --> {y_max}')
        lines.append("    bar [" + ", ".join(str(x) for x in likes) + "]")
        lines.append("```")
        lines.append("")

    # 视频列表表格
    lines.append("## 视频列表")
    lines.append("")
    lines.append("| # | 标题 | 作者 | 播放 | 点赞 | 评论 | 链接 |")
    lines.append("|---|------|------|------|------|------|------|")
    for i, v in enumerate(videos, start=1):
        title = (v.get("title") or "").replace("|", "/")[: 40] or "(无标题)"
        author = (v.get("author") or "").replace("|", "/")[: 20] or "-"
        url = v.get("share_url") or ""
        link = f"[打开]({url})" if url else "-"
        lines.append(
            f"| {i} | {title} | {author} | {_fmt_num(v.get('play_count'))} "
            f"| {_fmt_num(v.get('like_count'))} | {_fmt_num(v.get('comment_count'))} | {link} |"
        )
    lines.append("")
    return "\n".join(lines)


def douyin_video_transcript(audio_path: str, language: str = "zh") -> dict:
    """对本地音频/视频文件做语音转写（获取视频文案）。

    说明：抖音视频的下载/解析属逆向，不会实现；此处转写针对用户已下载的本地媒体文件。
    依赖本地 ASR（local_asr），若未安装则返回提示，不影响主流程。
    """
    if not audio_path:
        return {"error": "missing audio_path"}
    try:
        from local_asr import transcribe as _transcribe
    except ImportError as e:
        return {
            "status": "stub",
            "error": f"local_asr 未安装，本地转写不可用：{e}",
            "hint": "当前可从 douyin_search 返回的 title/desc 获取视频文案",
        }
    try:
        result = _transcribe(audio_path, language=language)
    except Exception as e:  # noqa: BLE001
        logger.exception("douyin transcript failed")
        return {"status": "error", "error": str(e)}
    if not isinstance(result, dict):
        result = {"text": result}
    result.setdefault("status", "ok")
    return result


def register_douyin_tools(registry) -> None:
    """Register Douyin search tools into the Aerie tool registry."""
    registry.register(
        "douyin_search",
        douyin_search,
        {
            "description": "按关键词搜索抖音视频并返回基础数据（标题/作者/播放点赞评论/链接/封面）。走 JustOneAPI 聚合 API。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "sort_type": {
                        "type": "string",
                        "description": "排序: _0综合 / _1点赞最多 / _2最新",
                        "default": "_0",
                    },
                    "publish_time": {
                        "type": "string",
                        "description": "发布时间: _0不限 / _1最近24小时 / _7最近7天 / _180最近6个月",
                        "default": "_0",
                    },
                    "duration": {
                        "type": "string",
                        "description": "时长: _0不限 / _1 1分钟内 / _2 1-5分钟 / _3 超过5分钟",
                        "default": "_0",
                    },
                    "page": {"type": "integer", "description": "页码(>=1)", "default": 1},
                    "count": {"type": "integer", "description": "返回条数上限(1-30)", "default": 10},
                },
                "required": ["keyword"],
            },
        },
        provider_hint="text",
        category="douyin",
    )

    registry.register(
        "douyin_video_transcript",
        douyin_video_transcript,
        {
            "description": "对本地音频/视频文件做语音转写，返回视频文案文本。抖音视频下载/解析属逆向，不会实现；本工具针对用户已下载的本地媒体文件（依赖本地 ASR）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "audio_path": {"type": "string", "description": "本地音频/视频文件绝对路径"},
                    "language": {"type": "string", "description": "语言代码，默认 zh", "default": "zh"},
                },
                "required": ["audio_path"],
            },
        },
        provider_hint="text",
        category="douyin",
    )
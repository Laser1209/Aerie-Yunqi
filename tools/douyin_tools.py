"""Douyin MCP 工具包装 — 将 douyin-mcp 的浏览器工具接入 Aerie 工具注册表."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DOUYIN_MCP_ROOT = Path(__file__).resolve().parent.parent / "douyin-mcp"
_DOUYIN_SRC = _DOUYIN_MCP_ROOT / "src"

_browser_service: Any | None = None
_initialized = False


def _ensure_import_path() -> None:
    if str(_DOUYIN_SRC) not in sys.path:
        sys.path.insert(0, str(_DOUYIN_SRC))


def _ensure_initialized() -> Any:
    global _browser_service, _initialized
    if _initialized and _browser_service is not None:
        return _browser_service

    _ensure_import_path()

    try:
        from douyin_creator_mcp.config import load_settings, ensure_runtime_dirs
        from douyin_creator_mcp.services.browser_service import BrowserService
        from douyin_creator_mcp.storage.db import Database

        settings = load_settings(dotenv_path=_DOUYIN_MCP_ROOT / ".env")
        settings.data_dir = _DOUYIN_MCP_ROOT / "data"
        settings.douyin_browser_profile_dir = _DOUYIN_MCP_ROOT / "data" / "browser-profile"
        ensure_runtime_dirs(settings)

        db = Database(settings.data_dir / "douyin.sqlite")
        _browser_service = BrowserService(settings=settings, db=db)
        _initialized = True
        logger.info("douyin-mcp browser service initialized")
        return _browser_service
    except Exception as e:
        logger.exception("douyin-mcp init failed: %s", e)
        raise


def _call_sync(method: str, **kwargs: Any) -> dict[str, Any]:
    try:
        svc = _ensure_initialized()
        result = getattr(svc, method)(**kwargs)
        return {"ok": True, "data": result}
    except Exception as e:
        logger.exception("douyin %s error: %s", method, e)
        return {"ok": False, "error": str(e)}


async def _call_async(method: str, **kwargs: Any) -> dict[str, Any]:
    try:
        svc = _ensure_initialized()
        func = getattr(svc, method)
        if asyncio.iscoroutinefunction(func):
            result = await func(**kwargs)
        else:
            result = func(**kwargs)
        return {"ok": True, "data": result}
    except Exception as e:
        logger.exception("douyin %s error: %s", method, e)
        return {"ok": False, "error": str(e)}


def _wrap_sync(method: str):
    def _fn(**kwargs):
        return _call_sync(method, **kwargs)
    _fn.__name__ = f"douyin_{method}"
    return _fn


def _wrap_async(method: str):
    async def _fn(**kwargs):
        return await _call_async(method, **kwargs)
    _fn.__name__ = f"douyin_{method}"
    return _fn


def _schema(desc: str, props: dict | None = None, required: list | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "",
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props or {},
                "required": required or [],
            },
        },
    }


def register_douyin_tools(registry) -> None:
    """Register all douyin-mcp tools into the Aerie tool registry."""

    if not _DOUYIN_MCP_ROOT.exists():
        logger.warning("douyin-mcp not found at %s, skipping registration", _DOUYIN_MCP_ROOT)
        return

    sync_tools = [
        (
            "douyin_get_status",
            _wrap_sync("get_status"),
            _schema("读取本地缓存、同步任务、指标覆盖率和 profile 锁状态，不打开浏览器"),
            "douyin",
        ),
        (
            "douyin_login_status",
            _wrap_sync("login_status"),
            _schema("查询当前浏览器登录状态"),
            "douyin",
        ),
        (
            "douyin_list_videos",
            _wrap_sync("list_videos"),
            _schema(
                "分页查询本地作品和最新列表指标快照",
                {
                    "limit": {"type": "integer", "description": "每页数量", "default": 20},
                    "offset": {"type": "integer", "description": "偏移量", "default": 0},
                    "sort": {"type": "string", "description": "排序方式", "default": "publish_time_desc"},
                },
            ),
            "douyin",
        ),
        (
            "douyin_get_video_performance",
            _wrap_sync("get_video_performance"),
            _schema(
                "查询单条作品的列表、详情快照及派生指标",
                {
                    "video_id": {"type": "string", "description": "作品ID"},
                    "period": {"type": "string", "description": "统计周期: 7d/30d/all", "default": "30d"},
                },
                ["video_id"],
            ),
            "douyin",
        ),
        (
            "douyin_compare_videos",
            _wrap_sync("compare_videos"),
            _schema(
                "对比2~20条作品的关键指标",
                {
                    "video_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "作品ID列表",
                    },
                },
                ["video_ids"],
            ),
            "douyin",
        ),
        (
            "douyin_get_metric_coverage",
            _wrap_sync("get_metric_coverage"),
            _schema("查询字段覆盖率和缺失原因"),
            "douyin",
        ),
        (
            "douyin_rank_video_potential",
            _wrap_sync("rank_video_potential"),
            _schema(
                "使用透明规则进行作品潜力排序",
                {
                    "limit": {"type": "integer", "description": "返回数量", "default": 10},
                    "period": {"type": "string", "description": "统计周期", "default": "30d"},
                },
            ),
            "douyin",
        ),
        (
            "douyin_generate_review",
            _wrap_sync("generate_review"),
            _schema(
                "生成带证据和警告的复盘上下文",
                {
                    "period": {"type": "string", "description": "统计周期", "default": "30d"},
                },
            ),
            "douyin",
        ),
        (
            "douyin_export_data",
            _wrap_sync("export_data"),
            _schema(
                "导出JSON或CSV格式的作品数据",
                {
                    "format": {"type": "string", "description": "导出格式: json/csv", "default": "json"},
                    "period": {"type": "string", "description": "统计周期", "default": "all"},
                },
            ),
            "douyin",
        ),
    ]

    async_tools = [
        (
            "douyin_login_start",
            _wrap_async("login_start"),
            _schema("打开可见浏览器；首次登录或登录过期时需要扫码"),
            "douyin",
        ),
        (
            "douyin_sync_creator_data",
            _wrap_async("sync_creator_data"),
            _schema(
                "同步作品列表及页面可见指标",
                {
                    "mode": {"type": "string", "description": "同步模式: visible/headless", "default": "visible"},
                    "force": {"type": "boolean", "description": "是否强制同步，忽略缓存", "default": False},
                },
            ),
            "douyin",
        ),
        (
            "douyin_sync_video_details",
            _wrap_async("sync_video_details"),
            _schema(
                "分批采集作品详情页指标",
                {
                    "recent_limit": {"type": "integer", "description": "最近N条作品", "default": 20},
                    "batch_size": {"type": "integer", "description": "每批处理数量", "default": 10},
                    "mode": {"type": "string", "description": "同步模式", "default": "visible"},
                },
            ),
            "douyin",
        ),
        (
            "douyin_sync_if_needed",
            _wrap_async("sync_if_needed"),
            _schema(
                "仅在缓存过期时同步列表、详情或全部数据",
                {
                    "scope": {"type": "string", "description": "同步范围: list/detail/all", "default": "list"},
                    "max_age_hours": {"type": "integer", "description": "最大缓存年龄(小时)"},
                    "recent_limit": {"type": "integer", "description": "最近N条作品", "default": 20},
                },
            ),
            "douyin",
        ),
    ]

    for name, func, schema, hint in sync_tools:
        schema["function"]["name"] = name
        registry.register(name, func, schema, provider_hint=hint)

    for name, func, schema, hint in async_tools:
        schema["function"]["name"] = name
        registry.register(name, func, schema, provider_hint=hint)

    total = len(sync_tools) + len(async_tools)
    logger.info("douyin-mcp tools registered (%d tools)", total)

"""网页工具

支持操作：
- web_search — DuckDuckGo 搜索
- weather — 获取指定城市天气（wttr.in）
- fetch_url — 抓取并解析网页内容
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from loguru import logger

from tools.base import Tool


# ===== 工具函数：错误信息格式化 =====

def _format_error(e: Exception, prefix: str) -> str:
    """统一错误信息：带异常类型名，避免 str(e) 为空时无法定位"""
    err_type = type(e).__name__
    err_msg = str(e) or "(无错误信息)"
    return f"{prefix} [{err_type}]: {err_msg}"


# ===== DuckDuckGo 解析降级链 =====

def _parse_ddg_html(html: str) -> list:
    """
    多重正则匹配 DuckDuckGo 搜索结果（兼容旧版/新版/回退）
    返回: [(snippet, link), ...]
    """
    import re

    # 方案 1：旧版 HTML（class="result__snippet" / class="result__url"）
    snippets_v1 = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
    links_v1 = re.findall(r'class="result__url"[^>]*href="([^"]+)"', html)
    if snippets_v1 and links_v1:
        return list(zip(snippets_v1[:max(len(snippets_v1), len(links_v1))],
                        links_v1[:max(len(snippets_v1), len(links_v1))]))

    # 方案 2：新版 HTML（data-testid="result" 或 [data-testid="result__snippet"]）
    snippets_v2 = re.findall(r'data-testid="result__snippet"[^>]*>(.*?)</[^>]+>', html, re.DOTALL)
    links_v2 = re.findall(r'data-testid="result__a"[^>]*href="([^"]+)"', html)
    if snippets_v2 and links_v2:
        return list(zip(snippets_v2[:max(len(snippets_v2), len(links_v2))],
                        links_v2[:max(len(snippets_v2), len(links_v2))]))

    # 方案 3：通用兜底（任何带 href 的 result 块）
    links_v3 = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
    titles_v3 = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
    if links_v3:
        # 只有链接，摘要留空
        return list(zip([""] * len(links_v3), links_v3))

    return []


class WebSearchTool(Tool):
    name = "web_search"
    description = "在互联网上搜索信息。返回搜索结果摘要。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数，默认 5",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str = "", max_results: int = 5, **kwargs) -> Tuple[bool, str]:
        if not query:
            return False, "错误：未提供搜索关键词"

        # 重试 1 次（指数退避 2s）
        last_error = None
        for attempt in range(2):
            try:
                import aiohttp

                # 使用 DuckDuckGo HTML 搜索（无需 API Key）
                url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=15) as resp:
                        if resp.status != 200:
                            return False, f"搜索请求失败: HTTP {resp.status}"
                        html = await resp.text()

                # 多重正则匹配
                pairs = _parse_ddg_html(html)
                import re
                results = []
                for i, (snip, link) in enumerate(pairs):
                    if i >= max_results:
                        break
                    snip_text = re.sub(r"<[^>]+>", "", snip).strip() if snip else ""
                    if snip_text or link:
                        results.append(f"{i+1}. {snip_text[:200]}\n   {link}")

                if not results:
                    return True, f"未找到关于「{query}」的搜索结果"

                logger.info(f"web_search: {query} → {len(results)} 结果 (attempt {attempt+1})")
                return True, f"🔍 搜索「{query}」:\n\n" + "\n\n".join(results)

            except ImportError as e:
                return False, _format_error(e, "aiohttp 未安装")
            except Exception as e:
                last_error = e
                logger.exception(f"web_search 失败: query={query!r}, attempt={attempt+1}")
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue

        return False, _format_error(last_error, "搜索失败")


class WeatherTool(Tool):
    name = "get_weather"
    description = "获取指定城市的当前天气信息（温度、湿度、风速、天气状况）"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称（中文或英文），如 北京、上海、Tokyo",
                },
            },
            "required": ["city"],
        }

    async def execute(self, city: str = "", **kwargs) -> Tuple[bool, str]:
        if not city:
            return False, "错误：未指定城市"

        try:
            import aiohttp

            # wttr.in 免费天气 API
            url = f"https://wttr.in/{quote(city)}?format=%C+%t+%h+%w&lang=zh"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        return False, f"天气查询失败: HTTP {resp.status}"
                    raw = await resp.text()

            if not raw.strip():
                return False, f"未找到城市「{city}」的天气信息"

            logger.info(f"weather: {city} → {raw.strip()}")
            return True, f"🌤 {city} 天气: {raw.strip()}"
        except ImportError as e:
            return False, _format_error(e, "aiohttp 未安装")
        except Exception as e:
            logger.exception(f"weather 失败: city={city!r}")
            return False, _format_error(e, "天气查询失败")


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = "获取指定网页的文本内容"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要获取的网址（必须以 http:// 或 https:// 开头）",
                },
            },
            "required": ["url"],
        }

    async def execute(self, url: str = "", **kwargs) -> Tuple[bool, str]:
        if not url:
            return False, "错误：未提供网址"
        if not url.startswith(("http://", "https://")):
            return False, "错误：网址必须以 http:// 或 https:// 开头"

        try:
            import aiohttp

            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as resp:
                    if resp.status != 200:
                        return False, f"请求失败: HTTP {resp.status}"
                    html = await resp.text()

            # 简单提取文本
            import re
            # 移除 script/style 标签
            html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
            # 移除 HTML 标签
            text = re.sub(r"<[^>]+>", " ", html)
            # 压缩空白
            text = re.sub(r"\s+", " ", text).strip()

            if len(text) > 3000:
                text = text[:3000] + f"\n... [截断: 原始长度 {len(text)} 字符]"

            logger.info(f"fetch_url: {url} → {len(text)} chars")
            return True, text
        except ImportError as e:
            return False, _format_error(e, "aiohttp 未安装")
        except Exception as e:
            logger.exception(f"fetch_url 失败: url={url!r}")
            return False, _format_error(e, "获取网页失败")

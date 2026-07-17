"""Kimi WebBridge 浏览器操作工具 — 接入 Aerie 工具注册表."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "http://127.0.0.1:10086"


class WebBridgeClient:
    def __init__(self, base_url: str = _DEFAULT_BASE):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60.0)

    async def _command(self, action: str, **kwargs: Any) -> dict[str, Any]:
        try:
            payload = {"action": action, **kwargs}
            r = await self._client.post(
                f"{self.base_url}/command",
                json=payload,
                timeout=60.0,
            )
            r.raise_for_status()
            return {"ok": True, "data": r.json()}
        except httpx.HTTPError as e:
            logger.warning("webbridge %s http error: %s", action, e)
            return {"ok": False, "error": f"HTTP error: {e}"}
        except Exception as e:
            logger.exception("webbridge %s error: %s", action, e)
            return {"ok": False, "error": str(e)}

    async def status(self) -> dict[str, Any]:
        try:
            r = await self._client.get(f"{self.base_url}/status", timeout=5.0)
            return {"ok": True, "data": r.json()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def navigate(self, url: str) -> dict[str, Any]:
        return await self._command("navigate", url=url)

    async def snapshot(self) -> dict[str, Any]:
        return await self._command("snapshot")

    async def click(self, selector: str) -> dict[str, Any]:
        return await self._command("click", selector=selector)

    async def fill(self, selector: str, value: str) -> dict[str, Any]:
        return await self._command("fill", selector=selector, value=value)

    async def evaluate(self, code: str) -> dict[str, Any]:
        return await self._command("evaluate", code=code)

    async def screenshot(self, format: str = "png", selector: str | None = None) -> dict[str, Any]:
        kwargs = {"format": format}
        if selector:
            kwargs["selector"] = selector
        result = await self._command("screenshot", **kwargs)
        if result.get("ok") and result.get("data", {}).get("base64"):
            b64 = result["data"]["base64"]
            result["data"]["size"] = len(base64.b64decode(b64))
        return result

    async def key_type(self, text: str) -> dict[str, Any]:
        return await self._command("key_type", text=text)

    async def send_keys(self, keys: str) -> dict[str, Any]:
        return await self._command("send_keys", keys=keys)

    async def list_tabs(self) -> dict[str, Any]:
        return await self._command("list_tabs")

    async def find_tab(self, url: str) -> dict[str, Any]:
        return await self._command("find_tab", url=url)

    async def close_tab(self) -> dict[str, Any]:
        return await self._command("close_tab")

    async def save_as_pdf(self, paper_format: str = "A4") -> dict[str, Any]:
        return await self._command("save_as_pdf", paper_format=paper_format)


_client: WebBridgeClient | None = None


def get_client() -> WebBridgeClient:
    global _client
    if _client is None:
        _client = WebBridgeClient()
    return _client


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


def register_webbridge_tools(registry) -> None:
    """Register all Kimi WebBridge tools into the Aerie tool registry."""

    client = get_client()

    tools = [
        (
            "browser_status",
            client.status,
            _schema("检查浏览器桥接服务状态和扩展连接情况"),
            "browser",
        ),
        (
            "browser_navigate",
            client.navigate,
            _schema(
                "在浏览器中打开指定URL的网页",
                {"url": {"type": "string", "description": "要打开的网页URL"}},
                ["url"],
            ),
            "browser",
        ),
        (
            "browser_snapshot",
            client.snapshot,
            _schema("获取当前页面的无障碍树结构快照，用于了解页面内容和元素"),
            "browser",
        ),
        (
            "browser_click",
            client.click,
            _schema(
                "通过CSS选择器点击页面上的元素",
                {"selector": {"type": "string", "description": "要点击元素的CSS选择器"}},
                ["selector"],
            ),
            "browser",
        ),
        (
            "browser_fill",
            client.fill,
            _schema(
                "在表单输入框中填写文本内容",
                {
                    "selector": {"type": "string", "description": "输入框的CSS选择器"},
                    "value": {"type": "string", "description": "要填写的文本内容"},
                },
                ["selector", "value"],
            ),
            "browser",
        ),
        (
            "browser_evaluate",
            client.evaluate,
            _schema(
                "在页面上执行JavaScript代码并返回结果",
                {"code": {"type": "string", "description": "要执行的JavaScript代码"}},
                ["code"],
            ),
            "browser",
        ),
        (
            "browser_screenshot",
            client.screenshot,
            _schema(
                "对当前页面或指定元素进行截图",
                {
                    "format": {"type": "string", "description": "图片格式: png/jpeg", "default": "png"},
                    "selector": {"type": "string", "description": "可选，只截取指定元素"},
                },
            ),
            "browser",
        ),
        (
            "browser_key_type",
            client.key_type,
            _schema(
                "在当前聚焦的元素中输入文本",
                {"text": {"type": "string", "description": "要输入的文本"}},
                ["text"],
            ),
            "browser",
        ),
        (
            "browser_send_keys",
            client.send_keys,
            _schema(
                "发送键盘按键或快捷键",
                {"keys": {"type": "string", "description": "要发送的按键"}},
                ["keys"],
            ),
            "browser",
        ),
        (
            "browser_list_tabs",
            client.list_tabs,
            _schema("列出当前浏览器的所有标签页"),
            "browser",
        ),
        (
            "browser_find_tab",
            client.find_tab,
            _schema(
                "根据URL查找并切换到对应的标签页",
                {"url": {"type": "string", "description": "要查找的URL关键词"}},
                ["url"],
            ),
            "browser",
        ),
        (
            "browser_close_tab",
            client.close_tab,
            _schema("关闭当前标签页"),
            "browser",
        ),
        (
            "browser_save_as_pdf",
            client.save_as_pdf,
            _schema(
                "将当前页面保存为PDF文件",
                {
                    "paper_format": {"type": "string", "description": "纸张格式: A4/Letter", "default": "A4"},
                },
            ),
            "browser",
        ),
    ]

    for name, func, schema, hint in tools:
        schema["function"]["name"] = name
        registry.register(name, func, schema, provider_hint=hint)

    logger.info("kimi webbridge tools registered (%d tools)", len(tools))

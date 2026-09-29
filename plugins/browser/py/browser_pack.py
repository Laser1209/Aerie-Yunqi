"""browser 功能包 —— 自建 Playwright 内核的 13 个 `browser_*` 工具。

与核心内置 WebBridge 的关系（重要）：`ToolRegistry.register()` 是覆盖语义，
而核心在功能包**之后**注册工具，所以 `tools/__init__.py::_browser_backend()`
在 `backend: auto` 下会**主动让位**——装了本包就是 Playwright，没装就走 WebBridge。
因此本包的工具名必须与 `tools/browser_tools.py` **逐个对齐**（多一个少一个都会
让"装了包反而少工具"）。

顶层不 import playwright（见 plugins/README.md 约束 1）：重库在第一次工具调用时
由 `BrowserSession.ensure()` 惰性拉起。
"""
from __future__ import annotations

import logging
from typing import Any

from browser_session import BrowserSession

logger = logging.getLogger(__name__)

_SESSION = BrowserSession()
_CTX: Any = None


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


def _output_path(filename: str) -> str:
    """产物统一落在 data_dir/browser_downloads 下（绝不写仓库根）。"""
    from core.paths import data_dir

    target = data_dir() / "browser_downloads"
    target.mkdir(parents=True, exist_ok=True)
    return str(target / filename)


# ── 工具实现（全部 async，与核心 WebBridge 的形状一致）─────

async def browser_status() -> dict[str, Any]:
    return _SESSION.status()


async def browser_navigate(url: str) -> dict[str, Any]:
    if not str(url or "").strip():
        return {"error": "missing url"}
    try:
        return {"status": "ok", "url": await _SESSION.goto(url)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_snapshot() -> dict[str, Any]:
    try:
        return {"status": "ok", "snapshot": await _SESSION.snapshot()}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_click(selector: str) -> dict[str, Any]:
    try:
        await _SESSION.click(selector)
        return {"status": "ok", "clicked": selector}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_fill(selector: str, value: str) -> dict[str, Any]:
    try:
        await _SESSION.fill(selector, value)
        return {"status": "ok", "filled": selector}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_evaluate(code: str) -> dict[str, Any]:
    try:
        return {"status": "ok", "result": await _SESSION.evaluate(code)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_screenshot(format: str = "png", selector: str = "") -> dict[str, Any]:
    import time

    ext = "jpg" if str(format).lower() in ("jpg", "jpeg") else "png"
    path = _output_path(f"shot_{int(time.time() * 1000)}.{ext}")
    try:
        return {"status": "ok", "path": await _SESSION.screenshot(path, selector, format)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_key_type(text: str) -> dict[str, Any]:
    try:
        await _SESSION.key_type(text)
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_send_keys(keys: str) -> dict[str, Any]:
    try:
        await _SESSION.send_keys(keys)
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_list_tabs() -> dict[str, Any]:
    tabs = _SESSION.tabs()
    return {"status": "ok", "count": len(tabs), "tabs": tabs}


async def browser_find_tab(url: str) -> dict[str, Any]:
    found = await _SESSION.find_tab(url)
    if not found:
        return {"status": "error", "error": f"没有匹配 {url!r} 的标签页"}
    return {"status": "ok", "url": url}


async def browser_close_tab() -> dict[str, Any]:
    try:
        await _SESSION.close_tab()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


async def browser_save_as_pdf(paper_format: str = "A4") -> dict[str, Any]:
    import time

    del paper_format  # Playwright 的 pdf() 走默认纸张，这里不假装支持自定义规格
    path = _output_path(f"page_{int(time.time() * 1000)}.pdf")
    try:
        return {"status": "ok", "path": await _SESSION.save_as_pdf(path)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300]}


# ── 生命周期 ────────────────────────────────────────────

def start(companion: Any) -> None:
    """只记录配置，**不启动浏览器**（170MB 内核要等第一次真用到再拉）。"""
    config: dict[str, Any] = {}
    try:
        if _CTX is not None:
            config = _CTX.get_config() or {}
    except Exception:
        logger.debug("browser pack: 读取配置失败，用默认值", exc_info=True)

    pack_root = None
    try:
        if _CTX is not None:
            pack_root = _CTX.root
    except Exception:
        pass
    _SESSION.configure(config, pack_root)


async def stop() -> None:
    await _SESSION.close()


# ── 注册 ────────────────────────────────────────────────

def register(ctx: Any) -> None:
    """注册 13 个 browser_* 工具（名字与 tools/browser_tools.py 逐个对齐）。"""
    global _CTX
    _CTX = ctx

    tools: list[tuple[str, Any, dict]] = [
        ("browser_status", browser_status, _schema("检查浏览器内核状态与当前页面")),
        ("browser_navigate", browser_navigate, _schema(
            "在浏览器中打开指定 URL 的网页",
            {"url": {"type": "string", "description": "要打开的网页 URL"}}, ["url"])),
        ("browser_snapshot", browser_snapshot, _schema(
            "获取当前页面的可读结构快照（标题 + 可交互元素），用于了解页面内容")),
        ("browser_click", browser_click, _schema(
            "通过 CSS 选择器点击页面上的元素",
            {"selector": {"type": "string", "description": "要点击元素的 CSS 选择器"}}, ["selector"])),
        ("browser_fill", browser_fill, _schema(
            "在表单输入框中填写文本内容",
            {"selector": {"type": "string", "description": "输入框的 CSS 选择器"},
             "value": {"type": "string", "description": "要填写的文本内容"}},
            ["selector", "value"])),
        ("browser_evaluate", browser_evaluate, _schema(
            "在页面上执行 JavaScript 代码并返回结果",
            {"code": {"type": "string", "description": "要执行的 JavaScript 代码"}}, ["code"])),
        ("browser_screenshot", browser_screenshot, _schema(
            "对当前页面或指定元素截图，产物落在本机 data/browser_downloads 下",
            {"format": {"type": "string", "description": "图片格式: png/jpeg", "default": "png"},
             "selector": {"type": "string", "description": "可选，只截取指定元素"}})),
        ("browser_key_type", browser_key_type, _schema(
            "在当前聚焦的元素中输入文本",
            {"text": {"type": "string", "description": "要输入的文本"}}, ["text"])),
        ("browser_send_keys", browser_send_keys, _schema(
            "发送键盘按键或快捷键",
            {"keys": {"type": "string", "description": "要发送的按键"}}, ["keys"])),
        ("browser_list_tabs", browser_list_tabs, _schema("列出当前浏览器的所有标签页")),
        ("browser_find_tab", browser_find_tab, _schema(
            "根据 URL 查找并切换到对应的标签页",
            {"url": {"type": "string", "description": "要查找的 URL 关键词"}}, ["url"])),
        ("browser_close_tab", browser_close_tab, _schema("关闭当前标签页")),
        ("browser_save_as_pdf", browser_save_as_pdf, _schema(
            "将当前页面保存为 PDF 文件",
            {"paper_format": {"type": "string", "description": "纸张格式: A4/Letter", "default": "A4"}})),
    ]

    for name, func, schema in tools:
        schema["function"]["name"] = name
        ctx.tool_registry.register(name, func, schema, provider_hint="browser", category="browser")

    logger.info("browser pack: 注册 %d 个 browser_* 工具", len(tools))

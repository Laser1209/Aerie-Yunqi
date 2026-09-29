"""Playwright 会话管理 —— 惰性启动、失败软着陆。

为什么要单独一层：浏览器内核是**重资产**（Playwright + Chromium ≈170MB），
不能在包加载/后端启动时拉起。这里把"什么时候真的开浏览器"推迟到**第一次工具调用**，
并把所有失败都收敛成可读的错误串（工具返回 `status: error` 而不是炸掉对话）。

两种接入方式：

- **自建内核**（默认）：用本包 `bin/ms-playwright` 里的 Chromium（发布产物自带），
  通过 `PLAYWRIGHT_BROWSERS_PATH` 指过去；
- **接现有浏览器**（`cdp_url` 配置）：`connect_over_cdp` 连到用户已经开着的
  Chrome/Edge（带 `--remote-debugging-port`），不下载任何内核。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BrowserSession:
    """一个进程内单页会话（一次只服务一个标签页栈，够用且省内存）。"""

    def __init__(self) -> None:
        self._playwright: Optional[Any] = None
        self._browser: Optional[Any] = None
        self._context: Optional[Any] = None
        self._page: Optional[Any] = None
        self._error: str = ""
        self._config: dict[str, Any] = {}
        self._pack_root: Optional[Path] = None

    # ── 配置 ────────────────────────────────────────────

    def configure(self, config: dict[str, Any], pack_root: Optional[Path] = None) -> None:
        """记录配置与包根（在 start 阶段调用，此阶段仍不 import playwright）。"""
        self._config = dict(config or {})
        self._pack_root = pack_root

    @property
    def error(self) -> str:
        return self._error

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "running": self._browser is not None,
            "url": self._page.url if self._page is not None else "",
            "mode": "cdp" if str(self._config.get("cdp_url") or "").strip() else "bundled",
            "error": self._error,
        }

    # ── 生命周期 ────────────────────────────────────────

    async def ensure(self) -> None:
        """确保浏览器已就绪；失败只记错误，由调用方转成工具错误返回。"""
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright

            # 自建内核：把 Chromium 指到包内 bin/ms-playwright（没配就交给默认查找）。
            if self._pack_root is not None:
                bundled = self._pack_root / "bin" / "ms-playwright"
                if bundled.is_dir():
                    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled))

            self._playwright = await async_playwright().start()

            cdp_url = str(self._config.get("cdp_url") or "").strip()
            if cdp_url:
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                contexts = self._browser.contexts
                self._context = contexts[0] if contexts else await self._browser.new_context()
            else:
                self._browser = await self._playwright.chromium.launch(
                    headless=bool(self._config.get("headless", True)),
                )
                self._context = await self._browser.new_context()

            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            self._error = ""
            logger.info("browser pack: 会话就绪 (%s)", cdp_url or "bundled chromium")
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            await self.close()
            logger.warning("browser pack: 启动失败（%s）", self._error)

    async def close(self) -> None:
        for attr in ("_browser", "_playwright"):
            obj = getattr(self, attr)
            setattr(self, attr, None)
            if obj is None:
                continue
            try:
                closer = getattr(obj, "close", None)
                if closer is not None:
                    result = closer()
                    if hasattr(result, "__await__"):
                        await result
                else:
                    stopper = getattr(obj, "stop", None)
                    if stopper is not None:
                        await stopper()
            except Exception:
                logger.debug("browser pack: 关闭 %s 失败", attr, exc_info=True)
        self._context = None
        self._page = None

    # ── 页面访问 ────────────────────────────────────────

    def _bad(self, reason: str) -> dict[str, Any]:
        return {"status": "error", "error": reason or self._error or "浏览器未就绪"}

    async def page(self) -> Any:
        await self.ensure()
        if self._page is None:
            raise RuntimeError(self._error or "浏览器未就绪")
        return self._page

    async def goto(self, url: str) -> str:
        page = await self.page()
        await page.goto(str(url), wait_until=str(self._config.get("wait_until") or "domcontentloaded"))
        return page.url

    async def snapshot(self) -> str:
        """收一份可读的页面结构（标题 + 可交互元素），比原始 HTML 省 token。"""
        page = await self.page()
        return await page.evaluate(
            """() => {
                const pick = ['a','button','input','textarea','select','[role=button]'];
                const nodes = Array.from(document.querySelectorAll(pick.join(',')));
                const lines = nodes.slice(0, 200).map((el, i) => {
                    const label = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 60);
                    return `${i}. <${el.tagName.toLowerCase()}> ${label}`;
                });
                return `# ${document.title}\\n${location.href}\\n` + lines.join('\\n');
            }"""
        )

    async def click(self, selector: str) -> None:
        page = await self.page()
        await page.click(str(selector))

    async def fill(self, selector: str, value: str) -> None:
        page = await self.page()
        await page.fill(str(selector), str(value))

    async def evaluate(self, code: str) -> Any:
        page = await self.page()
        return await page.evaluate(str(code))

    async def screenshot(self, path: str, selector: str = "", fmt: str = "png") -> str:
        page = await self.page()
        target = page.locator(selector) if selector else page
        await target.screenshot(path=str(path), type="jpeg" if str(fmt).lower() in ("jpg", "jpeg") else "png")
        return str(path)

    async def save_as_pdf(self, path: str) -> str:
        page = await self.page()
        await page.pdf(path=str(path))
        return str(path)

    async def key_type(self, text: str) -> None:
        page = await self.page()
        await page.keyboard.type(str(text))

    async def send_keys(self, keys: str) -> None:
        page = await self.page()
        await page.keyboard.press(str(keys))

    def tabs(self) -> list[dict[str, Any]]:
        if self._context is None:
            return []
        return [{"index": i, "url": p.url} for i, p in enumerate(self._context.pages)]

    async def find_tab(self, keyword: str) -> bool:
        if self._context is None:
            return False
        needle = str(keyword or "").lower()
        for page in self._context.pages:
            if needle in (page.url or "").lower():
                self._page = page
                await page.bring_to_front()
                return True
        return False

    async def close_tab(self) -> None:
        if self._page is None:
            return
        await self._page.close()
        pages = self._context.pages if self._context is not None else []
        self._page = pages[0] if pages else None

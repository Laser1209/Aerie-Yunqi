#!/usr/bin/env python3
"""Render floor plan SVGs to PNG using Playwright (Chromium) at exact 1400x980."""
import asyncio
from playwright.async_api import async_playwright

async def render():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1400, "height": 980}, device_scale_factor=2)
        page = await context.new_page()
        for level in [1, 2]:
            url = f"file:///e:/Agent_reply/ita-river-loft-room.design-project/assets/wrap_l{level}.html"
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(800)
            out = f"e:\\Agent_reply\\ita-river-loft-room.design-project\\assets\\floor_plan_level{level}.png"
            await page.screenshot(path=out, clip={"x": 0, "y": 0, "width": 1400, "height": 980}, omit_background=False)
            print(f"Wrote {out}")
        await browser.close()

asyncio.run(render())

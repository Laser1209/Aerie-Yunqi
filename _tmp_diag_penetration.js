"use strict";
/* 诊断穿透：手动 dispatch vs CDP mouse.move */
const { chromium } = require("e:/Agent_reply/electron/node_modules/playwright-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.connectOverCDP("http://127.0.0.1:9222");
  let island = null;
  for (const ctx of browser.contexts()) {
    for (const p of ctx.pages()) {
      if (p.url().includes("dynamic-island.html")) { island = p; break; }
    }
  }
  if (!island) { console.log("FAIL: island not found"); process.exit(1); }
  await island.reload();
  await sleep(2500);

  const calls = [];
  const info = await island.evaluate((arr) => {
    const hasApi = !!window.aerie?.dynamicIsland;
    const api = window.aerie?.dynamicIsland;
    if (api) api.setIgnoreMouse = (ignore) => { arr.push(ignore); return Promise.resolve({ ok: true }); };
    const cap = document.querySelector("#di-capsule").getBoundingClientRect();
    return { hasApi, capLeft: cap.left, capTop: cap.top, capW: cap.width };
  }, calls);
  console.log("api exists:", info.hasApi, "cap:", info.capLeft, info.capTop, info.capW);

  // 手动 dispatch mousemove 到胶囊外
  await island.evaluate(() => document.dispatchEvent(new MouseEvent("mousemove", { clientX: 30, clientY: 32, bubbles: true })));
  await sleep(100);
  console.log("after manual dispatch (outside):", JSON.stringify(calls));

  // 手动 dispatch 到胶囊中心
  const cx = info.capLeft + info.capW / 2;
  await island.evaluate((x) => document.dispatchEvent(new MouseEvent("mousemove", { clientX: x, clientY: 32, bubbles: true })), cx);
  await sleep(100);
  console.log("after manual dispatch (capsule):", JSON.stringify(calls));

  // CDP mouse.move
  await island.mouse.move(30, 32);
  await sleep(200);
  console.log("after CDP move (outside):", JSON.stringify(calls));

  await browser.close();
  process.exit(0);
})().catch((e) => { console.error("ERR:", e && e.message); process.exit(1); });

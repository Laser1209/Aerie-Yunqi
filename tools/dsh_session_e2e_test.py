#!/usr/bin/env python3
"""端到端验证：会话聚合层在 pipeline 里的连续消息续接。

链路：两条相关消息 → router → aggregator.decide → delegate → 验证 session_id 一致。

用法：python tools/dsh_session_e2e_test.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv(".env")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
for _name in (
    "core.pipeline", "core.dsh_cli", "core.work_mode_router",
    "core.session_aggregator",
):
    logging.getLogger(_name).setLevel(logging.INFO)

from communication.message import IncomingMessage  # noqa: E402
from config.persona_loader import load_settings  # noqa: E402
from core.companion import Companion  # noqa: E402


MSG_1 = "帮我整理 D:\\T08171634 文件夹"
MSG_2 = "顺便把重复文件也删了"   # 补充指令，预期续接同一 session


async def main() -> None:
    comp = Companion(settings=load_settings())
    await comp.start()
    pipeline = comp.pipeline
    print(f"[ok] Companion started, DSH enabled={pipeline._dsh_enabled}", flush=True)

    if not pipeline._dsh_enabled or not pipeline._dsh_aggregator:
        print("[skip] DSH 未启用或聚合层未初始化，跳过", flush=True)
        await comp.stop()
        return

    try:
        # ── 消息 1：首次委托 ──
        print(f"\n{'='*60}", flush=True)
        print(f"消息 1: {MSG_1}", flush=True)
        print(f"{'='*60}", flush=True)
        t0 = time.monotonic()
        resp1 = await pipeline._try_delegate_to_dsh(MSG_1, IncomingMessage.from_local(MSG_1, 12345))
        print(f"  耗时: {time.monotonic() - t0:.1f}s", flush=True)

        if resp1 is None:
            print("  [stop] 消息 1 未委托（路由未命中或 delegate 失败）", flush=True)
            await comp.stop()
            return

        state1 = pipeline._dsh_session_state.get("file-organizer", {})
        sid1 = state1.get("session_id")
        print(f"  session_id: {sid1}", flush=True)
        print(f"  response text: {(resp1.text or '')[:120]}", flush=True)

        # ── 消息 2：补充指令（预期续接同一 session）──
        print(f"\n{'='*60}", flush=True)
        print(f"消息 2: {MSG_2}", flush=True)
        print(f"{'='*60}", flush=True)
        t1 = time.monotonic()
        resp2 = await pipeline._try_delegate_to_dsh(MSG_2, IncomingMessage.from_local(MSG_2, 12345))
        print(f"  耗时: {time.monotonic() - t1:.1f}s", flush=True)

        if resp2 is None:
            print("  [stop] 消息 2 未委托", flush=True)
            await comp.stop()
            return

        state2 = pipeline._dsh_session_state.get("file-organizer", {})
        sid2 = state2.get("session_id")
        print(f"  session_id: {sid2}", flush=True)
        print(f"  response text: {(resp2.text or '')[:120]}", flush=True)

        # ── 验证 ──
        print(f"\n{'='*60}", flush=True)
        if sid1 and sid2 and sid1 == sid2:
            print(f"✅ 验证通过：两条消息续接同一 session ({sid1})", flush=True)
        else:
            print(f"⚠️  未续接：sid1={sid1}  sid2={sid2}", flush=True)
            print("   可能原因：聚合层判定为 new_task（语义不相关），或超时开新会话", flush=True)

    finally:
        await comp.stop()
        print("\n[ok] Companion stopped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

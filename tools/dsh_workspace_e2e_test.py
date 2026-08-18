#!/usr/bin/env python3
"""端到端验证 v0.4.1:人格化翻译层 + 工作区管理器在真实链路中的表现。

链路:router → aggregator → delegate → 协议执行 → 人格化翻译 → 工作区日志。
用法: python tools/dsh_workspace_e2e_test.py
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
    "core.session_aggregator", "core.work_persona", "core.workspace",
):
    logging.getLogger(_name).setLevel(logging.INFO)

from communication.message import IncomingMessage  # noqa: E402
from config.persona_loader import load_settings  # noqa: E402
from core.companion import Companion  # noqa: E402

TASK = "帮我整理 D:\\T08171634 文件夹，看看里面有什么"


async def main() -> None:
    comp = Companion(settings=load_settings())
    await comp.start()
    pipeline = comp.pipeline
    print(f"[ok] Companion started, DSH enabled={pipeline._dsh_enabled}", flush=True)

    if not pipeline._dsh_enabled:
        print("[skip] DSH 未启用", flush=True)
        await comp.stop()
        return

    try:
        # 1. 委托(触发工作区注册 + 人格化翻译)
        print(f"\n任务: {TASK}", flush=True)
        t0 = time.monotonic()
        resp = await pipeline._try_delegate_to_dsh(TASK, IncomingMessage.from_local(TASK, 12345))
        print(f"耗时: {time.monotonic() - t0:.1f}s", flush=True)

        if resp is None:
            print("[stop] 未委托", flush=True)
            await comp.stop()
            return

        print(f"\n回复(期望是伊塔口吻,非机械):\n{resp.text}", flush=True)

        # 2. 工作区:检查临时目录注册 + 操作日志
        ws = pipeline._dsh_workspace
        if ws is None:
            print("\n[skip] 工作区未初始化", flush=True)
        else:
            print(f"\n工作区根目录: {ws.roots()}", flush=True)
            print("操作日志:", flush=True)
            for act in ws.activities(limit=10):
                print(f"  [{act['kind']}] {act['detail']} (preset={act['preset']})", flush=True)

            # 3. 文件树实测
            print("\n文件树(D:\\T08171634 顶层):", flush=True)
            try:
                tree = ws.tree(r"D:\T08171634")
                for e in tree["entries"][:10]:
                    mark = "[dir]" if e["is_dir"] else f"[{e.get('ext', '')}] {e.get('size_human', '')}"
                    print(f"  {mark} {e['name']}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  (文件树失败: {exc})", flush=True)

            # 4. 缩略图实测
            print("\n缩略图(D:\\T08171634\\images\\1.png):", flush=True)
            try:
                data = ws.thumbnail(r"D:\T08171634\images\1.png", size=64)
                if data:
                    print(f"  ✅ 生成 {len(data)} 字节 PNG", flush=True)
                else:
                    print("  ⚠️  未生成(非图片或失败)", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  (缩略图失败: {exc})", flush=True)

        print("\n[ok] 验证完成", flush=True)
    finally:
        await comp.stop()


if __name__ == "__main__":
    asyncio.run(main())

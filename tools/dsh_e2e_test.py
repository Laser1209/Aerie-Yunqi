#!/usr/bin/env python3
"""端到端测试(完整委托链路 + 协议执行):整理 D:\\T08171634。

链路:router → dsh_cli(注入 protocol_prompt) → DSH 产出 WorkProtocol →
      work_protocol.execute → FileOrganizer preview→execute。

展示:协议结构 + FileOrganizer 执行日志 + 结果。
用法: python tools/dsh_e2e_test.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
for _name in ("core.work_mode_router", "core.work_protocol", "core.pipeline", "core.dsh_cli", "core.file_organizer"):
    logging.getLogger(_name).setLevel(logging.INFO)

from config.persona_loader import load_settings  # noqa: E402
from core.companion import Companion  # noqa: E402
from core.pipeline import _parse_work_protocol  # noqa: E402

TASK = "帮我整理 D:\\T08171634 文件夹，把里面所有文件按文件类型和内容归档整理，同类的放在一起"


async def main() -> None:
    comp = Companion(settings=load_settings())
    await comp.start()
    print("[ok] Companion started", flush=True)

    pipeline = comp.pipeline
    router = pipeline._dsh_router
    cli = pipeline._dsh_cli
    executor = pipeline._dsh_executor

    # 1. 路由判定
    print("\n=== 1. router.decide ===", flush=True)
    decision = await router.decide(TASK, user_id="0")
    print(f"decision: kind={decision.kind} preset={decision.preset} reason={decision.reason}", flush=True)

    if decision.kind != "delegate":
        print("[stop] 未委托", flush=True)
        await comp.stop()
        return

    # 2. 加载协议提示词
    system_prompt = pipeline._load_preset_protocol_prompt(decision.preset)
    print(f"\n=== 2. protocol_prompt ===\n{system_prompt}", flush=True)

    # 3. 委托(注入协议提示词)
    print("\n=== 3. dsh_cli.delegate ===", flush=True)
    result = await cli.delegate(TASK, preset=decision.preset, system_prompt=system_prompt)
    print(f"finish_reason: {result.finish_reason}", flush=True)
    print(f"DSH 原始输出:\n{result.final_response}", flush=True)

    # 4. 解析协议
    protocol = _parse_work_protocol(result.final_response)
    print(f"\n=== 4. WorkProtocol 解析 ===", flush=True)
    if protocol is None:
        print("[结果] DSH 未产出有效协议(走了纯文本路径)", flush=True)
        await comp.stop()
        return
    print(json.dumps(protocol, ensure_ascii=False, indent=2), flush=True)

    # 5. 执行协议
    print("\n=== 5. work_protocol.execute ===", flush=True)
    op_results = await executor.execute(protocol)
    print("\n执行结果:", flush=True)
    print(json.dumps(op_results, ensure_ascii=False, indent=2), flush=True)

    await comp.stop()
    print("\n[done]", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

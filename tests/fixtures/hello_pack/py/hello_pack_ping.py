"""hello-pack 验收夹具：验证 .aeriepack 契约的最小闭环。

真实功能包（browser/voice-asr/voice-rvc）的 register 必须遵循同一形态：
只通过 ctx 五件套接入，不在模块顶层 import 重型库（重库延迟到 start）。
"""

from __future__ import annotations

from fastapi import APIRouter

_router = APIRouter()
_started_with: object = None


@_router.get("/pong")
async def _pong() -> dict[str, str]:
    return {"ok": "true"}


async def start(companion: object) -> None:
    global _started_with
    _started_with = companion


async def stop() -> None:
    global _started_with
    _started_with = None


def register(ctx) -> None:
    def plugin_ping() -> dict[str, object]:
        return {"pong": True, "pack": ctx.pack_id}

    ctx.tool_registry.register(
        "plugin_ping",
        plugin_ping,
        {
            "name": "plugin_ping",
            "description": "hello-pack 验收工具：回铃",
            "parameters": {"type": "object", "properties": {}},
        },
        provider_hint="text",
        category="utility",
    )
    ctx.add_api_router(_router)

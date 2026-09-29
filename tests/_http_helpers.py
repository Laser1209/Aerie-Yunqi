"""构造最小 Starlette ``Request`` 的测试辅助。

后端有一批「读 JSON body → 写 .env」的端点（平台凭证、MCP 服务器、模型角色…），
测试它们不必起 TestClient（那会拉起整个 app 生命周期），只喂一个能 ``await
request.json()`` 的 Request 就够。多个测试文件共用这一份，避免各写各的。
"""

from __future__ import annotations

import json

from starlette.requests import Request


def make_request(body: dict, path: str = "/") -> Request:
    """按给定 body 造一个可直接传给端点的 POST Request。"""
    payload = json.dumps(body).encode("utf-8")

    async def receive() -> dict:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
        },
        receive,
    )

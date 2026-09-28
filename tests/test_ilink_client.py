import base64
import json
import re

import httpx
import pytest

from communication.ilink.client import ILinkClient
from communication.ilink.errors import (
    ILinkHTTPError,
    ILinkProtocolError,
    ILinkRateLimitError,
    ILinkSessionExpired,
)


@pytest.mark.asyncio
async def test_business_request_adds_protocol_headers_and_base_info():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"ret": 0, "msgs": [], "get_updates_buf": "cursor"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient(
            base_url="https://ilinkai.weixin.qq.com",
            token="secret-token",
            http_client=transport_client,
        )
        response = await client.get_updates("previous-cursor")

    request = requests[0]
    assert response.cursor == "cursor"
    assert request.headers["iLink-App-Id"] == "bot"
    assert request.headers["iLink-App-ClientVersion"] == ILinkClient.APP_CLIENT_VERSION
    assert request.headers["AuthorizationType"] == "ilink_bot_token"
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert request.headers.get("Content-Length") is not None
    assert base64.b64decode(request.headers["X-WECHAT-UIN"]).decode("ascii").isdigit()
    payload = json.loads(request.content)
    assert payload["get_updates_buf"] == "previous-cursor"
    assert payload["base_info"] == {"channel_version": "2.1.1"}


@pytest.mark.asyncio
async def test_business_request_generates_a_new_uin_each_time(monkeypatch):
    values = iter([1, 2])
    monkeypatch.setattr("communication.ilink.client.secrets.randbits", lambda _bits: next(values))

    async def handler(request):
        return httpx.Response(200, json={"ret": 0, "msgs": [], "get_updates_buf": ""})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        first = client.business_headers()["X-WECHAT-UIN"]
        second = client.business_headers()["X-WECHAT-UIN"]

    assert first != second


@pytest.mark.asyncio
async def test_http_errors_are_structured_without_response_body():
    async def handler(request):
        return httpx.Response(403, text="token=must-not-leak")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "secret-token", transport_client)
        with pytest.raises(ILinkHTTPError) as captured:
            await client.get_updates("")

    assert captured.value.status_code == 403
    assert "must-not-leak" not in str(captured.value)
    assert "secret-token" not in str(captured.value)


@pytest.mark.asyncio
async def test_rate_limit_exposes_retry_after():
    async def handler(request):
        return httpx.Response(429, headers={"Retry-After": "12"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        with pytest.raises(ILinkRateLimitError) as captured:
            await client.get_updates("")

    assert captured.value.retry_after == 12.0


@pytest.mark.asyncio
async def test_session_expiry_is_raised_from_business_response():
    async def handler(request):
        return httpx.Response(
            200,
            json={"ret": 1, "errcode": -14, "errmsg": "expired", "msgs": [], "get_updates_buf": ""},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        with pytest.raises(ILinkSessionExpired):
            await client.get_updates("")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ret", "errcode"),
    [
        (1, 0),
        (0, 40001),
    ],
)
async def test_nonzero_business_result_is_rejected(ret, errcode):
    async def handler(request):
        return httpx.Response(
            200,
            json={
                "ret": ret,
                "errcode": errcode,
                "errmsg": "failed",
                "msgs": [],
                "get_updates_buf": "",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        with pytest.raises(ILinkProtocolError, match="business request failed"):
            await client.get_updates("")


@pytest.mark.asyncio
async def test_send_text_posts_finished_bot_message_with_context():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ret": 0, "errcode": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        sent = await client.send_text("wx-owner", "收到。", "context-1")

    assert sent is True
    assert requests[0].url.path == "/ilink/bot/sendmessage"
    payload = json.loads(requests[0].content)
    client_id = payload["msg"]["client_id"]
    assert re.fullmatch(r"openclaw-weixin:\d+-[0-9a-f]{8}", client_id)
    assert payload == {
        "msg": {
            "from_user_id": "",
            "to_user_id": "wx-owner",
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": "收到。"}}],
            "context_token": "context-1",
        },
        "base_info": {"channel_version": "2.1.1"},
    }


@pytest.mark.asyncio
async def test_send_text_treats_missing_ret_as_success():
    """成功响应常不带 ret；缺 ret 不该被判失败（否则配对后依然发不出微信）。"""

    async def handler(request):
        del request
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        sent = await client.send_text("wx-owner", "收到。", "context-1")

    assert sent is True


@pytest.mark.asyncio
async def test_send_text_raises_on_explicit_nonzero_ret():
    async def handler(request):
        del request
        return httpx.Response(200, json={"ret": 1001, "errmsg": "rate limited"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        with pytest.raises(ILinkProtocolError, match="ret=1001"):
            await client.send_text("wx-owner", "收到。", "context-1")


@pytest.mark.asyncio
async def test_send_file_posts_nested_media_file_item():
    """文件项的 media 是**嵌套对象**，且 len 必须是字符串。

    这两点是与官方 SDK（Go/Rust/Python/TS）核对出来的协议要求：
    media 写成扁平字段、或 len 传 int，服务端只会回一个笼统的参数错误。
    """
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ret": 0, "errcode": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        sent = await client.send_file(
            "wx-owner",
            "context-1",
            file_name="笔记.txt",
            file_md5="d41d8cd98f00b204e9800998ecf8427e",
            file_size=1024,
            encrypt_query_param="param-abc",
            aes_key="a2V5",
        )

    assert sent is True
    assert requests[0].url.path == "/ilink/bot/sendmessage"
    payload = json.loads(requests[0].content)
    client_id = payload["msg"]["client_id"]
    assert payload == {
        "msg": {
            "from_user_id": "",
            "to_user_id": "wx-owner",
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "item_list": [
                {
                    "type": 4,
                    "file_item": {
                        "media": {
                            "encrypt_query_param": "param-abc",
                            "aes_key": "a2V5",
                        },
                        "file_name": "笔记.txt",
                        "md5": "d41d8cd98f00b204e9800998ecf8427e",
                        "len": "1024",
                    },
                }
            ],
            "context_token": "context-1",
        },
        "base_info": {"channel_version": "2.1.1"},
    }


@pytest.mark.asyncio
async def test_send_image_posts_nested_media_image_item():
    """图片项与文件项同形态：``image_item.media`` 是嵌套对象，消息项 type 取 2。

    图片项不带 ``file_name`` / ``len`` 这些文件专有字段——多塞会被判参数错误。
    """
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ret": 0, "errcode": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        sent = await client.send_image(
            "wx-owner",
            "context-1",
            encrypt_query_param="param-abc",
            aes_key="a2V5",
        )

    assert sent is True
    payload = json.loads(requests[0].content)
    assert payload["msg"]["item_list"] == [
        {
            "type": 2,
            "image_item": {
                "media": {
                    "encrypt_query_param": "param-abc",
                    "aes_key": "a2V5",
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_send_image_shares_text_success_semantics():
    """图片与文本共用同一信封：成功判定不能分叉。"""

    async def handler(request):
        del request
        return httpx.Response(200, json={"ret": -2, "errmsg": "invalid param"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        with pytest.raises(ILinkProtocolError, match="ret=-2"):
            await client.send_image(
                "wx-owner",
                "context-1",
                encrypt_query_param="param",
                aes_key="key",
            )


@pytest.mark.asyncio
async def test_send_file_shares_text_success_semantics():
    """媒体与文本共用同一信封：成功判定不能分叉。"""

    async def handler(request):
        del request
        return httpx.Response(200, json={"ret": -2, "errmsg": "invalid param"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", transport_client)
        with pytest.raises(ILinkProtocolError, match="ret=-2"):
            await client.send_file(
                "wx-owner",
                "context-1",
                file_name="a.txt",
                file_md5="0" * 32,
                file_size=1,
                encrypt_query_param="param",
                aes_key="key",
            )

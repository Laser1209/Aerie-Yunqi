import asyncio
import base64

import httpx
import pytest

from core import ilink_auth_flow as flow_module
from core.ilink_auth_flow import ILinkLoginFlow
from core.ilink_credentials import ILinkCredentialsStore


PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def install_transport(monkeypatch, responses):
    from communication.ilink.client import ILinkClient

    transport = httpx.MockTransport(_make_handler(responses))
    async_client = httpx.AsyncClient(transport=transport)

    def factory(base_url):
        return ILinkClient(base_url=base_url, http_client=async_client)

    monkeypatch.setattr(flow_module, "ILinkClient", factory)
    return async_client


def _make_handler(responses):
    async def handler(request):
        # Yield control like the real ~40s long-poll does.
        await asyncio.sleep(0.02)
        return next(responses)
    return handler


def test_login_url_is_rendered_into_png_data_url():
    from core.ilink_auth_flow import _to_data_url

    result = _to_data_url("https://liteapp.weixin.qq.com/q/abc?bot_type=3")

    assert result.startswith("data:image/png;base64,")
    decoded = base64.b64decode(result.split(",", 1)[1])
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_start_returns_qrcode_data_url_and_cancel_resets(tmp_path, monkeypatch):
    async def handler(request):
        if request.url.path.endswith("/get_bot_qrcode"):
            return httpx.Response(200, json={"qrcode": "sess-1", "qrcode_img_content": PNG_1X1})
        # Emulate the upstream long-poll: yield control so the loop can cancel.
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"status": "wait"})

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    from communication.ilink.client import ILinkClient
    monkeypatch.setattr(
        flow_module,
        "ILinkClient",
        lambda base_url: ILinkClient(base_url=base_url, http_client=async_client),
    )

    flow = ILinkLoginFlow(ILinkCredentialsStore(tmp_path / "creds.json"))
    status = await flow.start()

    assert status["phase"] == "waiting"
    assert status["qrcode_available"] is True
    assert status["qrcode_image"].startswith("data:image/png;base64,")

    await asyncio.sleep(0.05)
    await flow.cancel()
    assert flow.get_status()["phase"] == "idle"


@pytest.mark.asyncio
async def test_confirmed_persists_credentials_and_invokes_callback(tmp_path, monkeypatch):
    responses = iter([
        httpx.Response(200, json={"qrcode": "sess-2", "qrcode_img_content": PNG_1X1}),
        httpx.Response(200, json={"status": "scaned"}),
        httpx.Response(200, json={
            "status": "confirmed",
            "bot_token": "tok-1",
            "ilink_bot_id": "bot-9",
            "ilink_user_id": "user-9",
            "baseurl": "https://ilinkai.weixin.qq.com",
        }),
    ])
    install_transport(monkeypatch, responses)

    store = ILinkCredentialsStore(tmp_path / "creds.json")
    callback_args = []

    async def on_confirmed(credentials):
        callback_args.append(credentials)

    flow = ILinkLoginFlow(store, on_confirmed=on_confirmed)
    await flow.start()
    for _ in range(40):
        await asyncio.sleep(0.05)
        if flow.get_status()["phase"] == "confirmed":
            break

    assert flow.get_status()["phase"] == "confirmed"
    assert len(callback_args) == 1
    assert callback_args[0].bot_id == "bot-9"
    saved = store.load()
    assert saved is not None and saved.bot_token == "tok-1"


@pytest.mark.asyncio
async def test_expired_clears_qrcode(tmp_path, monkeypatch):
    responses = iter([
        httpx.Response(200, json={"qrcode": "sess-3", "qrcode_img_content": PNG_1X1}),
        httpx.Response(200, json={"status": "expired"}),
    ])
    install_transport(monkeypatch, responses)

    flow = ILinkLoginFlow(ILinkCredentialsStore(tmp_path / "creds.json"))
    await flow.start()
    for _ in range(40):
        await asyncio.sleep(0.05)
        if flow.get_status()["phase"] == "expired":
            break

    status = flow.get_status()
    assert status["phase"] == "expired"
    assert status["qrcode_available"] is False

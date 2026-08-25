import httpx
import pytest

from communication.ilink.auth import ILinkAuthSession
from communication.ilink.client import ILinkClient
from communication.ilink.errors import ILinkProtocolError
from communication.ilink.models import AuthStatus


@pytest.mark.asyncio
async def test_auth_session_requests_qrcode_and_tracks_pending_state():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"qrcode": "opaque-session", "qrcode_img_content": "opaque-payload"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", http_client=transport_client)
        session = ILinkAuthSession(client)
        challenge = await session.request_qrcode()

    assert challenge.qrcode == "opaque-session"
    assert session.status is AuthStatus.WAIT
    assert requests[0].url.path == "/ilink/bot/get_bot_qrcode"
    assert requests[0].url.params["bot_type"] == "3"
    assert "Authorization" not in requests[0].headers


@pytest.mark.asyncio
async def test_auth_session_tracks_scanned_and_confirmed_states():
    responses = iter(
        [
            httpx.Response(
                200,
                json={"qrcode": "opaque-session", "qrcode_img_content": "opaque-payload"},
            ),
            httpx.Response(200, json={"status": "scaned"}),
            httpx.Response(
                200,
                json={
                    "status": "confirmed",
                    "bot_token": "secret-token",
                    "ilink_bot_id": "bot@im.bot",
                    "ilink_user_id": "user@im.wechat",
                    "baseurl": "https://ilinkai.weixin.qq.com",
                },
            ),
        ]
    )

    async def handler(request):
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        session = ILinkAuthSession(
            ILinkClient("https://ilinkai.weixin.qq.com", http_client=transport_client)
        )
        await session.request_qrcode()
        scanned = await session.poll_status()
        confirmed = await session.poll_status()

    assert scanned.status is AuthStatus.SCANED
    assert confirmed.status is AuthStatus.CONFIRMED
    assert confirmed.credentials.bot_token == "secret-token"
    assert session.challenge is None


@pytest.mark.asyncio
async def test_auth_redirect_accepts_only_configured_https_host():
    responses = iter(
        [
            httpx.Response(
                200,
                json={"qrcode": "opaque-session", "qrcode_img_content": "opaque-payload"},
            ),
            httpx.Response(
                200,
                json={"status": "scaned_but_redirect", "redirect_host": "idc.weixin.qq.com"},
            ),
        ]
    )

    async def handler(request):
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        session = ILinkAuthSession(
            ILinkClient("https://ilinkai.weixin.qq.com", http_client=transport_client),
            allowed_redirect_hosts={"idc.weixin.qq.com"},
        )
        await session.request_qrcode()
        result = await session.poll_status()

    assert result.status is AuthStatus.SCANED_BUT_REDIRECT
    assert session.client.base_url == "https://idc.weixin.qq.com"


@pytest.mark.asyncio
async def test_auth_redirect_rejects_untrusted_host():
    responses = iter(
        [
            httpx.Response(
                200,
                json={"qrcode": "opaque-session", "qrcode_img_content": "opaque-payload"},
            ),
            httpx.Response(
                200,
                json={"status": "scaned_but_redirect", "redirect_host": "evil.example"},
            ),
        ]
    )

    async def handler(request):
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
        session = ILinkAuthSession(
            ILinkClient("https://ilinkai.weixin.qq.com", http_client=transport_client),
            allowed_redirect_hosts={"idc.weixin.qq.com"},
        )
        await session.request_qrcode()
        with pytest.raises(ILinkProtocolError, match="redirect_host"):
            await session.poll_status()


@pytest.mark.asyncio
async def test_auth_poll_requires_an_active_challenge():
    session = ILinkAuthSession(ILinkClient("https://ilinkai.weixin.qq.com"))

    with pytest.raises(ILinkProtocolError, match="active qrcode"):
        await session.poll_status()

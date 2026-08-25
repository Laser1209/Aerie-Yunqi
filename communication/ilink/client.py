from __future__ import annotations

import base64
import secrets
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from communication.ilink.errors import (
    ILinkHTTPError,
    ILinkProtocolError,
    ILinkRateLimitError,
    ILinkSessionExpired,
)
from communication.ilink.models import AuthPollResult, GetUpdatesResponse, QRCodeChallenge


class ILinkClient:
    APP_CLIENT_VERSION = "2.1.1"
    CHANNEL_VERSION = "2.1.1"
    DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=20.0, pool=10.0)

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.token = token
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT)

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("base_url must be an HTTPS origin")
        if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an HTTPS origin")
        return value.rstrip("/")

    def set_base_url(self, value: str) -> None:
        self.base_url = self._normalize_base_url(value)

    def common_headers(self) -> dict[str, str]:
        return {
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": self.APP_CLIENT_VERSION,
        }

    def business_headers(self) -> dict[str, str]:
        if not self.token:
            raise ILinkProtocolError("bot token is required")
        random_uin = str(secrets.randbits(32)).encode("ascii")
        return {
            **self.common_headers(),
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.token}",
            "X-WECHAT-UIN": base64.b64encode(random_uin).decode("ascii"),
        }

    async def request_qrcode(self) -> QRCodeChallenge:
        data = await self._get_json(
            "/ilink/bot/get_bot_qrcode",
            params={"bot_type": "3"},
            headers=self.common_headers(),
        )
        return QRCodeChallenge.from_dict(data)

    async def poll_qrcode_status(self, qrcode: str) -> AuthPollResult:
        data = await self._get_json(
            "/ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            headers=self.common_headers(),
            timeout=httpx.Timeout(connect=10.0, read=40.0, write=20.0, pool=10.0),
        )
        return AuthPollResult.from_dict(data)

    async def get_updates(self, cursor: str = "") -> GetUpdatesResponse:
        data = await self._post_json("/ilink/bot/getupdates", {"get_updates_buf": cursor})
        response = GetUpdatesResponse.from_dict(data)
        if response.errcode == -14:
            raise ILinkSessionExpired("iLink session expired")
        if response.ret != 0 or response.errcode not in (None, 0):
            raise ILinkProtocolError("iLink business request failed")
        return response

    async def get_upload_url(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post_json("/ilink/bot/getuploadurl", body)

    async def send_text(self, to_user_id: str, text: str, context_token: str) -> bool:
        client_id = f"openclaw-weixin:{int(time.time() * 1000)}-{secrets.token_hex(4)}"
        data = await self._post_json(
            "/ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": client_id,
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [
                        {"type": 1, "text_item": {"text": text}}
                    ],
                    "context_token": context_token,
                }
            },
        )
        if data.get("ret") != 0 or data.get("errcode") not in (None, 0):
            raise ILinkProtocolError("iLink business request failed")
        return True

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        timeout: httpx.Timeout | None = None,
    ) -> dict[str, Any]:
        response = await self._http_client.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=timeout or self.DEFAULT_TIMEOUT,
        )
        self._raise_for_status(response)
        return self._response_json(response)

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = {**body, "base_info": {"channel_version": self.CHANNEL_VERSION}}
        response = await self._http_client.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=self.business_headers(),
            timeout=self.DEFAULT_TIMEOUT,
        )
        self._raise_for_status(response)
        return self._response_json(response)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            parsed_retry_after = None
            if retry_after is not None:
                try:
                    parsed_retry_after = float(retry_after)
                except ValueError:
                    parsed_retry_after = None
            raise ILinkRateLimitError(parsed_retry_after)
        if response.is_error:
            raise ILinkHTTPError(response.status_code)

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ILinkProtocolError("iLink response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ILinkProtocolError("iLink response must be an object")
        return data

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> ILinkClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

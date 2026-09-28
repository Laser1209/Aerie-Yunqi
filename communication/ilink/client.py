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
from communication.ilink.models import (
    AuthPollResult,
    GetUpdatesResponse,
    MessageItemType,
    QRCodeChallenge,
)


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

    @property
    def http_client(self) -> httpx.AsyncClient:
        """媒体传输复用同一条连接池，避免每个附件都新建连接。"""
        return self._http_client

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
        return await self._send_message(
            to_user_id,
            context_token,
            [{"type": MessageItemType.TEXT, "text_item": {"text": text}}],
        )

    async def send_file(
        self,
        to_user_id: str,
        context_token: str,
        *,
        file_name: str,
        file_md5: str,
        file_size: int,
        encrypt_query_param: str,
        aes_key: str,
    ) -> bool:
        """把已上传到 CDN 的文件作为文件消息发出。

        文件项的 ``media`` 是**嵌套对象**（不是扁平字段），字段名与取值形态
        已与官方 SDK（Go/Rust/Python/TS）逐项核对：``file_name`` 显示名、
        ``md5`` 明文摘要、``len`` 明文长度。
        """
        return await self._send_message(
            to_user_id,
            context_token,
            [
                {
                    "type": MessageItemType.FILE,
                    "file_item": {
                        "media": {
                            "encrypt_query_param": encrypt_query_param,
                            "aes_key": aes_key,
                        },
                        "file_name": file_name,
                        "md5": file_md5,
                        # 协议里 len 是**字符串**；传 int 会被判成参数错误。
                        "len": str(file_size),
                    },
                }
            ],
        )

    async def send_image(
        self,
        to_user_id: str,
        context_token: str,
        *,
        encrypt_query_param: str,
        aes_key: str,
    ) -> bool:
        """把已上传到 CDN 的图片作为图片消息发出。

        ``image_item`` 与 ``file_item`` 是同一形态：``media`` 是**嵌套对象**，
        字段名 ``encrypt_query_param`` / ``aes_key`` 一致；协议差别只在消息项
        ``type`` 取 2（图片）。图片项**不**带 ``file_name`` / ``len`` 这类文件字段。
        """
        return await self._send_message(
            to_user_id,
            context_token,
            [
                {
                    "type": MessageItemType.IMAGE,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": encrypt_query_param,
                            "aes_key": aes_key,
                        },
                    },
                }
            ],
        )

    async def _send_message(
        self,
        to_user_id: str,
        context_token: str,
        item_list: list[dict[str, Any]],
    ) -> bool:
        """发一条 bot 已完成的私聊消息（文本与媒体共用同一信封）。

        信封与成功判定集中在此处：``ret`` 语义的坑（成功响应常常省略 ret）
        只允许有一个实现，否则文本通了、媒体又踩一遍。
        """
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
                    "item_list": item_list,
                    "context_token": context_token,
                }
            },
        )
        # iLink 成功响应常常根本不带 ret 字段（与 getupdates 同一模式，实测确认过）。
        # 原写法 `data.get("ret") != 0` 会把缺失的 ret 判成 None != 0 → 抛错，
        # 于是配对成功后依然一条微信都发不出去（2026-09-27 定位）。
        # 缺失即视为 0；只有显式非 0 或非 0 errcode 才算失败。
        ret = data.get("ret")
        errcode = data.get("errcode")
        if (ret is not None and ret != 0) or (errcode not in (None, 0)):
            raise ILinkProtocolError(
                f"iLink send failed: ret={ret!r} errcode={errcode!r} keys={sorted(data.keys())}"
            )
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

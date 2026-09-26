"""Scan-to-login orchestration for the iLink (WeChat) bot channel.

Wraps the protocol-level ``ILinkAuthSession`` with an application-friendly
state machine (``idle → waiting → scanned → confirmed``), persists credentials
via DPAPI once the phone scan is confirmed, and then hands off to the running
``ILinkGateway``.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import qrcode

from communication.ilink.auth import ILinkAuthSession
from communication.ilink.client import ILinkClient
from communication.ilink.errors import ILinkError
from communication.ilink.models import (
    AuthStatus,
    ILinkCredentials as ProtocolCredentials,
)
from core.ilink_credentials import (
    CredentialsError,
    ILinkCredentials,
    ILinkCredentialsStore,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
# Official iLink auth redirect hosts (see protocol tests); the initial origin
# is always allowed in addition to these.
_TRUSTED_REDIRECT_HOSTS = frozenset({"idc.weixin.qq.com"})

# Polling pauses: the upstream status call long-polls ~40s itself.
_RETRY_PAUSE_SECONDS = 3.0


@dataclass(frozen=True)
class LoginOutcome:
    credentials: ILinkCredentials


ConfirmedCallback = Callable[[ProtocolCredentials], Awaitable[Any]]


def _render_url_as_data_url(url: str) -> str:
    """Render a login landing URL into a scannable QR PNG data URL.

    iLink returns the URL the phone should open (an HTML landing page), not an
    image, so the panel needs a locally rendered QR just like the QQ flow.
    """
    image = qrcode.QRCode(border=2, box_size=10)
    image.add_data(url)
    image.make(fit=True)
    buffer = io.BytesIO()
    image.make_image().save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _to_data_url(image_content: str) -> str:
    """Normalize the upstream qrcode payload into a browser data URL."""
    if image_content.startswith("data:"):
        return image_content
    stripped = image_content.strip()
    if stripped.startswith(("http://", "https://")):
        return _render_url_as_data_url(stripped)
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError):
        if stripped.lstrip().startswith("<svg"):
            return "data:image/svg+xml;charset=utf-8," + stripped
        raise
    if decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif decoded[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    else:
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(decoded).decode('ascii')}"


class ILinkLoginFlow:
    """Holds one active QR login session and exposes snapshot-able state."""

    def __init__(
        self,
        credentials_store: ILinkCredentialsStore,
        *,
        base_url: str = DEFAULT_BASE_URL,
        on_confirmed: ConfirmedCallback | None = None,
        trusted_redirect_hosts: frozenset[str] = _TRUSTED_REDIRECT_HOSTS,
    ) -> None:
        self.credentials_store = credentials_store
        self.base_url = base_url.rstrip("/")
        self.on_confirmed = on_confirmed
        self.trusted_redirect_hosts = trusted_redirect_hosts
        self._session: ILinkAuthSession | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._client: ILinkClient | None = None
        self._phase = "idle"  # idle | waiting | scanned | confirmed | expired | error
        self._qrcode_image = ""
        self._error_code = ""

    def get_status(self) -> dict[str, Any]:
        return {
            "phase": self._phase,
            "qrcode_available": bool(self._qrcode_image)
            and self._phase in ("waiting", "scanned"),
            "qrcode_image": self._qrcode_image,
            "error_code": self._error_code,
        }

    async def start(self) -> dict[str, Any]:
        """Request a fresh QR code and begin background status polling."""
        await self.cancel()
        client = ILinkClient(self.base_url)
        session = ILinkAuthSession(
            client,
            allowed_redirect_hosts=self.trusted_redirect_hosts
            | {self.base_url.split("//", 1)[1]},
        )
        try:
            challenge = await session.request_qrcode()
        except ILinkError as exc:
            await client.close()
            self._phase = "error"
            self._error_code = "qrcode_request_failed"
            logger.warning("iLink qrcode request failed: %s", exc)
            return self.get_status()
        self._client = client
        self._session = session
        self._qrcode_image = _to_data_url(challenge.image_content)
        self._error_code = ""
        self._phase = "waiting"
        self._poll_task = asyncio.create_task(self._poll_loop(session))
        return self.get_status()

    async def cancel(self) -> dict[str, Any]:
        task = self._poll_task
        self._poll_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._session is not None:
            self._session.cancel()
            self._session = None
        client = self._client
        self._client = None
        if client is not None:
            await client.close()
        self._phase = "idle"
        self._qrcode_image = ""
        self._error_code = ""
        return self.get_status()

    async def _poll_loop(self, session: ILinkAuthSession) -> None:
        while True:
            try:
                result = await session.poll_status()
            except asyncio.CancelledError:
                raise
            except ILinkError as exc:
                # Long-poll network hiccups are transient; keep the displayed
                # code and retry until it expires server-side.
                logger.debug("iLink auth poll retry after error: %s", exc)
                await asyncio.sleep(_RETRY_PAUSE_SECONDS)
                continue

            status = result.status
            if status is AuthStatus.WAIT:
                self._phase = "waiting"
            elif status in (AuthStatus.SCANED, AuthStatus.SCANED_BUT_REDIRECT):
                self._phase = "scanned"
            elif status is AuthStatus.EXPIRED:
                self._phase = "expired"
                self._qrcode_image = ""
                return
            elif status is AuthStatus.CONFIRMED and result.credentials is not None:
                await self._handle_confirmation(result.credentials)
                return

    async def _handle_confirmation(self, protocol_creds: ProtocolCredentials) -> None:
        credentials = ILinkCredentials(
            bot_token=protocol_creds.bot_token,
            bot_id=protocol_creds.bot_id,
            user_id=protocol_creds.user_id,
            base_url=protocol_creds.base_url,
        )
        try:
            self.credentials_store.save(credentials)
        except CredentialsError:
            self._phase = "error"
            self._error_code = "credential_save_failed"
            logger.exception("failed to persist iLink credentials")
            return
        self._phase = "confirmed"
        self._qrcode_image = ""
        logger.info("iLink login confirmed for bot %s", credentials.bot_id)
        if self.on_confirmed is not None:
            try:
                await self.on_confirmed(protocol_creds)
            except Exception:
                logger.exception("iLink post-login gateway start failed")

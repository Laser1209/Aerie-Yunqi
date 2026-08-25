from __future__ import annotations

from urllib.parse import urlparse

from communication.ilink.client import ILinkClient
from communication.ilink.errors import ILinkProtocolError
from communication.ilink.models import AuthPollResult, AuthStatus, QRCodeChallenge


class ILinkAuthSession:
    def __init__(
        self,
        client: ILinkClient,
        allowed_redirect_hosts: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.client = client
        initial_host = urlparse(client.base_url).hostname
        self.allowed_redirect_hosts = frozenset(
            allowed_redirect_hosts or ({initial_host} if initial_host else set())
        )
        self.challenge: QRCodeChallenge | None = None
        self.status: AuthStatus | None = None

    async def request_qrcode(self) -> QRCodeChallenge:
        challenge = await self.client.request_qrcode()
        self.challenge = challenge
        self.status = AuthStatus.WAIT
        return challenge

    async def poll_status(self) -> AuthPollResult:
        if self.challenge is None:
            raise ILinkProtocolError("active qrcode is required")
        result = await self.client.poll_qrcode_status(self.challenge.qrcode)
        if result.status is AuthStatus.SCANED_BUT_REDIRECT:
            self._apply_redirect(result.redirect_host)
        self.status = result.status
        if result.status in (AuthStatus.CONFIRMED, AuthStatus.EXPIRED):
            self.challenge = None
        return result

    def _apply_redirect(self, redirect_host: str | None) -> None:
        if redirect_host is None or redirect_host not in self.allowed_redirect_hosts:
            raise ILinkProtocolError("redirect_host is not allowed")
        if urlparse(f"https://{redirect_host}").hostname != redirect_host:
            raise ILinkProtocolError("redirect_host is invalid")
        self.client.set_base_url(f"https://{redirect_host}")

    def cancel(self) -> None:
        self.challenge = None
        self.status = None

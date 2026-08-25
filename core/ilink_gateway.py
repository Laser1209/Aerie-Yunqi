from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from typing import Any

import httpx

from communication.ilink.channel import ILinkChannel, TextCallback
from communication.ilink.client import ILinkClient
from communication.ilink.errors import ILinkHTTPError, ILinkRateLimitError, ILinkSessionExpired
from core.ilink_credentials import ILinkCredentials, ILinkCredentialsStore
from core.ilink_state import ILinkStateStore


class ILinkGateway:
    def __init__(
        self,
        credentials_store: ILinkCredentialsStore,
        state_store: ILinkStateStore,
        primary_user_id: int,
        on_text: TextCallback,
        *,
        client_factory: Callable[[ILinkCredentials], ILinkClient] | None = None,
        channel_factory: Callable[..., ILinkChannel] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.credentials_store = credentials_store
        self.state_store = state_store
        self.primary_user_id = primary_user_id
        self.on_text = on_text
        self.client_factory = client_factory or self._create_client
        self.channel_factory = channel_factory or ILinkChannel
        self.sleep = sleep
        self.jitter = jitter
        self.poll_task: asyncio.Task[None] | None = None
        self._client: ILinkClient | None = None
        self._bot_id: str | None = None
        self._stop_lock = asyncio.Lock()

    async def start(self) -> asyncio.Task[None]:
        if self.poll_task is not None and not self.poll_task.done():
            return self.poll_task
        credentials = self.credentials_store.load()
        if credentials is None:
            raise RuntimeError("iLink credentials are required")
        self._bot_id = credentials.bot_id
        self._client = self.client_factory(credentials)
        channel = self.channel_factory(
            self._client,
            self.state_store,
            credentials.bot_id,
            self.primary_user_id,
            self.on_text,
        )
        self.poll_task = asyncio.create_task(self._poll(channel, credentials.bot_id))
        return self.poll_task

    def is_configured(self) -> bool:
        return self.credentials_store.load() is not None

    def get_status(self) -> dict[str, Any]:
        configured = self.is_configured()
        task = self.poll_task
        connected = self._client is not None and task is not None and not task.done()
        if connected:
            phase = "connected"
        elif configured:
            phase = "idle"
        else:
            phase = "disabled"
        return {
            "phase": phase,
            "configured": configured,
            "connected": connected,
        }

    async def stop(self) -> None:
        async with self._stop_lock:
            task = self.poll_task
            self.poll_task = None
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            client = self._client
            self._client = None
            if client is not None:
                await client.close()

    async def send_text(
        self,
        channel_account_id: str,
        content: str,
    ) -> bool:
        if self._client is None:
            raise RuntimeError("iLink gateway is not running")
        if self._bot_id is None:
            raise RuntimeError("iLink bot state is unavailable")
        context_token = self.state_store.get_context_token(self._bot_id)
        if not context_token:
            raise RuntimeError("iLink context token is required")
        return await self._client.send_text(
            channel_account_id,
            content,
            context_token,
        )

    async def _poll(self, channel: ILinkChannel, bot_id: str) -> None:
        failure_count = 0
        while True:
            try:
                await channel.poll_once()
                failure_count = 0
            except asyncio.CancelledError:
                raise
            except ILinkRateLimitError as exc:
                failure_count += 1
                delay = exc.retry_after
                if delay is None:
                    delay = self._backoff(failure_count)
                await self.sleep(delay)
            except ILinkSessionExpired:
                self.credentials_store.delete()
                self.state_store.clear(bot_id)
                if self._client is not None:
                    await self._client.close()
                    self._client = None
                self._bot_id = None
                self.poll_task = None
                return
            except ILinkHTTPError as exc:
                if exc.status_code < 500:
                    raise
                failure_count += 1
                await self.sleep(self._backoff(failure_count))
            except (OSError, TimeoutError, httpx.TimeoutException):
                failure_count += 1
                await self.sleep(self._backoff(failure_count))

    def _backoff(self, failure_count: int) -> float:
        base = min(2 ** failure_count, 30)
        return base * (1 + self.jitter() * 0.2)

    @staticmethod
    def _create_client(credentials: ILinkCredentials) -> ILinkClient:
        return ILinkClient(credentials.base_url, credentials.bot_token)

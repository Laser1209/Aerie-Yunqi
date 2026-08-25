import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from communication.ilink.errors import ILinkHTTPError, ILinkRateLimitError, ILinkSessionExpired
from core.ilink_credentials import ILinkCredentials, ILinkCredentialsStore
from core.ilink_gateway import ILinkGateway
from core.ilink_state import ILinkStateStore


class BlockingChannel:
    def __init__(self):
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def poll_once(self):
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@pytest.mark.asyncio
async def test_gateway_start_is_idempotent_and_stop_waits_for_poller_before_close(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    state_store.set_context_token("bot-1", "latest-context")
    client = AsyncMock()
    channel = BlockingChannel()
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: client,
        channel_factory=lambda *_args: channel,
    )

    first_task = await gateway.start()
    second_task = await gateway.start()
    await asyncio.wait_for(channel.entered.wait(), 1)

    assert first_task is second_task
    await gateway.stop()
    assert channel.cancelled.is_set()
    client.close.assert_awaited_once()
    assert gateway.poll_task is None
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_send_text_uses_running_client(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    state_store.set_context_token("bot-1", "latest-context")
    client = AsyncMock()
    client.send_text.return_value = True
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: client,
        channel_factory=lambda *_args: BlockingChannel(),
    )

    await gateway.start()
    sent = await gateway.send_text("wx-owner", "回复")
    await gateway.stop()

    assert sent is True
    client.send_text.assert_awaited_once_with("wx-owner", "回复", "latest-context")
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_stop_is_idempotent(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    client = AsyncMock()
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: client,
        channel_factory=lambda *_args: BlockingChannel(),
    )

    await gateway.start()
    await asyncio.gather(gateway.stop(), gateway.stop())

    client.close.assert_awaited_once()
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_uses_retry_after_then_increases_backoff_for_consecutive_failure(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    delays = []
    finished = asyncio.Event()

    class RetryingChannel:
        calls = 0

        async def poll_once(self):
            self.calls += 1
            if self.calls == 1:
                raise ILinkRateLimitError(7)
            if self.calls == 2:
                raise OSError("temporary")
            finished.set()
            await asyncio.Event().wait()

    async def sleep(delay):
        delays.append(delay)

    client = AsyncMock()
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: client,
        channel_factory=lambda *_args: RetryingChannel(),
        sleep=sleep,
        jitter=lambda: 0,
    )

    await gateway.start()
    await asyncio.wait_for(finished.wait(), 1)
    await gateway.stop()

    assert delays == [7, 4]
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_resets_backoff_after_successful_poll(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    delays = []
    finished = asyncio.Event()

    class RecoveringChannel:
        calls = 0

        async def poll_once(self):
            self.calls += 1
            if self.calls in {1, 3}:
                raise OSError("temporary")
            if self.calls == 2:
                return
            finished.set()
            await asyncio.Event().wait()

    async def sleep(delay):
        delays.append(delay)

    client = AsyncMock()
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: client,
        channel_factory=lambda *_args: RecoveringChannel(),
        sleep=sleep,
        jitter=lambda: 0,
    )

    await gateway.start()
    await asyncio.wait_for(finished.wait(), 1)
    await gateway.stop()

    assert delays == [2, 2]
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_retries_server_errors(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    delays = []
    finished = asyncio.Event()

    class ServerErrorChannel:
        calls = 0

        async def poll_once(self):
            self.calls += 1
            if self.calls == 1:
                raise ILinkHTTPError(503)
            finished.set()
            await asyncio.Event().wait()

    async def sleep(delay):
        delays.append(delay)

    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: AsyncMock(),
        channel_factory=lambda *_args: ServerErrorChannel(),
        sleep=sleep,
        jitter=lambda: 0,
    )

    await gateway.start()
    await asyncio.wait_for(finished.wait(), 1)
    await gateway.stop()

    assert delays == [2]
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_does_not_retry_client_errors(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    sleep = AsyncMock()

    class ClientErrorChannel:
        async def poll_once(self):
            raise ILinkHTTPError(400)

    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: AsyncMock(),
        channel_factory=lambda *_args: ClientErrorChannel(),
        sleep=sleep,
    )

    task = await gateway.start()
    with pytest.raises(ILinkHTTPError):
        await task

    sleep.assert_not_awaited()
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_retries_httpx_timeouts(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    delays = []
    finished = asyncio.Event()

    class TimeoutChannel:
        calls = 0

        async def poll_once(self):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("timed out")
            finished.set()
            await asyncio.Event().wait()

    async def sleep(delay):
        delays.append(delay)

    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: AsyncMock(),
        channel_factory=lambda *_args: TimeoutChannel(),
        sleep=sleep,
        jitter=lambda: 0,
    )

    await gateway.start()
    await asyncio.wait_for(finished.wait(), 1)
    await gateway.stop()

    assert delays == [2]
    state_store.close()


@pytest.mark.asyncio
async def test_session_expiry_clears_credentials_and_state_then_stops(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    state_store.set_cursor("bot-1", "cursor")
    client = AsyncMock()

    class ExpiredChannel:
        async def poll_once(self):
            raise ILinkSessionExpired("expired")

    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: client,
        channel_factory=lambda *_args: ExpiredChannel(),
    )

    task = await gateway.start()
    await asyncio.wait_for(task, 1)

    assert credentials_store.load() is None
    assert state_store.get_cursor("bot-1") == ""
    assert gateway.poll_task is None
    client.close.assert_awaited_once()
    state_store.close()

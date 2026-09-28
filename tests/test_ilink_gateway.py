import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from communication.ilink.errors import ILinkHTTPError, ILinkRateLimitError, ILinkSessionExpired
from communication.ilink.media import UploadedMedia
from communication.ilink.models import MediaType
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


@pytest.mark.asyncio
async def test_gateway_start_issues_pairing_code_when_unbound(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: AsyncMock(),
        channel_factory=lambda *_args: BlockingChannel(),
    )

    await gateway.start()
    pairing = gateway.get_status()["pairing"]
    await gateway.stop()

    assert pairing["required"] is True
    assert pairing["bound"] is False
    assert pairing["expires_at"] is not None
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_start_keeps_existing_active_pairing_code(tmp_path, monkeypatch):
    import core.ilink_state as ilink_state

    monkeypatch.setattr(ilink_state.secrets, "randbelow", lambda upper: 24681357)
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    state_store.create_pairing_code("bot-1")
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: AsyncMock(),
        channel_factory=lambda *_args: BlockingChannel(),
    )

    await gateway.start()
    retained = state_store.verify_pairing("bot-1", "wx-owner", "24681357", 3998874040)
    await gateway.stop()

    assert retained is True
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_create_pairing_code_works_before_start(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: AsyncMock(),
        channel_factory=lambda *_args: BlockingChannel(),
    )

    result = gateway.create_pairing_code()

    assert len(result["code"]) == 8
    assert result["bot_id"] == "bot-1"
    assert result["expires_at"] is not None
    state_store.close()


def test_gateway_create_pairing_code_requires_credentials(tmp_path):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    state_store = ILinkStateStore(tmp_path / "state.db")
    gateway = ILinkGateway(credentials_store, state_store, 3998874040, AsyncMock())

    with pytest.raises(RuntimeError):
        gateway.create_pairing_code()
    state_store.close()


def _gateway_with_client(tmp_path, client):
    credentials_store = ILinkCredentialsStore(tmp_path / "credentials.json")
    credentials_store.save(
        ILinkCredentials("token", "bot-1", "bot-user", "https://ilinkai.weixin.qq.com")
    )
    state_store = ILinkStateStore(tmp_path / "state.db")
    state_store.set_context_token("bot-1", "latest-context")
    gateway = ILinkGateway(
        credentials_store,
        state_store,
        3998874040,
        AsyncMock(),
        client_factory=lambda _credentials: client,
        channel_factory=lambda *_args: BlockingChannel(),
    )
    return gateway, state_store


@pytest.mark.asyncio
async def test_gateway_send_file_uploads_with_file_media_type_then_sends(tmp_path):
    """发文件 = 先按 MediaType.FILE 上传，再把 CDN 凭据塞进 file_item 发出。"""
    client = AsyncMock()
    client.send_file.return_value = True
    gateway, state_store = _gateway_with_client(tmp_path, client)
    transfer = MagicMock(
        upload=AsyncMock(
            return_value=UploadedMedia(
                encrypt_query_param="param-abc",
                aes_key="a2V5",
                length=2048,
                md5="b" * 32,
                ciphertext_length=2064,
            )
        )
    )
    gateway._media_transfer = transfer
    source = tmp_path / "笔记.txt"
    source.write_text("hi", encoding="utf-8")

    await gateway.start()
    try:
        sent = await gateway.send_file("wx-owner", str(source))
    finally:
        await gateway.stop()
        state_store.close()

    assert sent is True
    # 上传必须用 3（MediaType.FILE），不是消息项的 4
    assert transfer.upload.await_args.kwargs["media_type"] == MediaType.FILE
    assert transfer.upload.await_args.kwargs["to_user_id"] == "wx-owner"
    # 文件名取磁盘 basename，长度与摘要用**明文**值
    client.send_file.assert_awaited_once_with(
        "wx-owner",
        "latest-context",
        file_name="笔记.txt",
        file_md5="b" * 32,
        file_size=2048,
        encrypt_query_param="param-abc",
        aes_key="a2V5",
    )


@pytest.mark.asyncio
async def test_gateway_send_file_requires_running_gateway(tmp_path):
    client = AsyncMock()
    gateway, state_store = _gateway_with_client(tmp_path, client)
    gateway._media_transfer = AsyncMock()

    with pytest.raises(RuntimeError, match="not running"):
        await gateway.send_file("wx-owner", str(tmp_path / "missing.txt"))
    client.send_file.assert_not_awaited()
    state_store.close()


@pytest.mark.asyncio
async def test_gateway_send_image_uploads_with_image_media_type_then_sends(tmp_path):
    """发图片 = 先按 MediaType.IMAGE 上传，再把 CDN 凭据塞进 image_item 发出。

    与发文件同构，但上传编号必须是 1（不是文件用的 3）——两套编号混用会被
    服务端当成参数错误。
    """
    client = AsyncMock()
    client.send_image.return_value = True
    gateway, state_store = _gateway_with_client(tmp_path, client)
    transfer = MagicMock(
        upload=AsyncMock(
            return_value=UploadedMedia(
                encrypt_query_param="param-img",
                aes_key="a2V5",
                length=4096,
                md5="c" * 32,
                ciphertext_length=4112,
            )
        )
    )
    gateway._media_transfer = transfer
    source = tmp_path / "自拍.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n")

    await gateway.start()
    try:
        sent = await gateway.send_image("wx-owner", str(source))
    finally:
        await gateway.stop()
        state_store.close()

    assert sent is True
    assert transfer.upload.await_args.kwargs["media_type"] == MediaType.IMAGE
    assert transfer.upload.await_args.kwargs["to_user_id"] == "wx-owner"
    client.send_image.assert_awaited_once_with(
        "wx-owner",
        "latest-context",
        encrypt_query_param="param-img",
        aes_key="a2V5",
    )


@pytest.mark.asyncio
async def test_gateway_send_image_requires_running_gateway(tmp_path):
    client = AsyncMock()
    gateway, state_store = _gateway_with_client(tmp_path, client)
    gateway._media_transfer = AsyncMock()

    with pytest.raises(RuntimeError, match="not running"):
        await gateway.send_image("wx-owner", str(tmp_path / "missing.png"))
    client.send_image.assert_not_awaited()
    state_store.close()

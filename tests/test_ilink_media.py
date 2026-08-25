import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from communication.ilink.client import ILinkClient
from communication.ilink.errors import ILinkMediaError, ILinkProtocolError
from communication.ilink.media import ILinkMediaTransfer, MediaDownload
from communication.ilink.media_crypto import encrypt_media


def encrypted_payload(value: bytes, key: bytes) -> bytes:
    destination = bytearray()

    class Destination:
        def write(self, chunk):
            destination.extend(chunk)

    encrypt_media(source=MemoryReader(value), destination=Destination(), key=key)
    return bytes(destination)


class MemoryReader:
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.offset = 0

    def read(self, size: int) -> bytes:
        chunk = self.value[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_download_streams_ciphertext_and_atomically_keeps_verified_plaintext(tmp_path):
    plaintext = b"verified inbound media" * 5000
    key = b"0123456789abcdef"
    ciphertext = encrypted_payload(plaintext, key)
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, content=ciphertext)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        transfer = ILinkMediaTransfer(http_client, tmp_path)
        result = await transfer.download(
            MediaDownload(
                url="https://novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param=opaque",
                aes_key=base64.b64encode(key).decode("ascii"),
                expected_length=len(plaintext),
                expected_md5=hashlib.md5(plaintext).hexdigest(),
                filename="photo.jpg",
                max_ciphertext_bytes=len(ciphertext),
            )
        )

    assert requests[0].method == "GET"
    assert result.path.read_bytes() == plaintext
    assert result.length == len(plaintext)
    assert result.md5 == hashlib.md5(plaintext).hexdigest()
    assert result.path.name == "photo.jpg"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["photo.jpg"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://novac2c.cdn.weixin.qq.com/c2c/download",
        "https://novac2c.cdn.weixin.qq.com.evil.example/download",
        "https://user@novac2c.cdn.weixin.qq.com/download",
        "https://127.0.0.1/download",
    ],
)
async def test_download_rejects_urls_outside_tencent_cdn_allowlist(tmp_path, url):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)) as http_client:
        transfer = ILinkMediaTransfer(http_client, tmp_path)
        with pytest.raises(ILinkMediaError, match="allowlist"):
            await transfer.download(
                MediaDownload(
                    url=url,
                    aes_key=base64.b64encode(b"0123456789abcdef").decode("ascii"),
                    expected_length=1,
                    expected_md5="0" * 32,
                    filename="media.bin",
                    max_ciphertext_bytes=16,
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["oversize", "integrity"])
async def test_download_deletes_all_temporary_files_on_size_or_integrity_failure(tmp_path, failure):
    plaintext = b"media payload"
    key = b"0123456789abcdef"
    ciphertext = encrypted_payload(plaintext, key)

    async def handler(request):
        return httpx.Response(200, content=ciphertext)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        transfer = ILinkMediaTransfer(http_client, tmp_path)
        with pytest.raises(ILinkMediaError):
            await transfer.download(
                MediaDownload(
                    url="https://novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param=opaque",
                    aes_key=base64.b64encode(key).decode("ascii"),
                    expected_length=len(plaintext),
                    expected_md5="0" * 32 if failure == "integrity" else hashlib.md5(plaintext).hexdigest(),
                    filename="payload.bin",
                    max_ciphertext_bytes=len(ciphertext) - 1 if failure == "oversize" else len(ciphertext),
                )
            )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_uses_official_post_contract_and_returns_encrypted_header(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"outbound media payload")
    requests = []

    async def handler(request):
        requests.append(request)
        if request.url.path == "/ilink/bot/getuploadurl":
            payload = json.loads(request.content)
            assert payload["filekey"]
            assert payload["media_type"] == 3
            assert payload["to_user_id"] == "owner@im.wechat"
            assert payload["rawsize"] == source.stat().st_size
            assert payload["rawfilemd5"] == hashlib.md5(source.read_bytes()).hexdigest()
            assert payload["filesize"] == 32
            assert payload["aeskey"] == "30313233343536373839616263646566"
            assert payload["no_need_thumb"] is True
            assert payload["base_info"] == {"channel_version": "2.1.1"}
            return httpx.Response(
                200,
                json={"upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?signed=opaque"},
            )
        assert request.method == "POST"
        assert request.headers["Content-Type"] == "application/octet-stream"
        assert request.content != source.read_bytes()
        return httpx.Response(200, headers={"x-encrypted-param": "download-reference"})

    monkeypatch.setattr("communication.ilink.media.secrets.token_bytes", lambda size: b"0123456789abcdef")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", http_client)
        transfer = ILinkMediaTransfer(http_client, tmp_path / "media")
        result = await transfer.upload(client, source, to_user_id="owner@im.wechat", media_type=3)

    assert [request.method for request in requests] == ["POST", "POST"]
    assert result.encrypt_query_param == "download-reference"
    assert result.aes_key == base64.b64encode(b"0123456789abcdef").decode("ascii")
    assert list((tmp_path / "media").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response_mode", ["missing_url", "bad_url", "missing_header"])
async def test_upload_rejects_invalid_protocol_results_and_cleans_temporary_file(
    tmp_path,
    response_mode,
):
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")

    async def handler(request):
        if request.url.path == "/ilink/bot/getuploadurl":
            if response_mode == "missing_url":
                return httpx.Response(200, json={"upload_param": "legacy"})
            host = "evil.example" if response_mode == "bad_url" else "novac2c.cdn.weixin.qq.com"
            return httpx.Response(200, json={"upload_full_url": f"https://{host}/upload"})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", http_client)
        transfer = ILinkMediaTransfer(http_client, tmp_path / "media")
        expected_error = ILinkProtocolError if response_mode == "missing_url" else ILinkMediaError
        with pytest.raises(expected_error):
            await transfer.upload(client, source, to_user_id="owner@im.wechat", media_type=3)

    assert list((tmp_path / "media").iterdir()) == []

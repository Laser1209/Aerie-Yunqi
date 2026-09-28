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
        # CDN 只认**带 Content-Length 的整块**上传：改成流式（chunked）会被回 500。
        # 真机对照实测：同一 URL 整块 200、流式 500，故把传输编码钉死在这。
        assert "chunked" not in request.headers.get("Transfer-Encoding", "").lower()
        assert int(request.headers["Content-Length"]) == len(request.content)
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


# ── 出站上传的两道闸门：专用超时 + 体积上限 ────────────────────────────
# 背景（计划 §5.2-P0-3）：出站体积上限无公开数字、失败无错误码。整块上传是 CDN 的
# 硬要求（流式已被真机否掉，见上），也就是密文必须整体进内存 —— 所以必须有体积
# 闸门，把"超大"变成一条**可回报**的失败原因，而不是 45s 超时后用户只看到"没收到"。


def test_upload_limits_defaults():
    from communication.ilink.media import upload_limits

    timeout_sec, max_bytes = upload_limits()
    assert timeout_sec == 300.0
    assert max_bytes == 512 * 1024 * 1024


def test_upload_limits_read_from_settings(monkeypatch):
    from communication.ilink import media

    monkeypatch.setattr(
        "config.persona_loader.load_settings",
        lambda: {"ilink": {"media_upload_timeout_sec": 600, "media_upload_max_mib": 64}},
    )
    assert media.upload_limits() == (600.0, 64 * 1024 * 1024)


def test_upload_limits_fall_back_on_garbage(monkeypatch):
    """配置写坏了不能拒绝服务：回落默认值。"""
    from communication.ilink import media

    monkeypatch.setattr(
        "config.persona_loader.load_settings",
        lambda: {"ilink": {"media_upload_timeout_sec": "abc", "media_upload_max_mib": None}},
    )
    assert media.upload_limits() == (media._DEFAULT_UPLOAD_TIMEOUT_SEC, int(media._DEFAULT_MAX_UPLOAD_MIB * 1024 * 1024))


@pytest.mark.asyncio
async def test_upload_rejects_oversize_before_touching_cdn(tmp_path, monkeypatch):
    """超限 → 明确报 too large，且**不请求** getuploadurl（不消耗配额、不占内存）。"""
    from communication.ilink import media

    monkeypatch.setattr(media, "upload_limits", lambda: (300.0, 4))
    source = tmp_path / "big.bin"
    source.write_bytes(b"x" * 1024)
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"upload_full_url": "https://novac2c.cdn.weixin.qq.com/upload"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", http_client)
        transfer = ILinkMediaTransfer(http_client, tmp_path / "media")
        with pytest.raises(ILinkMediaError) as excinfo:
            await transfer.upload(client, source, to_user_id="owner@im.wechat", media_type=3)

    # describe_failure 只认 "too large"，据此渲染成"文件超出通道体积上限"
    assert "too large" in str(excinfo.value)
    assert requests == []
    assert list((tmp_path / "media").iterdir()) == []


@pytest.mark.asyncio
async def test_upload_uses_dedicated_timeout_not_client_default(tmp_path, monkeypatch):
    """上传用专用超时（默认 300s），不复用日常 RPC 的 45s 读超时。"""
    from communication.ilink import media

    monkeypatch.setattr(media, "upload_limits", lambda: (777.0, 512 * 1024 * 1024))
    monkeypatch.setattr("communication.ilink.media.secrets.token_bytes", lambda size: b"0123456789abcdef")
    source = tmp_path / "source.bin"
    source.write_bytes(b"outbound media payload")
    seen: dict = {}

    async def handler(request):
        if request.url.path == "/ilink/bot/getuploadurl":
            return httpx.Response(
                200,
                json={"upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?signed=opaque"},
            )
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, headers={"x-encrypted-param": "ref"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", http_client)
        transfer = ILinkMediaTransfer(http_client, tmp_path / "media")
        await transfer.upload(client, source, to_user_id="owner@im.wechat", media_type=3)

    assert seen["timeout"]["read"] == 777.0
    assert seen["timeout"]["write"] == 777.0


def test_streaming_upload_is_off_by_default(monkeypatch):
    """流式默认关：生产走已真机验证的整块路径。"""
    from communication.ilink import media

    monkeypatch.setattr("config.persona_loader.load_settings", lambda: {"ilink": {}})
    assert media.streaming_upload_enabled() is False
    monkeypatch.setattr(
        "config.persona_loader.load_settings",
        lambda: {"ilink": {"media_upload_streaming": True}},
    )
    assert media.streaming_upload_enabled() is True


@pytest.mark.asyncio
async def test_streaming_upload_sends_explicit_content_length(tmp_path, monkeypatch):
    """开关打开 → 分块发送但**显式**给 Content-Length（不能退化成 chunked）。"""
    from communication.ilink import media

    monkeypatch.setattr(media, "streaming_upload_enabled", lambda: True)
    monkeypatch.setattr("communication.ilink.media.secrets.token_bytes", lambda size: b"0123456789abcdef")
    source = tmp_path / "source.bin"
    source.write_bytes(b"streamed outbound payload")
    seen: dict = {}

    async def handler(request):
        if request.url.path == "/ilink/bot/getuploadurl":
            return httpx.Response(
                200,
                json={"upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?signed=opaque"},
            )
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, headers={"x-encrypted-param": "ref"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ILinkClient("https://ilinkai.weixin.qq.com", "token", http_client)
        transfer = ILinkMediaTransfer(http_client, tmp_path / "media")
        result = await transfer.upload(client, source, to_user_id="owner@im.wechat", media_type=3)

    assert result.encrypt_query_param == "ref"
    assert "chunked" not in seen["headers"].get("transfer-encoding", "").lower()
    assert int(seen["headers"]["content-length"]) == len(seen["body"])
    # 分块发出去的内容与整块路径完全一致（同一个加密临时文件）
    assert seen["body"] == encrypted_payload(source.read_bytes(), b"0123456789abcdef")

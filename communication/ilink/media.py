from __future__ import annotations

import base64
import binascii
import os
import secrets
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath
from urllib.parse import urlparse

import httpx

from communication.ilink.client import ILinkClient
from communication.ilink.errors import ILinkMediaError, ILinkProtocolError
from communication.ilink.media_crypto import decrypt_media, encrypt_media


TENCENT_CDN_HOSTS = frozenset({"novac2c.cdn.weixin.qq.com"})
STREAM_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class MediaDownload:
    url: str
    aes_key: str
    expected_length: int
    expected_md5: str
    filename: str
    max_ciphertext_bytes: int


@dataclass(frozen=True)
class DownloadedMedia:
    path: Path
    length: int
    md5: str


@dataclass(frozen=True)
class UploadedMedia:
    encrypt_query_param: str
    aes_key: str
    length: int
    md5: str
    ciphertext_length: int


class ILinkMediaTransfer:
    def __init__(self, http_client: httpx.AsyncClient, storage_dir: str | Path) -> None:
        self._http_client = http_client
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def download(self, request: MediaDownload) -> DownloadedMedia:
        _validate_cdn_url(request.url)
        _validate_download_request(request)
        key = _parse_aes_key(request.aes_key)
        filename = _safe_filename(request.filename)
        encrypted_path = self._temporary_path(".encrypted")
        plaintext_path = self._temporary_path(".plaintext")
        destination = self.storage_dir / filename
        try:
            ciphertext_length = 0
            async with self._http_client.stream("GET", request.url) as response:
                _raise_media_status(response)
                with encrypted_path.open("wb") as encrypted_file:
                    async for chunk in response.aiter_bytes(STREAM_CHUNK_SIZE):
                        ciphertext_length += len(chunk)
                        if ciphertext_length > request.max_ciphertext_bytes:
                            raise ILinkMediaError("media ciphertext exceeds the configured size limit")
                        encrypted_file.write(chunk)
            with encrypted_path.open("rb") as encrypted_file, plaintext_path.open("wb") as plaintext_file:
                result = decrypt_media(
                    encrypted_file,
                    plaintext_file,
                    key,
                    expected_length=request.expected_length,
                    expected_md5=request.expected_md5,
                )
                plaintext_file.flush()
                os.fsync(plaintext_file.fileno())
            os.replace(plaintext_path, destination)
            return DownloadedMedia(path=destination, length=result.length, md5=result.md5)
        finally:
            encrypted_path.unlink(missing_ok=True)
            plaintext_path.unlink(missing_ok=True)

    async def upload(
        self,
        client: ILinkClient,
        source_path: str | Path,
        *,
        to_user_id: str,
        media_type: int,
    ) -> UploadedMedia:
        source = Path(source_path)
        if not source.is_file():
            raise ILinkMediaError("media source must be an existing file")
        if media_type not in (1, 2, 3, 4):
            raise ILinkMediaError("media type is invalid")
        if not isinstance(to_user_id, str) or not to_user_id:
            raise ILinkMediaError("media target user is required")
        key = secrets.token_bytes(16)
        encrypted_path = self._temporary_path(".encrypted")
        try:
            with source.open("rb") as source_file, encrypted_path.open("wb") as encrypted_file:
                result = encrypt_media(source_file, encrypted_file, key)
                encrypted_file.flush()
                os.fsync(encrypted_file.fileno())
            ciphertext_length = encrypted_path.stat().st_size
            upload_response = await client.get_upload_url(
                {
                    "filekey": uuid.uuid4().hex,
                    "media_type": media_type,
                    "to_user_id": to_user_id,
                    "rawsize": result.length,
                    "rawfilemd5": result.md5,
                    "filesize": ciphertext_length,
                    "no_need_thumb": True,
                    "aeskey": key.hex(),
                }
            )
            upload_url = upload_response.get("upload_full_url")
            if not isinstance(upload_url, str) or not upload_url:
                raise ILinkProtocolError("iLink upload response must contain upload_full_url")
            _validate_cdn_url(upload_url)
            with encrypted_path.open("rb") as encrypted_file:
                response = await self._http_client.post(
                    upload_url,
                    content=_file_stream(encrypted_file),
                    headers={"Content-Type": "application/octet-stream"},
                )
            _raise_media_status(response)
            encrypted_param = response.headers.get("x-encrypted-param")
            if not encrypted_param:
                raise ILinkMediaError("CDN upload response is missing x-encrypted-param")
            return UploadedMedia(
                encrypt_query_param=encrypted_param,
                aes_key=base64.b64encode(key).decode("ascii"),
                length=result.length,
                md5=result.md5,
                ciphertext_length=ciphertext_length,
            )
        finally:
            encrypted_path.unlink(missing_ok=True)

    def _temporary_path(self, suffix: str) -> Path:
        descriptor, value = tempfile.mkstemp(dir=self.storage_dir, prefix="ilink_", suffix=suffix)
        os.close(descriptor)
        return Path(value)


async def _file_stream(source):
    while chunk := source.read(STREAM_CHUNK_SIZE):
        yield chunk


def _validate_cdn_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in TENCENT_CDN_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ILinkMediaError("media URL is outside the Tencent CDN allowlist")


def _validate_download_request(request: MediaDownload) -> None:
    if request.expected_length < 0:
        raise ILinkMediaError("media plaintext length must not be negative")
    if request.max_ciphertext_bytes <= 0:
        raise ILinkMediaError("media ciphertext size limit must be positive")
    if len(request.expected_md5) != 32:
        raise ILinkMediaError("media MD5 must contain 32 hexadecimal characters")
    try:
        int(request.expected_md5, 16)
    except ValueError as exc:
        raise ILinkMediaError("media MD5 must contain 32 hexadecimal characters") from exc


def _parse_aes_key(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ILinkMediaError("media AES key is required")
    if len(value) == 32:
        try:
            return bytes.fromhex(value)
        except ValueError:
            pass
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ILinkMediaError("media AES key encoding is invalid") from exc
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            return bytes.fromhex(decoded.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    raise ILinkMediaError("media AES key must decode to 16 bytes")


def _safe_filename(value: str) -> str:
    if not isinstance(value, str) or not value or value in (".", ".."):
        raise ILinkMediaError("media filename is invalid")
    if PurePath(value).name != value or "/" in value or "\\" in value or "\x00" in value:
        raise ILinkMediaError("media filename is invalid")
    return value


def _raise_media_status(response: httpx.Response) -> None:
    if response.is_error:
        raise ILinkMediaError(f"media HTTP request failed with status {response.status_code}")

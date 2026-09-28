from __future__ import annotations

import base64
import binascii
import logging
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
from communication.ilink.models import MediaType

logger = logging.getLogger(__name__)


TENCENT_CDN_HOSTS = frozenset({"novac2c.cdn.weixin.qq.com"})
STREAM_CHUNK_SIZE = 64 * 1024

# ── 出站媒体上传（CDN PUT）的两道闸门 ──────────────────────────────────
# ① 专用超时：不复用 client.DEFAULT_TIMEOUT（read=45s）。大文件整块 PUT 的耗时
#    与体积成正比，45s 会把"能发但慢"误判成"发不出去"，而失败原因只剩一个
#    `timeout`（用户只看到"没收到"）。
# ② 体积闸门：整块上传是 CDN 的硬要求（见 upload 内的实测注释），也就是密文必须
#    **整体读进内存**。没有上限的话，超大文件的表现是 OOM 或长时间无响应，而不是
#    一条可回报的失败原因。超限时明确报"too large"，让
#    ``core.delivery_ledger.describe_failure`` 渲染成"文件超出通道体积上限"，
#    再由 P0-2 回执回到模型 —— 而不是让 Agent 继续宣称"已经发过去了"。
#
# 两个值都可在 settings.yaml 的 ilink 段调整（探测脚本跑出真实阈值后再定）。
_DEFAULT_UPLOAD_TIMEOUT_SEC = 300.0
_DEFAULT_MAX_UPLOAD_MIB = 512.0


def upload_limits() -> tuple[float, int]:
    """读 ``ilink.media_upload_timeout_sec`` / ``ilink.media_upload_max_mib``。

    读不到或非法一律回落默认值 —— 上传是主链路，不能因为配置格式写错就拒绝服务。
    """
    timeout_sec = _DEFAULT_UPLOAD_TIMEOUT_SEC
    max_bytes = int(_DEFAULT_MAX_UPLOAD_MIB * 1024 * 1024)
    try:
        from config.persona_loader import load_settings

        cfg = (load_settings() or {}).get("ilink") or {}
        raw_timeout = cfg.get("media_upload_timeout_sec")
        if raw_timeout is not None:
            timeout_sec = max(10.0, float(raw_timeout))
        raw_max = cfg.get("media_upload_max_mib")
        if raw_max is not None:
            max_bytes = max(1, int(float(raw_max) * 1024 * 1024))
    except Exception:
        logger.debug("ilink upload limits read failed; using defaults", exc_info=True)
    return timeout_sec, max_bytes


def streaming_upload_enabled() -> bool:
    """是否用**分块流式**上传（``ilink.media_upload_streaming``，默认 False）。

    为什么默认关：整块上传是已**真机验证**过的路径（chunked 编码会被 CDN 回 500，
    同一 URL 整块 200 —— 见 upload 内注释）。但计划 §5.2 步骤2 要求的是"异步生成器
    **加显式 Content-Length**"，与当时那次真机实验未必是同一写法：不显式给长度时
    httpx 会退化成 chunked，很可能就是那次 500 的原因。

    所以这一条留成开关而不是直接替换：生产默认走已验证的整块路径；要判定流式能否
    成立（以及它是否能让 278 MB 不必整个进内存），把它打开跑一次真机即可 —— 一次
    实验就能给出确定的结论，不需要改代码。
    """
    try:
        from config.persona_loader import load_settings

        cfg = (load_settings() or {}).get("ilink") or {}
        return bool(cfg.get("media_upload_streaming", False))
    except Exception:
        logger.debug("ilink streaming flag read failed; using whole-body", exc_info=True)
        return False


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
        if media_type not in tuple(int(item) for item in MediaType):
            raise ILinkMediaError("media type is invalid")
        if not isinstance(to_user_id, str) or not to_user_id:
            raise ILinkMediaError("media target user is required")
        key = secrets.token_bytes(16)
        encrypted_path = self._temporary_path(".encrypted")
        upload_timeout_sec, max_upload_bytes = upload_limits()
        try:
            with source.open("rb") as source_file, encrypted_path.open("wb") as encrypted_file:
                result = encrypt_media(source_file, encrypted_file, key)
                encrypted_file.flush()
                os.fsync(encrypted_file.fileno())
            ciphertext_length = encrypted_path.stat().st_size
            if ciphertext_length > max_upload_bytes:
                # 整块上传 = 密文整体进内存；超限就明确失败，别让它变成 45s 后的
                # 一个没有原因的 timeout（用户只看到"没收到"，模型照旧说"发过去了"）。
                raise ILinkMediaError(
                    "media too large for outbound upload: "
                    f"{ciphertext_length} bytes > limit {max_upload_bytes} bytes"
                )
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
            # 默认**整块**上传（带 Content-Length）。用异步生成器会被 httpx 改成
            # chunked 传输编码，CDN 直接回 500——同一个 URL 整块 200、流式 500，
            # 2026-09-28 真机对照实测。官方 SDK 也一律 `data=ciphertext` 整块发。
            #
            # `ilink.media_upload_streaming` 打开时走分块 + **显式** Content-Length：
            # 计划 §5.2 步骤2 要的是这一种写法，与上面那次真机实验未必等价（不给长度
            # 才会退化成 chunked）。默认关，等真机给出确定结论后再决定要不要转正。
            if streaming_upload_enabled():
                headers = {
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(ciphertext_length),
                }
                logger.info(
                    "[iLink] 出站媒体上传（流式）ciphertext=%.1f MiB 超时=%.0fs chunk=%d CDN=%s",
                    ciphertext_length / (1024 * 1024), upload_timeout_sec, STREAM_CHUNK_SIZE,
                    urlparse(upload_url).hostname or "",
                )
                response = await self._http_client.post(
                    upload_url,
                    content=self._stream_file(encrypted_path),
                    headers=headers,
                    timeout=httpx.Timeout(
                        connect=10.0, read=upload_timeout_sec, write=upload_timeout_sec, pool=10.0,
                    ),
                )
            else:
                ciphertext = encrypted_path.read_bytes()
                logger.info(
                    "[iLink] 出站媒体上传 ciphertext=%.1f MiB 超时=%.0fs CDN=%s",
                    ciphertext_length / (1024 * 1024), upload_timeout_sec,
                    urlparse(upload_url).hostname or "",
                )
                response = await self._http_client.post(
                    upload_url,
                    content=ciphertext,
                    headers={"Content-Type": "application/octet-stream"},
                    # 上传专用超时：与日常 RPC 的 45s 读超时解耦（见文件头说明）。
                    timeout=httpx.Timeout(
                        connect=10.0, read=upload_timeout_sec, write=upload_timeout_sec, pool=10.0,
                    ),
                )
            _raise_media_status(response)
            encrypted_param = response.headers.get("x-encrypted-param")
            if not encrypted_param:
                raise ILinkMediaError("CDN upload response is missing x-encrypted-param")
            return UploadedMedia(
                encrypt_query_param=encrypted_param,
                aes_key=_outbound_aes_key(key),
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

    @staticmethod
    async def _stream_file(path: Path, chunk_size: int = STREAM_CHUNK_SIZE):
        """按块产出密文（配合显式 Content-Length 使用，见 streaming_upload_enabled）。

        文件句柄在生成器存活期间保持打开；httpx 会在请求体发送完毕后关闭生成器。
        """
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    return
                yield chunk


def _outbound_aes_key(key: bytes) -> str:
    """出站 ``CDNMedia.aes_key`` 的规范编码：**base64(16字节密钥的 hex 字符串)**。

    这是最容易写错、且错了不会报错的一处。两份可工作的参考实现都取这个编码，
    第三方那份还把结论写在注释里（"aes_key in sendmessage = base64(hex字符串)，
    与官方实现一致"）：

    * 腾讯官方插件 ``@tencent-weixin/openclaw-weixin`` ``src/messaging/send.ts``
      → ``Buffer.from(uploaded.aeskey).toString("base64")``（``aeskey`` 是 hex 串）
    * 第三方 ``im-claude`` ``src/adapters/wechat.adapter.ts``
      → ``Buffer.from(uploaded.aeskeyHex).toString("base64")``

    **传 base64(原始16字节) 时不会得到任何错误**：报文形状全对、``sendmessage``
    返回 ``message_id``、日志一片正常，但微信客户端拿不到可用的密钥，图片渲染成
    "图片已过期或被清理"（实测 2026-09-29）。所以这里不是风格问题，是唯一判据 ——
    只能对齐参考实现，不能按"看起来更合理"来选。

    注：**入站**解析另有一套宽容规则（见 ``_parse_aes_key``），两种编码都接受，
    因此这里改编码不影响收图。
    """
    return base64.b64encode(key.hex().encode("ascii")).decode("ascii")


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

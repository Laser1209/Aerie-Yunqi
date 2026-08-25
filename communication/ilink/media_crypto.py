from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import BinaryIO

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from communication.ilink.errors import ILinkMediaError


BLOCK_SIZE_BYTES = 16
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class MediaCryptoResult:
    length: int
    md5: str


def encrypt_media(source: BinaryIO, destination: BinaryIO, key: bytes) -> MediaCryptoResult:
    validated_key = _validate_key(key)
    encryptor = Cipher(algorithms.AES(validated_key), modes.ECB()).encryptor()
    padder = padding.PKCS7(BLOCK_SIZE_BYTES * 8).padder()
    digest = hashlib.md5()
    plaintext_length = 0

    while chunk := source.read(CHUNK_SIZE):
        plaintext_length += len(chunk)
        digest.update(chunk)
        padded = padder.update(chunk)
        if padded:
            destination.write(encryptor.update(padded))

    final_padded = padder.finalize()
    destination.write(encryptor.update(final_padded) + encryptor.finalize())
    return MediaCryptoResult(length=plaintext_length, md5=digest.hexdigest())


def decrypt_media(
    source: BinaryIO,
    destination: BinaryIO,
    key: bytes,
    *,
    expected_length: int | None = None,
    expected_md5: str | None = None,
) -> MediaCryptoResult:
    validated_key = _validate_key(key)
    decryptor = Cipher(algorithms.AES(validated_key), modes.ECB()).decryptor()
    unpadder = padding.PKCS7(BLOCK_SIZE_BYTES * 8).unpadder()
    digest = hashlib.md5()
    plaintext_length = 0
    ciphertext_length = 0

    while chunk := source.read(CHUNK_SIZE):
        ciphertext_length += len(chunk)
        plaintext = unpadder.update(decryptor.update(chunk))
        if plaintext:
            destination.write(plaintext)
            plaintext_length += len(plaintext)
            digest.update(plaintext)

    if ciphertext_length == 0 or ciphertext_length % BLOCK_SIZE_BYTES:
        raise ILinkMediaError("media ciphertext length must be a positive multiple of 16 bytes")

    try:
        final_plaintext = unpadder.update(decryptor.finalize()) + unpadder.finalize()
    except ValueError as exc:
        raise ILinkMediaError("media ciphertext has invalid PKCS7 padding") from exc

    if final_plaintext:
        destination.write(final_plaintext)
        plaintext_length += len(final_plaintext)
        digest.update(final_plaintext)

    actual_md5 = digest.hexdigest()
    if expected_length is not None and plaintext_length != expected_length:
        raise ILinkMediaError("media plaintext length does not match the declared length")
    if expected_md5 is not None and not hmac.compare_digest(actual_md5, expected_md5.lower()):
        raise ILinkMediaError("media plaintext MD5 does not match the declared MD5")
    return MediaCryptoResult(length=plaintext_length, md5=actual_md5)


def _validate_key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) != BLOCK_SIZE_BYTES:
        raise ILinkMediaError("media AES key must be exactly 16 bytes")
    return key

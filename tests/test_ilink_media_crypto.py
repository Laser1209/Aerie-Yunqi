import hashlib
import io

import pytest

from communication.ilink.errors import ILinkMediaError
from communication.ilink.media_crypto import decrypt_media, encrypt_media


class BoundedReader(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.read_sizes = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError("stream must use bounded reads")
        return super().read(size)


def test_encrypt_media_uses_aes_128_ecb_pkcs7_and_streams_input():
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    block = bytes.fromhex("00112233445566778899aabbccddeeff")
    plaintext = block * 5000
    source = BoundedReader(plaintext)
    destination = io.BytesIO()

    result = encrypt_media(source, destination, key)
    ciphertext = destination.getvalue()

    assert ciphertext[:16] == bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    assert ciphertext[:16] == ciphertext[16:32]
    assert len(ciphertext) == len(plaintext) + 16
    assert result.length == len(plaintext)
    assert result.md5 == hashlib.md5(plaintext).hexdigest()
    assert len(source.read_sizes) > 2
    assert all(size > 0 for size in source.read_sizes)


def test_decrypt_media_streams_and_validates_length_and_md5():
    key = b"0123456789abcdef"
    plaintext = bytes(range(256)) * 400
    encrypted = io.BytesIO()
    encrypt_media(io.BytesIO(plaintext), encrypted, key)
    source = BoundedReader(encrypted.getvalue())
    destination = io.BytesIO()

    result = decrypt_media(
        source,
        destination,
        key,
        expected_length=len(plaintext),
        expected_md5=hashlib.md5(plaintext).hexdigest().upper(),
    )

    assert destination.getvalue() == plaintext
    assert result.length == len(plaintext)
    assert result.md5 == hashlib.md5(plaintext).hexdigest()
    assert len(source.read_sizes) > 2
    assert all(size > 0 for size in source.read_sizes)


@pytest.mark.parametrize(
    ("expected_length", "expected_md5", "message"),
    [
        (12, hashlib.md5(b"media payload").hexdigest(), "length"),
        (13, "0" * 32, "MD5"),
    ],
)
def test_decrypt_media_rejects_integrity_mismatch(expected_length, expected_md5, message):
    key = b"0123456789abcdef"
    encrypted = io.BytesIO()
    encrypt_media(io.BytesIO(b"media payload"), encrypted, key)

    with pytest.raises(ILinkMediaError, match=message):
        decrypt_media(
            io.BytesIO(encrypted.getvalue()),
            io.BytesIO(),
            key,
            expected_length=expected_length,
            expected_md5=expected_md5,
        )


@pytest.mark.parametrize("key", [b"", b"short", b"x" * 15, b"x" * 17, "0123456789abcdef"])
def test_media_crypto_requires_a_16_byte_key(key):
    with pytest.raises(ILinkMediaError, match="16 bytes"):
        encrypt_media(io.BytesIO(b"payload"), io.BytesIO(), key)


def test_decrypt_media_rejects_invalid_ciphertext_or_padding():
    key = b"0123456789abcdef"

    with pytest.raises(ILinkMediaError, match="ciphertext"):
        decrypt_media(io.BytesIO(b"not-aes-block"), io.BytesIO(), key)

    encrypted = io.BytesIO()
    encrypt_media(io.BytesIO(b"payload"), encrypted, key)
    corrupted = encrypted.getvalue()[:-1] + bytes([encrypted.getvalue()[-1] ^ 1])

    with pytest.raises(ILinkMediaError, match="padding"):
        decrypt_media(io.BytesIO(corrupted), io.BytesIO(), key)

import json

import pytest


def test_credentials_round_trip_without_plaintext_on_disk(tmp_path):
    from core.ilink_credentials import ILinkCredentials, ILinkCredentialsStore

    path = tmp_path / "ilink_credentials.json"
    store = ILinkCredentialsStore(path)
    credentials = ILinkCredentials(
        bot_token="secret-bot-token",
        bot_id="bot-123",
        user_id="wx-user-456",
        base_url="https://ilinkai.weixin.qq.com",
    )

    store.save(credentials)

    content = path.read_bytes()
    envelope = json.loads(content)
    assert b"secret-bot-token" not in content
    assert b"wx-user-456" not in content
    assert set(envelope) == {"version", "ciphertext", "saved_at"}
    assert store.load() == credentials


def test_credentials_never_read_plaintext_fallback(tmp_path):
    from core.ilink_credentials import CredentialsError, ILinkCredentialsStore

    path = tmp_path / "ilink_credentials.json"
    path.write_text(
        json.dumps(
            {
                "bot_token": "plaintext-token",
                "bot_id": "bot-123",
                "user_id": "wx-user-456",
                "base_url": "https://ilinkai.weixin.qq.com",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CredentialsError):
        ILinkCredentialsStore(path).load()


def test_credentials_reject_corrupted_ciphertext(tmp_path):
    from core.ilink_credentials import CredentialsError, ILinkCredentialsStore

    path = tmp_path / "ilink_credentials.json"
    path.write_text(
        json.dumps(
            {"version": 1, "ciphertext": "bm90LWRwYXBp", "saved_at": "now"}
        ),
        encoding="utf-8",
    )

    with pytest.raises(CredentialsError):
        ILinkCredentialsStore(path).load()


def test_credentials_delete_removes_persisted_secret(tmp_path):
    from core.ilink_credentials import ILinkCredentials, ILinkCredentialsStore

    path = tmp_path / "ilink_credentials.json"
    store = ILinkCredentialsStore(path)
    store.save(
        ILinkCredentials(
            bot_token="secret",
            bot_id="bot",
            user_id="user",
            base_url="https://ilinkai.weixin.qq.com",
        )
    )

    store.delete()

    assert not path.exists()
    assert store.load() is None

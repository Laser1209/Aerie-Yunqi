import pytest

from communication.ilink.errors import ILinkProtocolError
from communication.ilink.models import (
    AuthPollResult,
    AuthStatus,
    GetUpdatesResponse,
    ILinkCredentials,
    MessageItemType,
    MessageState,
    MessageType,
    QRCodeChallenge,
)


def test_qrcode_challenge_requires_non_empty_strings():
    challenge = QRCodeChallenge.from_dict(
        {"qrcode": "opaque-session", "qrcode_img_content": "opaque-image-payload"}
    )

    assert challenge.qrcode == "opaque-session"
    assert challenge.image_content == "opaque-image-payload"

    with pytest.raises(ILinkProtocolError, match="qrcode_img_content"):
        QRCodeChallenge.from_dict({"qrcode": "opaque-session", "qrcode_img_content": ""})


def test_confirmed_auth_result_requires_complete_credentials():
    result = AuthPollResult.from_dict(
        {
            "status": "confirmed",
            "bot_token": "secret-token",
            "ilink_bot_id": "bot@im.bot",
            "ilink_user_id": "user@im.wechat",
            "baseurl": "https://ilinkai.weixin.qq.com",
        }
    )

    assert result.status is AuthStatus.CONFIRMED
    assert result.credentials == ILinkCredentials(
        bot_token="secret-token",
        bot_id="bot@im.bot",
        user_id="user@im.wechat",
        base_url="https://ilinkai.weixin.qq.com",
    )

    with pytest.raises(ILinkProtocolError, match="ilink_user_id"):
        AuthPollResult.from_dict(
            {
                "status": "confirmed",
                "bot_token": "secret-token",
                "ilink_bot_id": "bot@im.bot",
                "baseurl": "https://ilinkai.weixin.qq.com",
            }
        )


def test_auth_result_rejects_unknown_status():
    with pytest.raises(ILinkProtocolError, match="status"):
        AuthPollResult.from_dict({"status": "success"})


def test_get_updates_parses_messages_strictly():
    response = GetUpdatesResponse.from_dict(
        {
            "ret": 0,
            "errcode": None,
            "errmsg": None,
            "msgs": [
                {
                    "message_id": 42,
                    "from_user_id": "user@im.wechat",
                    "to_user_id": "bot@im.bot",
                    "client_id": "client-42",
                    "create_time_ms": 1_700_000_000_000,
                    "message_type": 1,
                    "message_state": 2,
                    "context_token": "context-42",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "你好"}},
                    ],
                }
            ],
            "get_updates_buf": "next-cursor",
            "longpolling_timeout_ms": 35_000,
        }
    )

    assert response.cursor == "next-cursor"
    assert response.messages[0].message_type is MessageType.USER
    assert response.messages[0].message_state is MessageState.FINISH
    assert response.messages[0].items[0].type is MessageItemType.TEXT
    assert response.messages[0].items[0].text == "你好"


def test_get_updates_rejects_wrong_field_types():
    with pytest.raises(ILinkProtocolError, match="msgs"):
        GetUpdatesResponse.from_dict(
            {"ret": 0, "errcode": None, "msgs": {}, "get_updates_buf": "cursor"}
        )
